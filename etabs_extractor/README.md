# etabs_extractor

Extract results from an **ETABS 22** model via the CSI COM API and write
them to CSV (also returning pandas DataFrames):

- **frame-element internal forces** — axial `P`, shears `V2`/`V3`, torsion
  `T`, moments `M2`/`M3` for every frame object across the model's load
  combinations (and optionally load cases) — `--extract frame` (default).
- **per-joint (base) reactions** — reaction forces `F1`/`F2`/`F3` and moments
  `M1`/`M2`/`M3` plus each point's global coordinates/elevation —
  `--extract base`.

## Quick start (live ETABS run)

For the common case — extracting from a running ETABS from a WSL shell —
just use the `run_etabs.sh` launcher. It auto-discovers the Windows Python,
converts `/mnt/<drive>/...` paths, and runs the package against the live
session. **Prerequisite:** ETABS is running with your model open (or pass
`--launch`).

```bash
cd ~/Projects/Structural\ Works/etabs_extractor

# Inventory / connectivity check (no extraction):
./run_etabs.sh --list-only --model "/mnt/d/.../model.EDB"

# Extract everything (all combos + all load cases) to a directory:
./run_etabs.sh --model "/mnt/d/.../model.EDB" --all --output "/mnt/d/.../out"

# Base (joint) reactions for a couple of combos:
./run_etabs.sh --extract base --model "/mnt/d/.../model.EDB" \
    --combos "ASD 1" "LRFD 1" --output "/mnt/d/.../out"

# Base reactions restricted to one elevation level (e.g. z=-16000):
./run_etabs.sh --extract base --model "/mnt/d/.../model.EDB" \
    --combos "ASD 1" "LRFD 1" --elevation -16000 --output "/mnt/d/.../out"

# Envelope ('Max') base reactions, only supports that carry load, one level:
./run_etabs.sh --extract base --model "/mnt/d/.../model.EDB" \
    --combos "ASD Max" "LRFD Max" --elevation -16000 --only-loaded --output "/mnt/d/.../out"

# Also plot plan-view figures of the base reactions (one PNG per load):
./run_etabs.sh --extract base --model "/mnt/d/.../model.EDB" \
    --combos "ASD 1" "LRFD 1" --output "/mnt/d/.../out" --plot
```

See "Running from WSL against a live ETABS (`run_etabs.sh`)" below for
details and fallbacks.

## Interactive GUI (base reactions + plotting)

A **tkinter GUI** (`etabs_extractor/gui/`) provides a point-and-click way to
check the active ETABS model, choose an export destination and filename tag,
configure plot appearance (dynamic figure size, fixed width/height, DPI —
default 800 — and label font size), run **base-reaction extraction**, and
preview / save **plan-view plots**. It also plots from an existing base CSV
with no ETABS running. Scope is base extraction + plotting only.

Launch from WSL against Windows ETABS:

```bash
cd ~/Projects/Structural\ Works/etabs_extractor
./run_gui.sh
```

Or from a Windows Python directly (also installed as `etabs-extractor-gui`):

```bash
python -m etabs_extractor.gui
```

In the window:

- **Model row** — file entry + Browse (`*.EDB` / `*.et`) + **"Check active
  model"**, which attaches to the running ETABS, fills the path field via
  `SapModel.GetModelFilename` (a cSapModel method on the model object, not
  the File interface; no path needed), **and** populates the load dropdown
  with the active model's **combinations and load cases** (via
  `get_combo_names` / `get_case_names`).
- **Destination row** — directory entry + Browse (defaults to `ETABS_OUTPUT`).
- **Tag row** — a filename suffix applied to every output (sanitized).
- **Load selection** — a **searchable multi-select checklist** of the active
  model's **combos + load cases** (opened via the **Select** button / click);
  you can search-as-you-type and tick as many combos and cases as you want.
  An empty selection keeps the default (all model combos). Optional
  `elevation`, and checkboxes for `only_loaded`, `run_analysis`, and `attach`
  (vs launch).
  - The plot preview renders **one marker per distinct plan (x/y) point
    returned by the extraction**. Envelope combos (Max/Min) are collapsed to
    a single governing marker per point (largest absolute value), so they do
    **not** duplicate points. However, points at the base level with all-zero
    reactions (non-load-bearing joints) still get a marker unless
    **"Only loaded supports"** is checked. For a clean plan-view of just the
    real supports, set `elevation` (e.g. `-16000`) **and** check `only_loaded`.
