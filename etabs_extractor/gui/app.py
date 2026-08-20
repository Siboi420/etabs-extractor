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
from etabs_extractor.gui.state import GuiSettings, parse_combos, parse_elevation
from etabs_extractor.gui.service import (
    build_extract_kwargs,
    build_figure_kwargs,
    build_plot_kwargs,
    load_from_csv,
    sanitize_tag,
)
from etabs_extractor.gui.widgets.fields import DirectoryField, FileField, LabeledEntry
from etabs_extractor.gui.widgets.plot_settings import PlotSettingsFrame
from etabs_extractor.gui.widgets.preview import PlotPreviewWindow


class EtabsExtractorApp(tk.Tk):
    """The GUI root window."""

    def __init__(self) -> None:
        super().__init__()
        self.title("etabs_extractor — base reactions + plotting")
        self.geometry("980x640")
        self.minsize(760, 560)

        self._settings = GuiSettings()
        self._runner = None
        self._result = None      # last extraction/load result dict
        self._preview_win = None # the open plot-preview pop-up (or None)
        self._poll_id = None

        self._build_layout()
        self._drain_pending()

    # ------------------------------------------------------------------ layout
    def _build_layout(self) -> None:
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

        # -- Load selection --------------------------------------------------
        load = ttk.LabelFrame(self, text="Load selection")
        load.pack(fill="x", padx=8, pady=4)
        self.combo_field = LabeledEntry(
            load, "Combos", "", width=50,
        )
        self.combo_field.pack(fill="x", padx=6, pady=3)
        ttk.Label(
            load, text="(comma/space separated; empty = all model combos)",
            foreground="#777", font=("", 8),
        ).pack(anchor="w", padx=14)
        opt = ttk.Frame(load)
        opt.pack(fill="x", padx=6, pady=3)
        self.elevation_field = LabeledEntry(load, "Elevation", "", width=14)
        self.elevation_field.pack(side="left", padx=6, pady=3)
        self.only_loaded_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="Only loaded supports", variable=self.only_loaded_var).pack(side="left", padx=8)
        self.run_analysis_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="Run analysis", variable=self.run_analysis_var).pack(side="left", padx=8)
        self.attach_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opt, text="Attach (not launch)", variable=self.attach_var
        ).pack(side="left", padx=8)

        # -- Plot settings ---------------------------------------------------
        self.plot_settings = PlotSettingsFrame(self, self._settings)
        self.plot_settings.pack(fill="x", padx=8, pady=4)
        self.plot_after_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self, text="Plot after extract (save figures to output dir)",
            variable=self.plot_after_var,
        ).pack(anchor="w", padx=14, pady=2)

        # -- CSV plotting (no ETABS) -----------------------------------------
        csv = ttk.LabelFrame(self, text="Plot from existing CSV (no ETABS)")
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

        # -- Preview pop-up trigger (manual) -------------------------------
        # The plan-view preview now lives in a separate pop-up window
        # (PlotPreviewWindow); the main window only holds an opener button.
        prow = ttk.Frame(self)
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
    def _collect_settings(self, *, not_plot: bool = False) -> GuiSettings:
        s = GuiSettings()
        s.model_path = self.model_field.get()
        s.output_dir = self.output_field.get()
        s.tag = self.tag_field.get()
        s.combos = self.combo_field.get()
        s.elevation = self.elevation_field.get()
        s.only_loaded = self.only_loaded_var.get()
        s.run_analysis = self.run_analysis_var.get()
        s.attach = self.attach_var.get()
        s.csv_path = self.csv_field.get()
        s.plot_after_extract = self.plot_after_var.get()
        self.plot_settings.to_settings(s)
        return s

    # ---------------------------------------------------------------- actions
    def on_check_model(self) -> None:
        from etabs_extractor.gui.runner import BackgroundRunner
        from etabs_extractor.gui.service import check_active_model

        self._set_log("Checking active model...")
        self.check_btn.configure(state="disabled")

        def _work():
            try:
                return ("ok", check_active_model(attach=self.attach_var.get()))
            except Exception as exc:  # noqa: BLE001
                return ("err", str(exc))

        runner = BackgroundRunner(_work)
        self._runner = runner
        self._poll_id = self.after(80, lambda: self._poll(runner, self._on_check_done))
        runner.start()

    def _on_check_done(self, payload):
        self.check_btn.configure(state="normal")
        kind, value = payload if isinstance(payload, tuple) else ("ok", "")
        if kind == "ok":
            if value:
                self.model_field.set(value)
                self.model_status.set(f"Active: {value}")
                self._set_log(f"Detected active model: {value}")
            else:
                self.model_status.set("No active model / empty filename.")
                self._set_log("No active model filename returned.")
        else:
            self.model_status.set(f"Failed: {value}")
            self._set_log(f"Check failed: {value}")

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
        if df is not None and len(df) > 0:
            self._set_log(
                f"Extracted {len(df)} reaction rows across {len(load_names)} load(s)."
            )
        else:
            self._set_log("Extraction produced no rows.")
        # Refresh an open preview pop-up with the new result (manual only).
        self._refresh_preview(result)
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
        """Point an already-open preview pop-up at the latest result.

        Manual only: this never *opens* the pop-up -- it only updates one
        that the user already opened via ``Plot preview``.
        """
        win = getattr(self, "_preview_win", None)
        if win is not None and win.is_alive():
            win.set_result(result)

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