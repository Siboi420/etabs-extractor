"""Embedded plot-preview panels for the etabs_extractor GUI.

Three pieces, all embedded directly in the main window's workspace tabs
(there are no separate pop-up windows):

* :class:`PlotCanvas` — an embedded matplotlib canvas + navigation toolbar
  (a ``FigureCanvasTkAgg`` host) for showing one figure, with an empty-state
  placeholder.  Matplotlib is imported lazily so importing this module never
  requires it.

* :class:`BasePreviewPanel` — a load dropdown, Refresh / Save image buttons
  and a :class:`PlotCanvas` for base-reaction plan views.

* :class:`FramePreviewPanel` — load/section/step/force-type/length dropdowns,
  Refresh / Save image / Batch plot all, and a :class:`PlotCanvas` for beam
  force diagram previews after frame extraction.  Preview always shows the
  beam with the highest |force| at the selected section + length + load.
  "Batch plot all" overlays every beam of that length on one diagram
  (star = highest-force beam).
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk

from etabs_extractor.gui.state import STEP_CHOICES

if TYPE_CHECKING:
    import pandas as pd

_NOTE = "Select a load to preview (or run Extract/Load preview)."

# Dropdown label -> plots.STEP_VARIANTS entry.
_STEP_VARIANT = {"Abs max": "absmax", "Max": "max", "Min": "min"}


def load_beam_viewer():
    """Lazily import ``beam_viewer.py`` (repo root, three levels above this
    file: widgets -> gui -> etabs_extractor -> repo root)."""
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    import beam_viewer

    return beam_viewer


class PlotCanvas(tk.Frame):
    """An embedded matplotlib figure canvas with a navigation toolbar and an
    empty-state placeholder.  Matplotlib is only imported when a figure is
    first shown, so importing this module needs no display/matplotlib.

    Deliberately a **plain ``tk.Frame``, not a ``ctk.CTkFrame``**: every
    customtkinter widget draws itself on an internal background ``CTkCanvas``
    (``place()``-managed, covering the widget's full rectangle) that competes
    for mouse events with any raw Tk widget packed inside it, which broke the
    matplotlib toolbar's pan/zoom outright when this was a ``CTkFrame``
    (confirmed empirically — see AGENTS.md). A plain frame has no such
    machinery. It's fine for this to sit *inside* a ``ctk.CTkFrame`` ancestor
    (``BasePreviewPanel``/``FramePreviewPanel``) — only this immediate host
    of the canvas+toolbar must not itself be a ``CTk*`` widget.
    """

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._mpl_canvas = None
        self._toolbar = None
        self._figure = None
        self._placeholder = ctk.CTkLabel(
            self, text=_NOTE, text_color="gray", wraplength=400,
        )
        self._placeholder.pack(fill="both", expand=True)
        self.sync_theme()

    def sync_theme(self) -> None:
        """Match this plain tk.Frame's background to the current ctk
        appearance mode (it has no automatic theming of its own)."""
        light, dark = ctk.ThemeManager.theme["CTkFrame"]["fg_color"]
        color = dark if ctk.get_appearance_mode() == "Dark" else light
        self.configure(bg=color)

    def _ensure_canvas(self):
        if self._mpl_canvas is not None:
            return self._mpl_canvas
        import matplotlib
        matplotlib.use("TkAgg")
        from matplotlib.backends.backend_tkagg import (
            FigureCanvasTkAgg,
            NavigationToolbar2Tk,  # type: ignore[reportPrivateImportUsage]
        )
        from matplotlib.figure import Figure

        self._placeholder.pack_forget()
        fig = Figure()
        self._mpl_canvas = FigureCanvasTkAgg(fig, master=self)
        self._toolbar = NavigationToolbar2Tk(self._mpl_canvas, self, pack_toolbar=False)
        self._toolbar.pack(side="bottom", fill="x")
        self._mpl_canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        return self._mpl_canvas

    def set_figure(self, fig) -> None:
        """Show ``fig`` (a matplotlib Figure), replacing/closing any current one."""
        import matplotlib.pyplot as plt

        canvas = self._ensure_canvas()
        old = self._figure
        canvas.figure = fig
        self._figure = fig
        canvas.draw_idle()
        if old is not None and old is not fig:
            plt.close(old)

    def clear(self) -> None:
        import matplotlib.pyplot as plt

        if self._figure is not None:
            plt.close(self._figure)
            self._figure = None
        if self._mpl_canvas is not None:
            self._mpl_canvas.figure.clf()
            self._mpl_canvas.draw_idle()
        else:
            self._placeholder.pack(fill="both", expand=True)

    def get_canvas(self):
        return self._mpl_canvas

    def current_figure(self):
        return self._figure


class BasePreviewPanel(ctk.CTkFrame):
    """Embedded preview panel for base-reaction plan-view plots.

    Callbacks from the owning application:

    * ``settings_provider`` — ``() -> GuiSettings``, used to build figure
      kwargs and read the save dpi/format.
    * ``figure_builder`` — ``(df, load_name, settings, *, step) ->
      matplotlib.Figure | None`` (the :func:`build_base_reactions_figure`
      call, kept in the app so this widget stays pure view).
    * ``batch_saver`` — ``(settings) -> None`` (the app's
      :func:`~etabs_extractor.gui.service.save_batch_plots` background-job
      entry point).  Optional; the Batch save button is inert without it.
    """

    def __init__(
        self, master, *, settings_provider, figure_builder, log=None,
        batch_saver=None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._settings_provider = settings_provider
        self._figure_builder = figure_builder
        self._batch_saver = batch_saver
        self._log = log
        self._result: dict = {}
        self._per_load: dict = {}
        self._current_fig = None

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=4, pady=(0, 6))
        ctk.CTkLabel(top, text="Load:").pack(side="left")
        self.load_var = ctk.StringVar(value="")
        self.load_menu = ctk.CTkOptionMenu(
            top, values=[], variable=self.load_var, width=180,
            command=lambda _v: self._render_current(),
        )
        self.load_menu.pack(side="left", padx=6)
        ctk.CTkLabel(top, text="Step:").pack(side="left")
        self.step_var = ctk.StringVar(value=STEP_CHOICES[0])
        self.step_menu = ctk.CTkOptionMenu(
            top, values=list(STEP_CHOICES), variable=self.step_var, width=90,
            command=lambda _v: self._render_current(),
        )
        self.step_menu.pack(side="left", padx=6)
        ctk.CTkButton(top, text="Refresh", command=self._refresh_settings, width=80).pack(side="left", padx=4)
        ctk.CTkButton(top, text="Save image...", command=self._save_preview, width=100).pack(side="left", padx=4)
        self.batch_btn = ctk.CTkButton(
            top, text="Batch save plots...", command=self._batch_save, width=140,
        )
        self.batch_btn.pack(side="left", padx=4)

        self.preview = PlotCanvas(self)
        self.preview.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ api
    def set_result(self, result: dict) -> None:
        """Set the extraction/load result dict, populate the load dropdown,
        and auto-render the first load with the current plot settings."""
        self._result = result or {}
        self._per_load = self._result.get("per_load") or {}
        load_names = self._result.get("load_names") or []
        self.load_menu.configure(values=load_names)
        if load_names:
            self.load_var.set(load_names[0])
            self._render_current()
        else:
            self.load_var.set("")
            self.preview.clear()

    def _refresh_settings(self) -> None:
        if self._log:
            self._log("Refreshed preview with current plot settings.")
        self._render_current()

    # --------------------------------------------------------------- render
    def _render_current(self) -> None:
        load_name = self.load_var.get()
        df = self._per_load.get(load_name)
        if not load_name or df is None:
            return
        settings = self._settings_provider()
        step = _STEP_VARIANT.get(self.step_var.get(), "absmax")
        try:
            fig = self._figure_builder(df, load_name, settings, step=step)
            if fig is None and step != "absmax":
                # No Max/Min rows for this load (plain case / legacy CSV):
                # fall back to the abs-max view instead of an empty canvas.
                if self._log:
                    self._log(
                        f"No {self.step_var.get()} steps for {load_name} — "
                        "showing abs max."
                    )
                fig = self._figure_builder(df, load_name, settings, step="absmax")
        except ImportError as exc:
            msg = f"Preview needs matplotlib: {exc}."
            if self._log:
                self._log(msg)
            messagebox.showerror("Plot preview", msg)
            return
        except Exception as exc:  # noqa: BLE001
            msg = f"Preview failed: {exc}"
            if self._log:
                self._log(msg)
            messagebox.showerror("Plot preview", msg)
            return
        if fig is not None:
            self._current_fig = fig
            self.preview.set_figure(fig)
            if self._log:
                step_note = "" if step == "absmax" else f" [{step}]"
                self._log(f"Previewing {load_name}{step_note} ({len(df)} points).")
        else:
            self._current_fig = None
            self.preview.clear()
            if self._log:
                self._log(f"No plottable points for {load_name}.")

    # ---------------------------------------------------------------- batch
    def _batch_save(self) -> None:
        """Hand the current settings to the app's batch-saver (background job
        writing absmax/max/min plots for every load into the Batch plot dir)."""
        if not self._result:
            messagebox.showwarning(
                "Batch save plots", "Run Extract or Load preview first (no result loaded)."
            )
            return
        if self._batch_saver is None:
            messagebox.showinfo("Batch save plots", "Batch saving is not configured.")
            return
        self._batch_saver(self._settings_provider())

    # ---------------------------------------------------------------- save
    def _save_preview(self) -> None:
        current = self._current_fig
        if current is None:
            messagebox.showinfo("Save preview", "No preview figure to save.")
            return
        settings = self._settings_provider()
        load = self.load_var.get() or "preview"
        default_name = f"base_{load}_plan.{settings.format}"
        path = filedialog.asksaveasfilename(
            defaultextension=f".{settings.format}",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")],
            initialfile=default_name,
        )
        if not path:
            return
        try:
            current.savefig(path, dpi=settings.dpi, bbox_inches="tight")
            if self._log:
                self._log(f"Saved preview: {path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save preview", f"Could not save: {exc}")


class FramePreviewPanel(ctk.CTkFrame):
    """Embedded preview panel for beam force diagrams (frame-extraction mode).

    Unlike :class:`BasePreviewPanel` (which uses per-load data and
    ``build_base_reactions_figure``), this panel receives the full
    consolidated DataFrame and lets the user pick a load, section, and
    length to preview; the beam shown is always the one with the highest
    |force| at that selection.
    """

    def __init__(self, master, *, figure_builder, batch_figure_builder, log=None) -> None:
        super().__init__(master, fg_color="transparent")
        self._figure_builder = figure_builder
        self._batch_figure_builder = batch_figure_builder
        self._log = log
        self._df: pd.DataFrame | None = None
        self._current_fig = None
        self._length_map: dict[str, float] = {}

        # -- Selector row: Load, Section, Step, Force, Length ---------------
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=4, pady=(0, 4))

        ctk.CTkLabel(top, text="Load:").pack(side="left")
        self.load_var = ctk.StringVar(value="")
        self.load_menu = ctk.CTkOptionMenu(top, values=[], variable=self.load_var, width=110,
                                           command=lambda _v: self._on_selection_change())
        self.load_menu.pack(side="left", padx=(4, 8))

        ctk.CTkLabel(top, text="Section:").pack(side="left")
        self.section_var = ctk.StringVar(value="")
        self.section_menu = ctk.CTkOptionMenu(top, values=[], variable=self.section_var, width=80,
                                              command=lambda _v: self._on_section_change())
        self.section_menu.pack(side="left", padx=(4, 8))

        ctk.CTkLabel(top, text="Step:").pack(side="left")
        self.step_var = ctk.StringVar(value="Both")
        self.step_menu = ctk.CTkOptionMenu(top, values=["Both", "Max", "Min"], variable=self.step_var,
                                           width=80, command=lambda _v: self._on_selection_change())
        self.step_menu.pack(side="left", padx=(4, 8))

        ctk.CTkLabel(top, text="Force:").pack(side="left")
        self.force_var = ctk.StringVar(value="Moment (M3)")
        self.force_menu = ctk.CTkOptionMenu(
            top, values=["Moment (M3)", "Shear (V2)", "Axial (P)"], variable=self.force_var,
            width=110, command=lambda _v: self._on_selection_change(),
        )
        self.force_menu.pack(side="left", padx=(4, 8))

        ctk.CTkLabel(top, text="Length:").pack(side="left")
        self.length_var = ctk.StringVar(value="")
        self.length_menu = ctk.CTkOptionMenu(top, values=[], variable=self.length_var, width=90,
                                             command=lambda _v: self._on_selection_change())
        self.length_menu.pack(side="left", padx=(4, 0))

        # -- Button row 1: Refresh / Save -------------------------
        btn1 = ctk.CTkFrame(self, fg_color="transparent")
        btn1.pack(fill="x", padx=4, pady=(0, 2))
        ctk.CTkButton(btn1, text="Refresh", command=self._refresh_settings, width=80).pack(side="left", padx=4)
        ctk.CTkButton(btn1, text="Save image...", command=self._save_preview, width=100).pack(side="left", padx=4)
        ctk.CTkButton(btn1, text="Batch plot all (overlay)", command=self._batch_plot, width=170).pack(side="left", padx=4)
        ctk.CTkLabel(
            btn1, text="* = highest |force|", text_color="gray",
        ).pack(side="left", padx=8)

        # -- Canvas -----------------------------------------------------------
        self.preview = PlotCanvas(self)
        self.preview.pack(fill="both", expand=True)

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

        self.load_menu.configure(values=loads)
        self.section_menu.configure(values=sections)

        if loads:
            self.load_var.set(loads[0])
        if sections:
            self.section_var.set(sections[0])
        self._populate_lengths()
        lengths = list(self.length_menu.cget("values") or [])
        if lengths:
            self.length_var.set(lengths[0])
        self._render_current()

    # ---------------------------------------------------------------- helpers
    @property
    def _force_col(self) -> str:
        label = self.force_var.get()
        return {"Moment (M3)": "M3", "Shear (V2)": "V2", "Axial (P)": "P"}.get(label, "M3")

    def _get_highest_frame(self) -> int | str | None:
        """Return the frame with the highest |force_col| at the current
        selection, or None if no data."""
        section = self.section_var.get()
        length_label = self.length_var.get()
        load_name = self.load_var.get()
        if not section or not length_label or not load_name or self._df is None:
            return None
        length_mm = self._length_map.get(length_label, 0)
        bv = load_beam_viewer()
        return bv.find_highest_force_frame(
            self._df, section, load_name,
            force_col=self._force_col, length_mm=length_mm,
        )

    def _populate_lengths(self) -> None:
        """Fill the length dropdown from the selected section."""
        section = self.section_var.get()
        if not section or self._df is None:
            self.length_menu.configure(values=[])
            return
        bv = load_beam_viewer()
        lengths = bv.get_lengths_for_section(self._df, section)
        lf = bv._length_scale(bv._data_units(self._df))
        labels = [f"{length * lf:.2f}m" for length in lengths]
        self._length_map = dict(zip(labels, lengths, strict=True))
        self.length_menu.configure(values=labels)

    # ------------------------------------------------------------ callbacks
    def _on_section_change(self) -> None:
        self._populate_lengths()
        lengths = list(self.length_menu.cget("values") or [])
        if lengths:
            self.length_var.set(lengths[0])
        self._render_current()

    def _on_selection_change(self) -> None:
        """Re-render on any dropdown change (load, step, force, length)."""
        self._render_current()

    def _refresh_settings(self) -> None:
        if self._log:
            self._log("Refreshed frame preview.")
        self._render_current()

    # --------------------------------------------------------------- render
    def _render_current(self) -> None:
        if self._df is None or self._df.empty:
            return
        load_name = self.load_var.get()
        section = self.section_var.get()
        step_val = self.step_var.get()
        if not load_name or not section:
            return
        step_type = None if step_val == "Both" else step_val

        try:
            frame_val = self._get_highest_frame()
        except ImportError as exc:
            msg = f"Preview needs matplotlib: {exc}."
            if self._log:
                self._log(msg)
            messagebox.showerror("Frame preview", msg)
            return
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
                self._log(f"Beam {frame_val} (highest |{self._force_col}|) - {section} {load_name}")
        else:
            self._current_fig = None
            self.preview.clear()

    # ---------------------------------------------------------------- save
    def _save_preview(self) -> None:
        current = self._current_fig
        if current is None:
            messagebox.showinfo("Save preview", "No preview figure to save.")
            return
        load = self.load_var.get() or "preview"
        sec = self.section_var.get() or "X"
        step = self.step_var.get() or "X"
        default_name = f"frame_{sec}_{load}_{step}_diagram.png"
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")],
            initialfile=default_name,
        )
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        fmt = ext.lstrip(".") if ext else "png"
        try:
            current.savefig(path, dpi=150, bbox_inches="tight", format=fmt)
            if self._log:
                self._log(f"Saved frame preview: {path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save preview", f"Could not save: {exc}")

    def _batch_plot(self) -> None:
        """Render overlay of all beams at the selected section + length."""
        section = self.section_var.get()
        length_label = self.length_var.get()
        load_name = self.load_var.get()
        step_val = self.step_var.get()
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