- **Plot appearance** — `dynamic size` checkbox (figure follows data) with
  width/height fields disabled while dynamic; **X/Y label offsets (in)**
  (default 1.0 in each way — extra axis-limit padding so edge point labels
  render inside the axes box), dpi (default 800), label font
  size (default 2.4), units (`model`/`kN-m`), format (`png`/`pdf`/`svg`); plus
  a **"Plot after extract"** checkbox.
- **Actions** — a single **Extract** button in the bottom bar (next to
  `Quit`), plus the `Plot preview` opener above. There is **one** Extract
  button only.
- **Plot from existing CSV (no ETABS)** — pick a base CSV, "Load preview".
- **Plot preview (pop-up window, manual)** — a separate ``Plot preview`` button
  opens the preview in its own pop-up window (load dropdown + embedded
  matplotlib canvas + ``Preview`` / ``Refresh`` / ``Save preview image``
  buttons); it is shared by both extract and CSV results.  It is **not**
  auto-opened after Extract / Load-preview — only the ``Plot preview`` button
  opens it.  When a result is loaded the **first load renders automatically**
  with the current plot settings; the **Refresh** button re-captures the
  appearance settings from the main window (font size, units, offsets, …) and
  re-renders the selected load.

Extract / Load preview run in a **background thread** (COM is initialised in
the worker via comtypes `CoInitialize()`/`CoUninitialize()` — required on
Windows; a no-op elsewhere), so the UI stays responsive with a progress bar
and status line.

The live in-GUI preview canvas needs **matplotlib installed on the Windows
Python** that drives the GUI (the one `run_gui.sh` discovers). If it's
missing, the preview shows a message like `Preview needs matplotlib: ...
Install it on the Windows Python (pip install matplotlib).` — install it via
``<windows-python> -m pip install matplotlib``.

> **Note on "Check active model"**: it attaches to the *running* ETABS
> instance and reads whatever model is open there — it does **not** use the
> model you've typed in the field. If ETABS is closed, that button errors with
> a "running (or pass attach/launch)" message. To extract from a specific
> model, leave the path in the **Model** field (or Browse to it) and click
> **Extract** — ensure ETABS is running with the target model open.

## Plotting base reactions

Plan-view (x-y) scatter figures of the extracted base reactions, with each
support point annotated with its `Fz`, `M2`, `M3` values (horizontal shears
`Fx`/`Fy` omitted by default), can be
rendered **two ways** — both need only matplotlib (no COM, no ETABS):

```bash
# 1) Right after a base extraction, alongside the CSVs:
./run_etabs.sh --extract base --model "/mnt/d/.../model.EDB" \
    --combos "ASD 1" "LRFD 1" --output "out" --plot

# 2) Standalone, from an existing base CSV (works in WSL, no ETABS):
python -m etabs_extractor --plot-csv out/all_base_reactions.csv

# Custom image format (png default; also pdf, svg):
python -m etabs_extractor --plot-csv out/all_base_reactions.csv --plot-format pdf

# Plot with coordinates in m instead of mm (forces/moments are always kN/kN·m):
python -m etabs_extractor --plot-csv out/all_base_reactions.csv --units kN-m

# Append a filename suffix to every CSV / plot (e.g. `_KM13`):
python -m etabs_extractor --plot-csv out/all_base_reactions.csv --tag KM13
```

Each produces one `base_<load>_plan.<fmt>` (or `base_<load>_plan_<tag>.<fmt>`
with `--tag`) figure per load name in the
output directory (or, for `--plot-csv`, next to the CSV). Every point is
labelled with its **point/joint number as the first line** (bare number, e.g.
`1`), followed by its `Fz`, `M2`, `M3` values. See "Library API"
for the components map and how to change/annotate a different set.

`--units` controls the coordinate display unit: `model` (default; kN, kN·m, mm)
or `kN-m` (kN, kN·m, m — coordinates mm→m). Base reactions are exported in
kN / kN·m, so forces and moments are shown in those units under both systems;
only the coordinate length unit differs. Both `--plot` and `--plot-csv` accept it.

## Filename suffix (`--tag NAME`)

