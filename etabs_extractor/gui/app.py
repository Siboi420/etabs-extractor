"""Main application window for the etabs_extractor GUI.

A sidebar (model, mode switch, load selection, mode-scoped filters, output,
Extract) beside a tabbed workspace (Preview / Plot settings / CSV / Log).
All real work is delegated to :func:`~etabs_extractor.gui.service` and run
on a background thread via :class:`~etabs_extractor.gui.runner.BackgroundRunner`;
customtkinter/Tk is only used as the view layer. Creating an instance
requires a display; importing the module does not.
"""

from __future__ import annotations

import queue
from tkinter import messagebox

import customtkinter as ctk

from etabs_extractor.config import resolve_output_dir
from etabs_extractor.gui.runner import BackgroundRunner
from etabs_extractor.gui.service import (
    build_elevation_labels,
    build_figure_kwargs,
    do_extract,
    inspect_active_model,
    load_from_csv,
    save_batch_plots,
)
from etabs_extractor.gui.state import (
    APPEARANCE_CHOICES,
    BATCH_STEP_CHOICES,
    FORCE_UNIT_CHOICES,
    LENGTH_UNIT_CHOICES,
    GuiSettings,
    parse_elevation,
)
from etabs_extractor.gui.widgets.fields import (
    DirectoryField,
    FileField,
    LabeledEntry,
    Section,
)
from etabs_extractor.gui.widgets.load_selection import LoadSelectionField
from etabs_extractor.gui.widgets.log_panel import LogPanel
from etabs_extractor.gui.widgets.plot_settings import PlotSettingsFrame
from etabs_extractor.gui.widgets.preview import (
    BasePreviewPanel,
    FramePreviewPanel,
    load_beam_viewer,
)


