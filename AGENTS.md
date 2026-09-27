# AGENTS.md — etabs_extractor

Project-specific guidance for the **etabs_extractor** package. Read this
before editing. It explains the architecture, the invariants you must not
break, and the rules for safely maintaining/extending the code.

---

## What this project is

A **self-contained Python package** that extracts from an **ETABS 22** model
over the **CSI COM API**, and writes them to CSV (plus returns pandas
DataFrames):

- **frame-element internal forces** (`P`, `V2`, `V3`, `T`, `M2`, `M3`) via
  `Results.FrameForce` (`--extract frame`, the default), and
- **per-joint (base) reactions** (`F1`-`F3`, `M1`-`M3`) with point
  coordinates/elevation via `Results.JointReact` (`--extract base`).

It lives at `~/Projects/Structural Works/etabs_extractor/`. This is a
**reference/delivery copy** — working originals may live under
`StructuralEngineeringWorkspace/`. Follow the parent AGENTS rules: no
`/mnt/d`-hardcoding, never fabricate results, report real output.

## The single most important fact

**COM is Windows-only.** The package talks to ETABS through `comtypes`,
which requires a **Windows Python process**. On WSL/Linux the package's
*pure-Python core* imports fine, but any COM call fails.

This shapes everything below: the module layering, where `comtypes` is
imported, how tests work, and how the package is actually run against a live
ETABS.

---

## Architecture (module by module)

```text
etabs_extractor/
  __init__.py     # public API re-exports (lazy-COM-safe only)
  config.py       # defaults, env-var resolution, /mnt/<drv> -> <DRV>:\ path helper
  units.py        # UnitSystem, force/length conversion factors, ETABS unit enums  [pure]
  models.py       # FrameForceRecord + JointReactionRecord, column order, *_dataframe()  [pure]
  connection.py   # EtabsSession: COM attach/launch, open model, read APIs     [COM here]
  results.py      # orchestration: extract_forces() (frames) + extract_base_reactions()  [pure-ish]
  io.py           # CSV writers (per-load, *_all, envelope summary)              [pure]
  plots.py        # matplotlib plan-view plotting of base reactions (lazy mpl)   [pure]
  cli.py          # argparse CLI entry point (--extract frame|base, --plot, --plot-csv)
  __main__.py     # enables `python -m etabs_extractor`
  gui/            # customtkinter GUI (base + frame extraction, embedded plotting) — lazy ctk/mpl/COM
    __init__.py   # run_gui() entry
    __main__.py   # enables `python -m etabs_extractor.gui`
    state.py      # GuiSettings dataclass + parse helpers          [pure]
    service.py    # settings -> library call mapping + do_extract/load_from_csv/inspect_active_model  [pure-ish]
    runner.py     # background thread + queue wrapper              [pure-ish]
    widgets/
      fields.py, load_selection.py, log_panel.py, plot_settings.py, preview.py  # ctk widgets, lazy mpl
    app.py        # EtabsExtractorApp(ctk.CTk): sidebar + tabbed workspace view layer
  requirements.txt
  README.md
  tests/test_dry_run.py       # FakeSapModel stub, no COM
  tests/test_plot_settings.py # GUI pure-layer + figure-builder tests, no display/COM
  tests/test_gui_smoke.py     # headed widget<->settings + mode-switch + preview-render smoke test
run_etabs.sh      # WSL->Windows launcher (runs pkg under Windows Python)
run_gui.sh        # WSL->Windows launcher for the GUI
pyproject.toml    # setuptools; package is `etabs_extractor*`; [project.scripts] etabs-extractor-gui
pyrightconfig.json
.venv/            # WSL venv for editing/testing only (NO COM)
```

### Layering invariants

- **`models.py`, `io.py`, `config.py`, `units.py` are pure** — no COM, no
  Windows, no `comtypes`. They must stay importable on any platform (WSL
  included).
- **`plots.py` is pure too**, and imports **matplotlib lazily** (inside
  functions) exactly like pandas is imported lazily in `models.py`, so the
  module imports safely even where matplotlib is absent. Do not hoist a
  top-level `import matplotlib`.
- **`connection.py` is the ONLY place that touches COM.** Every `comtypes`
  import there is **lazy** (inside functions), so importing other modules
  never forces COM. `EtabsSession` exposes a small, **duck-typed** surface
  (`frame_force`, `joint_react`, `get_frame_names`, `get_combo_names`,
  `get_case_names`, `get_point_names`, `get_point_coords`,
  `get_section_for_frame`, `get_frame_length_mm`, `get_present_units`,
  `get_story_elevations`, `get_all_point_coords`, `setup_select_loads`,
  `open_model`, `run_analysis`) so tests substitute a fake.
- **`results.py` orchestrates against the duck-typed surface**, never
  against COM directly. Same code path runs on a live session or the test
  fake. This is what makes the dry-run test possible without ETABS.
- **`__init__.py` re-exports only non-COM symbols at top level.** Adding a
  COM-touching import here would break WSL importability.

### Data flow

```text
# Frame extraction (--extract frame, default)
CLI/API -> results.extract_forces()
        -> _connect_session()        (resolve model, get EtabsSession)
        -> _extract() driver         (shared by every ExtractKind)
           -> _resolve_unit_ctx()    (session.get_present_units() -> src;
                                      resolve_target(src, force_unit, length_unit)
                                      -> dst; factors(src, dst) -> _UnitCtx)
           -> _select_loads() -> setup_select_loads()  (enable outputs in ETABS)
        -> get_frame_names()
        -> _read_frame_forces() per frame  (session.frame_force, uctx)
        -> FrameForceRecord[]        (one per station, with length_mm,
                                      force_unit, length_unit — all in uctx.dst)
        -> models.to_dataframe()  -> consolidated + per-load DataFrames
        -> io.write_csv / write_all_forces_csv / write_envelope_csv

# Base-reaction extraction (--extract base)
CLI/API -> results.extract_base_reactions()
        -> _connect_session() -> _extract() driver  (same as frames:
           _resolve_unit_ctx() -> _select_loads() -> setup_select_loads())
        -> session.get_point_names()            (all point objects)
        -> per point: get_point_coords() -> (x,y,z); session.joint_react(); uctx
        -> JointReactionRecord[]        (one per load per point, force_unit/length_unit)
        -> models.to_base_dataframe() -> consolidated + per-load DataFrames
        -> io.write_base_csv / write_all_base_csv / write_base_envelope_csv
           + write_base_envelope_min_csv / write_base_envelope_max_csv
```

### Run paths

- **Dry run / tests (any platform):** `python etabs_extractor/tests/test_dry_run.py`
  injects `FakeSapModel`, exercises extraction → DataFrame → CSV, asserts
  column order + row counts. All stub values are synthetic. It now also
  drives `extract_base_reactions()` over the fake (`joint_react`), asserting
  `BASE_COLUMNS` order, populated `x/y/z`, and the `base_*.csv` family.
- **Live ETABS (Windows-only):** via `run_etabs.sh` (see below), or directly
  with Windows Python `python -m etabs_extractor ...`.

### CLI modes

```text
--extract frame   (default)  Results.FrameForce  -> all_forces.csv + combo_*/case_* + envelope_summary.csv
--extract base               Results.JointReact  -> all_base_reactions.csv + base_combo_*/base_case_* + base_envelope_summary.csv
                             + base_envelope_min.csv / base_envelope_max.csv
--list-only                  inventory (frames, points, combos, cases, units, elevations)
--frames <names>             frame-only name filter (ignored for base)
--points <names>             base-only point name filter (applied first)
--elevation <z>              base-only: only points at this z elevation, in the OUTPUT
                             length unit (e.g. -16000 for mm, -16.0 for --length-unit m)
--only-loaded                base-only: drop points with all-zero reactions (keeps loaded)
--combos/--cases/--all       same load-selection mechanism for BOTH modes
--force-unit <unit>          output force/moment unit: model (default, no conversion) |
                             N | kN | kgf | tonf | lb | kip. Applies to BOTH modes.
--length-unit <unit>         output length unit (coords/station/length): model (default) |
                             mm | cm | m | in | ft. Applies to BOTH modes.
--plot                       base-only: render plan-view (x-y) figures of the base reactions
                             (one PNG per load) into the output dir after extraction
--plot-csv <path>            standalone: read a base CSV and plot it (no COM/model; WSL-ok)
--plot-format <fmt>          image format for --plot/--plot-csv (default png; e.g. pdf, svg)
--plot-steps <v,v,...>       comma-separated plot variants for --plot/--plot-csv: absmax,max,min
                             (default "absmax" — today's behavior). max/min plot only that
                             envelope step's rows (stepless loads skip them; filenames get
                             _max/_min) — see "Step variants" in README / plots.STEP_VARIANTS
--units <unit>               plot display units: model/data (default; the CSV/DataFrame's own
                             force_unit/length_unit, unconverted), a named preset (kN-m, kN-mm,
                             N-mm, tonf-m, kgf-m), or any "<force>-<length>" pair (e.g. tonf-mm)
--components <c,c,...>       reaction components shown in each point's label (applies to
                             --plot/--plot-csv): Fx Fy Fz M1 M2 M3 (argparse choices; default
                             Fz M2 M3). Empty selection -> point-number-only labels
--label-dx <pts>             label offset from its marker, points, x dir (default -6);
                             applies to --plot/--plot-csv. POSITION offset — distinct from
                             the X/Y edge padding (inches)
--label-dy <pts>             label offset from its marker, points, y dir (default -18);
                             same scope as --label-dx
--tag <name>                 append `_<name>` to EVERY CSV and plot filename (sanitized suffix;
                             absence/empty/whitespace = no suffix)
```

---

## Invariants / hard rules (do not break)