`--tag NAME` appends `_NAME` to **every** CSV and plot filename (frame + base

- plots), so multiple extraction runs can be kept side by side without
clobbering each other. The tag is sanitized to a filesystem-safe suffix
(spaces/illegal chars → `_`, stripped); an absent/empty/whitespace-only tag
takes the default (no suffix). Example with `--tag KM13`:

| Without tag | With tag |
| --- | --- |
| `combo_<load>.csv` / `case_<load>.csv` | `combo_<load>_KM13.csv` / `case_<load>_KM13.csv` |
| `all_forces.csv` | `all_forces_KM13.csv` |
| `envelope_summary.csv` | `envelope_summary_KM13.csv` |
| `base_combo_<load>.csv` / `base_case_<load>.csv` | `base_combo_<load>_KM13.csv` / `base_case_<load>_KM13.csv` |
| `base_combo_<load>_min.csv` / `_max.csv` (envelope loads) | `base_combo_<load>_min_KM13.csv` / `_max_KM13.csv` |
| `all_base_reactions.csv` | `all_base_reactions_KM13.csv` |
| `base_envelope_summary.csv` | `base_envelope_summary_KM13.csv` |
| `base_envelope_min.csv` | `base_envelope_min_KM13.csv` |
| `base_envelope_max.csv` | `base_envelope_max_KM13.csv` |
| `base_<load>_plan.<fmt>` | `base_<load>_plan_KM13.<fmt>` |
| `base_<load>_plan_min.<fmt>` / `_max.<fmt>` (single-step CSV) | `base_<load>_plan_min_KM13.<fmt>` / `_max_KM13.<fmt>` |

## What it does

- Connects to a running ETABS instance (or launches one) over COM.
- Opens an ETABS model (`.et` ASCII or `.EDB`) and enumerates frame objects,
  point objects, response combinations, and load cases.
- Selectively enables the requested combinations/cases for output via
  `Results.Setup`, then reads per element:
  - **frames:** forces per frame object with `Results.FrameForce`
    (`eItemTypeElm = 0`, object-level stations).
  - **base:** reactions per point object with `Results.JointReact`(point,
    `eItemTypeElm = 0`), plus point coordinates via `PointObj.GetCoordCartesian`.
- Assembles `FrameForceRecord` / `JointReactionRecord` rows → a consolidated
  long-format DataFrame, a `{load_name: DataFrame}` map, and (optionally)
  CSVs.

## Units

The model in this project is configured in **N, mm, °C**. Frame forces come
out as `P`, `V2`, `V3` in **N**; moments `T`, `M2`, `M3` in **N·mm**
(frame forces are not converted).

**Base reactions are exported in kN / kN·m:** reaction forces `F1`-`F3` are
converted from source N to **kN**, and reaction moments `M1`-`M3` are
converted from source N·mm to **kN·m** (forces ÷ 1000, moments ÷ 1e6).
Coordinates `x`/`y`/`z` stay in **mm** (`z` = elevation). Columns are labeled
with these units; the conversion is applied at extraction so both the
returned DataFrame and every written CSV carry converted values.

## Requirements / runtime

- **Windows** with **ETABS 22** installed (COM server registered). ETABS is a
  Windows-only application; `comtypes` needs the Windows `_ctypes.COMError`,
  so extraction **must** run on a Windows Python interpreter.
- Python ≥ 3.9 with `comtypes`, `pandas`, and `matplotlib` (matplotlib is
  needed only for plotting; it is imported lazily so the pure core imports
  fine without it).

```bash
pip install -r etabs_extractor/requirements.txt
```

The pure-Python core (`config`, `models`, `io`, `results`, `plots`) does not
require COM and imports fine on any platform — this is what the dry-run test
exercises with a synthetic stub. `plots.py` additionally imports matplotlib
lazily so the core stays importable even where matplotlib is absent.

## CLI usage

