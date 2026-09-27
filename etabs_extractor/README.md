# etabs_extractor

Extract results from an **ETABS 22** model via the CSI COM API and write
them to CSV (also returning pandas DataFrames), **in the active model's own
units by default** (or any unit system you request — see "Units" below):

- **frame-element internal forces** — axial `P`, shears `V2`/`V3`, torsion
  Each row also carries the frame object's **Euclidean length** (`length_mm`
  column, named for historical reasons but now in the output length unit),
  computed from the end-point coordinates via `FrameObj.GetPoints`.
  Unknown/unresolvable lengths are `None` (NaN in the DataFrame).
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

# Output in specific units instead of the model's own (default: model units,
# read live via the COM API — see "Units" below):
./run_etabs.sh --extract base --model "/mnt/d/.../model.EDB" \
    --combos "ASD 1" "LRFD 1" --output "/mnt/d/.../out" \
    --force-unit kN --length-unit m
```

See "Running from WSL against a live ETABS (`run_etabs.sh`)" below for
details and fallbacks.

## Interactive GUI (base reactions + frame forces)

A **customtkinter GUI** (`etabs_extractor/gui/`) provides a point-and-click
way to check the active ETABS model, choose an export destination and
filename tag, configure plot appearance, and **switch between two extraction
modes**: **Base reactions** (default) or **Frame forces**. It's a sidebar +
tabbed-workspace layout: the sidebar holds the model/output/mode/load
controls and the single **Extract** action; the workspace tabs hold the
**Preview** (rendered inline — no pop-up windows), **Plot settings**, **CSV**
(plot from an existing base CSV, no ETABS needed) and **Log**.

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

- **Model & output card** — model file entry + Browse (`*.EDB` / `*.et`) +
  **"Check active model"**, which attaches to the running ETABS, fills the
  path field via `SapModel.GetModelFilename` (a cSapModel method on the model
  object, not the File interface; no path needed), and populates the **Load
  selection** picker with the active model's **combos + cases** (via
  `get_combo_names` / `get_case_names`), for frame mode the **Sections**
  picker with the model's **section names** (via `get_frame_section_names`),
  and (see **Units** card below) the model's **present units** and **elevation
  inventory**. A status line under the button shows the checked model path and
  the combo/case/section counts. Also holds the output directory (defaults to
  `ETABS_OUTPUT`, with a **Browse** button — like the Model field's, always
  visible/clickable regardless of window width; both fields stack their label
  above the entry+Browse row rather than packing all three side by side), a
  **Tag** field (filename suffix, sanitized, with a live "Suffix: _xxx" hint),
  and **Attach (not launch)** / **Run analysis** switches.
- **Units card** — **Force** and **Length** dropdowns selecting the output
  unit system (default **`model`** on both — the active model's own present
  units, read live via `EtabsSession.get_present_units()`; no conversion), plus
  a hint line showing "Model: `<force>, <length>` → Output: `<force>,
  <force>·<length>, <length>`" once the model has been checked. Changing
  either dropdown re-renders the hint and re-labels the Elevation combobox
  below (see **Base filters**) in the newly selected length unit.
- **Extraction mode card** — a segmented **Base reactions** / **Frame
  forces** switch. Switching mode swaps the sidebar's mode-scoped filter card
  and the workspace Preview tab's contents (base plan-view panel vs. frame
  force-diagram panel) — nothing is hidden behind a checkbox, the layout just
  changes.
- **Load selection card** — a **searchable multi-select checklist** of the
  active model's **combos + cases** (opened via the **Select** button/click
  on the summary field); search-as-you-type, tick as many as you want. An
  empty selection keeps the default (all model combos).
- **Base filters** (base mode only) — an **editable Elevation combobox**
  (label reads "Elevation (`<unit>`)"), switches for **Only loaded supports**
  and **Plot after extract**. "Check active model" fills the combobox with
  every distinct elevation the model has, labelled by story name (or "Base"
  for the model's base level) and point count — e.g. `-18.55  (Base, 42
  pts)` — displayed in the currently selected output length unit; you can
  also just type a value. Parsing takes the leading number and ignores the
  trailing `(...)` label.
  - The base preview renders **one marker per distinct plan (x/y) point**.
    Envelope combos (Max/Min) collapse to a single governing marker per point
    (largest absolute value), so they do **not** duplicate points. Points
    with all-zero reactions (non-load-bearing joints) still get a marker
    unless **"Only loaded supports"** is checked. For a clean plan-view of
    just the real supports, set `elevation` (e.g. from the dropdown) **and**
    check `only_loaded`.
- **Section filter** (frame mode only) — the same searchable multi-select
  checklist widget, over the model's section names; empty = all sections.
- **Extract** — a single button at the bottom of the sidebar. Runs on a
  **background thread** (`gui/runner.py`'s `BackgroundRunner`, COM
  initialised in the worker via comtypes `CoInitialize()`/`CoUninitialize()`
  — required on Windows, a no-op elsewhere), so the UI stays responsive; the
  status bar's progress indicator animates while a job is in flight and the
  sidebar's action buttons disable. On completion the workspace switches to
  the **Preview** tab and renders the first load automatically.
- **Preview tab** — embedded, not a pop-up:
  - *Base mode* (`BasePreviewPanel`): a Load dropdown, **Refresh** (re-reads
    the Plot settings tab and re-renders) and **Save image...** buttons over
    an embedded matplotlib canvas.
  - *Frame mode* (`FramePreviewPanel`): Load / Section / Step
    (Both/Max/Min) / Force (Moment M3, Shear V2, Axial P) / Length
    dropdowns, **Refresh**, **Save image...**, and **Batch plot all
    (overlay)** (every beam of that section+length in one diagram, star =
    highest |force|). The beam shown is always the one with the highest
    |force| at the current selection — there's no beam dropdown.
- **Plot settings tab** — `dynamic size` switch (figure follows data) with
  width/height fields disabled while dynamic; **X/Y label offsets (in)**
  (default 1.0 in each way — extra axis-limit padding so edge point labels
  render inside the axes box), dpi (default 800), label font size (default
  2.4), **units** (`data` default — the extraction's own units, unconverted;
  plus `kN-m`/`kN-mm`/`N-mm`/`tonf-m`/`kgf-m`), format (`png`/`pdf`/`svg`).
  Applies to the base preview and to `--plot-after-extract`/CSV plotting; the
  frame preview's "Save image..." always saves at dpi 150 (diagram, not a
  publication plan-view).
- **CSV tab** — pick a base-reaction CSV, an optional **Plot output**
  directory (Browse; blank saves next to the CSV file), and **Load preview**
  (no ETABS/COM needed); the result renders in the base Preview panel like a
  live extract.
- **Log tab** — a running, timestamped log of every action (also mirrored to
  the status-bar line).
- **Status bar** — progress indicator + status text + an **Appearance**
  selector (`System`/`Light`/`Dark`, applies immediately via
  `ctk.set_appearance_mode`). The app chrome follows the theme; **plotted
  figures stay light** (white background) on screen and when saved — the
  point labels are drawn in white boxes, so a dark plot would put white text
  on white.

The embedded preview canvases need **matplotlib installed on the Windows
Python** that drives the GUI (the one `run_gui.sh` discovers). If it's
missing, the preview logs `Preview needs matplotlib: ...` — install it via
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

# Plot in a specific unit system, converted from whatever the CSV itself
# carries (its own force_unit/length_unit columns):
python -m etabs_extractor --plot-csv out/all_base_reactions.csv --units kN-m

# Any "<force>-<length>" pair works, e.g. tonnes-force and millimetres:
python -m etabs_extractor --plot-csv out/all_base_reactions.csv --units tonf-mm

# Append a filename suffix to every CSV / plot (e.g. `_KM13`):
python -m etabs_extractor --plot-csv out/all_base_reactions.csv --tag KM13
```

