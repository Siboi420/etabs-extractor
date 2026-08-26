"""Plot-preview widgets for the etabs_extractor GUI.

Three pieces:

* :class:`PlotPreviewFrame` — an embedded matplotlib canvas (a
  ``FigureCanvasTkAgg`` host) for showing one figure.

* :class:`PlotPreviewWindow` — a separate ``tk.Toplevel`` pop-up that hosts
  a load dropdown, a ``Preview`` button, a ``Save preview image`` button and
  a :class:`PlotPreviewFrame` canvas for base-reaction plan views.

* :class:`FramePreviewWindow` — a pop-up with load/section/step/force-type/
  length dropdowns for beam force diagram previews after frame extraction.
  Preview always shows the beam with the highest |force| at the selected
  section + length + load.  "Batch plot all" overlays every beam of that
  length on one diagram (★ = highest-force beam).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

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
        ttk.Button(top, text="Refresh", command=self._refresh_settings).pack(side="left", padx=4)
        ttk.Button(top, text="Save preview image", command=self._save_preview).pack(side="left", padx=4)

        self.preview = PlotPreviewFrame(self, width=660, height=440)
        self.preview.pack(fill="both", expand=True, padx=8, pady=8)

    # ------------------------------------------------------------------ api
    def set_result(self, result: dict) -> None:
        """Set the extraction/load result dict, populate the load combo, and
        auto-render the first load with the current plot settings."""
        self._result = result or {}
        self._per_load = self._result.get("per_load") or {}
        load_names = self._result.get("load_names") or []
        self.load_combo.configure(values=load_names)
        if load_names:
            self.load_combo.current(0)
            # Apply the current plot appearance immediately instead of leaving
            # the canvas empty until the user presses Preview/Refresh.
            self._render_current()
        else:
            self.preview.clear()

    def _refresh_settings(self) -> None:
        """Re-capture the plot settings from the main window and re-render the
        currently selected load (the ``settings_provider`` reads the main
        window's plot widgets fresh on every call)."""
        if self._log:
            self._log("Refreshed preview with current plot settings.")
        self._render_current()

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


class FramePreviewWindow(tk.Toplevel):
    """A separate pop-up window hosting beam force diagram previews.

    Used in frame-extraction mode.  Contains load, section, and beam
    dropdowns plus Preview / Save / Refresh buttons and a
    :class:`PlotPreviewFrame` canvas.  Manual-open only.

    Unlike :class:`PlotPreviewWindow` (which uses per_load data and
    ``build_base_reactions_figure``), this window receives the full
    consolidated DataFrame and lets the user pick a load, section, and
    beam to preview.
    """

    def __init__(
        self,
        master,
        *,
        figure_builder,         # (df, frame, load_name, section, step_type) -> Figure | None
        batch_figure_builder,   # (df, load_name, section, length_mm, force_col, step_type) -> Figure | None
        log=None,
        closed=None,
    ) -> None:
        super().__init__(master)
        self.title("Frame force preview")
        self.geometry("820x620")
        self.minsize(600, 440)
        self.transient(master)
        self._figure_builder = figure_builder
        self._batch_figure_builder = batch_figure_builder
        self._log = log
        self._closed = closed
        self._df: pd.DataFrame | None = None
        self._current_fig = None
        self._length_map: dict[str, float] = {}
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # -- Selector row: Load, Section, Step, Force, Length ---------------
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)

        ttk.Label(top, text="Load:").pack(side="left")
        self.load_combo = ttk.Combobox(top, state="readonly", width=18)
        self.load_combo.pack(side="left", padx=4)
        self.load_combo.bind("<<ComboboxSelected>>", self._on_selection_change)

        ttk.Label(top, text="Section:").pack(side="left", padx=(8, 0))
        self.section_combo = ttk.Combobox(top, state="readonly", width=8)
        self.section_combo.pack(side="left", padx=4)
        self.section_combo.bind("<<ComboboxSelected>>", self._on_section_change)

        ttk.Label(top, text="Step:").pack(side="left", padx=(8, 0))
        self.step_combo = ttk.Combobox(top, state="readonly", width=7,
                                       values=("Both", "Max", "Min"))
        self.step_combo.pack(side="left", padx=4)
        self.step_combo.current(0)
        self.step_combo.bind("<<ComboboxSelected>>", self._on_selection_change)

        ttk.Label(top, text="Force:").pack(side="left", padx=(8, 0))
        self.force_combo = ttk.Combobox(
            top, state="readonly", width=10,
            values=("Moment (M3)", "Shear (V2)", "Axial (P)"),
        )
        self.force_combo.pack(side="left", padx=4)
        self.force_combo.current(0)
        self.force_combo.bind("<<ComboboxSelected>>", self._on_selection_change)

        ttk.Label(top, text="Length:").pack(side="left", padx=(8, 0))
        self.length_combo = ttk.Combobox(top, state="readonly", width=9)
        self.length_combo.pack(side="left", padx=4)
        self.length_combo.bind("<<ComboboxSelected>>", self._on_selection_change)

        # -- Button row 1: Preview / Refresh / Save -------------------------
        btn1 = ttk.Frame(self)
        btn1.pack(fill="x", padx=8, pady=(0, 2))
        ttk.Button(btn1, text="Preview", command=self._render_current).pack(side="left", padx=4)
        ttk.Button(btn1, text="Refresh", command=self._refresh_settings).pack(side="left", padx=4)
        ttk.Button(btn1, text="Save preview image", command=self._save_preview).pack(side="left", padx=4)

        # -- Button row 2: Batch plot all -----------------------------------
        btn2 = ttk.Frame(self)
        btn2.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Button(btn2, text="Batch plot all (overlay)",
                   command=self._batch_plot).pack(side="left", padx=4)
        ttk.Label(
            btn2, text="All beams overlaid in one diagram; ★ = highest |force|",
            foreground="#777", font=("", 8),
        ).pack(side="left", padx=4)

        # -- Canvas -----------------------------------------------------------
        self.preview = PlotPreviewFrame(self, width=720, height=500)
        self.preview.pack(fill="both", expand=True, padx=8, pady=4)

    # ------------------------------------------------------------------ api
    def set_result(self, result: dict) -> None:
        """Set the extraction result dict and populate all dropdowns."""
        self._df = result.get("df")
        if self._df is None or self._df.empty:
            if self._log:
                self._log("No frame data available for preview.")
            return

        df = self._df
        sections = sorted(df["section"].unique())
        loads = sorted(df["load_name"].unique())

        self.load_combo.configure(values=loads)
        self.section_combo.configure(values=sections)

        if loads:
            self.load_combo.current(0)
        if sections:
            self.section_combo.current(0)
        self._populate_lengths()
        if self.length_combo.cget("values"):
            self.length_combo.current(0)

        self._render_current()

    # ---------------------------------------------------------------- helpers
    @property
    def _force_col(self) -> str:
        label = self.force_combo.get()
        return {"Moment (M3)": "M3", "Shear (V2)": "V2", "Axial (P)": "P"}.get(label, "M3")

    def _get_highest_frame(self) -> str | None:
        """Return the frame with the highest |force_col| at the current
        selection, or None if no data."""
        section = self.section_combo.get()
        length_label = self.length_combo.get()
        load_name = self.load_combo.get()
        if not section or not length_label or not load_name or self._df is None:
            return None
        length_mm = self._length_map.get(length_label, 0)
        import sys as _sys, os as _os
        _repo = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", ".."))
        if _repo not in _sys.path:
            _sys.path.insert(0, _repo)
        from beam_viewer import find_highest_force_frame  # noqa: PLC0415
        return find_highest_force_frame(
            self._df, section, load_name,
            force_col=self._force_col, length_mm=length_mm,
        )

    def _populate_lengths(self) -> None:
        """Fill the length dropdown from the selected section."""
        section = self.section_combo.get()
        if not section or self._df is None:
            self.length_combo.configure(values=[])
            return
        import sys as _sys, os as _os
        _repo = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", ".."))
        if _repo not in _sys.path:
            _sys.path.insert(0, _repo)
        from beam_viewer import get_lengths_for_section  # noqa: PLC0415
        lengths = get_lengths_for_section(self._df, section)
        labels = [f"{l/1000:.2f}m" for l in lengths]
        self._length_map = dict(zip(labels, lengths))
        self.length_combo.configure(values=labels)

    # ------------------------------------------------------------ callbacks
    def _on_section_change(self, _event=None) -> None:
        self._populate_lengths()
        if self.length_combo.cget("values"):
            self.length_combo.current(0)
        self._render_current()

    def _on_selection_change(self, _event=None) -> None:
        """Auto-render on any dropdown change (load, step, force, length)."""
        self._render_current()

    def _refresh_settings(self) -> None:
        if self._log:
            self._log("Refreshed frame preview.")
        self._render_current()

    def is_alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    # --------------------------------------------------------------- render
    def _render_current(self) -> None:
        if self._df is None or self._df.empty:
            return
        load_name = self.load_combo.get()
        section = self.section_combo.get()
        step_val = self.step_combo.get()
        if not load_name or not section:
            return
        step_type = None if step_val == "Both" else step_val

        # Auto-find the highest-force beam
        frame_val = self._get_highest_frame()
        if frame_val is None:
            if self._log:
                self._log(f"No data for {section} / {load_name}")
            return

        try:
            fig = self._figure_builder(self._df, frame_val, load_name, section,
                                       step_type=step_type)
        except ImportError as exc:
            msg = f"Preview needs matplotlib: {exc}."
            if self._log:
                self._log(msg)
            messagebox.showerror("Frame preview", msg)
            return
        except Exception as exc:  # noqa: BLE001
            msg = f"Preview failed: {exc}"
            if self._log:
                self._log(msg)
            messagebox.showerror("Frame preview", msg)
            return
        if fig is not None:
            self._current_fig = fig
            self.preview.set_figure(fig)
            if self._log:
                self._log(f"Beam {frame_val} (highest |{self._force_col}|) — {section} {load_name}")
        else:
            self._current_fig = None
            self.preview.clear()

    # ---------------------------------------------------------------- save
    def _save_preview(self) -> None:
        current = self._current_fig
        if current is None:
            messagebox.showinfo("Save preview", "No preview figure to save.")
            return
        load = self.load_combo.get() or "preview"
        sec = self.section_combo.get() or "X"
        step = self.step_combo.get() or "X"
        default_name = f"frame_{sec}_{load}_{step}_diagram.png"
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")],
            initialfile=default_name,
        )
        if not path:
            return
        import os  # noqa: PLC0415
        _ext = os.path.splitext(path)[1].lower()
        _fmt = _ext.lstrip(".") if _ext else "png"
        try:
            current.savefig(path, dpi=150, bbox_inches="tight", format=_fmt)
            if self._log:
                self._log(f"Saved frame preview: {path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save preview", f"Could not save: {exc}")

    def _batch_plot(self) -> None:
        """Render overlay of all beams at the selected section + length."""
        section = self.section_combo.get()
        length_label = self.length_combo.get()
        load_name = self.load_combo.get()
        step_val = self.step_combo.get()
        if not section or not length_label or not load_name or self._df is None:
            return
        length_mm = self._length_map.get(length_label, 0)
        step_type = None if step_val == "Both" else step_val

        try:
            fig = self._batch_figure_builder(
                self._df, load_name, section, length_mm,
                force_col=self._force_col, step_type=step_type,
            )
        except ImportError as exc:
            msg = f"Batch plot needs matplotlib: {exc}."
            if self._log:
                self._log(msg)
            messagebox.showerror("Batch plot", msg)
            return
        except Exception as exc:  # noqa: BLE001
            msg = f"Batch plot failed: {exc}"
            if self._log:
                self._log(msg)
            messagebox.showerror("Batch plot", msg)
            return
        if fig is not None:
            self._current_fig = fig
            self.preview.set_figure(fig)
            if self._log:
                self._log(f"Batch plot: {len(fig.axes)//3} beam(s) at {section} {length_label}")
        else:
            self._current_fig = None
            self.preview.clear()
            if self._log:
                self._log("Batch plot produced no data.")

    # ---------------------------------------------------------------- close
    def _on_close(self) -> None:
        try:
            self.destroy()
        except tk.TclError:
            pass
        if self._closed:
            self._closed(self)