```bash
# From inside a Windows Python that can see ETABS:
python -m etabs_extractor --model "D:\models\KM 13 2.0.EDB" --output out

# Inventory / connectivity check (no extraction):
python -m etabs_extractor --model "D:\models\KM 13 2.0.EDB" --list-only

# Start ETABS if not running, extract everything (combos + cases):
python -m etabs_extractor --model "path" --launch --all --output out

# Base (joint) reactions for a couple of combos:
python -m etabs_extractor --model "path" --extract base --combos "ASD 1" "LRFD 1" --output out

# Combo/case selection (same for frame and base):
python -m etabs_extractor --model "path" --combos "LRFD 1" "ASD 1" --output out
python -m etabs_extractor --model "path" --cases "Dead" "Live" --output out
# Passing BOTH --combos and --cases extracts both streams together:
python -m etabs_extractor --model "path" --combos "ASD 1" --cases "Dead" --output out

# Optional element filters:
python -m etabs_extractor --model "path" --extract frame --frames "B1" "C2" --output out
python -m etabs_extractor --model "path" --extract base --points "1" "2" --output out
python -m etabs_extractor --model "path" --extract base --elevation -16000 --output out

# Base envelope reactions, only loaded supports:
python -m etabs_extractor --model "path" --extract base --combos "ASD Max" "LRFD Max" \
    --elevation -16000 --only-loaded --output out

# Plot base reactions right after extraction (one PNG per load):
python -m etabs_extractor --model "path" --extract base --combos "ASD 1" "LRFD 1" --output out --plot

# ... with coordinates in m (forces/moments are always kN/kN·m):
python -m etabs_extractor --model "path" --extract base --combos "ASD 1" "LRFD 1" --output out --plot --units kN-m

# Standalone plotting from an existing CSV (no COM/model; WSL-ok):
python -m etabs_extractor --plot-csv out/all_base_reactions.csv --plot-format png --units kN-m

# No CSV output (DataFrames only), re-run analysis first:
python -m etabs_extractor --model "path" --no-csv --run-analysis
```

The model path can also be supplied via the `ETABS_MODEL` env var and the
output dir via `ETABS_OUTPUT`. The package **never hardcodes** model paths.

`--extract` takes `frame` (default) or `base`. `--frames` filters frame
objects for `--extract frame`; `--points` filters point objects and
`--elevation` restricts to a single `z` elevation (model length units, e.g.
`-16000`) and `--only-loaded` drops all-zero supports for `--extract base`
(point-name filter applied first, and only the matching level is read).
`--list-only` reports `Frame objs`, `Point objs`, `Combos`, and `Load cases`.

`--plot` (after `--extract base`) renders one plan-view figure per load into
the output dir; `--plot-csv PATH` is a standalone mode that reads a base CSV
and plots it with no model/COM (wins over any model args and exits first).
`--plot-format` sets the image format (default `png`). `--units` selects the
coordinate display unit: `model` (default; kN, kN·m, mm) or `kN-m` (kN,
kN·m, m — coordinates mm→m). Since base reactions are exported in kN / kN·m,
forces and moments are shown in those units under both systems; only the
coordinate length unit differs. `--tag NAME` appends `_NAME` to every CSV and
plot filename (sanitized to a filesystem-safe suffix; see "Filename suffix"
above).

## Library API

```python
from etabs_extractor import extract_forces, extract_base_reactions, list_available

# Frame-element internal forces:
df, per_load, records = extract_forces(
    "D:/models/KM 13 2.0.EDB", "out",
    combos=None,        # default: combos only (all of them)
    cases=None,         # pass a list to extract load cases instead
    all_requested=False,# True → both combos and cases
    # passing BOTH combos AND cases now extracts both streams together
    attach=True, launch=False, run_analysis=False,
    frames=["B1", "C2"],# optional object-name filter
    tag="KM13",        # optional filename suffix
)

# Base (joint) reactions — same load-selection API:
bdf, bper_load, brecords = extract_base_reactions(
    "D:/models/KM 13 2.0.EDB", "out",
    combos=["ASD Max", "LRFD Max"],  # envelope combos
    points=["1", "2"],   # optional point-name filter
    elevation=-16000.0,     # optional: only this z elevation
    only_loaded=True,        # optional: drop all-zero supports
    tag="KM13",             # optional filename suffix
)

info = list_available("D:/models/KM 13 2.0.EDB")
# {"model_path":…, "frame_names":[…], "point_names":[…], "combos":[…], "cases":[…]}

# From an already-connected session, read the currently-open model's filename
# (used by the GUI's "Check active model"):
from etabs_extractor.connection import EtabsSession
session = EtabsSession.connect(attach=True)          # attach to running ETABS
name = session.get_model_filename(include_path=True) # e.g. "D:\...\model.EDB"
```

