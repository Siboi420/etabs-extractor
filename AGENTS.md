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
  models.py       # FrameForceRecord + JointReactionRecord, column order, *_dataframe()  [pure]
  connection.py   # EtabsSession: COM attach/launch, open model, read APIs     [COM here]
  results.py      # orchestration: extract_forces() (frames) + extract_base_reactions()  [pure-ish]
  io.py           # CSV writers (per-load, *_all, envelope summary)              [pure]
  plots.py        # matplotlib plan-view plotting of base reactions (lazy mpl)   [pure]
  cli.py          # argparse CLI entry point (--extract frame|base, --plot, --plot-csv)
  __main__.py     # enables `python -m etabs_extractor`
  gui/            # tkinter GUI (base extraction + plotting) — lazy tk/mpl/COM
    __init__.py   # run_gui() entry
    __main__.py   # enables `python -m etabs_extractor.gui`
    state.py      # GuiSettings dataclass + parse helpers          [pure]
    service.py    # settings -> library call mapping + do_extract/load_from_csv/check_active_model  [pure-ish]
    runner.py     # background thread + queue wrapper              [pure-ish]
    widgets/
      fields.py, plot_settings.py, preview.py   # tk widgets, lazy mpl
    app.py        # EtabsExtractorApp(tk.Tk) view layer
  requirements.txt
  README.md
  tests/test_dry_run.py       # FakeSapModel stub, no COM
  tests/test_plot_settings.py # GUI pure-layer + figure-builder tests, no display/COM