Each produces one `base_<load>_plan.<fmt>` (or `base_<load>_plan_<tag>.<fmt>`
with `--tag`) figure per load name in the
output directory (or, for `--plot-csv`, next to the CSV). Every point is
labelled with its **point/joint number as the first line** (bare number, e.g.
`1`), followed by its `Fz`, `M2`, `M3` values. See "Library API"
for the components map and how to change/annotate a different set.

`--units` selects the plot's display units: `model`/`data` (default —
display the CSV/DataFrame's own units unconverted, i.e. whatever the
extraction was run with), a named preset (`kN-m`, `kN-mm`, `N-mm`, `tonf-m`,
`kgf-m`), or any `"<force>-<length>"` pair (e.g. `tonf-mm`). The source units
are read from the CSV's own `force_unit`/`length_unit` columns (see "Units"
below); a legacy CSV without those columns falls back to the historical
`kN`/`mm` assumption. Both `--plot` and `--plot-csv` accept it.

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

Extraction is **model-aware**: it reads the active model's own present
force/length units live via the COM API (`SapModel.GetPresentUnits_2` /
`GetPresentUnits`, wrapped as `EtabsSession.get_present_units()` ->
`etabs_extractor.units.UnitSystem`) instead of assuming a fixed unit system.
By default (`--force-unit model --length-unit model`, or simply omitting
both flags) the output is in **whatever units the model itself is set to** —
no conversion, no guessing. Every frame-force and base-reaction row (and
CSV) carries the resolved units as trailing `force_unit`/`length_unit`
columns (e.g. `"kN"` / `"m"`), so a file is always self-describing; moments
are `force_unit·length_unit` (e.g. `"kN·m"`).