`df` (frame) is a long-format DataFrame with columns
`frame, section, station, load_name, load_kind, P, V2, V3, T, M2, M3,
obj_sta, elm, elm_sta`.

`bdf` (base) has columns `point, x, y, z, load_name, load_kind, F1, F2, F3,
M1, M2, M3` (`z` is the elevation). `F1`-`F3` are in **kN** and `M1`-`M3` in
**kN·m**; `x`/`y`/`z` are in model length units (mm). `per_load`/`bper_load`
map each load name to its own DataFrame.

```python
from etabs_extractor import plot_base_reactions, plot_base_reactions_from_csv

# Plan-view figures of bdf — one PNG per load, each point annotated with its
# Fz, M2, M3 values (default; horizontal Fx/Fy omitted).
written = plot_base_reactions(bdf, "plots")               # -> [Path, ...]
written = plot_base_reactions(bdf, "plots", fmt="pdf")      # pdf output
written = plot_base_reactions(bdf, "plots", load_name="ASD 1")  # just one load
written = plot_base_reactions(bdf, "plots", units="kN-m")    # coords in m
written = plot_base_reactions(bdf, "plots", tag="KM13")      # filename suffix

# Plot-appearance control (all backward compatible):
written = plot_base_reactions(
    bdf, "plots",
    dynamic_size=False, figsize=(12, 6),   # fixed canvas (inches)
    dpi=300, label_fontsize=5,             # save resolution + label font
    x_offset=1.0, y_offset=1.0,            # edge-label padding on the axis limits (in)
)

# Build a figure without saving (returns a matplotlib Figure you can embed or
# annotate; None when the load has no plottable points).
fig = build_base_reactions_figure(
    bdf, "ASD 1", dynamic_size=False, figsize=(12, 6),
    x_offset=1.0, y_offset=1.0,
)

# Standalone: read a base CSV and plot into its parent dir (no COM / model).
written = plot_base_reactions_from_csv("out/all_base_reactions.csv")
written = plot_base_reactions_from_csv("out/all_base_reactions.csv", units="kN-m")
written = plot_base_reactions_from_csv("out/all_base_reactions.csv", tag="KM13")
written = plot_base_reactions_from_csv(
    "out/all_base_reactions.csv", dynamic_size=False, figsize=(12, 6), dpi=300
)
```

Default plotted components and their mapping (extend as needed):

```python
from etabs_extractor import DEFAULT_COMPONENTS, COMPONENT_COLUMNS, COMPONENT_UNITS
# DEFAULT_COMPONENTS == ("Fz", "M2", "M3")   (Fx/Fy intentionally omitted)
# COMPONENT_COLUMNS == {"Fx": "F1", "Fy": "F2", "Fz": "F3", "M1": "M1", "M2": "M2", "M3": "M3"}
# COMPONENT_UNITS   == {"Fx": "kN", "Fy": "kN", "Fz": "kN", "M1": "kN·m", "M2": "kN·m", "M3": "kN·m"}
# Pass components=("Fx","Fy","Fz","M2","M3") to restore the full set.
```

Unit systems are exposed as `UNITS` (keys `"model"` and `"kN-m"`), with
`DEFAULT_UNITS == "model"`. Base reactions are already exported in kN / kN·m,
so `force_scale`/`moment_scale` are identity (1.0) in both systems; the only
difference is `length_scale` — `model` keeps coordinates in mm, `kN-m`
converts them mm→m. `--units` maps to these on the CLI.

## Outputs

When `output_dir` is given:

**Frame (`--extract frame`, default):**

- `combo_<name>.csv` / `case_<name>.csv` — one per load name.
- `all_forces.csv` — all rows concatenated.
- `envelope_summary.csv` — min/max of each force per (frame, load name).

**Base (`--extract base`):**

- `base_combo_<name>.csv` / `base_case_<name>.csv` — one per load name.
- `base_combo_<name>_min.csv` / `base_combo_<name>_max.csv` — for loads with
  envelope **Max/Min steps**, the same per-load rows split by ETABS `StepType`
  into a MIN file and a MAX file (case loads get `base_case_<name>_min/max.csv`).
  Written **in addition to** the mixed per-load file, only when non-empty;
  rows with any other step stay in the mixed file only.  Each carries a
  `step_type` column (`Min` / `Max`) and the full `BASE_COLUMNS` schema, so
  they remain directly plottable via `--plot-csv` / "Load preview".
