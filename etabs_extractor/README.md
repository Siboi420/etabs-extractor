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

# Plot in kN / m instead of model units (N, N·mm, mm):
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

`--units` controls the display unit system: `model` (default; N, N·mm, mm)
or `kN-m` (forces N→kN, moments N·mm→kN·m, coordinates mm→m). Both `--plot`
and `--plot-csv` accept it.

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
| `all_base_reactions.csv` | `all_base_reactions_KM13.csv` |
| `base_envelope_summary.csv` | `base_envelope_summary_KM13.csv` |
| `base_envelope_min.csv` | `base_envelope_min_KM13.csv` |
| `base_envelope_max.csv` | `base_envelope_max_KM13.csv` |
| `base_<load>_plan.<fmt>` | `base_<load>_plan_KM13.<fmt>` |

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
out as `P`, `V2`, `V3` in **N**; moments `T`, `M2`, `M3` in **N·mm**.
Base-reaction forces `F1`-`F3` are **N** and moments `M1`-`M3` are **N·mm**;
coordinates `x`/`y`/`z` are **mm** (`z` = elevation). Columns are labeled
with these units and values are **not** converted.

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

# Optional element filters:
python -m etabs_extractor --model "path" --extract frame --frames "B1" "C2" --output out
python -m etabs_extractor --model "path" --extract base --points "1" "2" --output out
python -m etabs_extractor --model "path" --extract base --elevation -16000 --output out

# Base envelope reactions, only loaded supports:
python -m etabs_extractor --model "path" --extract base --combos "ASD Max" "LRFD Max" \
    --elevation -16000 --only-loaded --output out

# Plot base reactions right after extraction (one PNG per load):
python -m etabs_extractor --model "path" --extract base --combos "ASD 1" "LRFD 1" --output out --plot

# ... in kN / m display units:
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
display unit system: `model` (default) or `kN-m` (forces N→kN, moments
N·mm→kN·m, coordinates mm→m). `--tag NAME` appends `_NAME` to every CSV and
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
```

`df` (frame) is a long-format DataFrame with columns
`frame, section, station, load_name, load_kind, P, V2, V3, T, M2, M3,
obj_sta, elm, elm_sta`.

`bdf` (base) has columns `point, x, y, z, load_name, load_kind, F1, F2, F3,
M1, M2, M3` (`z` is the elevation; all in model units). `per_load`/`bper_load`
map each load name to its own DataFrame.

```python
from etabs_extractor import plot_base_reactions, plot_base_reactions_from_csv

# Plan-view figures of bdf — one PNG per load, each point annotated with its
# Fz, M2, M3 values (default; horizontal Fx/Fy omitted).
written = plot_base_reactions(bdf, "plots")               # -> [Path, ...]
written = plot_base_reactions(bdf, "plots", fmt="pdf")      # pdf output
written = plot_base_reactions(bdf, "plots", load_name="ASD 1")  # just one load
written = plot_base_reactions(bdf, "plots", units="kN-m")    # kN / m display
written = plot_base_reactions(bdf, "plots", tag="KM13")      # filename suffix

# Standalone: read a base CSV and plot into its parent dir (no COM / model).
written = plot_base_reactions_from_csv("out/all_base_reactions.csv")
written = plot_base_reactions_from_csv("out/all_base_reactions.csv", units="kN-m")
written = plot_base_reactions_from_csv("out/all_base_reactions.csv", tag="KM13")
```

Default plotted components and their mapping (extend as needed):

```python
from etabs_extractor import DEFAULT_COMPONENTS, COMPONENT_COLUMNS, COMPONENT_UNITS
# DEFAULT_COMPONENTS == ("Fz", "M2", "M3")   (Fx/Fy intentionally omitted)
# COMPONENT_COLUMNS == {"Fx": "F1", "Fy": "F2", "Fz": "F3", "M1": "M1", "M2": "M2", "M3": "M3"}
# COMPONENT_UNITS   == {"Fx": "N", "Fy": "N", "Fz": "N", "M1": "N·mm", "M2": "N·mm", "M3": "N·mm"}
# Pass components=("Fx","Fy","Fz","M2","M3") to restore the full set.
```

Unit systems are exposed as `UNITS` (keys `"model"` and `"kN-m"`), with
`DEFAULT_UNITS == "model"`. `--units` maps to these on the CLI.

## Outputs

When `output_dir` is given:

**Frame (`--extract frame`, default):**

- `combo_<name>.csv` / `case_<name>.csv` — one per load name.
- `all_forces.csv` — all rows concatenated.
- `envelope_summary.csv` — min/max of each force per (frame, load name).

**Base (`--extract base`):**

- `base_combo_<name>.csv` / `base_case_<name>.csv` — one per load name.
- `all_base_reactions.csv` — all rows concatenated.
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
  its `Fz, M2, M3` values (default components; axis and labels in the `--units`
  system — model N/N·mm/mm by default, or kN/kN·m/m with `--units kN-m`).
  `--plot-format` selects the extension (default `png`).

## Testing / verification

`py_compile` and the dry run run on **any** platform (WSL included) because
they never touch COM:

```bash
python3 -m py_compile etabs_extractor/*.py etabs_extractor/tests/*.py
MPLBACKEND=Agg python3 etabs_extractor/tests/test_dry_run.py
```

The dry run injects a `FakeSapModel` stub that returns fabricated force and
reaction arrays, exercising the real extraction → DataFrame → CSV → **plot**
pipeline for **both** the frame (`extract_forces`) and base
(`extract_base_reactions`) paths, asserting column order, CSV row counts, and
that one plan PNG per load is produced (and the CSV-driven `plot-csv` path
yields the same). The test sets `matplotlib.use("Agg")` for headless runs.
All stub values are synthetic; the dry run does **not** fabricate any
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
process and a reachable (running) ETABS COM server.