Pass `--force-unit` / `--length-unit` (CLI) or `force_unit=`/`length_unit=`
(library) to have the extraction convert to a specific system instead:

```bash
# Model is e.g. kN/m; ask for kN/mm output instead:
python -m etabs_extractor --model "path" --extract base --force-unit kN --length-unit mm --output out
```

- `--force-unit`: `model` (default), `N`, `kN`, `kgf`, `tonf`, `lb`, `kip`.
- `--length-unit`: `model` (default), `mm`, `cm`, `m`, `in`, `ft`.

Coordinates `x`/`y`/`z` (base reactions) and `station`/`length_mm`/`obj_sta`/
`elm_sta` (frame forces) scale with the length unit; `F1`-`F3`/`P`/`V2`/`V3`
scale with the force unit; `M1`-`M3`/`T`/`M2`/`M3` scale with force×length
(moment). `--elevation` is interpreted in the **output** length unit (so a
model reported in metres takes e.g. `--elevation -18.55`, not `-18550`).

This replaced an earlier hardcoded assumption (frame forces always N/N·mm,
base reactions always exported as kN/kN·m) that silently gave wrong numbers
on any model not actually configured in those units — e.g. a model set to
kN/m had its coordinates divided by 1000 as if they were millimetres. The
model-aware default fixes that; pass explicit `--force-unit`/`--length-unit`
to reproduce the old fixed-unit behavior if you depend on it (`kN`/`mm` for
base reactions matched the historical default).

