"""Main application window for the etabs_extractor GUI.

Composes the model/destination/tag rows, combo selection, plot settings and
preview canvas, and wires the buttons to worker-threaded extraction /
plotting.  All real work is delegated to
:func:`~etabs_extractor.gui.service`; Tk is only used as the view layer.
Creating an instance requires a display; importing the module does not.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from etabs_extractor.config import resolve_output_dir
from etabs_extractor.gui.state import GuiSettings, parse_elevation
from etabs_extractor.gui.service import (
    build_extract_kwargs,
    build_figure_kwargs,
    build_plot_kwargs,
    load_from_csv,
    sanitize_tag,
)
from etabs_extractor.gui.widgets.fields import DirectoryField, FileField, LabeledEntry
from etabs_extractor.gui.widgets.load_selection import LoadSelectionField
from etabs_extractor.gui.widgets.plot_settings import PlotSettingsFrame
from etabs_extractor.gui.widgets.preview import FramePreviewWindow, PlotPreviewWindow


class EtabsExtractorApp(tk.Tk):
    """The GUI root window."""

    def __init__(self) -> None:
        super().__init__()
        self.title("etabs_extractor — base reactions & frame forces")
        self.geometry("980x640")
        self.minsize(760, 560)

        self._settings = GuiSettings()
        self._runner = None
        self._result = None      # last extraction/load result dict
        self._preview_win = None # the open plot-preview pop-up (or None)
        self._frame_preview_win = None  # the open frame-preview pop-up (or None)
        self._poll_id = None

        self._build_layout()
        self._drain_pending()

    # ------------------------------------------------------------------ layout
    def _build_layout(self) -> None:
        # Widgets scoped to the active extraction mode are registered here so
        # the mode radios can show/hide them via pack()/pack_forget().  Default
        # mode is "base", so base-only widgets are packed at build; the
        # frame-only selector is created but not yet packed (revealed by
        # _apply_mode).
        self._base_only: dict[str, tuple] = {}
        self._frame_only: dict[str, tuple] = {}

        def _reg(target, key, widget, **kwargs):
            target[key] = (widget, kwargs)
            return widget

        # -- Model / destination / tag rows ---------------------------------
        frame = ttk.LabelFrame(self, text="Model & output")
        frame.pack(fill="x", padx=8, pady=4)
        self.model_field = FileField(
            frame, "Model", "",
            filetypes="ETABS model", patterns=("*.EDB", "*.edb", "*.et"),
        )
        self.model_field.pack(fill="x", padx=6, pady=3)
        row = ttk.Frame(frame)
        row.pack(fill="x", padx=6, pady=3)
        self.check_btn = ttk.Button(
            row, text="Check active model", command=self.on_check_model
        )
        self.check_btn.pack(side="left")
        self.model_status = tk.StringVar(value="")
        ttk.Label(row, textvariable=self.model_status, foreground="#444").pack(side="left", padx=8)

        self.output_field = DirectoryField(
            frame, "Output dir", str(resolve_output_dir())
        )
        self.output_field.pack(fill="x", padx=6, pady=3)
        self.tag_field = LabeledEntry(frame, "Tag", "")
        self.tag_field.pack(fill="x", padx=6, pady=3)

        # -- Extraction mode switch (radio; default base) --------------------
        mode = ttk.LabelFrame(self, text="Extraction mode")
        mode.pack(fill="x", padx=8, pady=4)
        self.mode_var = tk.StringVar(value="base")
        for _label, _val in (( "Base reactions", "base"), ("Frame forces", "frame")):
            ttk.Radiobutton(
                mode, text=_label, value=_val,
                variable=self.mode_var, command=self._apply_mode,
            ).pack(side="left", padx=6)

        # -- Load selection --------------------------------------------------
        load = ttk.LabelFrame(self, text="Load selection")
        load.pack(fill="x", padx=8, pady=4)
        self.load_field = LoadSelectionField(load)
        self.load_field.pack(fill="x", padx=6, pady=3)
        ttk.Label(
            load, text="(Check active model to load combos/cases; multi-select; "
                      "empty = all combos)",
            foreground="#777", font=("", 8),
        ).pack(anchor="w", padx=14)
        opt = ttk.Frame(load)
        opt.pack(fill="x", padx=6, pady=3)
        # Base-only controls (elevation + only-loaded) live in the same row as
        # the shared toggles; they are removed individually in frame mode.
        self.elevation_field = LabeledEntry(load, "Elevation", "", width=14)
        _reg(self._base_only, "elevation", self.elevation_field, side="left", padx=6, pady=3)
        self.elevation_field.pack(side="left", padx=6, pady=3)
        self.only_loaded_var = tk.BooleanVar(value=False)
        _ol_cb = ttk.Checkbutton(opt, text="Only loaded supports", variable=self.only_loaded_var)
        _reg(self._base_only, "only_loaded", _ol_cb, side="left", padx=8)
        _ol_cb.pack(side="left", padx=8)
        self.run_analysis_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="Run analysis", variable=self.run_analysis_var).pack(side="left", padx=8)
        self.attach_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opt, text="Attach (not launch)", variable=self.attach_var
        ).pack(side="left", padx=8)
        # Frame-only control: section + frame-object selector (hidden in base).
        self.frame_field = LoadSelectionField(
            load, label="Frames", title="Select frames",
            empty_summary="all frames", kind_a="section", kind_b="frame",
        )
        _reg(self._frame_only, "frames", self.frame_field, fill="x", padx=6, pady=3)

        # -- Frame-force preview button (frame-mode only) --------------------
        fprow = ttk.Frame(self)
        ttk.Button(fprow, text="Frame force preview", command=self.on_open_frame_preview).pack(side="left", padx=4)
        ttk.Label(fprow, text="View beam force diagrams (P, V2, M3) in a pop-up",
                     foreground="#777", font=("", 8)).pack(side="left", padx=4)
        _reg(self._frame_only, "frame_preview", fprow, fill="x", padx=8, pady=2)

        # -- Plot settings (base-only) ----------------------------------------
        self.plot_settings = PlotSettingsFrame(self, self._settings)
        _reg(self._base_only, "plot_settings", self.plot_settings, fill="x", padx=8, pady=4)
        self.plot_settings.pack(fill="x", padx=8, pady=4)
        self.plot_after_var = tk.BooleanVar(value=False)
        _pa_cb = ttk.Checkbutton(
            self, text="Plot after extract (save figures to output dir)",
            variable=self.plot_after_var,
        )
        _reg(self._base_only, "plot_after", _pa_cb, anchor="w", padx=14, pady=2)
        _pa_cb.pack(anchor="w", padx=14, pady=2)

        # -- CSV plotting (no ETABS) — base-only -----------------------------
        csv = ttk.LabelFrame(self, text="Plot from existing CSV (no ETABS)")
        _reg(self._base_only, "csv", csv, fill="x", padx=8, pady=4)
        csv.pack(fill="x", padx=8, pady=4)
        self.csv_field = FileField(
            csv, "CSV file", "", filetypes="CSV", patterns=("*.csv",)
        )
        self.csv_field.pack(fill="x", padx=6, pady=3)
        row2 = ttk.Frame(csv)
        row2.pack(fill="x", padx=6, pady=3)
        self.load_preview_btn = ttk.Button(
            row2, text="Load preview", command=self.on_load_preview
        )
        self.load_preview_btn.pack(side="left")

        # -- Preview pop-up trigger (manual, base-only) ----------------------
        # The plan-view preview lives in a separate pop-up window
        # (PlotPreviewWindow); the main window only holds an opener button.
        prow = ttk.Frame(self)
        _reg(self._base_only, "preview", prow, fill="x", padx=8, pady=4)
        prow.pack(fill="x", padx=8, pady=4)
        ttk.Button(prow, text="Plot preview", command=self.on_open_preview).pack(side="left", padx=4)
        ttk.Label(prow, text="Open the plot preview in a separate pop-up window",
                     foreground="#777", font=("", 8)).pack(side="left", padx=4)

        # -- Actions + progress ----------------------------------------------
        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100, value=0)
        self.progress.pack(fill="x", padx=8, pady=(6, 2))
        self.log_var = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.log_var, anchor="w").pack(
            fill="x", padx=8, pady=(0, 2)
        )
        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=8, pady=4)
        self.extract_btn = ttk.Button(actions, text="Extract", command=self.on_extract)
        self.extract_btn.pack(side="left")
        ttk.Button(actions, text="Quit", command=self.destroy).pack(side="right")

    # --------------------------------------------------------------- settings
    def _apply_mode(self) -> None:
        """Show/hide mode-scoped widgets as the extract-mode radio changes.

        ``base`` shows the base-only controls (elevation, only-loaded, plot
        settings, CSV, preview) and hides the frame selector; ``frame`` does the
        reverse.
        """
        base = self.mode_var.get() == "base"
        self._apply_group(self._base_only if base else self._frame_only, show=True)
        self._apply_group(self._frame_only if base else self._base_only, show=False)

    def _apply_group(self, group: dict, *, show: bool) -> None:
        for _widget, _kwargs in group.values():
            try:
                if show:
                    _widget.pack(** _kwargs)
                else:
                    _widget.pack_forget()
            except tk.TclError:
                pass

    def _collect_settings(self, *, not_plot: bool = False) -> GuiSettings:
        s = GuiSettings()
        s.model_path = self.model_field.get()
        s.output_dir = self.output_field.get()
        s.tag = self.tag_field.get()
        s.extract_mode = self.mode_var.get()
        s.selected_combos, s.selected_cases = self.load_field.get_selected()
        s.run_analysis = self.run_analysis_var.get()
        s.attach = self.attach_var.get()
        if s.extract_mode == "frame":
            s.selected_sections, s.selected_frames = self.frame_field.get_selected()
            return s
        s.elevation = self.elevation_field.get()
        s.only_loaded = self.only_loaded_var.get()
        s.csv_path = self.csv_field.get()
        s.plot_after_extract = self.plot_after_var.get()
        self.plot_settings.to_settings(s)
        return s

    # ---------------------------------------------------------------- actions
    def on_check_model(self) -> None:
        from etabs_extractor.gui.runner import BackgroundRunner
        from etabs_extractor.gui.service import inspect_active_model

        self._set_log("Checking active model...")
        self.check_btn.configure(state="disabled")

        def _work():
            try:
                return ("ok", inspect_active_model(attach=self.attach_var.get()))
            except Exception as exc:  # noqa: BLE001
                return ("err", str(exc))

        runner = BackgroundRunner(_work)
        self._runner = runner
        self._poll_id = self.after(80, lambda: self._poll(runner, self._on_check_done))
        runner.start()

    def _on_check_done(self, payload):
        self.check_btn.configure(state="normal")
        kind, value = payload if isinstance(payload, tuple) else ("ok", None)
        if kind == "ok" and isinstance(value, dict):
            model_path = value.get("model_path") or ""
            combos = list(value.get("combos") or [])
            cases = list(value.get("cases") or [])
            sections = list(value.get("sections") or [])
            frames = list(value.get("frames") or [])
            if model_path:
                self.model_field.set(model_path)
                self.model_status.set(f"Active: {model_path}")
                self._set_log(f"Detected active model: {model_path}")
            else:
                self.model_status.set("No active model / empty filename.")
                self._set_log("No active model filename returned.")
            # Populate the load dropdown with the model's combos/cases.
            self.load_field.set_items(combos, cases)
            # Populate the frame-mode selector with sections + frames.
            self.frame_field.set_items(sections, frames)
            n_combos = len(combos)
            n_cases = len(cases)
            self._set_log(
                f"Active model has {n_combos} combo(s), {n_cases} case(s), "
                f"{len(frames)} frame(s), {len(sections)} section(s)."
            )
        else:
            err = str(value) if value else "unknown error"
            self.model_status.set(f"Failed: {err}")
            self._set_log(f"Check failed: {err}")

    def on_extract(self) -> None:
        settings = self._collect_settings()
        self._settings = settings
        # Validate elevation early for a clear message.
        try:
            parse_elevation(settings.elevation)
        except ValueError as exc:
            messagebox.showerror("Invalid elevation", str(exc))
            return
        self._set_log("Extracting... (in background)")
        self._set_progress(0)

        from etabs_extractor.gui.runner import BackgroundRunner
        from etabs_extractor.gui.service import do_extract

        runner = BackgroundRunner(do_extract, settings)
        self._runner = runner
        self._poll_id = self.after(80, lambda: self._poll(runner, self._on_extract_done))
        runner.start()

    def _on_extract_done(self, result):
        self._result = result
        self._set_progress(100)
        df = result.get("df")
        load_names = result.get("load_names") or []
        mode = self.mode_var.get()
        if df is not None and len(df) > 0:
            unit = "rows" if mode == "base" else "force records"
            self._set_log(
                f"Extracted {len(df)} {unit} across {len(load_names)} load(s)."
            )
        else:
            self._set_log("Extraction produced no rows.")
        # Refresh any open preview pop-ups with the new result.
        self._refresh_preview(result)
        self._refresh_frame_preview(result)
        plot_paths = result.get("plot_paths") or []
        nrows = len(df) if df is not None else 0
        self._set_log(f"Extracted {nrows} rows; saved {len(plot_paths)} figure(s).")

    def on_load_preview(self) -> None:
        settings = self._collect_settings()
        self._settings = settings
        from etabs_extractor.gui.runner import BackgroundRunner
        from etabs_extractor.gui.service import load_from_csv

        self._set_log("Loading CSV preview...")
        runner = BackgroundRunner(load_from_csv, settings)
        self._runner = runner
        self._poll_id = self.after(80, lambda: self._poll(runner, self._on_csv_done))
        runner.start()

    def _on_csv_done(self, result):
        self._result = result
        load_names = result.get("load_names") or []
        df = result.get("df")
        self._set_log(
            f"Loaded CSV with {len(df)} rows across {len(load_names)} load(s)."
        )
        # Refresh an open preview pop-up with the new result (manual open).
        self._refresh_preview(result)

    # ---------------------------------------------------------------- preview
    def on_open_preview(self) -> None:
        """Open (or re-raise) the separate plot-preview pop-up window.

        Manual only: does nothing auto after Extract / Load-preview.  If a
        result is already loaded the pop-up is populated from it immediately.
        """
        if self._preview_win is not None and self._preview_win.is_alive():
            self._preview_win.lift()
            if self._result is not None:
                self._preview_win.set_result(self._result)
            return
        self._preview_win = PlotPreviewWindow(
            self,
            settings_provider=self._collect_settings,
            figure_builder=self._build_preview_figure,
            log=self._set_log,
            closed=self._on_preview_closed,
        )
        if self._result is not None:
            self._preview_win.set_result(self._result)

    def _on_preview_closed(self, window) -> None:
        """Called when the pop-up is closed; drop the stale reference."""
        if self._preview_win is window:
            self._preview_win = None

    def _build_preview_figure(self, df, load_name, settings):
        """Build one preview figure via the shared plots layer (lazy mpl)."""
        from etabs_extractor.plots import build_base_reactions_figure
        from etabs_extractor.gui.service import build_figure_kwargs

        return build_base_reactions_figure(
            df, load_name, **build_figure_kwargs(settings)
        )

    def _refresh_preview(self, result: dict) -> None:
        """Point an already-open preview pop-up at the latest result."""
        win = getattr(self, "_preview_win", None)
        if win is not None and win.is_alive():
            win.set_result(result)

    # ---------------------------------------------------------------- frame preview

    def on_open_frame_preview(self) -> None:
        """Open (or re-raise) the frame-force diagram preview pop-up."""
        if self._frame_preview_win is not None and self._frame_preview_win.is_alive():
            self._frame_preview_win.lift()
            if self._result is not None:
                self._frame_preview_win.set_result(self._result)
            return
        self._frame_preview_win = FramePreviewWindow(
            self,
            figure_builder=self._build_frame_preview_figure,
            log=self._set_log,
            closed=self._on_frame_preview_closed,
        )
        if self._result is not None:
            self._frame_preview_win.set_result(self._result)

    def _on_frame_preview_closed(self, window) -> None:
        if self._frame_preview_win is window:
            self._frame_preview_win = None

    def _build_frame_preview_figure(self, df, frame, load_name, section, *,
                                    step_type=None):
        """Build a 3-panel beam force diagram figure (P, V2, M3).

        ``beam_viewer.py`` lives at the repo root (one level up from
        ``etabs_extractor/``), so we add its parent to ``sys.path``
        before importing.
        """
        import os as _os
        import sys as _sys
        _repo_root = _os.path.abspath(
            _os.path.join(_os.path.dirname(__file__), "..", "..")
        )
        if _repo_root not in _sys.path:
            _sys.path.insert(0, _repo_root)
        from beam_viewer import build_frame_figure  # noqa: PLC0415
        return build_frame_figure(df, frame, load_name, section,
                                  step_type=step_type)

    # -------------------------------------------------------- worker draining
    def _drain_pending(self, limit: int = 50000) -> None:
        """Drain any completed runner result (used on startup / after a poll)."""
        if not self._runner:
            return
        q = self._runner.queue
        got = False
        try:
            while True:
                kind, payload = q.get_nowait()
                got = True
                if kind == "result":
                    # Deliver to the pending callback, then reset.
                    cb = getattr(self, "_pending_cb", None)
                    if cb:
                        cb(payload)
                    self._pending_cb = None
                    self._runner = None
                    break
                elif kind == "error":
                    self._set_log(f"Error: {payload}")
                    messagebox.showerror("etabs_extractor", f"{payload}")
                    self._pending_cb = None
                    self._runner = None
                    break
                elif kind == "done":
                    break
        except Exception:  # noqa: BLE001 - empty queue
            pass
        if got:
            self._poll_id = self.after(80, lambda: self._poll(self._runner, None)) \
                if self._runner else None

    def _poll(self, runner, callback) -> None:
        """Poll the runner queue; invoke ``callback(payload)`` on a result."""
        if runner is None or runner is not self._runner:
            return
        self._pending_cb = callback
        # Trigger a drain.
        try:
            while True:
                kind, payload = runner.queue.get_nowait()
                if kind == "result":
                    if callback:
                        callback(payload)
                    else:
                        # store result if no callback
                        self._result = payload
                    self._pending_cb = None
                    self._runner = None
                    return
                elif kind == "error":
                    self._set_log(f"Error: {payload}")
                    messagebox.showerror("etabs_extractor", f"{payload}")
                    self._pending_cb = None
                    self._runner = None
                    return
                elif kind == "done":
                    self._pending_cb = None
                    self._runner = None
                    return
        except Exception:  # noqa: BLE001 - empty queue; keep polling
            if runner is self._runner:
                self._poll_id = self.after(80, lambda: self._poll(runner, callback))

    # -------------------------------------------------------------- status
    def _set_log(self, text: str) -> None:
        self.log_var.set(text)

    def _set_progress(self, fraction: float) -> None:
        try:
            self.progress.configure(value=float(fraction))
        except (TypeError, ValueError, tk.TclError):
            return