class EtabsExtractorApp(ctk.CTk):
    """The GUI root window."""

    def __init__(self) -> None:
        # Must run before super().__init__(): customtkinter's periodic
        # per-monitor DPI-awareness poll (~every 100ms) can mis-detect a
        # scaling change on some Windows displays, briefly drop the window's
        # alpha and force a scaling redraw across every widget — which
        # interrupts an in-progress mouse drag and breaks the matplotlib
        # toolbar's pan/zoom. Deactivating it keeps DPI scaling static
        # (factor 1) for the life of the process; window/font sizes are
        # otherwise unaffected since we don't rely on ctk's auto-DPI scaling.
        ctk.deactivate_automatic_dpi_awareness()
        super().__init__()
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.title("etabs_extractor — base reactions & frame forces")
        self.geometry("1180x740")
        self.minsize(980, 620)

        self._settings = GuiSettings()
        self._runner: BackgroundRunner | None = None
        self._pending_cb = None
        self._result: dict | None = None
        self._poll_id = None
        self._busy_widgets: list = []
        # Populated by on_check_model / _on_check_done: the active model's
        # own present units and elevation inventory (model length units),
        # used to build the elevation combobox's labels in the currently
        # selected output length unit.
        self._model_units: dict = {"force": "", "length": ""}
        self._elevations: list = []

        self._build_layout()
        self._apply_mode()
        self._set_log("Ready.")

    # ------------------------------------------------------------------ layout
    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_workspace()
        self._build_status_bar()

    def _build_sidebar(self) -> None:
        self.sidebar = ctk.CTkScrollableFrame(
            self, width=340, corner_radius=0, label_text="etabs_extractor",
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        # -- Model & output ---------------------------------------------
        model_section = Section(self.sidebar, "Model & output")
        model_section.pack(fill="x", pady=(0, 10))
        self.model_field = FileField(
            model_section.body, "Model", "",
            filetypes="ETABS model", patterns=("*.EDB", "*.edb", "*.et"),
        )
        self.model_field.pack(fill="x", pady=3)

        check_row = ctk.CTkFrame(model_section.body, fg_color="transparent")
        check_row.pack(fill="x", pady=(3, 0))
        self.check_btn = ctk.CTkButton(
            check_row, text="Check active model", command=self.on_check_model, width=160,
        )
        self.check_btn.pack(side="left")
        self._busy_widgets.append(self.check_btn)

        self.model_status_var = ctk.StringVar(value="No active model checked.")
        ctk.CTkLabel(
            model_section.body, textvariable=self.model_status_var, anchor="w",
            text_color="gray", wraplength=280, justify="left",
        ).pack(fill="x", pady=(4, 6))

        self.output_field = DirectoryField(
            model_section.body, "Output dir", str(resolve_output_dir()),
        )
        self.output_field.pack(fill="x", pady=3)
        self.batch_plot_field = DirectoryField(
            model_section.body, "Batch plot dir", "",
        )
        self.batch_plot_field.pack(fill="x", pady=3)
        ctk.CTkLabel(
            model_section.body,
            text="(blank: extraction → Output dir; CSV → Plot output / CSV folder)",
            text_color="gray", anchor="w", wraplength=280, justify="left",
        ).pack(fill="x")  # batch-save fallback target, see service.save_batch_plots

        # Batch save plots: which step variants to write (all three by default).
        batch_steps_row = ctk.CTkFrame(model_section.body, fg_color="transparent")
        batch_steps_row.pack(fill="x", pady=(2, 0))
        ctk.CTkLabel(batch_steps_row, text="Batch steps:", anchor="w").pack(side="left")
        self.batch_step_vars: dict[str, ctk.BooleanVar] = {}
        for label, variant in BATCH_STEP_CHOICES:
            var = ctk.BooleanVar(value=variant in ("absmax", "max", "min"))
            self.batch_step_vars[variant] = var
            ctk.CTkCheckBox(batch_steps_row, text=label, variable=var, width=72).pack(
                side="left", padx=(6, 0),
            )
        self.tag_field = LabeledEntry(model_section.body, "Tag", "")
        self.tag_field.pack(fill="x", pady=3)
        self.tag_hint_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            model_section.body, textvariable=self.tag_hint_var, text_color="gray", anchor="w",
        ).pack(fill="x")
        self.tag_field.var.trace_add("write", lambda *a: self._update_tag_hint())

        opt_row = ctk.CTkFrame(model_section.body, fg_color="transparent")
        opt_row.pack(fill="x", pady=(4, 0))
        self.attach_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opt_row, text="Attach (not launch)", variable=self.attach_var).pack(
            side="left", padx=(0, 10),
        )
        self.run_analysis_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(opt_row, text="Run analysis", variable=self.run_analysis_var).pack(side="left")

        # -- Units ----------------------------------------------------------
        units_section = Section(self.sidebar, "Units")
        units_section.pack(fill="x", pady=(0, 10))
        units_row = ctk.CTkFrame(units_section.body, fg_color="transparent")
        units_row.pack(fill="x")
        ctk.CTkLabel(units_row, text="Force", anchor="w", width=60).pack(side="left")
        self.force_unit_var = ctk.StringVar(value="model")
        ctk.CTkOptionMenu(
            units_row, values=list(FORCE_UNIT_CHOICES), variable=self.force_unit_var,
            width=90, command=self._on_units_changed,
        ).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(units_row, text="Length", anchor="w", width=60).pack(side="left")
        self.length_unit_var = ctk.StringVar(value="model")
        ctk.CTkOptionMenu(
            units_row, values=list(LENGTH_UNIT_CHOICES), variable=self.length_unit_var,
            width=90, command=self._on_units_changed,
        ).pack(side="left")
        self.units_hint_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            units_section.body, textvariable=self.units_hint_var, text_color="gray",
            anchor="w", wraplength=290, justify="left",
        ).pack(fill="x", pady=(4, 0))
        self._update_units_hint()

        # -- Extraction mode ----------------------------------------------
        mode_section = Section(self.sidebar, "Extraction mode")
        mode_section.pack(fill="x", pady=(0, 10))
        self.mode_var = ctk.StringVar(value="base")
        self.mode_switch = ctk.CTkSegmentedButton(
            mode_section.body, values=["Base reactions", "Frame forces"],
            command=self._on_mode_changed,
        )
        self.mode_switch.set("Base reactions")
        self.mode_switch.pack(fill="x")

        # -- Load selection -------------------------------------------------
        loads_section = Section(self.sidebar, "Load selection")
        loads_section.pack(fill="x", pady=(0, 10))
        self.load_field = LoadSelectionField(
            loads_section.body, label="Loads", title="Select loads", empty_summary="all combos",
        )
        self.load_field.pack(fill="x", pady=2)
        ctk.CTkLabel(
            loads_section.body,
            text="(Check active model to load combos/cases; empty = all combos)",
            text_color="gray", wraplength=280, justify="left", anchor="w",
        ).pack(fill="x")

        # -- Mode-scoped filter containers (one packed at a time) -----------
        self.base_filter = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        base_inner = Section(self.base_filter, "Base filters")
        base_inner.pack(fill="x")
        self.elevation_label_var = ctk.StringVar(value="Elevation (model)")
        ctk.CTkLabel(base_inner.body, textvariable=self.elevation_label_var, anchor="w").pack(
            fill="x", pady=(0, 2),
        )
        self.elevation_var = ctk.StringVar(value="")
        self.elevation_combo = ctk.CTkComboBox(
            base_inner.body, values=[], variable=self.elevation_var,
        )
        self.elevation_combo.pack(fill="x", pady=(0, 3))
        ctk.CTkLabel(
            base_inner.body,
            text="(Check active model to list elevations; or type a value)",
            text_color="gray", wraplength=280, justify="left", anchor="w",
        ).pack(fill="x")
        self.only_loaded_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(base_inner.body, text="Only loaded supports", variable=self.only_loaded_var).pack(
            anchor="w", pady=2,
        )
        self.plot_after_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(base_inner.body, text="Plot after extract", variable=self.plot_after_var).pack(
            anchor="w", pady=2,
        )

        self.frame_filter = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        frame_inner = Section(self.frame_filter, "Section filter")
        frame_inner.pack(fill="x")
        self.section_field = LoadSelectionField(
            frame_inner.body, label="Sections", title="Select sections",
            empty_summary="all sections", kind_a="section", kind_b="_unused",
        )
        self.section_field.pack(fill="x", pady=2)
        ctk.CTkLabel(
            frame_inner.body, text="(empty = all sections)", text_color="gray", anchor="w",
        ).pack(fill="x")

        # -- Extract ---------------------------------------------------------
        self.extract_btn = ctk.CTkButton(
            self.sidebar, text="Extract", command=self.on_extract, height=38,
            font=ctk.CTkFont(weight="bold"),
        )
        self.extract_btn.pack(fill="x", pady=(6, 12))
        self._busy_widgets.append(self.extract_btn)

    def _build_workspace(self) -> None:
        self.workspace = ctk.CTkFrame(self, fg_color="transparent")
        self.workspace.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.workspace.grid_rowconfigure(0, weight=1)
        self.workspace.grid_columnconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(self.workspace)
        self.tabs.grid(row=0, column=0, sticky="nsew")
        self.tabs.add("Preview")
        self.tabs.add("Plot settings")
        self.tabs.add("CSV")
        self.tabs.add("Log")

        preview_tab = self.tabs.tab("Preview")
        preview_tab.grid_rowconfigure(0, weight=1)
        preview_tab.grid_columnconfigure(0, weight=1)
        self.base_preview = BasePreviewPanel(
            preview_tab, settings_provider=self._collect_settings,
            figure_builder=self._build_preview_figure, log=self._set_log,
            batch_saver=self._on_batch_save,
        )
        self.frame_preview = FramePreviewPanel(
            preview_tab, figure_builder=self._build_frame_preview_figure,
            batch_figure_builder=self._build_batch_frame_preview_figure, log=self._set_log,
        )
        self.base_preview.grid(row=0, column=0, sticky="nsew")
        # frame_preview is grid()-ed/forgotten by _apply_mode.

        plot_tab = self.tabs.tab("Plot settings")
        self.plot_settings = PlotSettingsFrame(plot_tab, self._settings)
        self.plot_settings.pack(fill="both", expand=True, padx=4, pady=4)

        csv_tab = self.tabs.tab("CSV")
        ctk.CTkLabel(
            csv_tab, text="Plot from an existing base-reaction CSV (no ETABS needed)", anchor="w",
        ).pack(fill="x", padx=6, pady=(6, 2))
        self.csv_field = FileField(csv_tab, "CSV file", "", filetypes="CSV", patterns=("*.csv",))
        self.csv_field.pack(fill="x", padx=6, pady=4)
        self.plot_output_field = DirectoryField(csv_tab, "Plot output (optional)", "")
        self.plot_output_field.pack(fill="x", padx=6, pady=4)
        ctk.CTkLabel(
            csv_tab, text="(blank = save next to the CSV file)", text_color="gray", anchor="w",
        ).pack(fill="x", padx=6)
        self.load_preview_btn = ctk.CTkButton(
            csv_tab, text="Load preview", command=self.on_load_preview, width=130,
        )
        self.load_preview_btn.pack(anchor="w", padx=6, pady=4)
        self._busy_widgets.append(self.load_preview_btn)

        log_tab = self.tabs.tab("Log")
        self.log_panel = LogPanel(log_tab)
        self.log_panel.pack(fill="both", expand=True, padx=4, pady=4)

    def _build_status_bar(self) -> None:
        status = ctk.CTkFrame(self, fg_color="transparent")
        status.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
        status.grid_columnconfigure(1, weight=1)

        self.progress = ctk.CTkProgressBar(status, mode="indeterminate", width=140)
        self.progress.grid(row=0, column=0, sticky="w", padx=(0, 10))

        self.status_var = ctk.StringVar(value="Ready.")
        ctk.CTkLabel(status, textvariable=self.status_var, anchor="w").grid(
            row=0, column=1, sticky="ew",
        )

        ctk.CTkLabel(status, text="Appearance:").grid(row=0, column=2, padx=(10, 4))
        self.appearance_var = ctk.StringVar(value="System")
        ctk.CTkOptionMenu(
            status, values=list(APPEARANCE_CHOICES), variable=self.appearance_var,
            width=90, command=self._on_appearance_changed,
        ).grid(row=0, column=3)

    # -------------------------------------------------------------- mode switch
    def _on_mode_changed(self, label: str) -> None:
        self.mode_var.set("base" if label == "Base reactions" else "frame")
        self._apply_mode()

    def _apply_mode(self) -> None:
        """Show/hide mode-scoped widgets as the extract-mode switch changes.

        ``base`` shows the base-only filters + preview; ``frame`` shows the
        section filter + frame preview instead.
        """
        base = self.mode_var.get() == "base"
        if base:
            self.frame_filter.pack_forget()
            self.base_filter.pack(fill="x", pady=(0, 10), before=self.extract_btn)
            self.frame_preview.grid_forget()
            self.base_preview.grid(row=0, column=0, sticky="nsew")
        else:
            self.base_filter.pack_forget()
            self.frame_filter.pack(fill="x", pady=(0, 10), before=self.extract_btn)
            self.base_preview.grid_forget()
            self.frame_preview.grid(row=0, column=0, sticky="nsew")

    def _on_appearance_changed(self, value: str) -> None:
        ctk.set_appearance_mode(value)
        self._settings.appearance_mode = value
        self.base_preview.preview.sync_theme()
        self.frame_preview.preview.sync_theme()

    def _update_tag_hint(self) -> None:
        from etabs_extractor.gui.service import sanitize_tag

        suffix = sanitize_tag(self.tag_field.get())
        self.tag_hint_var.set(f"Suffix: _{suffix}" if suffix else "")

    # -------------------------------------------------------------- units
    def _on_units_changed(self, _value: str | None = None) -> None:
        """Re-render the units hint and the elevation combobox's labels
        whenever the Force/Length output-unit choice changes."""
        self._update_units_hint()
        self._refresh_elevation_choices()

    def _update_units_hint(self) -> None:
        model = self._model_units or {}
        model_force, model_length = model.get("force") or "", model.get("length") or ""
        force = self.force_unit_var.get()
        length = self.length_unit_var.get()
        out_force = model_force if force == "model" else force
        out_length = model_length if length == "model" else length
        if model_force and model_length:
            model_label = f"{model_force}, {model_length}"
        else:
            model_label = "unknown (Check active model)"
        if out_force and out_length:
            out_label = f"{out_force}, {out_force}·{out_length}, {out_length}"
        else:
            out_label = "model (no conversion)"
        self.units_hint_var.set(f"Model: {model_label}  →  Output: {out_label}")

    def _refresh_elevation_choices(self) -> None:
        """Rebuild the elevation combobox's values in the current output
        length unit, keeping the user's typed/selected value if possible."""
        length = self.length_unit_var.get()
        model_length = (self._model_units or {}).get("length") or "mm"
        labels = build_elevation_labels(self._elevations, model_length, length)
        self.elevation_combo.configure(values=labels)
        shown_length = model_length if length == "model" else length
        self.elevation_label_var.set(f"Elevation ({shown_length})")

    # ------------------------------------------------------------ settings
    def _collect_settings(self) -> GuiSettings:
        s = GuiSettings()
        s.model_path = self.model_field.get()
        s.output_dir = self.output_field.get()
        s.batch_plot_dir = self.batch_plot_field.get()
        s.plot_steps = [v for _, v in BATCH_STEP_CHOICES if self.batch_step_vars[v].get()]
        s.tag = self.tag_field.get()
        s.extract_mode = self.mode_var.get()
        s.selected_combos, s.selected_cases = self.load_field.get_selected()
        s.run_analysis = bool(self.run_analysis_var.get())
        s.attach = bool(self.attach_var.get())
        s.appearance_mode = self.appearance_var.get()
        s.force_unit = self.force_unit_var.get()
        s.length_unit = self.length_unit_var.get()
        if s.extract_mode == "frame":
            sections, _ = self.section_field.get_selected()
            s.selected_sections = sections
            s.selected_frames = []
        else:
            s.elevation = self.elevation_var.get()
            s.only_loaded = bool(self.only_loaded_var.get())
            s.csv_path = self.csv_field.get()
            s.plot_output_dir = self.plot_output_field.get()
            s.plot_after_extract = bool(self.plot_after_var.get())
        self.plot_settings.to_settings(s)
        return s

    # ---------------------------------------------------------------- log/status
    def _set_log(self, text: str) -> None:
        self.status_var.set(text)
        if hasattr(self, "log_panel"):
            self.log_panel.append(text)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for w in self._busy_widgets:
            w.configure(state=state)
        if busy:
            self.progress.start()
        else:
            self.progress.stop()

    # ---------------------------------------------------------------- actions
    def on_check_model(self) -> None:
        """Attach to the active ETABS model and populate the load/section pickers."""
        self._set_log("Checking active model...")
        self._start_job(inspect_active_model, attach=bool(self.attach_var.get()))
        self._pending_cb = self._on_check_done

    def _on_check_done(self, info: dict) -> None:
        self.model_field.set(info.get("model_path", ""))
        combos = info.get("combos", [])
        cases = info.get("cases", [])
        sections = info.get("sections", [])
        self.load_field.set_items(combos, cases)
        self.section_field.set_items(sections, [])
        self._model_units = info.get("units") or {"force": "", "length": ""}
        self._elevations = info.get("elevations") or []
        self._update_units_hint()
        self._refresh_elevation_choices()
        self.model_status_var.set(
            f"{info.get('model_path') or 'No active model'} — "
            f"{len(combos)} combos, {len(cases)} cases, {len(sections)} sections"
        )
        self._set_log("Active model checked.")

    def on_extract(self) -> None:
        """Collect settings and run the extraction workflow in the background."""
        settings = self._collect_settings()
        try:
            parse_elevation(settings.elevation)
        except ValueError as exc:
            messagebox.showerror("Invalid elevation", str(exc))
            return
        self._settings = settings
        self._set_log("Extracting...")
        self._start_job(do_extract, settings)
        self._pending_cb = self._on_extract_done

    def _on_extract_done(self, result: dict) -> None:
        self._result = result
        load_names = result.get("load_names") or []
        df = result.get("df")
        rows = len(df) if df is not None else 0
        self._set_log(f"Extraction complete: {rows} row(s) across {len(load_names)} load(s).")
        plot_paths = result.get("plot_paths") or []
        if plot_paths:
            self._set_log(f"Saved {len(plot_paths)} plot(s) to {result.get('output_dir')}")
        self._refresh_preview()

    def on_load_preview(self) -> None:
        """Load a base reaction CSV (no ETABS) and preview it."""
        settings = self._collect_settings()
        if not settings.csv_path:
            messagebox.showwarning("Missing CSV", "Please select a CSV file first.")
            return
        self._settings = settings
        self._set_log("Loading CSV...")
        self._start_job(load_from_csv, settings)
        self._pending_cb = self._on_csv_done

    def _on_csv_done(self, result: dict) -> None:
        self._result = result
        load_names = result.get("load_names") or []
        df = result.get("df")
        rows = len(df) if df is not None else 0
        self._set_log(f"Loaded CSV with {rows} row(s) across {len(load_names)} load(s).")
        self._refresh_preview()

    def _on_batch_save(self, settings: GuiSettings) -> None:
        """Batch-save absmax/max/min plots for every load of the current
        result (BasePreviewPanel's Batch save plots button), on the
        background thread like every other job."""
        if self._result is None:
            messagebox.showwarning(
                "Batch save plots", "Run Extract or Load preview first."
            )
            return
        self._settings = settings
        self._set_log("Saving batch plots...")
        self._start_job(save_batch_plots, self._result, settings)
        self._pending_cb = self._on_batch_done

    def _on_batch_done(self, paths: list) -> None:
        target = str(paths[0].parent) if paths else "?"
        self._set_log(f"Saved {len(paths)} plot(s) to {target}")

    def _refresh_preview(self) -> None:
        if self._result is None:
            return
        if self.mode_var.get() == "frame":
            self.frame_preview.set_result(self._result)
        else:
            self.base_preview.set_result(self._result)
        self.tabs.set("Preview")

    # ------------------------------------------------------------- preview figures
    def _build_preview_figure(self, df, load_name, settings, step=None):
        """Build one base-reaction preview figure via the shared plots layer."""
        from etabs_extractor.plots import build_base_reactions_figure

        return build_base_reactions_figure(
            df, load_name, **build_figure_kwargs(settings), step=step,
        )

    def _build_frame_preview_figure(self, df, frame, load_name, section, *, step_type=None):
        """Build a 3-panel beam force diagram figure (P, V2, M3)."""
        bv = load_beam_viewer()
        return bv.build_frame_figure(df, frame, load_name, section, step_type=step_type)

    def _build_batch_frame_preview_figure(self, df, load_name, section, length_mm, *,
                                          force_col="M3", step_type=None):
        """Build a multi-panel batch figure for all beams at the given
        section + length, sorted by descending peak |force_col|."""
        bv = load_beam_viewer()
        return bv.build_batch_frame_figure(
            df, load_name, section, length_mm, force_col=force_col, step_type=step_type,
        )

    # -------------------------------------------------------- background jobs
    def _start_job(self, fn, *args, **kwargs) -> None:
        """Run ``fn(*args, **kwargs)`` on a background thread and begin polling."""
        self._set_busy(True)
        self._runner = BackgroundRunner(fn, *args, **kwargs)
        self._runner.start()
        self._poll_id = self.after(80, self._poll)

    def _poll(self) -> None:
        runner = self._runner
        if runner is None:
            return
        try:
            while True:
                kind, payload = runner.queue.get_nowait()
                if kind == "result":
                    cb = self._pending_cb
                    self._pending_cb = None
                    self._runner = None
                    self._set_busy(False)
                    if cb:
                        try:
                            cb(payload)
                        except Exception as exc:  # noqa: BLE001 - surface UI-side errors
                            messagebox.showerror("etabs_extractor", str(exc))
                            self._set_log(f"Error: {exc}")
                    return
                elif kind == "error":
                    self._pending_cb = None
                    self._runner = None
                    self._set_busy(False)
                    self._set_log(f"Error: {payload}")
                    messagebox.showerror("etabs_extractor", str(payload))
                    return
                elif kind == "done":
                    continue
        except queue.Empty:
            pass
        self._poll_id = self.after(80, self._poll)

    def destroy(self) -> None:
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception as exc:  # noqa: BLE001 - best-effort cleanup on close
                self._set_log(f"Cleanup on close: {exc}")
            self._poll_id = None
        super().destroy()