**Listing a model's elevations** — `--list-only` (CLI) / "Check active
model" (GUI) additionally read the model's story table (`Story.
GetStories_2`) and every point's `z` coordinate (`PointObj.GetAllPoints`, one
COM call) to report the distinct elevations, each labelled by story name (or
`"Base"` for the model's base level) with a point count — see
`etabs_extractor.results.list_elevations()`. Use this to find a level's exact
elevation before passing `--elevation`.

## Requirements / runtime

- **Windows** with **ETABS 22** installed (COM server registered). ETABS is a
  Windows-only application; `comtypes` needs the Windows `_ctypes.COMError`,
  so extraction **must** run on a Windows Python interpreter.
- Python ≥ 3.9 with `comtypes`, `pandas`, and `matplotlib` (matplotlib is
  needed only for plotting; it is imported lazily so the pure core imports
  fine without it).
- The **GUI** additionally needs `customtkinter` (>=5.2.0) on whichever
  Python launches it (the WSL `.venv` for editing/tests, and the **Windows**
  Python that `run_gui.sh` drives for a live run). If it's missing, `run_gui`
  prints a one-line `pip install customtkinter` hint instead of a raw
  traceback.

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

# ... displayed in kN/m regardless of the extraction's own units:
python -m etabs_extractor --model "path" --extract base --combos "ASD 1" "LRFD 1" --output out --plot --units kN-m

# Standalone plotting from an existing CSV (no COM/model; WSL-ok):
python -m etabs_extractor --plot-csv out/all_base_reactions.csv --plot-format png --units kN-m

# Output in a specific unit system instead of the model's own (see "Units"):
python -m etabs_extractor --model "path" --extract base --force-unit kN --length-unit m --output out

# List a model's distinct elevations (labelled by story) alongside the usual inventory:
python -m etabs_extractor --model "path" --list-only

# No CSV output (DataFrames only), re-run analysis first:
python -m etabs_extractor --model "path" --no-csv --run-analysis
```

The model path can also be supplied via the `ETABS_MODEL` env var and the
output dir via `ETABS_OUTPUT`. The package **never hardcodes** model paths.

`--extract` takes `frame` (default) or `base`. `--frames` filters frame
objects for `--extract frame`; per-load MIN/MAX step split CSVs are emitted
automatically for frame envelope combos (see Outputs). `--points` filters
point objects and `--elevation` restricts to a single `z` elevation
(**output** length unit — see "Units" — e.g. `-16000` for a model reported in
mm, or `-16.0` with `--length-unit m`) and `--only-loaded` drops all-zero
supports for `--extract base` (point-name filter applied first, and only the
matching level is read). `--force-unit` / `--length-unit` select the output
unit system (default `model` — the active model's own present units; see
"Units"). `--list-only` reports `Frame objs`, `Point objs`, `Combos`,
`Load cases`, `Units`, and the model's `Elevations` (one line per distinct
level: `z`, story label, point count).

`--plot` (after `--extract base`) renders one plan-view figure per load into
the output dir; `--plot-csv PATH` is a standalone mode that reads a base CSV
and plots it with no model/COM (wins over any model args and exits first).
`--plot-format` sets the image format (default `png`). `--units` selects the
plot's display units: `model`/`data` (default — the CSV/DataFrame's own
units, unconverted), a named preset (`kN-m`, `kN-mm`, `N-mm`, `tonf-m`,
`kgf-m`), or any `"<force>-<length>"` pair. `--tag NAME` appends `_NAME` to
every CSV and plot filename (sanitized to a filesystem-safe suffix; see
"Filename suffix" above).

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
    frames=["B1", "C2"],  # optional object-name filter
    sections=["COL1"],    # optional section-name filter (AND with frames)
    tag="KM13",           # optional filename suffix
    force_unit="model",   # default: the model's own present units (no conversion)
    length_unit="model",  # pass e.g. "kN"/"m" to convert at extraction time
)

# Base (joint) reactions — same load-selection API:
bdf, bper_load, brecords = extract_base_reactions(
    "D:/models/KM 13 2.0.EDB", "out",
    combos=["ASD Max", "LRFD Max"],  # envelope combos
    points=["1", "2"],   # optional point-name filter
    elevation=-16000.0,     # optional: only this z elevation (output length unit)
    only_loaded=True,        # optional: drop all-zero supports
    tag="KM13",             # optional filename suffix
    force_unit="model", length_unit="model",  # see extract_forces above
)

info = list_available("D:/models/KM 13 2.0.EDB")
# {"model_path":…, "frame_names":[…], "point_names":[…], "combos":[…], "cases":[…],
#  "units": {"force": "kN", "length": "m"}, "elevations": [{"z":…, "label":…, "n_points":…}, …]}