- `all_base_reactions.csv` — all rows concatenated, with a `step_type` column
  (`Max` / `Min` for envelope rows, empty for plain loads) so steps can be
  filtered in any spreadsheet.
- `base_envelope_summary.csv` — min/max of each reaction component per
  (point, load name).
- `base_envelope_min.csv` — per (point, load name): the **minimum** of each
  reaction component (`F1_min…M3_min`).
- `base_envelope_max.csv` — per (point, load name): the **maximum** of each
  reaction component (`F1_max…M3_max`).

All restrained point objects are reported (any elevation); base-level
filtering for dot-plotting is done downstream.

**Plots (from `--plot` or `--plot-csv`):**

- `base_<load>_plan.<fmt>` — one plan-view x-y figure per load name, each
  support annotated with its point/joint number (first label line) followed by
  its `Fz, M2, M3` values (default components; forces in kN and moments in
  kN·m under both `--units` systems, coordinates in mm by default or m with
  `--units kN-m`). `--plot-format` selects the extension (default `png`).
- **Step-aware naming:** plotting a subset that holds exactly one distinct
  `step_type` (e.g. `--plot-csv` on `base_combo_<load>_min.csv`) produces
  `base_<load>_plan_min.<fmt>` (title `ASD Max (Min)`); the `_max.csv` →
  `base_<load>_plan_max.<fmt>`. The two files of one load never overwrite each
  other. Mixed / multi-step inputs (`all_base_reactions.csv`, the mixed
  per-load CSV) keep the legacy `base_<load>_plan.<fmt>` names.

## Testing / verification

`py_compile` and the dry run run on **any** platform (WSL included) because
they never touch COM:

```bash
python3 -m py_compile etabs_extractor/*.py etabs_extractor/tests/*.py
MPLBACKEND=Agg python3 etabs_extractor/tests/test_dry_run.py
MPLBACKEND=Agg python3 etabs_extractor/tests/test_plot_settings.py
```

`test_dry_run.py` injects a `FakeSapModel` stub that returns fabricated force
and reaction arrays, exercising the real extraction → DataFrame → CSV →
**plot** pipeline for **both** the frame (`extract_forces`) and base
(`extract_base_reactions`) paths, asserting column order, CSV row counts, and
that one plan PNG per load is produced (and the CSV-driven `plot-csv` path
yields the same). `test_plot_settings.py` covers the GUI's pure layers and the
reusable figure builder headlessly: `build_base_reactions_figure` fixed vs
dynamic size and no-points→`None`, `plot_base_reactions` dpi/figsize/fontsize
threading, and the `gui.service` settings→args mapping + `gui.state` parsing
(no display, no comtypes). The tests set `matplotlib.use("Agg")` for headless
runs. All stub values are synthetic; the dry run does **not** fabricate any
real-model results.

## Design notes / limitations

- Extraction gathers **all output stations** per frame object (no max-only
  filtering) and **all restrained joints** for base reactions (any elevation;
  interior elevated points legitimately read zeros), so full envelopes are
  preserved; the envelope summaries provide min/max convenience columns.
- `FrameForce` occasionally returns `NumberResults = 0` (a known COM quirk);
  affected frames are skipped with a warning rather than crashing. The same
  0-results guard applies to `JointReact` (point returns `None`).
- **`JointReact` returns 11 output arrays, not 12** (unlike `FrameForce`);
  `joint_react()` returns `NumberResults` + those 11 = a 12-tuple (retcode
  dropped). If you extend the COM read layer, keep this arity in lock-step
  with the fake in `tests/test_dry_run.py`.
- The `Results.Setup` selection is reset before each extraction to avoid
  state bleeding across runs.
- `comtypes` is imported lazily inside `connection.py` so the rest of the
  package stays importable on non-Windows platforms. Likewise `plots.py`
  imports `matplotlib` lazily (inside functions) so the pure core imports
  fine even where matplotlib is absent — only the explicit plot entry points
  require it.
- The **GUI** (`etabs_extractor/gui/`) follows the same discipline: importing
  the package (or `gui.app`) never requires a display or comtypes — `tkinter`
  is imported inside the application methods and `matplotlib` only inside the
  preview canvas / plot calls. `gui/state.py` and `gui/service.py` are pure
  and headless-testable. Extraction runs on a background thread (COM
  initialised in the worker) and posts queue messages so the Tk main thread
  stays responsive.