1. **Never hardcode a model path or `/mnt/d` / `D:\` path** in code. Model &
   output locations come from CLI args or `ETABS_MODEL` / `ETABS_OUTPUT`
   env vars with non-binding defaults. `config.to_windows_path()` does the
   POSIX→Windows conversion at the connection layer.
2. **COM stays quarantined in `connection.py` and lazy.** If you add a new
   ETABS read (e.g. walls, base reactions), the new COM call goes on
   `EtabsSession` (with `comtypes` imported lazily), and `results.py`
   consumes the **duck-typed** method only.
3. **All `int()` / `float()` coercions of COM values must be null-safe** and
   follow the existing `_to_int` / `_f` / `_f_optional` pattern. Bare
   `int()`/`float()` outside try/except is flagged by the
   `unchecked-throwing-call-python` rule — do not reintroduce it.
4. **No silent `except: pass`.** Best-effort teardown goes through
   `_release_helper()` (logs a debug line). Bare `pass` excepts are flagged
   by the `python-empty-except` rule.
5. **Never fabricate results.** Any number, path, or claim must trace to real
   tool output. The dry run's `FakeSapModel` forces are explicitly synthetic
   and must stay labeled as such — it is a *pipeline* test, not a results
   source.
6. **Keep the editable-install triple together:** `etabs_extractor/` +
   `pyproject.toml` + `.venv/` must stay colocated (the venv's editable
   install maps to that layout). Moving one breaks `import etabs_extractor`
   from elsewhere.
7. **Update `run_etabs.sh`** if the CLI/launcher behaviour changes.

8. **Keep AGENTS.md and README.md in sync — always update BOTH.** Whenever a
   feature, workaround, or known bug is added/changed in this project,
   reflect it in BOTH this file and `etabs_extractor/README.md` in the same
   change. This is a standing, automatic requirement for every edit that
   affects behaviour, architecture, CLI surface, outputs, or known issues:
   - AGENTS.md is the canonical developer guidance (architecture, invariants,
     verification steps, extending pattern).
   - README.md is the user-facing doc (quick start, CLI usage, library API,
     outputs, live-run launcher).
   If a change is worth making, it is worth documenting in both — do not
   ship a feature that updates only one. If you are unsure a change needs
   docs, still check that neither file is now stale (e.g. a new CLI flag or
   output file must appear in both).

9. **Plotting is pure + lazy-matplotlib.** `plots.py` never touches COM and
   imports matplotlib only inside functions, so the package stays importable
   on any platform without matplotlib (same lazy pattern as pandas in
   `models.py`). New plot entry points / components go in `plots.py`;
   document any change in both docs.

10. **The GUI is a thin view with lazy deps, built on customtkinter.** The
    `gui/` package adds no COM/matplotlib at *module* import time. `app.py`
    and the `widgets/` modules import `customtkinter` (as `ctk`) at module
    level — unavoidable, since `EtabsExtractorApp(ctk.CTk)` and every widget
    class subclass a `ctk` base class at class-definition time — but this
    still needs **no display** to import (only instantiating a window does),
    same as the stdlib `tkinter` it wraps; it *does* need the `customtkinter`
    package installed (a real pip dependency, unlike stdlib `tkinter`), which
    is why `run_gui()` (`gui/__init__.py`) catches `ImportError` and prints a
    one-line `pip install customtkinter` hint instead of a raw traceback.
    Matplotlib is imported lazily in `widgets/preview.py` / `plots.py` (inside
    functions, never at module level), and COM is only reached via the
    existing `connection.py`/`results.py`/`plots.py` layers through
    `service.py`. All real work stays in those layers; the GUI is pure view +
    orchestration. `state.py` and `service.py` are importable headlessly with
    **no** `customtkinter` dependency and are unit-tested in
    `tests/test_plot_settings.py`; `tests/test_gui_smoke.py` exercises the
    `ctk`-dependent view layer itself (skips cleanly with no display).
    **Keep the background runner**: extraction runs on a `threading.Thread`
    (`gui/runner.py`'s `BackgroundRunner`) and posts `(kind, payload)` queue
    messages so the main thread stays responsive; COM is initialised in the
    worker thread (comtypes `CoInitialize()` before the job, `CoUninitialize()`
    after — required on Windows for COM calls off the main thread; a no-op on
    non-Windows). Don't hoist top-level `import matplotlib` into the package
    modules, and don't do COM or blocking work on the main thread.
    **Previews are embedded, not pop-ups**: `BasePreviewPanel` /
    `FramePreviewPanel` (`widgets/preview.py`) live inside the workspace's
    "Preview" tab and are shown/hidden by grid()/grid_forget() as the mode
    switch changes, rather than opened as separate `Toplevel` windows.

---

## The `run_etabs.sh` launcher (how live runs work from WSL)

COM needs a Windows Python process, but WSL can execute Windows binaries.
`run_etabs.sh` bridges that:

- **Auto-discovers** the Windows Python (`python.exe` at standard locations;
  override with `WIN_PY=`, or drop a colocated `windows_python.exe`). Never
  hardcode a versioned name like `python3.14-64.exe` — that typo is exactly
  what made first-try runs fail historically.
- **Converts `/mnt/<drv>/…` args → `<DRV>:\…`** (already done at the config
  layer too, but the launcher makes it seamless for users).
- **`cd`s into the package root** before launching, avoiding `cmd.exe`
  "UNC paths not supported".
- Requires **ETABS running** (or pass `--launch`) and the referenced model
  open in that session.

Usage:

```bash
cd ~/Projects/Structural\ Works/etabs_extractor
./run_etabs.sh --list-only --model "/mnt/d/.../model.EDB"
./run_etabs.sh --model "/mnt/d/.../model.EDB" --all --output "/mnt/d/.../out"
```

---

## Known issue (FIXED): the WSL venv console-scripts were stale

The `.venv/` was moved after creation, so `.venv/bin/pip` and
`.venv/bin/pyright` had broken shebangs (pointing at the old
`/home/siboi/Projects/Structural Works/.venv`). These were repaired by
rewriting the `'''exec' "..."` line in each wrapper to point at the current
`.venv` (so `.venv/bin/pyright` and `.venv/bin/pip` now work again). A full
venv rebuild would also have fixed them; the in-place fix avoids reinstalling
deps. If you ever move `.venv` again, re-apply the same shebang fix (or
rebuild) — nothing else depends on it beyond those two console wrappers.

---

## How to check your work

- **Compile:** `python -m py_compile etabs_extractor/*.py etabs_extractor/gui/*.py etabs_extractor/gui/widgets/*.py etabs_extractor/tests/*.py`
- **Type:** `python -m pyright etabs_extractor/`  (keep 0 errors)
- **Tests:** `MPLBACKEND=Agg python etabs_extractor/tests/test_dry_run.py` → expect `PASSED`
  (uses the non-interactive Agg backend; covers frame + base + plan plotting, plus
  tagged/untagged filenames, split min/max envelopes, point-number labels, model-aware
  unit conversion (`force_unit`/`length_unit`, an explicit non-model conversion against
  the fake's N/mm present units) and `list_elevations()` story labelling)
- **GUI pure-layer + figure-builder tests:**
  `MPLBACKEND=Agg python etabs_extractor/tests/test_plot_settings.py` → expect `PASSED`
  (headless, no display, no comtypes; covers `build_base_reactions_figure` fixed/dynamic
  size + no-points->None, `plot_base_reactions` dpi/figsize/fontsize threading, the
  `gui.service` settings->args mapping (incl. `force_unit`/`length_unit`,
  `build_elevation_labels`) + `gui.state` parsing (incl. the elevation combobox's
  labelled-entry format), and `etabs_extractor.units`'s conversion factors; also imports
  `gui.app` / `gui.runner` / `gui.widgets.preview` / `gui.widgets.plot_settings` to
  confirm they import with no display — this DOES require `customtkinter` installed,
  since those modules import it at module level). Also covers the step-variant
  plotting: `plot_base_reactions(steps=...)` file sets per envelope/stepless load,
  invalid-variant `ValueError`s, `build_base_reactions_figure(step=...)` label-text
  filtering (Max-only vs abs-max), and the `service.save_batch_plots` target-dir
  fallback chain. Also covers the editable label settings:
  `build_base_reactions_figure(label_dx=..., label_dy=...)` annotation offsets
  (via `get_position()`, defaults `(-6, -18)`), label component content
  (`components=("Fz", "Fx")` adds an `Fx=` line; `()` = point-number-only),
  `plot_base_reactions` label-kwarg threading (incl. a steps variant), and
  `service.build_plot_kwargs`/`build_figure_kwargs` `label_dx`/`label_dy`/
  `components` mapping + the CSV plot path's key-filter passthrough.
- **GUI headed smoke test (needs a real display, e.g. WSLg):**
  `MPLBACKEND=Agg python etabs_extractor/tests/test_gui_smoke.py` → expect `PASSED`
  (prints `SKIPPED (no display)` and exits cleanly with none). Builds the real
  `EtabsExtractorApp` (withdrawn, no mainloop), fills sidebar widgets and asserts
  `_collect_settings()` maps them (incl. `force_unit`/`length_unit`); asserts the
  sidebar's Model/Output Browse buttons fit inside their field's geometry (guards the
  fields.py layout fix — checked via geometry bounds, not `winfo_ismapped()`, since the
  window is withdrawn); round-trips a units change through the units hint + elevation
  combobox labels; toggles the mode switch and asserts the base/frame filter containers
  and preview panels swap via pack/grid visibility; feeds a synthetic base-reaction
  result into `BasePreviewPanel` and asserts a figure renders; exercises the
  base preview's **Step** dropdown (envelope data re-renders Max-only labels,
  stepless data falls back to abs max) and the **Batch save plots** wiring
  (`batch_saver == app._on_batch_save`), and round-trips the **Batch plot
  dir** through `_collect_settings` in both modes. No
  COM/ETABS/matplotlib-in-Windows-Python involved.
- **Plot smoke (no COM, WSL):** `python -m etabs_extractor --plot-csv <dir>/all_base_reactions.csv`
  → expect a `base_<load>_plan.png` next to the CSV for each load. With
  `--tag KM13` the files become `base_<load>_plan_KM13.png`.
  Split CSVs plot to step-suffixed figures: `--plot-csv <dir>/base_combo_ASD_Max_min.csv`
  → `base_ASD_Max_plan_min.png` (title `ASD Max (Min)`); the `_max.csv` →
  `base_ASD_Max_plan_max.png` (distinct file, no overwrite).
  With `--plot-steps absmax,max,min` every envelope load yields three files
  (`base_<load>_plan.png`, `_max`, `_min`); stepless loads yield one.
- **pi-lens:** run diagnostics on edited files; the two known rules to respect
  are `unchecked-throwing-call-python` (int/float/open) and `python-empty-except`
  (no bare `pass`).
- **Live sanity (if ETABS is running + user asks):** `./run_etabs.sh --list-only --model <path>`
  → expect real frame/combo/case counts (and `Point objs`), plus `Units: <force>,
  <length>` and one `z=... -> N point(s)` line per model elevation.
  `./run_etabs.sh --extract base --model <path> --combos "ASD 1" --output <dir>`
  → expect a populated `all_base_reactions.csv` and two `base_combo_*.csv`, with
  `force_unit`/`length_unit` columns matching the model's own present units (default
  `--force-unit model --length-unit model`). **Note:** `--model` always calls
  `File.OpenFile`, even to "attach" — if the model is already open and you don't want it
  reopened, prefer `EtabsSession.connect(attach=True)` with no `model_path` (the GUI's
  "Check active model" path) to exercise `get_present_units()` / `list_elevations()` /
  `extract_base_reactions(session=..., model_path=session.get_model_filename())`.

---

## Extending the framework (columns / walls / base reactions)

The architecture is designed to make this additive. The pattern:

1. **New COM read** → add a method on `EtabsSession` in `connection.py`
   (lazy `comtypes` import), returning a duck-typed result your orchestrator
   consumes.
2. **New record type** → add a dataclass in `models.py` mirroring
   `FrameForceRecord` / `JointReactionRecord` (with its own `to_dict()` +
   `COLUMNS` if the schema differs, e.g. walls have different axes/forces).
3. **New read function** → add `_read_<type>_forces()` in `results.py`
   beside `_read_frame_forces()` / `_read_point_reactions()` — signature
   `(session, name, combos, cases) -> list[Record]`.
4. **Register the kind** → build an `ExtractKind` in `results.py` (label,
   `get_names`, `read`, `to_df`, `write`). The shared driver
   `_extract(kind, ...)` already owns connection, load selection
   (`_select_loads` → `setup_select_loads`), name filtering, per-item
   reads, optional `post_filter`, DataFrame assembly and teardown; the
   kind supplies only what differs. Frame forces use the module-level
   `_FRAME_KIND`; per-call kinds capture extra context via closures (e.g.
   `_make_point_reader(elevation)`).
5. **I/O** → `io.py` has writers for both the frame (`write_csv`,
   `write_all_forces_csv`, `write_envelope_csv`) and base-reaction schemas
   (`write_base_csv`, `write_all_base_csv`, `write_base_envelope_csv`, plus the
   split `write_base_envelope_min_csv` / `write_base_envelope_max_csv`). The
   writers are concrete per schema (each takes its own `*_COLUMNS` + rows);
   add new writers beside them rather than duplicating frame logic by copy,
   then point the kind's `write` at a small per-kind writer (like
   `_write_frame_csvs` / `_write_base_csvs`).
6. **Public wrapper** → `extract_<type>` becomes a thin function that builds
   the kind and calls `_extract(...)` (see `extract_forces` /
   `extract_base_reactions`); the driver and the other kinds are untouched.

### Completed: base reactions (already implemented)

`--extract base` was built exactly along this pattern:

- `JointReactionRecord` (`models.py`) + `BASE_COLUMNS` + `to_base_dataframe()`
  - `summarize_base_envelope()` + `summarize_base_envelope_minmax()`
    (split MIN/MAX subsets).
- `EtabsSession.get_point_names` / `get_point_coords` / `joint_react`
  (`connection.py`), with the null-safe `_f_coord` helper for coordinates.
- `extract_base_reactions()` + `_read_point_reactions()` (`results.py`);
  `list_available()` also returns `point_names`.
- `write_base_csv` / `write_all_base_csv` / `write_base_envelope_csv` (`io.py`),
  plus `write_base_envelope_min_csv` / `write_base_envelope_max_csv` (the
  per-(point, load) MIN / MAX subsets: `F1_min…M3_min` / `F1_max…M3_max`).
  Combined `base_envelope_summary.csv` is retained alongside the two new files.
- CLI `--extract frame|base` + `--points` (name filter) + `--elevation`
  (single-`z` filter); `__init__.py` re-exports the new pure symbols; tests
  extended with `_FakePointObj` / `_FakeJointReact`.
- **Base-reaction export units** (superseded by "Completed: model-aware
  units" below): `_read_point_reactions()` (`results.py`) originally always
  divided source **N** forces by `1000` (→ kN) and source **N·mm** moments by
  `1e6` (→ kN·m), hardcoding the assumption that every model is N/mm. This is
  now model-aware — see below for the current behavior.

  Note on ordering: `--only-loaded` runs **after** unit conversion, so
  `_is_null_reaction()` compares already-converted values. That is still
  correct for genuinely-zero supports (0 in any unit remains 0), so the
  filter behavior is unchanged.

The `--elevation` filter compares each point's `z` against the requested
value with a small tolerance (`_z_match`, `tol` ≈ 1mm expressed in the
*model's own* length unit — see "Completed: model-aware units"; a fixed
`tol=1.0` was wrong for any model not natively in mm, e.g. a kN/m model
merged story elevations under a metre apart) before reading reactions — so
extracting one level (e.g. `-16000`) skips reading every other joint
entirely. It applies after the `--points` name filter.

`--only-loaded` post-filters the assembled records with `_is_null_reaction`
(all six components ≈ 0 → dropped), so the CSV holds only supports that
actually carry load — e.g. with envelope combos `ASD Max`/`LRFD Max` at
`z=-16000` this yields the 100 loaded points that match the reference
`KM13 Chamber 3.0.xlsx` 1-to-1.

### Completed: per-load MIN/MAX step split CSVs + step-aware plotting + preview Refresh

Two linked changes made the base-reaction export step-aware and the preview
re-appliable:

**Per-load MIN/MAX split CSVs (base reactions only):**

- `JointReactionRecord` gains `step_type: str = ""` (`models.py`, last field so
  the dataclass default ordering stays valid) — the ETABS `StepType` value
  (`"Max"` / `"Min"` for envelope combos, `""` for plain loads).  It is
  exported between `load_kind` and `F1` in `to_dict()` and in `BASE_COLUMNS`,
  so `all_base_reactions.csv` and every base DataFrame distinguish steps.
- `_read_point_reactions()` (`results.py`) captures `step_type=_s(StepType, i)`
  (`StepType` was already in the unpacked `JointReact` tuple, position 4,
  previously discarded).  New null-safe `_s(seq, i) -> str` helper mirrors `_f`.
- New `io.write_base_step_csv(records, output_dir, load_name, load_kind,
  step, tag=None) -> Path | None` writes `base_combo_<load>_<step>.csv` /
  `base_case_<load>_<step>.csv` (`step` lowercased + `_sanitize_filename`, tag
  appended last — e.g. `base_combo_ASD_Max_min_KM13.csv`); returns `None` for
  empty records (no placeholder files).  Schema is the full `BASE_COLUMNS`.
- `extract_base_reactions()` partitions each load's records by step via the
  `_step_key()` helper (lowercased/stripped; only `"max"`/`"min"` match):
  `Min` rows → `_min.csv`, `Max` rows → `_max.csv`; rows with any other step
  (`""`, `"Step By Step"`, …) stay only in the mixed per-load file.  Split
  files are written **in addition to** the mixed `base_combo_<load>.csv` and
  only when non-empty.  Frame-force CSVs are unchanged (base-only scope).

**Step-aware plotting (split CSVs stay plottable):**

- `plots._single_step(df) -> str | None` returns the single distinct non-empty
  `step_type` of a frame (``None`` for multi-step / stepless).  `_build_title`
  appends it in parentheses (``ASD Max (Min)``) and `_plot_one` appends
  ``_<step>`` (lowercased) to the figure stem before any tag, so plotting both
  split files of one load into a directory never overwrites
  (`base_<load>_plan_min.png` vs `base_<load>_plan_max.png`; with a tag
  `base_<load>_plan_min_KM13.png`).  Mixed/multi-step inputs (the consolidated
  df, `all_base_reactions.csv`, the mixed per-load CSV) keep today's names and
  titles exactly.  `--plot-csv` / `plot_base_reactions_from_csv` / GUI "Load
  preview" accept the split CSVs unchanged (same `BASE_COLUMNS` schema).

**Step variants for plots (abs-max / Max / Min):**

- `plots.STEP_VARIANTS = ("absmax", "max", "min")` (re-exported from
  `__init__.py`).  `plots._filter_step(df, step)` returns `df` unchanged for
  `None`/`absmax` and, for `max`/`min` (case-insensitive), only the rows whose
  `step_type` equals it (null/NaN never match; unknown variant →
  `ValueError` naming the known list).  `plots._normalize_steps()` validates a
  `steps` sequence (`None`/empty → `("absmax",)`).
- `build_base_reactions_figure(..., step=None)` filters via `_filter_step`
  before the plottable check, and builds the title from the (step-filtered)
  frame so a max/min variant gets the existing `(Max)`/`(Min)` suffix;
  `plot_base_reactions(..., steps=None)` and
  `plot_base_reactions_from_csv(..., steps=None)` render one figure per load
  per variant — the abs-max path is byte-identical to before (including the
  `Path()` placeholder return), empty filtered frames are skipped with a
  debug log and no placeholder.  No naming code changed: the filtered frame
  carries exactly one `step_type`, so the existing `_single_step` stem logic
  and `_build_title` produce `base_<load>_plan_max.<fmt>` / `_min` + `(Max)`/
  `(Min)` titles naturally.
- CLI `--plot-steps absmax,max,min` (default `absmax`) threads `steps=` into
  both `--plot` and `--plot-csv`; an unknown variant raises `ValueError`
  surfaced by the CLI's existing plot error handling (exit 2/3 with a clear
  message).
- GUI: the base preview's **Step** dropdown (`Abs max`/`Max`/`Min`,
  `gui.state.STEP_CHOICES`, mapped via `preview._STEP_VARIANT`) re-renders on
  change through `app._build_preview_figure(df, load, settings, step=...)`;
  an empty step selection falls back to abs-max with a log note ("No Max
  steps for `<load>` — showing abs max").  The **Batch save plots...** button
  calls `service.save_batch_plots(result, settings)` via the background
  runner: it writes all three variants for **every load of the current
  result** into the sidebar's **Batch plot dir** (`GuiSettings.batch_plot_dir`;
  blank → Output dir for an extraction result, Plot output dir / CSV parent
  for a CSV-loaded result) and logs "Saved N plot(s) to `<dir>`".

**Preview Refresh + auto-render (`gui/widgets/preview.py`):**

- A **Refresh** button next to Preview/Save re-captures the plot settings from
  the main window (`settings_provider` — `_collect_settings` — already reads
  the plot widgets fresh on every call) and re-renders the selected load
  (`_refresh_settings()`), logging "Refreshed preview with current plot
  settings."
- `set_result()` now **auto-renders the first load** with the current settings
  instead of leaving the canvas empty (so a new extract/CSV result shows the
  figure immediately; changed settings are applied by Refresh/Preview).
- `dpi`/`format` remain save-time only (the canvas is screen-resolution; `Save
  preview image` already uses `settings.dpi` / `settings.format`).

### Completed: interactive GUI + plot-appearance params

A **tkinter GUI** was added (`etabs_extractor/gui/`) covering **base
reaction extraction + plotting only** (per scope). It is a thin view over
`results`/`plots`/`connection`.

Plot-appearance args were added to the plotting entry points (backward
compatible, defaults unchanged):

- `dynamic_size: bool = True` — True uses ``_dynamic_figsize`` (figure
  follows data extent); False uses the fixed ``figsize`` in inches.
- `figsize: tuple[float, float] | None = None` — fixed size (default
  ``(10, 8)``) when ``dynamic_size=False``.
- `dpi: int = 800` — save resolution (replaces the hardcoded ``800`` in
  ``savefig``).
- `label_fontsize` — already existed (default ``2.4``).
- **`x_offset: float = 1.0` / `y_offset: float = 1.0`** — edge-label padding
  (inches) applied to the **axis limits**, not the canvas: the equal-aspect
  data scale converts the inches to data units, and `xlim`/`ylim` are widened
  by that amount on each side (on top of matplotlib's normal 5% auto
  margins), so edge point labels render **inside** the axes box and the box
  border never cuts through a label. The figure size stays exactly the base
  size (dynamic or fixed); pass `x_offset=0, y_offset=0` for no extra
  padding.
- **`label_dx: float = -6.0` / `label_dy: float = -18.0`** — the label's
  offset from its marker, in **points** (`xytext=(label_dx, label_dy)` with
  `textcoords="offset points"`, replacing the hardcoded `(-6, -18)`).
  Position only — distinct from the inch-based x/y edge padding above.
- Threaded through `plot_base_reactions`, `plot_base_reactions_from_csv`,
  and the new `build_base_reactions_figure` (all three also take the
  existing `components` param, validated by `_validate_components`).

`build_base_reactions_figure(df, load_name, *, components, title, units,
label_fontsize, dynamic_size, figsize, x_offset, y_offset) -> Figure | None`
is a new **public** reusable figure builder: it draws one plan-view figure
(scatter + annotations + title/axes) **without saving**, and returns ``None``
when a load has no plottable points. `_plot_one` now calls it then
`savefig(..., dpi=dpi)` and closes. The GUI preview renders it into a
`PlotPreviewFrame` canvas inside a **separate pop-up window**
(`PlotPreviewWindow`, a `tk.Toplevel`) opened manually via the `Plot preview`
button — not embedded in the main window.

The offset layout in `build_base_reactions_figure`:

- figure size is exactly the base size (dynamic or fixed) — offsets never
  inflate the canvas;
- `fig.subplots_adjust(left=0.1, right=0.9, bottom=0.1, top=0.9)` fixes the
  axes box, and `_pad_axis_limits()` widens `xlim`/`ylim` by the offset
  converted from inches to data units via the equal-aspect scale, on top of
  the default 5% auto margins — the whitespace sits **inside** the axes box,
  so labels near the edges render inside the box instead of crossing its
  border;
- `ax.set_aspect("equal", adjustable="box")` keeps the data aspect true
  while the box stays fixed (the shorter direction letterboxes inside the
  axes);
- annotations keep `annotation_clip=False` / `clip_on=False` as a safety
  net; `_plot_one` keeps `bbox_inches="tight"` so saved images expand to fit
  the outermost label.

New COM touchpoint (quarantined in `connection.py`):
`EtabsSession.get_model_filename(include_path: bool = True) -> str` — calls
``SapModel.GetModelFilename(bool)`` (a **cSapModel** method on the model
object, **not** the `File` interface; calling it on `File` fails at runtime),
null-safe-coerces the comtypes return (str or list) to `str`, raises
`EtabsConnectionError` on failure.  Used by the GUI's "Check active model"
button.  The dry-run fake mirrors this real contract (`GetModelFilename` on
on the fake `SapModel`, returning a plain string).

GUI layout/behaviour (full detail in `service.py` / `app.py`):

- **Model row**: file entry + Browse (`.EDB`/`.et`) + "Check active model"
  (attaches to ETABS, backfills the path via `get_model_filename`, and also
  reads `get_combo_names` / `get_case_names` to populate the load dropdown
  below — see "Searchable multi-select load dropdown").
- **Destination row**: dir entry + Browse (defaults from `ETABS_OUTPUT`),
  **Tag row** (sanitized like `io._sanitize_filename`).
- **Load selection** — a **searchable multi-select checklist** widget
  (`LoadSelectionField` in `gui/widgets/load_selection.py`) of the active
  model's **combos + cases**; empty selection keeps today's default (all model
  combos). Selecting both kinds extracts both (see "Both-streams extraction").
  Plus optional `elevation`, `only_loaded`, `run_analysis`, `attach`
  checkboxes.
  Note: the plot preview renders one marker per distinct plan (x/y) point
  returned by the extraction — envelope Max/Min steps collapse to one
  governing marker per point (no duplication). But all-zero (non-load-bearing)
  base joints are still plotted unless **only_loaded** is checked; for a clean
  plan use `elevation` + `only_loaded`.
- **Plot settings frame**: `dynamic_size` checkbox, width/height (disabled
  when dynamic), **X/Y label offset (in)** fields (default 1.0 each — extra
  axis-limit padding so edge labels render inside the axes box), dpi
  (default 800), label font size (default 2.4), units
  (`model`/`kN-m`), format (`png`/`pdf`/`svg`), **Label** component
  checkboxes (`Fx Fy Fz M1 M2 M3`, default `Fz M2 M3` — which reaction
  values each point's label shows) and **Label dx/dy (pts)** entries
  (defaults `-6`/`-18` — the label's offset from its marker, in points).
  "Plot after extract".
- **CSV section (no ETABS)**: CSV file + Browse + "Load preview".
- **Plot preview pop-up (manual)**: a separate `tk.Toplevel`
  (`PlotPreviewWindow` in `gui/widgets/preview.py`) hosts the load dropdown
  - embedded `PlotPreviewFrame` canvas + `Preview` / `Save preview image`
  buttons. Opened only via the **Plot preview** button in the main window —
  never auto-popped after Extract / Load-preview. It builds figures through
  `build_base_reactions_figure` (via `app._build_preview_figure`) and saves
  at the chosen dpi/format. Closing it leaves the main window alive.
- **Actions**: a **single** `Extract` button in the bottom bar + `Quit`.
  Extract / Load preview run in a background thread; progress bar + log
  line.

Launcher: `./run_gui.sh` (mirrors `run_etabs.sh`) → Windows Python
`python -m etabs_extractor.gui`. Installable console script:
`etabs-extractor-gui` via `[project.scripts]` in `pyproject.toml`.

### Completed: searchable multi-select load dropdown + both-streams extraction

Two linked changes replace the GUI's free-text combo field with an
interactive checklist, and let **combos and cases be extracted together**:

- **`service.inspect_active_model(attach=True, session=None) -> dict`** — a
  richer replacement for the old `check_active_model`: returns
  `{"model_path", "combos", "cases"}` by reading
  `get_model_filename` / `get_combo_names` / `get_case_names`. `check_active_model`
  is now a thin wrapper returning `inspect_active_model(...)['model_path']`
  (kept for backward compatibility; internal GUI API only).
- **`LoadSelectionModel`** (in `gui/state.py`, pure/headless-testable): holds
  distinct combo + case item lists with `selected` flags, a `matches(query)`
  substring filter, and `get_selected() -> (combos, cases)`. `set_items`,
  `set_selected`, `toggle(index, bool)`, `clear` round out the API.
- **`LoadSelectionField`** (new `gui/widgets/load_selection.py`) — a `tk.Frame`
  with a read-only summary entry ("N selected" / "all combos") that opens a
  `tk.Toplevel` popup on the **Select** button / entry click. The popup has a
  search `ttk.Entry` (filters the checklist as you type, case-insensitive
  substring over the `(combo) NAME` / `(case) NAME` labels) and a scrolling
  checklist of `ttk.Checkbutton`s; a **Done** button closes it. Selection
  persists across opens. API: `set_items(combos, cases)`, `get_selected()`, `clear()`.
- **`app.py`** — `self.combo_field` (`LabeledEntry`) is replaced by
  `self.load_field` (`LoadSelectionField`) under "Load selection". `on_check_model`
  / `_on_check_done` now call `inspect_active_model`, backfill the model path,
  and call `load_field.set_items(combos, cases)`. `_collect_settings` stores
  `selected_combos` / `selected_cases` on `GuiSettings`.
- **`gui/state.py`** — `GuiSettings.combos` (free-text string) is **removed**
  in favor of `selected_combos: list[str]` and `selected_cases: list[str]`
  (default empty). `parse_combos` stays as a utility (no longer used by the
  GUI flow).
- **`service.build_extract_kwargs`** — maps `combos = selected_combos or None`,
  `cases = selected_cases or None`; empty selection → `None` (the existing "all
  model combos" default).
- **Both-streams extraction (CLI + GUI)**: `results._resolve_names` gained a
  both-streams branch — when both `combos` and `cases` are passed (both
  non-`None`), it returns `(combos, cases)` instead of cases superseding
  combos. All other branches (all_requested / cases-only / combos-only /
  default-all-combos) are unchanged. This is deliberate: passing `--combos`
  and `--cases` together now extracts both.
- **`EtabsSession.setup_select_loads(combos, cases)`** (COM, `connection.py`):
  calls `DeselectAllCasesAndCombosForOutput()` **once**, then selects the given
  combos and cases together. It is now the **only** selection method:
  `results._select_loads` routes every branch (combos-only / cases-only /
  both) through it, passing an empty list for the skipped stream — the old
  `setup_select_combos` / `setup_select_cases` were removed (calling one
  then the other would have each `DeselectAll...` the other's selection).
  Mirror it on `_FakeSession`
  in `tests/test_dry_run.py`, and make the fake `_records_for` return the
  **union** of selected combos + cases (matching the real COM contract).
- **Label offsets**: see the "Plot appearance" bullet in the GUI section above
  for the `x_offset` / `y_offset` params and the axis-limit padding layout in
  `build_base_reactions_figure`.

### Completed: editable label contents + offsets (components, label_dx/label_dy)

The per-point label boxes on base-reaction plan plots are configurable in
content and placement (defaults reproduce the historical rendering exactly):

- **Library** (`plots.py`): `build_base_reactions_figure`,
  `plot_base_reactions`, and `plot_base_reactions_from_csv` gained
  `label_dx: float = -6.0` / `label_dy: float = -18.0` — threaded through
  `_plot_steps` / `_plot_one` to the annotation's
  `xytext=(label_dx, label_dy)` (was hardcoded `(-6, -18)`). The existing
  `components` param (validated by `_validate_components` against
  `COMPONENT_COLUMNS`) was already supported by the library; an empty
  selection renders point-number-only labels (`_format_label` behavior —
  intentional and documented, no special-casing).
- **CLI** (`cli.py`): `--components Fz M2 M3` (nargs `*`, choices from
  `COMPONENT_COLUMNS`, default `None` = library default) and
  `--label-dx` / `--label-dy` (floats, defaults `-6`/`-18`), applied to both
  `--plot` and `--plot-csv`. The flags are **position** offsets (points),
  distinct from the inch-based X/Y edge padding.
- **GUI**: `GuiSettings` gained `label_dx`/`label_dy` (floats) and
  `label_components: list[str]` (default `Fz M2 M3`);
  `PlotSettingsFrame` renders six canonical-order checkboxes
  (`COMPONENT_CHECKBOXES` in `gui/widgets/plot_settings.py`) plus
  dx/dy entries (`parse_float` fallback-on-invalid, same as the other
  numeric fields); `service._label_components()` normalizes the ticked set
  to canonical `COMPONENT_COLUMNS` order, and `build_plot_kwargs` /
  `build_figure_kwargs` pass `label_dx`/`label_dy`/`components` through —
  so the preview, Refresh, plot-after-extract, CSV plotting, and Batch save
  plots all pick them up automatically. `load_from_csv`'s key filter for
  `plot_base_reactions_from_csv` now also passes the three new keys
  (its `components=None` hardcode was removed).
- **Tests** (`tests/test_plot_settings.py`): label-offset assertion
  (`get_position()` — an `Annotation.xyann` alias — equals the offset tuple;
  defaults `(-6, -18)`), component-content assertion (an `Fx=` line appears
  with `components=("Fz", "Fx")`, absent by default, point-number-only with
  `components=()`), `plot_base_reactions` threading incl. a steps variant,
  and `service.build_plot_kwargs`/`build_figure_kwargs` mapping + the CSV
  path's key-filter passthrough (end-to-end via `load_from_csv` on a temp
  CSV).

### Completed: plan-view plotting of base reactions

`plots.py` was added as a pure, lazy-matplotlib module (no COM):

- `plot_base_reactions(df, output_dir, *, components, load_name, fmt, title, units)`
  → one plan-view x-y scatter per `load_name`, each point annotated with its
  component values. Default components `("Fz","M2","M3")` map to
  ETABS columns `F1/F2/F3/M2/M3` (M1/Mx omitted by design).
- `plot_base_reactions_from_csv(csv_path, output_dir?, *, units, ...)` → reads
  a base CSV (no model/COM) and plots into the CSV's parent dir by default.
- Component/unit maps `COMPONENT_COLUMNS` / `COMPONENT_UNITS` are module-level
  and extensible for future components (e.g. adding `Mx`/`M1` back).
- Unit systems live in the `UNITS` dict (keys `"model"` and `"kN-m"`, plus
  `DEFAULT_UNITS == "model"`). Base reactions are already exported in
  kN / kN·m, so `force_scale`/`moment_scale` are identity (1.0) in both
  systems; only `length_scale` differs — `model` keeps coordinates in mm,
  `kN-m` converts them mm→m (÷1000). Labels, axes, and the shared-`z` title
  all reflect the chosen unit. Add a new key to `UNITS` to extend.
- Points with `NaN` x/y are skipped (logged at debug) — never crash; scale
  reads go through the null-safe `_scale` helper (mirrors `_f`).
- **Point-number label:** `_aggregate_maxabs` preserves the `point` name
  across the (x,y) group merge, and `_format_label` renders it as the **first
  label line** (bare number, e.g. `1`) so each marker is traceable to its
  joint — omitted defensively when the point is null.
- **Envelope aggregation:** `_aggregate_maxabs` collapses the per-point
  multi-rows (Max/Min envelope steps) to one label per component — the value
  with the largest absolute magnitude, sign preserved — so a point has a
  single marker and a single governing value.
- **Dynamic figure size:** `_dynamic_figsize` picks the canvas from the
  plotted x–y extent (aspect-equal, longer axis ~8–20in, min 6×5in), so the
  figure follows the plan geometry instead of a fixed 10×8in.
- **Plain label numbers:** `_fmt_plain` renders label values to ~3 sig figs in
  fixed notation (no scientific exponent), so labels show `12300` not
  `1.23e+04`.
- CLI: `--plot` (after `--extract base`), standalone `--plot-csv` (no COM),
  and `--plot-format` (default `png`) + `--units` (default `model`).
- **Step-aware plot naming:** a plotted subset holding exactly one distinct
  non-empty `step_type` (e.g. a `base_combo_<load>_min.csv` read via
  `--plot-csv`) gets `_<step>` (lowercased) in the figure stem and the step in
  the title — `base_ASD_Max_plan_min.png` titled `ASD Max (Min)`.  Multi-step
  / stepless inputs keep the legacy `base_<load>_plan.png` names.
- **Filename suffix `--tag NAME`:** applies to **all** outputs (frame + base +
  plots). Every public writer/plot function takes `tag: str | None = None`
  (threaded from the CLI and from `extract_forces` / `extract_base_reactions`
  / `plot_base_reactions` / `plot_base_reactions_from_csv`); the stem is
  suffixed via the `io._append_tag(stem, tag)` helper, which sanitizes the
  value with `_sanitize_filename` and treats empty/whitespace tags as no tag.
  E.g. `--tag KM13` → `all_base_reactions_KM13.csv`, `base_envelope_min_KM13.csv`,
  `base_ASD_Max_plan_KM13.png`.
- Re-exported from `__init__.py` (all pure / top-level-safe), incl.
  `UNITS` / `DEFAULT_UNITS`, `summarize_base_envelope_minmax`,
  `write_base_envelope_min_csv`, `write_base_envelope_max_csv`.

### Completed: frame-mode GUI switch + frame step-split CSVs + frame section/frame selector

A follow-up to base-reaction work added **frame extraction to the GUI** as a
second mode, plus per-load frame MIN/MAX step-split CSVs and an optional
section-name filter (library + GUI):

**Frame records: step type (library)**

- `FrameForceRecord` gains `step_type: str = ""` (last field, default keeps
the arg order valid) — the ETABS `StepType` value (`"Max"`/`"Min"` for
envelope combos, `""` for plain loads). It is exported between `load_kind`
and `N` in `to_dict()` and in `COLUMNS`, so `all_forces.csv` and every frame
DataFrame distinguish steps.
- `_read_frame_forces` (`results.py`) captures `step_type=_s(StepType, i)`
(the `StepType` array was already unpacked, previously discarded).

**Frame per-load MIN/MAX split CSVs (library)** — `io.write_frame_step_csv`
writes `combo_<load>_<min_or_max>.csv` / `case_<load>_<step>.csv` (no
`base_` prefix; returns `None` for empty records). `_write_frame_csvs`
partitions each load by `_step_key(r.step_type)` and writes the split
only when non-empty — **in addition to** the existing mixed
`combo_<load>.csv`. Frame-force envelope summary files are unchanged.
Exported from `__init__.py`.

**Section-name listing + section filter (library)** —
`EtabsSession.get_frame_section_names()` via `_gp(PropFrame.GetNameList)`
(same `_gp` pattern as `FrameObj.GetNameList`; COM quarantined).
`extract_forces(..., sections=None)` builds a per-call `ExtractKind` whose
reader early-returns `[]` when a frame's section is not in the filter
(`_make_frame_reader`), giving **AND** semantics with the existing
`frames` name filter (each optional). `list_available()` adds
`"section_names"` (best-effort try/except like `point_names`).

**GUI mode switch + frame selector** —
- `gui.state`: `GuiSettings` gains `extract_mode="base"`,
  `selected_sections: list[str]`, `selected_frames: list[str]`; `MODE_CHOICES`.
  `LoadSelectionModel` generalised to configurable group kinds
  (`kind_a="combo"`, `kind_b="case"` in `__init__`/`set_items`);
  `get_selected()` still returns a 2-tuple over the two groups;
  `all_combos`/`all_cases` are thin aliases of group-a/group-b (kept for the
  existing tests).
- `LoadSelectionField` gains `label`/`title`/`empty_summary` /
  `kind_a`/`kind_b` constructor args (defaults preserve base-mode behaviour);
  `set_items`/`get_selected` forward to the model.
- `app.py`: a `mode_var` radio row switches base vs frame;
  `_apply_mode()` (registered mode-scoped widgets in `_build_layout`)
  shows/hides base-only (elevation, only-loaded, plot frame, plot-after,
  CSV frame, plan-preview row) and frame-only (a second `LoadSelectionField`
  with `kind_a="section"`, `kind_b="frame"`, label `Frames`) via
  `pack()`/`pack_forget()`. `_collect_settings` sets `extract_mode`,
  reads `selected_sections/selected_frames` in frame mode, and leaves
  base-only fields untouched in frame mode. `frame_field` is populated when
  `inspect_active_model` returns `sections`/`frames`.
- `service.py`: `inspect_active_model` additionally returns `"sections"` and
  `"frames"` (each best-effort try/except → `[]`), `build_mode_kwargs`
  maps the active mode (frame → `{frames, sections, ...}`) and `do_extract`
  dispatches on `extract_mode` (frame → `extract_forces`, never plots;
  base keeps `extract_base_reactions` + optional plot). Result-dict shape is
  unchanged, so the plan-preview already carries `df`/`per_load` for both
  modes.

**Out of scope (intentionally):** no frame plotting/force-diagram preview
(result dict already carries `df`/`per_load`); no CLI `--sections` flag (CLI
`--extract frame` gains the step-split CSVs via `_write_frame_csvs`
automatically); no frame envelope MIN/MAX split files (`envelope_summary.csv`
stays as-is).

### Completed: beam force diagram viewer

A standalone interactive **beam force diagram viewer** (`beam_viewer.py`) was
added to the repository root. It loads the `all_forces.csv` output from a
frame-force extraction and displays axial-force (P), shear (V2), and
bending-moment (M3) diagrams for any beam in the model. No COM connection or
running ETABS is needed — it reads the CSV file directly.

**Architecture:**

- `beam_viewer.py` is a self-contained script (not part of the `etabs_extractor`
  package) that uses matplotlib for rendering and user interaction.
- It loads the CSV via pandas, filters by section type (B1, B2, K1, P600, RB-1)
  and load case, and auto-selects the beam with the highest absolute |M3| value.
- Forces are converted from model units (N / N·mm) to display units (kN / kN·m)
  for readability.
- Positive and negative regions are filled in green and red respectively, with
  max/min annotations on each diagram.

**Keyboard controls:**

| Key | Action |
|-----|--------|
| `←` / `→` | Cycle load cases |
| `↑` / `↓` | Cycle beams within the current section |
| `S` | Cycle section type |
| `H` | Toggle auto-select highest-force beam |
| `Q` | Quit |

**Usage:**

```bash
# After extracting frame forces, run the viewer from any platform:
cd ~/Projects/Structural\ Works/etabs_extractor
.venv/bin/python beam_viewer.py "/mnt/d/.../extracted/all_forces.csv"
```

**Known viewer limitations:**
- The viewer always shows P, V2, and M3 (the primary bending axis). For beams
  with significant V3/M2 (biaxial bending), only V2/M3 is displayed by default.
  The `FORCE_DIAGRAMS` tuple in the script can be edited to show V3/M2 instead.
- Station data is plotted as-is from the CSV; beams with very few stations
  (e.g. 3 for some P600 piles) produce coarser diagrams.
- Interactive mode requires a display (X11/Wayland on WSL/Linux, native on
  Windows). For headless batch rendering, use the script's functions directly.

### Completed: GUI overhaul (customtkinter, sidebar + embedded workspace)

The GUI was rebuilt from `tkinter`/`ttk` onto **customtkinter**, and the
layout redesigned from "everything stacked in one window + pop-up preview
windows" to a **sidebar + tabbed workspace**. This supersedes the pop-up
window descriptions in "Completed: interactive GUI + plot-appearance params"
and "Completed: frame-mode GUI switch" above — read those for the *feature*
history (plot-appearance params, section/frame selectors, both-streams
extraction), but for *how the window is laid out today*, this section and
the README's "Interactive GUI" section are current.

**Why:** an earlier session's in-place tkinter->customtkinter port
(`etabs_extractor/gui/app.py` plus stray `Mostrar.`, a duplicate top-level
`gui/`, and an alternate `gui/app_new.py` draft) was left broken — a
`SyntaxError` (stray trailing `"""`), a `NameError` (`tk.Listbox` used
without `import tkinter as tk`), `_collect_settings()` deleted entirely (so
widget values never reached `GuiSettings`), the background `BackgroundRunner`
replaced with direct main-thread calls, `_apply_mode()` reduced to `pass`,
and both preview pop-ups stubbed to `pass`. Those files were reset to HEAD,
the stray files deleted, and the GUI rebuilt cleanly on customtkinter instead
of patched back to the broken port.

**Layout:** `EtabsExtractorApp(ctk.CTk)` is a `grid` of a `CTkScrollableFrame`
sidebar (column 0) and a `CTkTabview` workspace (column 1), with a status bar
spanning both columns in row 1.

- **Sidebar** (`_build_sidebar`): `Section` cards (a small `CTkFrame` +
  bold-title + `.body` sub-frame, replacing `ttk.LabelFrame` — customtkinter
  has no `CTkLabelFrame`) for **Model & output** (model `FileField`, "Check
  active model" + status line, output `DirectoryField`, `Tag` `LabeledEntry`
  with a live `sanitize_tag`-derived suffix hint, Attach/Run-analysis
  switches), **Extraction mode** (a `CTkSegmentedButton`, replacing the old
  radio buttons), and **Load selection** (`LoadSelectionField`). Two
  mode-scoped containers, `base_filter` / `frame_filter`, are `pack()`-ed
  and `pack_forget()`-ed by `_apply_mode()` (never both at once): base mode
  packs Elevation / Only-loaded / Plot-after-extract; frame mode packs a
  second `LoadSelectionField` (`kind_a="section"`) as the section filter.
  A single **Extract** button sits at the bottom.
- **Workspace** (`_build_workspace`): a `CTkTabview` with **Preview** (holds
  both `BasePreviewPanel` and `FramePreviewPanel`, `grid()`/`grid_forget()`-ed
  by `_apply_mode()` — only one is gridded at a time), **Plot settings**
  (`PlotSettingsFrame`, unchanged fields), **CSV** (`FileField` + "Load
  preview" button), and **Log** (`LogPanel`, a read-only `CTkTextbox` with
  timestamped `append()`, mirrored from every `_set_log()` call).
- **Status bar** (`_build_status_bar`): an indeterminate `CTkProgressBar`
  (started/stopped by `_set_busy()`), a status label, and an **Appearance**
  `CTkOptionMenu` (`System`/`Light`/`Dark`) wired straight to
  `ctk.set_appearance_mode()`. **Plotted figures intentionally stay
  light-themed** regardless of the app's appearance mode, on screen and when
  saved: `plots.py`'s point-label boxes are drawn `fc="white"`, so a dark
  matplotlib style would put white label text on white boxes. Only the app
  chrome follows the theme.

**Previews are embedded, not pop-ups** — the single biggest interaction
change. `widgets/preview.py` now exposes:
- `PlotCanvas` — a `FigureCanvasTkAgg` + `NavigationToolbar2Tk` host with an
  empty-state placeholder label; lazy `matplotlib` import exactly like
  before, just no longer inside a `Toplevel`. It is **`tk.Frame`, not
  `ctk.CTkFrame`** (see hard rule #2 below), and the matplotlib canvas object
  is stored as **`self._mpl_canvas`, never `self._canvas`** (hard rule #1).
  `sync_theme()` manually matches its background to the current ctk
  light/dark appearance mode (a plain `tk.Frame` has no theming of its own);
  `app.py`'s `_on_appearance_changed` calls it on both `base_preview.preview`
  and `frame_preview.preview` whenever the Appearance selector changes.

  **Rules for embedding a raw Tk/matplotlib widget under customtkinter**,
  found the hard way while debugging a still-**unresolved** preview pan/zoom
  bug (see "Known open issue: preview pan/zoom" below — each rule below is a
  real, confirmed, independently-worthwhile fix, but **none of them, alone or
  together, fixed the reported symptom in the full app** — don't re-close
  that issue on the strength of these alone):

  1. **`self._canvas` is reserved on every customtkinter widget.** Every
     `CTk*` widget (confirmed by grep across `ctk_frame.py`,
     `ctk_base_class.py`, and every other `ctk_*.py` in the installed
     package) uses `self._canvas` internally for its own background-drawing
     `CTkCanvas` (rounded corners etc., redrawn from
     `_draw()`/`_update_dimensions_event` on every `<Configure>`). Naming our
     matplotlib canvas attribute `self._canvas` on a `CTkFrame` subclass
     silently **clobbered** that reserved attribute. Symptom: constant
     `AttributeError: 'FigureCanvasTkAgg' object has no attribute
     'winfo_exists'` spam from inside customtkinter's own `_draw()`. Renaming
     to `_mpl_canvas` fixed the spam (confirmed, real fix, keep it) but did
     **not** fix pan/zoom. **Before adding any new attribute to a class that
     subclasses a `ctk.CTk*` widget, grep the installed `customtkinter`
     package for that exact `self._name` first** — this class of bug is
     silent (no import error, no immediate crash) and only surfaces as
     garbled behavior once the widget redraws.
  2. **Prefer a plain Tk widget over `ctk.CTkFrame` as the direct host of a
     raw Tk widget that needs reliable mouse-drag events** (e.g.
     matplotlib's `NavigationToolbar2Tk` pan/zoom). Every `CTk*` widget's
     internal `CTkCanvas` (rule 1) is `place()`d to cover its **entire**
     rectangle as a sibling of whatever you `pack()`/`grid()` inside it, and
     a matrix of throwaway probe scripts showed a bare `FigureCanvasTkAgg`
     packed *directly* into a `CTkFrame` breaks the toolbar's Zoom/Pan (no
     error at all — silent). `PlotCanvas` was changed from `ctk.CTkFrame` to
     `tk.Frame` for this reason (`sync_theme()` manually matches its
     background since it no longer themes itself). **This alone did not
     fix pan/zoom in the full app** (see below) — keep the change anyway,
     since it's still a real, confirmed-safer pattern in isolation, just not
     sufficient on its own.
  3. **Build figures via `Figure()` (or `Figure.subplots()`), never
     `pyplot.subplots()`/`pyplot.figure()`, for any figure that will be
     re-parented onto your own `FigureCanvasTkAgg`.** `pyplot.subplots()`
     creates the figure through matplotlib's global, stateful figure-manager
     registry (`Gcf`); reassigning that figure's `.canvas` to your own
     embedded canvas (as `PlotCanvas.set_figure()` does) leaves the
     original pyplot-side manager registered and orphaned. This is
     matplotlib's own documented embedding guidance (pyplot is for
     interactive/scripted use, `Figure()` for embedding), and it was a real
     bug here too: `plots.build_base_reactions_figure` and
     `beam_viewer.build_frame_figure`/`build_batch_frame_figure` (both feed
     the embedded preview panels) used `plt.subplots(...)`, switched to
     `Figure(...)` + `fig.add_subplot(...)`/`fig.subplots(...)`. **This also
     did not fix pan/zoom in the full app** — keep the change anyway (it's
     the documented-correct pattern and avoids leaking figure managers on
     every Refresh/load-change), just don't expect it alone to close the
     open issue.
  A once-suspected, **ruled-out** cause along the way: customtkinter's
  periodic per-monitor DPI-awareness poll (`ScalingTracker`, ~every 100ms,
  can briefly flip the window's alpha and force a redraw on a detected DPI
  change). `EtabsExtractorApp.__init__` calls
  `ctk.deactivate_automatic_dpi_awareness()` before `super().__init__()`
  regardless, since it's a reasonable defensive no-cost measure against a
  real (if here innocent) mechanism — but it did **not**, by itself, fix
  pan/zoom in testing either.
- `BasePreviewPanel` — replaces `PlotPreviewWindow`. Same
  `settings_provider`/`figure_builder`/`log` callback contract and the same
  `set_result()` auto-render-first-load behavior, just embedded in the
  Preview tab instead of a separate window (so there is no `is_alive()` /
  `closed` callback / manual "Plot preview" opener button anymore — it is
  always there).
- `FramePreviewPanel` — replaces `FramePreviewWindow`, same
  Load/Section/Step/Force/Length controls, highest-force auto-selection, and
  "Batch plot all (overlay)", also embedded.
- **One shared `load_beam_viewer()` loader** replaces the four separate
  `sys.path.insert` copies that used to live in `app.py` (x2) and
  `preview.py` (x2, one of which pointed at the **wrong** directory — see
  below). It resolves the repo root from `widgets/preview.py`'s own path
  (three `..` up: `widgets -> gui -> etabs_extractor -> repo root`) and is
  reused by both the panel's own `_get_highest_frame`/`_populate_lengths`
  and by `app.py`'s `_build_frame_preview_figure`/`_build_batch_frame_preview_figure`.

  **Bug fixed in passing:** the old `preview.py` computed the repo root with
  only two `..` (copying `app.py`'s calculation verbatim), but `preview.py`
  lives one directory deeper (`gui/widgets/` vs `gui/`), so it actually
  resolved to `etabs_extractor/` (the package dir) instead of the repo root
  containing `beam_viewer.py`. It only worked by accident because
  `run_gui.sh` `cd`s into the repo root first, which was already on
  `sys.path` via the invoking script's own directory. `load_beam_viewer()`
  now computes the correct three-level path.

**`_collect_settings()`** was restored from HEAD and extended: it always
reads model/output/tag/mode/loads/attach/run_analysis/appearance, then reads
the frame-only fields (sections) or the base-only fields (elevation,
only_loaded, csv_path, plot_after_extract) depending on `extract_mode`, and
finally lets `PlotSettingsFrame.to_settings()` fill the plot-appearance
fields — same contract as before, just re-implemented since the broken port
had deleted it outright.

**Background jobs**: `_start_job(fn, *args, **kwargs)` wraps
`BackgroundRunner` and starts one `after(80, self._poll)` loop; `_poll()`
drains `("result"|"error"|"done", payload)` from the runner's queue exactly
per `runner.py`'s documented protocol (see "Architecture" above), disables
the sidebar's action buttons and animates the progress bar via
`_set_busy(True/False)` for the duration, and dispatches the result to
whichever callback (`_on_check_done` / `_on_extract_done` / `_on_csv_done`)
was registered via `self._pending_cb` before the job started. `on_check_model`,
`on_extract`, and `on_load_preview` are the three entry points; all three
run through `_start_job`, so none of them block the main thread.
`EtabsExtractorApp.destroy()` is overridden to `after_cancel` the pending
poll before tearing down, so a job in flight when the window closes doesn't
leave a dangling `after()` callback.

**Dependency**: `customtkinter>=5.2.0` (added to `pyproject.toml` and
`requirements.txt` by the earlier, broken port; kept as-is since the
dependency itself was the right call, only its usage was broken). See
"Environment summary" below for install status on each interpreter.

### Completed: model-aware units + elevation inventory + output-folder Browse fix

The package used to **hardcode** its unit assumptions: frame forces were
always read as N/N·mm, and base reactions were always divided by 1000/1e6 on
the assumption the model itself is N/mm. On the live KM13B model, which is
actually configured in **kN, m** (`SapModel.GetPresentUnits_2()` → `[4, 6, 2,
0]`), this silently produced wrong output — coordinates divided by 1000 as if
they were millimetres, forces divided by 1000 as if they were newtons. This
was found and fixed by reading the model's own present units live instead of
assuming them, plus two related asks: a settings control for the output
unit system, and a way to browse for the output folder (the Browse button
was laid out past the sidebar's right edge and never actually drawn).

**New pure module `units.py`** — no COM, no pandas:

- `UnitSystem(force: str, length: str)` (frozen dataclass) with a derived
  `.moment` property (`f"{force}·{length}"`, e.g. `"kN·m"`).
- `FORCE_TO_N` / `LENGTH_TO_M`: conversion-factor tables to a common base
  (newtons / metres) for `N, kN, kgf, tonf, lb, kip` and
  `mm, cm, m, in, ft, micron`.
- `ETABS_FORCE_ENUM` / `ETABS_LENGTH_ENUM` / `ETABS_EUNITS`: the CSI OAPI's
  `eForce_*` / `eLength_*` / `eUnits_*` enum **values** (fixed by CSI,
  hardcoded here as documented API constants — not generated dynamically).
- `resolve_target(source, force="model", length="model") -> UnitSystem`:
  `"model"` (or empty) on a dimension means "keep the source's own unit for
  that dimension" (no conversion); any other value must be a known key.
- `factors(src, dst) -> (force_factor, moment_factor, length_factor)`:
  multipliers such that `value_dst = value_src * factor`.
- `LEGACY_BASE = UnitSystem("kN", "mm")` / `LEGACY_FRAME = UnitSystem("N",
  "mm")`: fallback source assumptions for a session with no unit API (an
  older/incompatible ETABS, or a test fake missing `get_present_units`) and
  for a legacy CSV plotted with no `force_unit`/`length_unit` columns.
- `FORCE_CHOICES` / `LENGTH_CHOICES`: the CLI/GUI dropdown choice tuples
  (`"model"` first).

**COM reads (`connection.py`, `EtabsSession`, all lazy-`comtypes`,
null-safe)**:

- `get_present_units() -> UnitSystem` — tries `GetPresentUnits_2()` (the
  modern per-dimension API: `[forceEnum, lengthEnum, tempEnum, retcode]`)
  first, falls back to the legacy combined `GetPresentUnits()` (a single
  `eUnits_*` enum) if that fails. **Read-only** — never calls
  `SetPresentUnits`, never mutates the model.
- `get_story_elevations() -> {"base": float|None, "stories": [(name, elev),
  ...]}` — `Story.GetStories_2()`. Real API shape confirmed live:
  `[base_elev, n_stories, names, elevations, heights, ...]`.
- `get_all_point_coords() -> {point_name: (x, y, z)}` — one COM call via
  `PointObj.GetAllPoints(0, [], [], [], [], "Global")`; falls back to
  per-point `get_point_coords` + `get_point_names` if unavailable.

**Unit-aware extraction (`results.py`)**:

- `_UnitCtx` (frozen dataclass: `force_factor`, `moment_factor`,
  `length_factor`, `src`, `dst`) is resolved **once per extraction run**
  (`_resolve_unit_ctx()`, right after connecting, before load selection) via
  `_source_units(session)` (calls `session.get_present_units()`, falls back
  to `LEGACY_FRAME` on any failure — old test fakes / older ETABS APIs
  degrade gracefully) and `resolve_target()` + `factors()`.
- **`ExtractKind.read`'s signature grew a trailing `uctx: _UnitCtx` arg**:
  `(session, name, combos, cases, uctx) -> list[record]` (was `(session,
  name, combos, cases)`). `_extract()` calls
  `kind.read(session, name, combos_use, cases_use, uctx)`. If you add a new
  `_read_<type>_forces()`, thread `uctx` through the same way (see
  `_read_frame_forces` / `_read_point_reactions`) — this is now part of the
  extending pattern in "Extending the framework" below.
  `_make_frame_reader()` / `_make_point_reader()`'s inner closures also
  gained the `uctx` parameter.
  - `_scale_opt(value, factor)` — null-safe optional scaling helper
    (mirrors `_f_optional`).
- **`BASE_FORCE_SCALE`/`BASE_MOMENT_SCALE` are gone.** Base reactions:
  `F1-F3 *= force_factor`, `M1-M3 *= moment_factor`, `x/y/z *= length_factor`.
  Frame forces: `P/V2/V3 *= force_factor`, `T/M2/M3 *= moment_factor`,
  `station`/`obj_sta`/`elm_sta`/`length_mm` `*= length_factor`.
  `extract_forces()` / `extract_base_reactions()` gained `force_unit="model"`
  / `length_unit="model"` kwargs.
- **`--elevation` is now interpreted in the OUTPUT length unit**, not the
  model's own: `_make_point_reader()` converts the requested elevation into
  model units (`elevation / uctx.length_factor`) before comparing against
  the raw (unscaled) COM `z`, and the match tolerance is ~1mm expressed in
  the **model's own** length unit (`0.001 / LENGTH_TO_M[uctx.src.length]`) —
  not a fixed `tol=1.0`, which was silently wrong (1 **metre**) for the
  live kN/m KM13B model.
- **`list_elevations(session) -> list[dict]`** (new, pure-ish orchestration
  function): reads every point's `z` (`get_all_point_coords`) and the story
  table (`get_story_elevations`, best-effort), groups z-values within the
  same model-unit tolerance above into one entry each, and labels each group
  `"Base"` (matches the story table's base elevation), a story name (matches
  one of its stories), or `""` (no match). Returns `{"z", "label",
  "n_points"}` dicts sorted by `z`, **in the model's own length unit** —
  callers (CLI, GUI) convert for display. **This tolerance bug was caught
  and fixed via a live test against KM13B**: with the naive `tol=1.0`, the
  model's `+1.90`/`+2.30` stories (0.4m apart) merged into one wrong,
  mislabeled elevation; the model-unit-aware tolerance separates all four
  real elevations correctly (`-18.55 Base`, `-2.55`, `+1.90`, `+2.30`).
- `list_available()` (used by `--list-only`) gained best-effort `"units"`
  (`{"force", "length"}`) and `"elevations"` (via `list_elevations`) keys.

**Unit-aware plotting (`plots.py`)**: `_resolve_units(units, df)` (was
`_resolve_units(units)` — every internal call site now passes `df`) reads
the **source** unit system from `df`'s own `force_unit`/`length_unit`
columns (`_source_unit_system(df)`, falling back to `LEGACY_BASE` for a
legacy CSV with no such columns) and resolves the **target** from `units`:
`"model"`/`"data"` (display the source unconverted), a named preset from
`UNITS` (now `{"kN-m", "kN-mm", "N-mm", "tonf-m", "kgf-m"}` — pre-computed
scale-factor dicts are gone; `UNITS` now holds just `{force, length}` target
pairs), or any other `"<force>-<length>"` string. `DEFAULT_UNITS` changed
from `"model"` to `"data"` (same behavior under the new naming — display
unconverted). `_scale()` / `_format_label()` / `_build_title()` /
`_pad_axis_limits()` etc. are unchanged (they still just consume the
resolved `units_def` dict's `force_scale`/`moment_scale`/`length_scale`).

**`beam_viewer.py`** (self-contained script, not part of the package) gained
the same source-unit-detection pattern: `_data_units(df)` (mirrors
`plots._source_unit_system`, fallback `LEGACY_FRAME`), `_length_scale(src)`
and `_length_tol(df)` replace the hardcoded `/1000.0` and `tol=1.0` /
`round(l)` (mm-assuming) length handling in `get_lengths_for_section` /
`get_frames_for_length` / `find_highest_force_frame` / `plot_beam_diagrams`
/ `build_batch_frame_figure`; `_scale_force(val, col, src)` gained the `src`
parameter (default `LEGACY_FRAME`, so old call sites without it still work).
Display stays fixed at kN/kN·m/m regardless of the CSV's actual units — only
the *source* assumption changed from hardcoded to data-derived.
`gui/widgets/preview.py`'s `_populate_lengths()` (the frame preview's length
dropdown) uses the same `bv._data_units()` / `bv._length_scale()` instead of
a bare `/1000`.

**Deliberate simplification vs. a full rename**: `FrameForceRecord.length_mm`
/ the CSV column `length_mm` **keeps its name** even though its value is now
in the *output* length unit (not always mm) — renaming it (and every
`beam_viewer.py` / `preview.py` reference) was judged not worth the added
blast radius for a niche filter/display field; the new explicit
`length_unit` column on every row removes any ambiguity about what unit it's
actually in.

**New `force_unit` / `length_unit` trailing columns** on every frame-force
and base-reaction record/DataFrame/CSV (last two columns in `COLUMNS` /
`BASE_COLUMNS`), e.g. `"kN"` / `"m"`; moments are implicitly
`force_unit·length_unit`. `summarize_envelope()` / `summarize_base_envelope()`
/ `summarize_base_envelope_minmax()` carry the two columns through as
pass-through metadata (the group's first value) — `benv_min`/`benv_max`'s
column list grew `["force_unit", "length_unit"]` at the end.

**CLI (`cli.py`)**: `--force-unit` / `--length-unit` (see "CLI modes"
above), module-level `from . import units as _units` (pure, safe to import
eagerly — used for the argparse `choices=`). `--units` (plotting) dropped
its fixed `choices=["model", "kN-m"]` (plots.py now accepts arbitrary
`"<force>-<length>"` strings, validated downstream with a clear
`ValueError`). `--list-only` additionally prints `Units: <force>, <length>`
and one `z=... (label) -> N point(s)` line per `list_elevations()` entry.

**GUI (`app.py` / `state.py` / `service.py`)**:

- **New "Units" sidebar card**: Force / Length `CTkOptionMenu`s
  (`FORCE_UNIT_CHOICES` / `LENGTH_UNIT_CHOICES`, default `"model"` on both)
  plus a hint label (`_update_units_hint()`) showing `Model: <force>,
  <length> → Output: ...`. Changing either menu (`_on_units_changed()`)
  re-renders the hint **and** re-labels the elevation combobox below (see
  next bullet) in the new length unit.
- **Elevation is now an editable `CTkComboBox`** (`elevation_var` /
  `elevation_combo`, replacing the old free-text `LabeledEntry`
  `elevation_field`). "Check active model" (`_on_check_done`) stores the raw
  model-unit elevation inventory (`self._elevations`,
  `service.inspect_active_model()`'s new `"elevations"` key) and model units
  (`self._model_units`), then `_refresh_elevation_choices()` calls
  `service.build_elevation_labels(elevations, model_length, length_unit)` to
  populate the combobox with entries like `-18.55  (Base, 42 pts)`, **in the
  currently selected output length unit** — re-called on every units change.
  `state.parse_elevation()` was extended with a regex (`^[+-]?\d+(?:\.\d+)?`)
  that takes the leading numeric token and ignores the trailing `(...)`
  label, so both a combobox selection and a freely-typed value parse.
- **`service.build_elevation_labels(elevations, model_length, length_unit)`**
  (new, pure) does the model-unit → output-unit conversion for display; unit
  tests in `tests/test_plot_settings.py`.
- **`service.inspect_active_model()`** gained `"units"` (`{"force",
  "length"}`, via `session.get_present_units()`) and `"elevations"` (via
  `results.list_elevations()`) keys, both best-effort (degrade to
  `{"force": "", "length": ""}` / `[]` rather than failing the whole check).
- **`GuiSettings`** gained `force_unit: str = "model"`, `length_unit: str =
  "model"` (threaded through `service.build_mode_kwargs()` for both base and
  frame mode), and `plot_output_dir: str = ""` (see next bullet).
  `units: str = "model"` (plot display) changed default to `"data"`.
  `UNITS_CHOICES` (plot display dropdown) is now `("data", "kN-m", "kN-mm",
  "N-mm", "tonf-m", "kgf-m")`.
- **CSV tab gained a "Plot output" `DirectoryField`** (`plot_output_field`,
  blank = save next to the CSV, matching `plot_base_reactions_from_csv`'s
  own default) — `load_from_csv()` (`service.py`) passes it as the plotting
  entry point's `output_dir` positional arg.

**Output-folder / model-file Browse button fix (`gui/widgets/fields.py`)**:
`DirectoryField` / `FileField` packed `label(96) + entry(220) + Browse(72)`
in **one horizontal row**, but the sidebar (`CTkScrollableFrame`) is only
`340px` wide — the Browse button was laid out at `x=328` in a `328px`-wide
frame and **never actually drawn or clickable** (`winfo_ismapped() == 0`,
confirmed under WSLg before the fix). Both widgets were changed to a
**stacked `grid` layout**: the label on its own row, then the entry
(`sticky="ew"`, column weight 1) and Browse button on the row below — this
keeps the Browse button inside the frame at any sidebar width. `FileField`'s
Browse also now opens at the current value's parent directory
(`initialdir`); `DirectoryField`'s opens at the current value.
`tests/test_gui_smoke.py`'s `test_browse_buttons_mapped` guards this via
geometry bounds (`btn.winfo_x() + btn.winfo_width() <= field.winfo_width()`)
rather than `winfo_ismapped()`, since the smoke test's window is withdrawn
(unmaps everything) — scoped to the sidebar's `model_field`/`output_field`
(fixed-width `CTkScrollableFrame`, gets real geometry even withdrawn); a
`CTkTabview` tab's content (e.g. the CSV tab's new `plot_output_field`) only
gets real stretch geometry once selected on a *mapped* window, which a
withdrawn smoke-test window never is, so the same geometry check there
would be meaningless — the shared `DirectoryField` class is already
exercised by the two sidebar instances.

**Verified live** against the running KM13B model (kN/m; see "Environment
summary"), read-only (`EtabsSession.connect(attach=True)`, no `model_path` —
never calls `File.OpenFile`, so the user's open model is never reopened):
`get_present_units()` → `kN, m` (matches the direct COM probe); `list_
elevations()` → all four real elevations, correctly separated and labelled
(`-18.55 Base/60pts`, `-2.55/88pts`, `1.9 "+ 1.90"/19pts`, `2.3 "+
2.30"/27pts`); `extract_base_reactions(force_unit="model",
length_unit="model")` → correct kN/m values (coordinates like `x=2.5, y=0.3`
in metres, `F3` in sensible kN magnitudes) where the old hardcoded ÷1000
path would have produced sub-millimetre coordinates and 1000×-too-small
forces; `service.inspect_active_model()` → the same units/elevations plus
126 combos / 17 cases / 10 sections / 76 frames.

### Known open issue: preview pan/zoom does not work (unresolved)

The embedded preview's matplotlib toolbar Zoom/Pan tools **do not work** in
the real running app (confirmed live, on the Windows Python, by the user,
repeatedly) — the button toggles fine, click-drag on the plot does nothing,
no error/log output at all. Three real, confirmed bugs were found and fixed
while investigating (see rules 1–3 above), and each is worth keeping on its
own merits, but **none of them fixed the symptom** — it was re-tested live
after each fix and still failed. Root cause is **not** found.

**Diagnostic history (throwaway probe scripts, all since deleted — rebuild
similarly if resuming this)**, run on the Windows Python via
`run_gui.sh`-style invocation (`cd` into the repo, then the discovered
`WIN_PY` interpreter), each testing "click the toolbar's zoom icon, then
drag a rectangle on the plot":

| # | Structure | Result |
|---|---|---|
| 1 | Bare `tk.Tk()` root, `FigureCanvasTkAgg`+toolbar direct children, simple `ax.plot()` | **Works** |
| 3 | `ctk.CTk()` root, `PlotCanvas` (then still `ctk.CTkFrame`) gridded directly, no `CTkTabview` | Fails (exception spam, before the rule-1 fix) |
| 4 | `ctk.CTk()` root, bare `FigureCanvasTkAgg`+toolbar as **direct children of the root** (no `CTkFrame` anywhere), `deactivate_automatic_dpi_awareness()` | **Works** — rules out `ctk.CTk()` root itself |
| 5 | `ctk.CTk()` root → `ctk.CTkFrame` → **`tk.Frame`** (mimicking the fixed `PlotCanvas`) → canvas+toolbar, simple `ax.plot()` | **Works** — the tk.Frame-hosting fix looked sufficient here |
| 7 | Same as #5 but wrapped in a `CTkTabview` tab | **Works** — rules out `CTkTabview` |
| 8 | Same as #7 plus a "top" sibling row (`CTkOptionMenu` + `CTkButton`s), matching `BasePreviewPanel`'s layout | **Works** — rules out the extra toolbar row |
| 6 / 9 | The **real** `BasePreviewPanel` class (imported, unmodified) inside a `CTkTabview`, fed a real `build_base_reactions_figure(...)` figure via `set_result()`, first with 2 synthetic points sharing one y-value (degenerate axes — ruled out separately: the user correctly suspected this, but a 4-point non-degenerate re-test still failed), then after the rule-3 (`Figure()` vs `plt.subplots()`) fix | **Fails**, every time |

So every *minimal, hand-built* reproduction of `PlotCanvas`'s exact
structure works, but the **real, unmodified `BasePreviewPanel` class** run
the same way still fails — meaning there is some remaining difference
between the throwaway probes and the real class/figure that was never
isolated. Candidates **not yet tested**, for whoever resumes this:

- Bisect `BasePreviewPanel.__init__` itself line-by-line against probe #8's
  known-working structure (probe #8 hand-built the layout; it never
  instantiated the real class) — e.g. try the real class's
  `ctk.CTkOptionMenu`'s `command=lambda _v: self._render_current()`
  callback (which calls back into instance state during construction) vs.
  probe #8's inert dropdown with no real callback.
- Try the **real running app itself** (not a probe) with `_render_current`
  temporarily short-circuited to render a plain `ax.plot()` figure instead of
  `build_base_reactions_figure`'s output, to re-isolate figure content vs.
  the surrounding widget tree in the actual app rather than a rebuild.
- Check whether `NavigationToolbar2Tk`'s internal event connections
  (`mpl_connect`) are being made against the right canvas at all when the
  figure is swapped post-construction (`_ensure_canvas()` builds the toolbar
  against an initial **empty** `Figure()`, then `set_figure()` swaps in the
  real one later) — this pattern was never isolated as its own variable
  across the probe matrix (every working probe fed its real figure at
  construction time, not via a later swap onto a placeholder-first canvas).
  This is the most likely remaining candidate.
- Consider matplotlib/Tk version-specific bugs on the exact Windows Python
  in use (`pythoncore-3.14-64`, matplotlib 3.11.1, customtkinter 6.0.0) —
  not cross-checked against another Python/matplotlib version.

Does not block the user's workflow (extraction/CSV export/static image
saving all work); parked at the user's request. Do not mark this fixed
without a live re-test confirming actual drag-zoom/pan on the real app.

### Known pitfalls / bugs to watch (base reactions)

- **`JointReact` returns 11 output arrays, not 12.** Unlike `FrameForce`
  (12 arrays + retcode), `JointReact` has `Obj, Elm, LoadCase, StepType,
  StepNum, F1, F2, F3, M1, M2, M3` = 11. `joint_react()` returns
  `NumberResults` + those 11 segments = a **12-tuple** (drop the retcode).
  Getting this wrong surfaces at runtime as
  `too many values to unpack (expected 12, got 13)` — a real bug the first
  live run hit, invisible to the dry run (whose fake tuple is hand-shaped).
  If you extend it, keep the return arity in lock-step with the fake in
  `tests/test_dry_run.py`.
- **All-restrained-joints, any elevation:** `extract_base_reactions` reports
  every point object (restraints, springs, grounded links) at any `z`;
  interior elevated joints legitimately return zeros. Filter to a base level
  downstream for dot-plotting.
- **Unresolvable point coordinates** coerce to `None` (NaN in the DataFrame)
  rather than raising, so no point is dropped and downstream can filter on
  `known z`.
- **Elevation-matching tolerance must be in the model's own length unit, not
  a fixed constant.** `_z_match`/`list_elevations`/`_make_point_reader`'s
  `tol` is `0.001 / LENGTH_TO_M[model_length]` (≈1mm in whatever unit the
  model is actually in). A fixed `tol=1.0` is silently wrong for any model
  not natively in mm — on the live kN/m KM13B model it merged two real
  stories 0.4m apart into one mislabeled elevation (caught by a live test;
  see "Completed: model-aware units").

---

## Environment summary (for orientation)

- WSL interpreter: `.venv/bin/python` (3.12, NO COM) — has `numpy`,
  `pandas 3.0.5`, `matplotlib 3.11.1` (needed for the headless `--plot` /
  `--plot-csv` path, which runs in WSL without ETABS), and
  `customtkinter 6.0.0` (needed to import/exercise `gui.app` and the
  `widgets/` modules — verified importable headlessly and used by
  `tests/test_gui_smoke.py` under WSLg's display).
- Windows interpreter (COM-capable, auto-discovered by `run_etabs.sh`):
  `/mnt/c/Users/user/AppData/Local/Python/...` — has `comtypes 1.4.16`,
  `pandas 3.0.5`, and (now) `matplotlib 3.11.1` (installed 2025-08; needed
  for the GUI's live preview canvas and for `--plot` right after a Windows
  extraction — an earlier failure was exactly ``No module named
  'matplotlib'`` on the Windows interpreter).
- Reference model live in ETABS (example): `D:\PROJECTS\...\Daan Mogot\13\ETABS\3.0\KM 13 3.0.EDB`
  (202 frames, **497 points**, 81 combos, 18 cases). Verified live: `--extract base`
  combos `ASD 1`+`LRFD 1` → 994 reaction rows (populated x/y/z; real
  sub-grade reactions at `z=-16000`, zeros at elevated unrestrained joints).
    Also verified live: `--extract base --combos "ASD Max" "LRFD Max"
  --elevation -16000 --only-loaded` → 400 rows (100 loaded points × 2 combos ×
  2 envelope steps Max/Min). **Base reactions are exported in kN/kN·m**
  (now written directly to the CSVs), then `--plot-csv ... --units kN-m`
  additionally renders `base_ASD_Max_plan.png` / `base_LRFD_Max_plan.png`
  with mm→m (÷1000) coordinate display — forces/moments already carry
  converted kN/kN·m values from extraction.

- **Second reference model, live in ETABS (used to verify model-aware
  units):** `D:\PROJECTS\Structural Engineering\Daan Mogot Revisi\KM13B\ETABS\
  1.0\KM 13B (Rev) 1.0.EDB` — configured in **kN, m** (confirmed via
  `GetPresentUnits_2()` → `[4, 6, 2, 0]`), 4 distinct elevations (`-18.55`
  Base/60pts, `-2.55`/88pts, `1.9` "+ 1.90"/19pts, `2.3` "+ 2.30"/27pts), 126
  combos, 17 cases, 10 sections, 76 frames. This is the model that exposed
  the hardcoded-N/mm bug (see "Completed: model-aware units") — the *first*
  reference model above happens to be N/mm, so the old hardcoded assumption
  coincidentally worked there and only failed here.

  For the GUI launcher, the Windows Python additionally needs `matplotlib`
  installed for the live in-GUI preview (done: installed on the Windows
  interpreter).  If the preview ever shows `No module named 'matplotlib'`,
  run ``<windows-python> -m pip install matplotlib`` (or relaunch via
  `run_gui.sh`, whose Windows Python should now have it).

  **`customtkinter` is NOT yet installed on the Windows Python** (verified:
  `pip show customtkinter` → "Package(s) not found" there, as of the
  customtkinter GUI overhaul). `run_gui()` (`gui/__init__.py`) catches this
  and prints a `pip install customtkinter` hint instead of crashing, but a
  live `./run_gui.sh` run needs it installed first:
  ``<windows-python> -m pip install customtkinter``.