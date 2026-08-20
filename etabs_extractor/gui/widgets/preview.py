"""Plot-preview widgets for the etabs_extractor GUI.

Two pieces:

* :class:`PlotPreviewFrame` — an embedded matplotlib canvas (a
  ``FigureCanvasTkAgg`` host) for showing one figure.  ``set_figure`` /
  ``clear`` are intended to be called only from the Tk main thread.

* :class:`PlotPreviewWindow` — a separate ``tk.Toplevel`` pop-up that hosts
  a load dropdown, a ``Preview`` button, a ``Save preview image`` button and
  a :class:`PlotPreviewFrame` canvas.  Opening it is manual (a ``Plot
  preview`` button in the main window), so the main window stays compact.

Both are pure view: figure building is delegated to
:func:`etabs_extractor.plots.build_base_reactions_figure` (via the caller) and
matplotlib is imported lazily (inside methods / on first canvas use).
tkinter  is imported at module level only for the class definitions — no root
window is created at import time, so the module imports fine with no display.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

_NOTE = "Select a load to preview (or run Extract/Load preview)."


class PlotPreviewFrame(tk.Frame):
    """A frame that hosts an embedded matplotlib canvas (created lazily)."""

    def __init__(self, master, *, width: int = 720, height: int = 480) -> None:
        super().__init__(master)
        self._canvas = None
        self._size = (width, height)
        self._empty_label = tk.Label(
            self, text=_NOTE, fg="gray", width=40, height=10, relief="sunken"
        )
        self._empty_label.pack(fill="both", expand=True, padx=4, pady=4)

    def _ensure_canvas(self):
        if self._canvas is None:
            import matplotlib  # noqa: PLC0415
            matplotlib.use("TkAgg")
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: PLC0415

            # Placeholder figure to attach the canvas.
            import matplotlib.pyplot as plt  # noqa: PLC0415

            self._placeholder = plt.figure(figsize=(self._size[0] / 100, self._size[1] / 100))
            self._canvas = FigureCanvasTkAgg(self._placeholder, master=self)
            self._empty_label.pack_forget()
            self._canvas.get_tk_widget().pack(fill="both", expand=True)
        return self._canvas

    def set_figure(self, fig) -> None:
        """Display ``fig`` (a matplotlib Figure) in the canvas."""
        canvas = self._ensure_canvas()
        # Drop the previous figure if it was our placeholder.
        old = getattr(self, "_current_fig", None)
        if old is not None and old is not self._placeholder:
            try:
                import matplotlib.pyplot as plt  # noqa: PLC0415
                plt.close(old)
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
        self._current_fig = fig
        try:
            # Attach the figure to the canvas (bypasses pyright's strict
            # FigureCanvasTkAgg.figure typing via setattr) and redraw.
            setattr(canvas, "figure", fig)
            canvas.draw()
        except Exception:  # noqa: BLE001 - canvas not ready; fall back to label
            pass

    def clear(self) -> None:
        """Reset to the empty placeholder."""
        if self._canvas is not None:
            try:
                setattr(self._canvas, "figure", getattr(self, "_placeholder", None))
                self._canvas.draw()
            except Exception:  # noqa: BLE001 - best-effort
                pass
            self._current_fig = None

    def get_canvas(self):
        """Return the TkAgg canvas, creating it on first access (may need a
        display)."""
        return self._ensure_canvas()

    def current_figure(self):
        """Return the figure currently displayed (or ``None``)."""
        return getattr(self, "_current_fig", None)


class PlotPreviewWindow(tk.Toplevel):
    """A separate pop-up window hosting the plot preview.

    Contains a load dropdown, ``Preview`` and ``Save preview image`` buttons,
    and a :class:`PlotPreviewFrame` canvas.  The window is opened manually via
    a ``Plot preview`` button in the main window; it is *not* auto-popped
    after Extract / Load-preview.

    The window receives callbacks from the owning application:

    * ``settings_provider`` — ``() -> GuiSettings``, used to build figure
      kwargs and read the save dpi/format.
    * ``figure_builder`` — ``(per_load_df, load_name, settings) ->
      matplotlib.Figure | None``, the :func:`build_base_reactions_figure`
      call (kept in the app so this widget stays pure view).
    * ``on_preview_load`` / ``on_save_preview`` — view-only handlers that
      render the selected load into the canvas / save the current figure.
    """

    def __init__(
        self,
        master,
        *,
        settings_provider,
        figure_builder,
        log=None,
        closed=None,
    ) -> None:
        super().__init__(master)
        self.title("Plot preview")
        self.geometry("720x540")
        self.minsize(480, 360)
        # Keep it above the main window but non-modal (manual open/reuse).
        self.transient(master)
        self._settings_provider = settings_provider
        self._figure_builder = figure_builder
        self._log = log
        self._closed = closed
        self._result = None
        self._per_load: dict = {}
        self._current_fig = None
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="Load:").pack(side="left")
        self.load_combo = ttk.Combobox(top, state="readonly", width=30)
        self.load_combo.pack(side="left", padx=6)
        self.load_combo.bind("<<ComboboxSelected>>", lambda e: self._render_current())
        ttk.Button(top, text="Preview", command=self._render_current).pack(side="left", padx=4)
        ttk.Button(top, text="Save preview image", command=self._save_preview).pack(side="left", padx=4)

        self.preview = PlotPreviewFrame(self, width=660, height=440)
        self.preview.pack(fill="both", expand=True, padx=8, pady=8)

    # ------------------------------------------------------------------ api
    def set_result(self, result: dict) -> None:
        """Set the extraction/load result dict and populate the load combo."""
        self._result = result or {}
        self._per_load = self._result.get("per_load") or {}
        load_names = self._result.get("load_names") or []
        self.load_combo.configure(values=load_names)
        if load_names:
            self.load_combo.current(0)
        self.preview.clear()

    def is_alive(self) -> bool:
        """True while the Toplevel still exists on screen."""
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    # --------------------------------------------------------------- render
    def _render_current(self) -> None:
        if not self._per_load:
            return
        load_name = self.load_combo.get()
        per_load = self._per_load
        if not load_name or load_name not in per_load:
            return
        settings = self._settings_provider() if self._settings_provider else None
        try:
            fig = self._figure_builder(per_load[load_name], load_name, settings)
        except ImportError as exc:  # e.g. matplotlib not installed (Windows py)
            if self._log:
                self._log(f"Preview needs matplotlib: {exc}. Install it on the "
                          f"Windows Python (pip install matplotlib).")
            return
        except Exception as exc:  # noqa: BLE001
            if self._log:
                self._log(f"Preview failed: {exc}")
            return
        if fig is not None:
            self._current_fig = fig
            self.preview.set_figure(fig)
        else:
            self._current_fig = None
            self.preview.clear()

    def _save_preview(self) -> None:
        """Save the current preview figure at the chosen dpi/format."""
        current = self._current_fig
        if current is None:
            messagebox.showinfo("Save preview", "No preview figure to save.")
            return
        settings = self._settings_provider() if self._settings_provider else None
        fmt = getattr(settings, "format", "png") if settings else "png"
        dpi = getattr(settings, "dpi", 800) if settings else 800
        default_name = (
            f"base_{self.load_combo.get() or 'preview'}_preview_{fmt}"
        )
        path = filedialog.asksaveasfilename(
            defaultextension=f".{fmt}",
            filetypes=[(fmt.upper(), f"*.{fmt}")],
            initialfile=default_name,
        )
        if not path:
            return
        try:
            current.savefig(path, dpi=dpi, bbox_inches="tight")
            if self._log:
                self._log(f"Saved preview image: {path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save preview", f"Could not save: {exc}")

    # ---------------------------------------------------------------- close
    def _on_close(self) -> None:
        """Close the pop-up; the main window stays alive."""
        try:
            self.destroy()
        except tk.TclError:
            pass
        if self._closed:
            self._closed(self)