# From an already-connected session, read the currently-open model's filename
# (used by the GUI's "Check active model"):
from etabs_extractor.connection import EtabsSession
session = EtabsSession.connect(attach=True)          # attach to running ETABS
name = session.get_model_filename(include_path=True) # e.g. "D:\...\model.EDB"
units = session.get_present_units()                  # UnitSystem(force="kN", length="m")

# List the model's distinct elevations, labelled by story (used by --list-only
# and the GUI's elevation combobox):
from etabs_extractor.results import list_elevations
elevations = list_elevations(session)
# [{"z": -18.55, "label": "Base", "n_points": 60}, …]  (model's own length unit)
```

`df` (frame) is a long-format DataFrame with columns `frame, section, station,
load_name, load_kind, step_type, P, V2, V3, T, M2, M3, length_mm, obj_sta,
elm, elm_sta, force_unit, length_unit`.

`bdf` (base) has columns `point, x, y, z, load_name, load_kind, step_type,
F1, F2, F3, M1, M2, M3, force_unit, length_unit` (`z` is the elevation).
`force_unit`/`length_unit` name the unit system every row was converted to
(default: the model's own present units — see "Units" above); `x`/`y`/`z`
and `F1`-`F3`/`M1`-`M3` are in those units. `per_load`/`bper_load` map each
load name to its own DataFrame.

```python
from etabs_extractor import plot_base_reactions, plot_base_reactions_from_csv