- Plotting annotates every support with its component values; with many
  points labels can crowd. Filter to a single base level upstream
  (`--elevation` / `--only-loaded`) for cleaner figures.
- Envelope combos (e.g. `ASD Max`/`LRFD Max`) report **two steps per point**
  (Max and Min envelope), so a point appears twice (or more) with different
  values. The plotter aggregates each point to **one** label per component —
  the value with the largest absolute magnitude, sign preserved (e.g.
  `F3 = +615760` wins over `F3 = -304458`). Coordinates still collapse to a
  single marker per point.
- The figure **canvas size adapts to the plotted data**: `_dynamic_figsize`
  sizes the axes from the x–y extent (aspect-equal, longer axis ~8–20 in, min
  6×5 in), so a wide or tall plan is not squeezed into a fixed 10×8 in box.
  Set `dynamic_size=False` (with a fixed `figsize`, e.g. 12×6 in) and/or a
  custom `dpi` / `label_fontsize` to override this via the CLI-independent
  plot API or the GUI's Plot Appearance frame.
- **Label offsets pad the axis limits**: by default `x_offset` / `y_offset`
  (1.0 in each) widen the `xlim`/`ylim` — the inches are converted to data
  units via the equal-aspect scale, on top of matplotlib's normal 5% auto
  margins — so the whitespace sits **inside** the axes box and edge point
  labels render inside the box instead of the box border cutting through
  them. The canvas is never inflated: the figure size is exactly the base
  size (dynamic or fixed). Annotations keep `annotation_clip=False` /
  `clip_on=False` as a safety net and `savefig` keeps `bbox_inches="tight"`,
  so saved images expand to exactly fit the outermost label. Set either
  offset to `0` to remove the extra padding.
- **Label values avoid scientific notation**: `_fmt_plain` renders ~3
  significant figures in fixed notation (``12300`` not ``1.23e+04``), so large
  kN / kN·m values read as plain numbers.

## Running from WSL against a live ETABS (`run_etabs.sh`)

COM can only be driven from a **Windows Python process**, but WSL can execute
Windows binaries directly. `run_etabs.sh` (in the project root) bridges the
gap so you can drive the package from a Linux/WSL shell:

- It **auto-discovers** the Windows Python interpreter (tries
  `python.exe` at the standard install locations) instead of hardcoding a
  versioned name like `python3.14-64.exe` — a path typo there is exactly the
  kind of thing that made first-try runs fail.
- It **converts `/mnt/<drive>/…` arguments to `<DRIVE>:\…`** so you can pass
  model/output paths the natural WSL way and they still reach ETABS over COM.
- It `cd`s into the package root before launching, avoiding the
  `cmd.exe` “UNC paths not supported” error when inheriting a WSL cwd.

```bash
cd "/home/siboi/Projects/Structural Works/etabs_extractor"

# Connectivity / inventory check against a running ETABS:
./run_etabs.sh --list-only --model "/mnt/d/.../KM 13 3.0.EDB"

# Live frame-force extraction (output path also auto-converted):
./run_etabs.sh --model "/mnt/d/.../KM 13 3.0.EDB" --all \
    --output "/mnt/d/.../forces_out"

# Live base-reaction extraction for specific combos:
./run_etabs.sh --extract base --model "/mnt/d/.../KM 13 3.0.EDB" \
    --combos "ASD 1" "LRFD 1" --output "/mnt/d/.../base_out"
```

Requirements for the live path:

- **ETABS must be running** (or pass `--launch`), and the model referenced by
  `--model` must be the one open in that session.
- The **Windows** Python must have `comtypes` + `pandas` installed (same
  `requirements.txt`).
- If auto-discovery fails, set `WIN_PY=<path-to-windows-python.exe>` or drop a
  `python.exe` next to the script as `windows_python.exe`.

This launcher only removes the *interpreter/path-discovery* friction; the
underlying rule is unchanged — extraction still requires a Windows Python
process and a reachable (running) ETABS COM server. The same discovery logic
backs `run_gui.sh` for the interactive GUI.

## GUI run example

```bash
cd ~/Projects/Structural\ Works/etabs_extractor

# Launch the GUI (Windows Python, ETABS should be running):
./run_gui.sh
```