run_etabs.sh      # WSL->Windows launcher (runs pkg under Windows Python)
run_gui.sh        # WSL->Windows launcher for the GUI
pyproject.toml    # setuptools; package is `etabs_extractor*`; [project.scripts] etabs-extractor-gui
pyrightconfig.json
.venv/            # WSL venv for editing/testing only (NO COM)
```

### Layering invariants

- **`models.py`, `io.py`, `config.py` are pure** — no COM, no Windows, no
  `comtypes`. They must stay importable on any platform (WSL included).
- **`plots.py` is pure too**, and imports **matplotlib lazily** (inside
  functions) exactly like pandas is imported lazily in `models.py`, so the
  module imports safely even where matplotlib is absent. Do not hoist a
  top-level `import matplotlib`.
- **`connection.py` is the ONLY place that touches COM.** Every `comtypes`
  import there is **lazy** (inside functions), so importing other modules
  never forces COM. `EtabsSession` exposes a small, **duck-typed** surface
  (`frame_force`, `joint_react`, `get_frame_names`, `get_combo_names`,
  `get_case_names`, `get_point_names`, `get_point_coords`,
  `get_section_for_frame`, `setup_select_combos/cases`, `open_model`,
  `run_analysis`) so tests substitute a fake.
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
        -> _resolve_names()          (combos+/-cases)
        -> setup_select_*()          (enable outputs in ETABS)
        -> get_frame_names()
        -> _read_frame_forces() per frame  (session.frame_force)
        -> FrameForceRecord[]        (one per station)
        -> models.to_dataframe()  -> consolidated + per-load DataFrames
        -> io.write_csv / write_all_forces_csv / write_envelope_csv

# Base-reaction extraction (--extract base)
CLI/API -> results.extract_base_reactions()
        -> _connect_session() _resolve_names() setup_select_*()  (same as frames)
        -> session.get_point_names()            (all point objects)
        -> per point: get_point_coords() -> (x,y,z); session.joint_react()
        -> JointReactionRecord[]        (one per load per point)
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
--list-only                  inventory (frames, points, combos, cases)
--frames <names>             frame-only name filter (ignored for base)
--points <names>             base-only point name filter (applied first)
--elevation <z>              base-only: only points at this z elevation (e.g. -16000)
--only-loaded                base-only: drop points with all-zero reactions (keeps loaded)
--combos/--cases/--all       same load-selection mechanism for BOTH modes
--plot                       base-only: render plan-view (x-y) figures of the base reactions
                             (one PNG per load) into the output dir after extraction
--plot-csv <path>            standalone: read a base CSV and plot it (no COM/model; WSL-ok)
--plot-format <fmt>          image format for --plot/--plot-csv (default png; e.g. pdf, svg)
--units <unit>               coordinate display unit: model (kN, kN·m, mm) or kN-m (kN, kN·m, m;
                             forces/moments already exported kN/kN·m, only coords mm→m differ)
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

10. **The GUI is a thin view with lazy deps.** The `gui/` package adds no
    COM/matplotlib/tk at *module* import time — `tkinter` is imported inside
    `app.py` methods (the module imports fine with no display), matplotlib is
    imported lazily in `preview.py` / `plots.py`, and COM is only reached via
    the existing `connection.py`/`results.py`/`plots.py` layers through
    `service.py`. All real work stays in those layers; the GUI is pure view +
    orchestration. `state.py` and `service.py` are importable headlessly and
    unit-tested in `tests/test_plot_settings.py`. **Keep the background
    runner**: extraction runs on a `threading.Thread` and posts `(kind,
    payload)` queue messages so the Tk main thread stays responsive; COM is
    initialised in the worker thread (comtypes `CoInitialize()` before the job,
    `CoUninitialize()` after — required on Windows for COM calls off the main
    thread; a no-op on non-Windows). Don't hoist top-level `import
    matplotlib` or `import tkinter` into the package modules.

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
  tagged/untagged filenames, split min/max envelopes, point-number labels)
- **GUI pure-layer + figure-builder tests:**
  `MPLBACKEND=Agg python etabs_extractor/tests/test_plot_settings.py` → expect `PASSED`
  (headless, no display, no comtypes; covers `build_base_reactions_figure` fixed/dynamic
  size + no-points->None, `plot_base_reactions` dpi/figsize/fontsize threading, and the
  `gui.service` settings->args mapping + `gui.state` parsing).
- **Plot smoke (no COM, WSL):** `python -m etabs_extractor --plot-csv <dir>/all_base_reactions.csv`
  → expect a `base_<load>_plan.png` next to the CSV for each load. With
  `--tag KM13` the files become `base_<load>_plan_KM13.png`.
- **pi-lens:** run diagnostics on edited files; the two known rules to respect
  are `unchecked-throwing-call-python` (int/float/open) and `python-empty-except`
  (no bare `pass`).
- **Live sanity (if ETABS is running + user asks):** `./run_etabs.sh --list-only --model <path>`
  → expect real frame/combo/case counts (and `Point objs`).
  `./run_etabs.sh --extract base --model <path> --combos "ASD 1" --output <dir>`
  → expect a populated `all_base_reactions.csv` and two `base_combo_*.csv`.

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
   beside `_read_frame_forces()` / `_read_point_reactions()`.
4. **I/O** → `io.py` has writers for both the frame (`write_csv`,
   `write_all_forces_csv`, `write_envelope_csv`) and base-reaction schemas
   (`write_base_csv`, `write_all_base_csv`, `write_base_envelope_csv`, plus the
   split `write_base_envelope_min_csv` / `write_base_envelope_max_csv`). The
   writers are concrete per schema (each takes its own `*_COLUMNS` + rows);
   add new writers beside them rather than duplicating frame logic by copy.

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
- **Base-reaction export units are kN / kN·m** (always-on, no opt-out):
  `_read_point_reactions()` (`results.py`) divides source **N** forces by
  `BASE_FORCE_SCALE = 1000.0` (→ kN) and source **N·mm** moments by
  `BASE_MOMENT_SCALE = 1e6` (→ kN·m) at record construction, so the
  record list, the returned DataFrame, and every base CSV all carry
  converted values. Coordinates `x`/`y`/`z` are **not** converted and stay
  in model length units (mm). The frame-force path is unaffected (still
  N / N·mm). This is the single source of truth for both DataFrame and CSV
  outputs.

  Note on ordering: `--only-loaded` runs **after** conversion, so
  `_is_null_reaction()` compares already-converted kN/kN·m values. That is
  still correct for genuinely-zero supports (0 in any unit remains 0), so
  the filter behavior is unchanged.

The `--elevation` filter compares each point's `z` against the requested
value with a small tolerance (`_z_match`, `tol=1.0` length units) before
reading reactions — so extracting one level (e.g. `-16000`) skips reading
every other joint entirely. It applies after the `--points` name filter.

`--only-loaded` post-filters the assembled records with `_is_null_reaction`
(all six components ≈ 0 → dropped), so the CSV holds only supports that
actually carry load — e.g. with envelope combos `ASD Max`/`LRFD Max` at
`z=-16000` this yields the 100 loaded points that match the reference
`KM13 Chamber 3.0.xlsx` 1-to-1.

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
- **`x_offset: float = 1.0` / `y_offset: float = 1.0`** — reserved whitespace
  margins (inches) around the plot area so edge point labels do not clip into
  the axes. Final figure size = base size + `2*x_offset` × `2*y_offset`;
  axes positioned via `fig.subplots_adjust(left=x/W, right=1-x/W, bottom=y/H,
  top=1-y/H)` (replaces the previous unconditional `fig.tight_layout()`). To
  reproduce the pre-change size pass `x_offset=0, y_offset=0`.
- Threaded through `plot_base_reactions`, `plot_base_reactions_from_csv`,
  and the new `build_base_reactions_figure`.

`build_base_reactions_figure(df, load_name, *, components, title, units,
label_fontsize, dynamic_size, figsize, x_offset, y_offset) -> Figure | None`
is a new **public** reusable figure builder: it draws one plan-view figure
(scatter + annotations + title/axes) **without saving**, and returns ``None``
when a load has no plottable points. `_plot_one` now calls it then
`savefig(..., dpi=dpi)` and closes. The GUI preview renders it into a
`PlotPreviewFrame` canvas inside a **separate pop-up window**
(`PlotPreviewWindow`, a `tk.Toplevel`) opened manually via the `Plot preview`
button — not embedded in the main window.

The offset layout changes in `build_base_reactions_figure`:

- figure size = base + `2*x_offset` × `2*y_offset`;
- `ax.set_aspect("equal", adjustable="datalim")` → `adjustable="box"` so
  equal-aspect letterboxes sit inside the reserved plot area rather than
  stretching data into the margins;
- annotations set `annotation_clip=False` and `clip_on=False` so labels render
  into the reserved margin; `_plot_one` keeps `bbox_inches="tight"` so saved
  images expand to fit the outermost label.

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
  when dynamic), **X/Y label offset (in)** fields (default 1.0 each), dpi
  (default 800), label font size (default 2.4), units
  (`model`/`kN-m`), format (`png`/`pdf`/`svg`). "Plot after extract".
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
  combos and cases together. `extract_forces` / `extract_base_reactions` now
  call it when both streams are requested (the old separate
  `setup_select_combos` then `setup_select_cases` calls each `DeselectAll...`
  the other, so they would clobber each other). `setup_select_combos` /
  `setup_select_cases` are kept for compatibility. Mirror it on `_FakeSession`
  in `tests/test_dry_run.py`, and make the fake `_records_for` return the
  **union** of selected combos + cases (matching the real COM contract).
- **Label offsets**: see the "Plot appearance" bullet in the GUI section above
  for the `x_offset` / `y_offset` params and the margin layout in
  `build_base_reactions_figure`.

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

---

## Environment summary (for orientation)

- WSL interpreter: `.venv/bin/python` (3.12, NO COM) — now has `numpy`,
  `pandas 3.0.5`, and `matplotlib 3.11.1` (needed for the headless `--plot` /
  `--plot-csv` path, which runs in WSL without ETABS).
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

  For the GUI launcher, the Windows Python additionally needs `matplotlib`
  installed for the live in-GUI preview (done: installed on the Windows
  interpreter).  If the preview ever shows `No module named 'matplotlib'`,
  run ``<windows-python> -m pip install matplotlib`` (or relaunch via
  `run_gui.sh`, whose Windows Python should now have it).