# Plan-view figures of bdf — one PNG per load, each point annotated with its
# Fz, M2, M3 values (default; horizontal Fx/Fy omitted).
written = plot_base_reactions(bdf, "plots")               # -> [Path, ...]
written = plot_base_reactions(bdf, "plots", fmt="pdf")      # pdf output
written = plot_base_reactions(bdf, "plots", load_name="ASD 1")  # just one load
written = plot_base_reactions(bdf, "plots", units="kN-m")    # convert to kN/m for display
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
# COMPONENT_UNITS   == {"Fx": "kN", ...}  historical/reference labels only —
#   the actual display unit is resolved per-plot from the data (see "Units").
# Pass components=("Fx","Fy","Fz","M2","M3") to restore the full set.
```

Named display-unit presets are exposed as `UNITS` (`"kN-m"`, `"kN-mm"`,
`"N-mm"`, `"tonf-m"`, `"kgf-m"`), with `DEFAULT_UNITS == "data"`. `"model"`/
`"data"` (the default) display the DataFrame/CSV's own units (its
`force_unit`/`length_unit` columns) unconverted; any other
`"<force>-<length>"` string not in `UNITS` is also accepted (e.g.
`"tonf-mm"`). `plots._resolve_units(units, df)` does the actual conversion
math (see `etabs_extractor.units.factors`) and is what every plot entry
point calls internally. `--units` on the CLI maps to the same values.

## Outputs

When `output_dir` is given:

**Frame (`--extract frame`, default):**

- `combo_<name>.csv` / `case_<name>.csv` — one per load name.
- `combo_<name>_min.csv` / `combo_<name>_max.csv` — for frame loads with
  envelope **Max/Min steps**, the same per-load rows split by ETABS
  `StepType` into a MIN file and a MAX file (case loads get
  `case_<name>_min/max.csv`). Written **in addition to** the mixed per-load
  file, only when non-empty; rows with any other step stay in the mixed file
  only.  Each carries a `step_type` column (`Min` / `Max`) and the full
  `COLUMNS` schema.
- `all_forces.csv` — all rows concatenated.
- `envelope_summary.csv` — min/max of each force per (frame, load name).

**Base (`--extract base`):**

- `base_combo_<name>.csv` / `base_case_<name>.csv` — one per load name.
- `base_combo_<name>_min.csv` / `base_combo_<name>_max.csv` — for loads with
  envelope **Max/Min steps**, the same per-load rows split by ETABS `StepType`
  into a MIN file and a MAX file (case loads get
  `base_combo_<name>_min/max.csv`). Written **in addition to** the mixed
  per-load file, only when non-empty; rows with any other step stay in the
  mixed file only.  Each carries a `step_type` column (`Min` / `Max`) and the
  full `BASE_COLUMNS` schema.

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
  its `Fz, M2, M3` values, displayed in the units selected by `--units`
  (default `model`/`data` — the extraction's own units, unconverted).
  `--plot-format` selects the extension (default `png`).
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

`test_dry_run.py` injects a `FakeSapModel` stub (present units N/mm, a story
table, and per-point coordinates) that returns fabricated force and reaction
arrays, exercising the real extraction → DataFrame → CSV → **plot** pipeline
for **both** the frame (`extract_forces`) and base (`extract_base_reactions`)
paths, asserting column order (including the `force_unit`/`length_unit`
columns), CSV row counts, model-aware unit conversion (an explicit
`force_unit="kN", length_unit="m"` extraction against the same N/mm fake),
`list_elevations()` story labelling, and that one plan PNG per load is
produced (and the CSV-driven `plot-csv` path yields the same).
`test_plot_settings.py` covers the GUI's pure layers and the reusable figure
builder headlessly: `build_base_reactions_figure` fixed vs dynamic size and
no-points→`None`, `plot_base_reactions` dpi/figsize/fontsize threading, the
`gui.service` settings→args mapping (incl. `force_unit`/`length_unit`,
`build_elevation_labels`) + `gui.state` parsing (incl. the elevation
combobox's labelled-entry format), and `etabs_extractor.units`'s conversion
factors (no display, no comtypes). The tests set `matplotlib.use("Agg")` for
headless runs. All stub values are synthetic; the dry run does **not** fabricate any
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
  the package (or `gui.app`) never requires a display or comtypes —
  `customtkinter`/`tkinter` are imported inside the application methods and
  `matplotlib` only inside the preview canvas / plot calls. `gui/state.py`
  and `gui/service.py` are pure and headless-testable. Extraction runs on a
  background thread (`gui/runner.py`'s `BackgroundRunner`, COM initialised in
  the worker) and posts queue messages so the main thread stays responsive.
  Previews are embedded panels in the workspace tabs (no separate pop-up
  windows).
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

# First time only: install the GUI's extra dependency on the Windows Python
# that run_gui.sh drives (see "Requirements / runtime" above):
#   <windows-python> -m pip install customtkinter

# Launch the GUI (Windows Python, ETABS should be running):
./run_gui.sh
```

## Beam Force Diagram Viewer

After extracting frame forces, use the interactive **beam viewer** to display
axial-force (P), shear (V2), and bending-moment (M3) diagrams for any beam
in the model. The viewer loads the `all_forces.csv` output and requires no
COM connection, so it works on any platform (WSL, Linux, Windows) with
matplotlib.

```bash
cd ~/Projects/Structural\ Works/etabs_extractor

# Run the viewer on extracted data (no COM needed):
python beam_viewer.py /path/to/all_forces.csv

# Or from WSL after a live extraction (using the .venv):
.venv/bin/python beam_viewer.py "/mnt/d/.../extracted/all_forces.csv"
```

Defaults to the beam with the highest absolute bending moment (|M3|) for
the selected section type and load case.

**Controls:**

| Key | Action |
|-----|--------|
| `←` / `→` | Cycle load cases |
| `↑` / `↓` | Cycle beams within the current section |
| `S` | Cycle section type (B1, B2, K1, P600, RB-1) |
| `H` | Toggle auto-select highest-force beam |
| `Q` | Quit |

**Force display:** always shown in kN / kN·m / m regardless of the CSV's own
units — read from its `force_unit`/`length_unit` columns and converted for
display (a legacy CSV without those columns falls back to the historical N /
mm assumption). Positive and negative regions are filled in green and red
respectively, with max/min annotations on each diagram.