"""Command-line interface for etabs_extractor.

Run ``python -m etabs_extractor --help`` for usage.  The CLI mirrors the
library API and adds a ``--list-only`` connectivity check.

NOTE ON RUNTIME: because the extraction talks to ETABS over COM, this CLI
*only* operates meaningfully on a Windows Python interpreter that can
connect to a running (or launchable) ETABS 22 instance.  On other platforms
it still parses arguments and reports a clear error if no model is
resolvable.
"""

from __future__ import annotations

import argparse
import sys

from . import units as _units


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="etabs_extractor",
        description=(
            "Extract frame-element forces (P, V2, V3, T, M2, M3) or per-joint "
            "base reactions (F1-F3, M1-M3) from an ETABS model's load "
            "combinations/cases via the COM API."
        ),
    )
    parser.add_argument(
        "--model",
        help="Path to the ETABS model (.et / .EDB). Falls back to $ETABS_MODEL.",
    )
    parser.add_argument(
        "--output",
        help="Output directory for CSVs. Defaults to $ETABS_OUTPUT or "
        "output/etabs_forces.",
    )
    parser.add_argument(
        "--extract",
        choices=["frame", "base"],
        default="frame",
        help="What to extract: ``frame`` (internal forces, default) or ``base`` "
        "(per-joint reactions at every restrained point).",
    )
    parser.add_argument(
        "--combos",
        nargs="*",
        default=None,
        help="Response combinations to extract (exact ETABS names). Default: all.",
    )
    parser.add_argument(
        "--cases",
        nargs="*",
        default=None,
        help="Load cases to extract (exact ETABS names). If given, supersedes combos scope.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Extract both all combinations and all load cases.",
    )
    parser.add_argument(
        "--frames",
        nargs="*",
        default=None,
        help="Optional filter: only these frame object names (e.g. B1 C2). "
        "Applies to --extract frame only.",
    )
    parser.add_argument(
        "--points",
        nargs="*",
        default=None,
        help="Optional filter: only these point object names (e.g. 1 2 3). "
        "Applies to --extract base only.",
    )
    parser.add_argument(
        "--elevation",
        type=float,
        default=None,
        help="For --extract base: only report points whose z-elevation equals "
        "this value, in the OUTPUT length unit (--length-unit; e.g. -16000 for "
        "a model reported in mm, or -16.0 if --length-unit m). Point name "
        "filter is applied first. Use --list-only to see the model's actual "
        "elevations.",
    )
    parser.add_argument(
        "--force-unit",
        default="model",
        metavar="UNIT",
        choices=list(_units.FORCE_CHOICES),
        help="Output force/moment unit (default: 'model' — the active "
        "model's own present units, read live via the COM API; no "
        "conversion). Choices: " + ", ".join(_units.FORCE_CHOICES) + ".",
    )
    parser.add_argument(
        "--length-unit",
        default="model",
        metavar="UNIT",
        choices=list(_units.LENGTH_CHOICES),
        help="Output length unit for coordinates/station/length columns "
        "(default: 'model' — the active model's own present units; no "
        "conversion). Choices: " + ", ".join(_units.LENGTH_CHOICES) + ".",
    )
    parser.add_argument(
        "--only-loaded",
        action="store_true",
        help="For --extract base: drop points with all-zero reactions, keeping "
        "only supports that actually carry load.",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="List frames/combos/cases and exit (COM connectivity check).",
    )
    parser.add_argument(
        "--launch",
        action="store_true",
        help="Start ETABS if it is not already running.",
    )
    parser.add_argument(
        "--run-analysis",
        action="store_true",
        help="Call Analyze.RunAnalysis before extracting. Off by default "
        "(assumes the model is already analyzed).",
    )
    parser.add_argument(
        "--no-csv",
        action="store_true",
        help="Return DataFrames without writing CSV files.",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="After a successful --extract base run, render plan-view (x-y) "
        "figures of the base reactions (one PNG per load) into the output dir. "
        "Requires matplotlib; ignored (error) for --extract frame.",
    )
    parser.add_argument(
        "--plot-csv",
        metavar="PATH",
        help="Standalone: read a base-reaction CSV (e.g. all_base_reactions.csv), "
        "render plan-view figures into its parent dir, and exit. Requires no "
        "model/COM, so it works in WSL without ETABS. If given alongside model "
        "args, this wins and exits before any COM connection.",
    )
    parser.add_argument(
        "--plot-format",
        default="png",
        metavar="FMT",
        help="Image format for --plot / --plot-csv (default: png; e.g. png, pdf, svg).",
    )
    parser.add_argument(
        "--units",
        default="model",
        metavar="UNIT",
        help="Unit system for plot display: 'model'/'data' (default; display "
        "the CSV/DataFrame's own units unconverted — the units the "
        "extraction was run with, read from its force_unit/length_unit "
        "columns), a named preset (kN-m, kN-mm, N-mm, tonf-m, kgf-m), or any "
        "'<force>-<length>' pair (e.g. tonf-mm). Applies to --plot and "
        "--plot-csv.",
    )
    parser.add_argument(
        "--tag",
        metavar="NAME",
        help="Append `_NAME` to every CSV and plot filename; sanitized to a "
        "filesystem-safe suffix.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    from .config import resolve_model_path, resolve_output_dir
    from .results import (
        ExtractionError,
        extract_base_reactions,
        extract_forces,
        list_available,
    )

    # --plot-csv path: standalone CSV plotting, no COM/model.  Wins over any
    # model/COM args and exits before connecting (so it works in WSL without
    # ETABS and without a model path).
    if args.plot_csv:
        try:
            from .plots import plot_base_reactions_from_csv

            paths = plot_base_reactions_from_csv(
                args.plot_csv,
                fmt=args.plot_format,
                units=args.units,
                tag=args.tag,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[etabs_extractor] could not plot CSV: {exc}", file=sys.stderr)
            return 2
        print(f"Plotted {len(paths)} figure(s) from {args.plot_csv}:")
        for p in paths:
            print(f"  {p}")
        return 0

    model = resolve_model_path(args.model)
    if model is None:
        parser.error(
            "No model path available. Pass --model PATH or set the "
            "ETABS_MODEL environment variable."
        )

    # --list-only path: connectivity / inventory check.
    if args.list_only:
        try:
            info = list_available(
                str(model),
                attach=not args.launch,
                launch=args.launch,
            )
        except Exception as exc:  # noqa: BLE001
            # COM/nonexistent-model surfaced cleanly.
            print(f"[etabs_extractor] could not list model: {exc}", file=sys.stderr)
            return 2

        print(f"Model path : {info['model_path']}")
        print(f"Frame objs : {len(info['frame_names'])}")
        print(f"Point objs : {len(info.get('point_names', []))}")
        print(f"Combos     : {len(info['combos'])} -> {', '.join(info['combos'])}")
        print(f"Load cases : {len(info['cases'])} -> {', '.join(info['cases'])}")
        units = info.get("units") or {}
        if units.get("force") and units.get("length"):
            print(f"Units      : {units['force']}, {units['length']}")
        elevations = info.get("elevations") or []
        if elevations:
            print(f"Elevations : {len(elevations)}")
            for e in elevations:
                label = f" ({e['label']})" if e.get("label") else ""
                print(f"  z={e['z']:g}{label} -> {e['n_points']} point(s)")
        return 0

    # Extraction path.
    output_dir = None if args.no_csv else str(resolve_output_dir(args.output))
    try:
        if args.extract == "base":
            df, per_load, _records = extract_base_reactions(
                str(model),
                output_dir,
                combos=args.combos,
                cases=args.cases,
                all_requested=args.all,
                attach=not args.launch,
                launch=args.launch,
                run_analysis=args.run_analysis,
                points=args.points,
                elevation=args.elevation,
                only_loaded=args.only_loaded,
                tag=args.tag,
                force_unit=args.force_unit,
                length_unit=args.length_unit,
            )
            print(
                f"Extracted {len(df)} base-reaction rows across "
                f"{len(per_load)} load name(s)."
            )
            if args.plot:
                # Plotting needs a real directory regardless of --no-csv
                # (--no-csv only disables CSV *writing*).
                plot_dir = str(resolve_output_dir(args.output))
                try:
                    from .plots import plot_base_reactions

                    plot_paths = plot_base_reactions(
                        df, plot_dir, fmt=args.plot_format, units=args.units,
                        tag=args.tag,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[etabs_extractor] plotting failed (CSVs still written): {exc}",
                        file=sys.stderr,
                    )
                    return 3
                print(f"Plotted {len(plot_paths)} base-reaction figure(s):")
                for p in plot_paths:
                    print(f"  {p}")
        else:
            if args.plot:
                parser.error("--plot applies to --extract base only.")
            df, per_load, _records = extract_forces(
                str(model),
                output_dir,
                combos=args.combos,
                cases=args.cases,
                all_requested=args.all,
                attach=not args.launch,
                launch=args.launch,
                run_analysis=args.run_analysis,
                frames=args.frames,
                tag=args.tag,
                force_unit=args.force_unit,
                length_unit=args.length_unit,
            )
            print(
                f"Extracted {len(df)} rows across {len(per_load)} load name(s)."
            )
    except (ExtractionError, RuntimeError) as exc:
        print(f"[etabs_extractor] extraction failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"[etabs_extractor] unexpected error: {exc}", file=sys.stderr)
        return 3

    if output_dir and not args.plot:
        print(f"CSVs written to: {output_dir}")
    elif not output_dir and not args.plot:
        print("CSV writing disabled (--no-csv); DataFrames returned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
