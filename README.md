# etabs_extractor

Extract results from an **ETABS 22** model via the CSI COM API and write
them to CSV (also returning pandas DataFrames):

- **frame-element internal forces** — axial `P`, shears `V2`/`V3`, torsion
  `T`, moments `M2`/`M3` for every frame object across the model's load
  combinations (and optionally load cases) — `--extract frame` (default).
- **per-joint (base) reactions** — reaction forces `F1`/`F2`/`F3` and moments
  `M1`/`M2`/`M3` plus each point's global coordinates/elevation —
  `--extract base`.
- **plan-view plotting** of the base reactions (one PNG per load, point
  labels, envelope Max/Min steps), from a live model or from an existing CSV
  (`--plot` / `--plot-csv`, no ETABS needed).
- **interactive tkinter GUI** (`etabs_extractor/gui/`, `./run_gui.sh`) for
  base-reaction extraction, plot preview, and CSV plotting.

> **COM is Windows-only.** The package talks to ETABS through `comtypes`,
> which requires a Windows Python process. The pure-Python core (models,
> CSV writing, plotting, tests) imports on any platform; live extraction
> needs ETABS running (or `--launch`) on Windows.

## Quick start (live ETABS run, from WSL)

The `run_etabs.sh` launcher auto-discovers the Windows Python, converts
`/mnt/<drive>/...` paths, and runs against the live session.

```bash
cd ~/Projects/Structural\ Works/etabs_extractor

# Inventory / connectivity check:
./run_etabs.sh --list-only --model "/mnt/d/.../model.EDB"

# Base reactions for a couple of combos, one level, only loaded supports:
./run_etabs.sh --extract base --model "/mnt/d/.../model.EDB" \
    --combos "ASD Max" "LRFD Max" --elevation -16000 --only-loaded \
    --output "/mnt/d/.../out"

# Also plot plan-view figures (one PNG per load):
./run_etabs.sh --extract base --model "/mnt/d/.../model.EDB" \
    --combos "ASD 1" "LRFD 1" --output "/mnt/d/.../out" --plot

# GUI (base extraction + plot preview):
./run_gui.sh
```

Envelope combos export per-load **MIN/MAX step split CSVs**
(`base_combo_<load>_min.csv` / `_max.csv`) alongside the mixed per-load
files, and a `step_type` column marks each row in `all_base_reactions.csv`.

## Documentation

- **User guide, CLI reference, outputs, and GUI walkthrough** →
  [`etabs_extractor/README.md`](etabs_extractor/README.md).
- **Developer guidance** (architecture, invariants, extending the
  framework) → [`AGENTS.md`](AGENTS.md).

## Repository layout

```text
etabs_extractor/        # the Python package
  cli.py                # argparse CLI (--extract frame|base, --plot, --plot-csv)
  models.py             # record types + DataFrame schema (pure)
  results.py            # extraction orchestration (COM via duck-typed session)
  connection.py         # EtabsSession: COM attach/launch/read (the only COM layer)
  io.py                 # CSV writers (pure)
  plots.py              # plan-view plotting, lazy matplotlib (pure)
  gui/                  # tkinter GUI (base extraction + plotting)
  tests/                # headless dry-run + pure-layer tests (no COM)
run_etabs.sh            # WSL -> Windows launcher (live ETABS runs)
run_gui.sh              # WSL -> Windows launcher for the GUI
```

## Tests

Run headless on any platform (no ETABS, no display):

```bash
MPLBACKEND=Agg python etabs_extractor/tests/test_dry_run.py
MPLBACKEND=Agg python etabs_extractor/tests/test_plot_settings.py
```

## License

MIT (see `pyproject.toml`).
