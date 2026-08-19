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
  requirements.txt
  README.md
  tests/test_dry_run.py   # FakeSapModel stub, no COM
run_etabs.sh      # WSL->Windows launcher (runs pkg under Windows Python)
pyproject.toml    # setuptools; package is `etabs_extractor*`
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
--units <unit>               display unit system: model (N, N·mm, mm) or kN-m (kN, kN·m, m)
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

## Known issue: the WSL venv console-scripts are stale

The `.venv/` was moved after creation, so `.venv/bin/pip` and
`.venv/bin/pyright` have broken shebangs (they point at the old
`/home/siboi/Projects/Structural Works/.venv`). **Use `python -m pip` /
`python -m pyright`** instead. A full venv rebuild would fix them, but the
workaround works and avoids reinstalling deps.

---

## How to check your work

- **Compile:** `python -m py_compile etabs_extractor/*.py etabs_extractor/tests/*.py`
- **Type:** `python -m pyright etabs_extractor/`  (keep 0 errors)
- **Tests:** `MPLBACKEND=Agg python etabs_extractor/tests/test_dry_run.py` → expect `PASSED`
  (uses the non-interactive Agg backend; covers frame + base + plan plotting, plus
  tagged/untagged filenames, split min/max envelopes, point-number labels)
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

The `--elevation` filter compares each point's `z` against the requested
value with a small tolerance (`_z_match`, `tol=1.0` length units) before
reading reactions — so extracting one level (e.g. `-16000`) skips reading
every other joint entirely. It applies after the `--points` name filter.

`--only-loaded` post-filters the assembled records with `_is_null_reaction`
(all six components ≈ 0 → dropped), so the CSV holds only supports that
actually carry load — e.g. with envelope combos `ASD Max`/`LRFD Max` at
`z=-16000` this yields the 100 loaded points that match the reference
`KM13 Chamber 3.0.xlsx` 1-to-1.

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
  `DEFAULT_UNITS == "model"`): `kN-m` converts forces N→kN (÷1000), moments
  N·mm→kN·m (÷1e6), coordinates mm→m (÷1000); labels, axes, and the shared-`z`
  title all reflect the chosen unit. Add a new key to `UNITS` to extend.
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
  `pandas 3.0.5`. For live `--plot` (plot right after a Windows extraction)
  it also needs `matplotlib` installed.
- Reference model live in ETABS (example): `D:\PROJECTS\...\Daan Mogot\13\ETABS\3.0\KM 13 3.0.EDB`
  (202 frames, **497 points**, 81 combos, 18 cases). Verified live: `--extract base`
  combos `ASD 1`+`LRFD 1` → 994 reaction rows (populated x/y/z; real
  sub-grade reactions at `z=-16000`, zeros at elevated unrestrained joints).
  Also verified live: `--extract base --combos "ASD Max" "LRFD Max"
  --elevation -16000 --only-loaded` → 400 rows (100 loaded points × 2 combos ×
  2 envelope steps Max/Min), then `--plot-csv ... --units kN-m` renders
  `base_ASD_Max_plan.png` / `base_LRFD_Max_plan.png` with N→kN (÷1000),
  N·mm→kN·m (÷1e6), mm→m (÷1000) display.
