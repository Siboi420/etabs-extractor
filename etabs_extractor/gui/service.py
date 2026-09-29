"""Pure mapping from :class:`GuiSettings` to the underlying library calls.

This module contains **no imports of Tk or matplotlib at module level** and
never touches COM directly — it simply decides, given a
:class:`~etabs_extractor.gui.state.GuiSettings`, which library functions to
invoke with which arguments.  It is therefore testable headlessly (pure
Python) and keeps all real work in the existing ``models`` / ``results`` /
``plots`` / ``connection`` layers.
"""

from __future__ import annotations

from pathlib import Path

from etabs_extractor.gui.state import (
    GuiSettings,
    parse_elevation,
)
from etabs_extractor.io import _sanitize_filename
from etabs_extractor.plots import COMPONENT_COLUMNS


def build_mode_kwargs(settings: GuiSettings) -> dict:
    """Return the keyword args for the active extraction mode's library call.

    ``base`` -> :func:`extract_base_reactions` kwargs (today's mapping);
    ``frame`` -> :func:`extract_forces` kwargs with ``frames``/``sections``.
    """
    if settings.extract_mode == "frame":
        combos = settings.selected_combos or None
        cases = settings.selected_cases or None
        return {
            "model_path": settings.model_path or None,
            "output_dir": settings.output_dir or None,
            "combos": combos,          # empty/None -> all model combos
            "cases": cases,
            "frames": settings.selected_frames or None,
            "sections": settings.selected_sections or None,
            "run_analysis": settings.run_analysis,
            "attach": settings.attach,
            "launch": not settings.attach,
            "tag": settings.tag or None,
            "force_unit": settings.force_unit,
            "length_unit": settings.length_unit,
        }
    return {
        "model_path": settings.model_path or None,
        "output_dir": settings.output_dir or None,
        "combos": settings.selected_combos or None,
        "cases": settings.selected_cases or None,
        "elevation": (
            parse_elevation(settings.elevation)
            if settings.elevation.strip()
            else None
        ),
        "only_loaded": settings.only_loaded,
        "run_analysis": settings.run_analysis,
        "attach": settings.attach,
        "launch": not settings.attach,
        "tag": settings.tag or None,
        "force_unit": settings.force_unit,
        "length_unit": settings.length_unit,
    }


def build_extract_kwargs(settings: GuiSettings) -> dict:
    """Return the keyword arguments for the extracted library call of the
    active mode (backwards-compatible alias of :func:`build_mode_kwargs`)."""
    return build_mode_kwargs(settings)


def _label_components(settings: GuiSettings) -> tuple[str, ...]:
    """Ticked label components in canonical COMPONENT_COLUMNS order."""
    return tuple(c for c in COMPONENT_COLUMNS if c in (settings.label_components or []))


def build_plot_kwargs(settings: GuiSettings) -> dict:
    """Return the keyword arguments for ``plot_base_reactions``."""
    figsize = None
    if not settings.dynamic_size:
        figsize = (settings.fig_width, settings.fig_height)
    return {
        "fmt": settings.format,
        "units": settings.units,
        "label_fontsize": settings.label_fontsize,
        "dynamic_size": settings.dynamic_size,
        "figsize": figsize,
        "dpi": settings.dpi,
        "x_offset": settings.x_offset,
        "y_offset": settings.y_offset,
        "label_dx": settings.label_dx,
        "label_dy": settings.label_dy,
        "components": _label_components(settings),
        "tag": settings.tag or None,
    }


def build_figure_kwargs(settings: GuiSettings) -> dict:
    """Return the kwargs for ``build_base_reactions_figure`` (preview)."""
    figsize = None
    if not settings.dynamic_size:
        figsize = (settings.fig_width, settings.fig_height)
    return {
        "units": settings.units,
        "label_fontsize": settings.label_fontsize,
        "dynamic_size": settings.dynamic_size,
        "figsize": figsize,
        "x_offset": settings.x_offset,
        "y_offset": settings.y_offset,
        "label_dx": settings.label_dx,
        "label_dy": settings.label_dy,
        "components": _label_components(settings),
    }


def build_elevation_labels(
    elevations: list[dict], model_length: str, length_unit: str
) -> list[str]:
    """Format a model's elevation inventory (see
    :func:`~etabs_extractor.results.list_elevations`, values in the model's
    own length unit) into combobox labels displayed in ``length_unit``
    (``"model"``/``""`` means no conversion).

    E.g. ``{"z": -18550.0, "label": "Base", "n_points": 42}`` with
    ``model_length="mm"``, ``length_unit="m"`` -> ``"-18.55  (Base, 42 pts)"``.
    """
    from etabs_extractor.units import LENGTH_TO_M

    src = model_length or "mm"
    dst = src if length_unit in (None, "", "model") else length_unit
    scale = LENGTH_TO_M.get(src, 1.0) / LENGTH_TO_M.get(dst, 1.0)
    labels = []
    for e in elevations:
        z = e["z"] * scale
        label = e.get("label") or ""
        n = e.get("n_points", 0)
        suffix = f"{label}, {n} pts" if label else f"{n} pts"
        labels.append(f"{z:g}  ({suffix})")
    return labels


def sanitize_tag(tag: str) -> str:
    """Sanitize a tag the same way filename stems are sanitized (see
    ``io._sanitize_filename``).  Used to preview the effective suffix."""
    if not tag or not tag.strip():
        return ""
    return _sanitize_filename(tag)


def do_extract(settings: GuiSettings) -> dict:
    """Run a full extract workflow and return a result dict.

    Dispatches on ``settings.extract_mode``: ``base`` calls
    ``results.extract_base_reactions`` (+ optional plot); ``frame`` calls
    ``results.extract_forces`` and never plots (plot stays base-only). Returns:

    ``{"df": DataFrame, "per_load": dict, "records": list,
        "output_dir": str|None, "tag": str, "load_names": list[str],
        "plot_paths": list[Path]}``
    """
    kwargs = build_extract_kwargs(settings)

    if settings.extract_mode == "frame":
        from etabs_extractor.results import extract_forces

        df, per_load, records = extract_forces(**kwargs)
        return {
            "df": df,
            "per_load": per_load,
            "records": records,
            "output_dir": kwargs.get("output_dir"),
            "tag": kwargs.get("tag"),
            "load_names": list(per_load.keys()) if per_load else [],
            "plot_paths": [],
        }

    from etabs_extractor.results import extract_base_reactions

    df, per_load, records = extract_base_reactions(**kwargs)

    plot_paths = []
    output_dir = kwargs.get("output_dir")
    if settings.plot_after_extract and output_dir is not None and df is not None and len(df) > 0:
        from etabs_extractor.plots import plot_base_reactions

        plot_paths = plot_base_reactions(
            df, output_dir, **build_plot_kwargs(settings)
        )

    return {
        "df": df,
        "per_load": per_load,
        "records": records,
        "output_dir": output_dir,
        "tag": kwargs.get("tag"),
        "load_names": list(per_load.keys()) if per_load else [],
        "plot_paths": plot_paths,
    }


def load_from_csv(settings: GuiSettings) -> dict:
    """Read an existing base CSV into a result dict (no ETABS required).

    Returns the same shape as :func:`do_extract` with ``df`` populated from
    the CSV (and ``records`` empty), so the caller can treat both sources
    uniformly for previewing/plotting.
    """
    import pandas as pd

    csv_path = (settings.csv_path or "").strip()
    if not csv_path:
        raise ValueError("No CSV file selected.")

    df = pd.read_csv(csv_path, encoding="utf-8")
    per_load = {str(name): grp for name, grp in df.groupby("load_name", sort=True)}

    plot_paths = []
    if settings.plot_after_extract:
        from etabs_extractor.plots import plot_base_reactions_from_csv

        plot_paths = plot_base_reactions_from_csv(
            csv_path,
            (settings.plot_output_dir or "").strip() or None,
            **{k: v for k, v in build_plot_kwargs(settings).items()
               if k in ("fmt", "units", "label_fontsize", "dynamic_size",
                        "figsize", "dpi", "tag", "label_dx", "label_dy",
                        "components")},
        )

    return {
        "df": df,
        "per_load": per_load,
        "records": [],
        "output_dir": None,
        "tag": settings.tag or None,
        "load_names": list(per_load.keys()),
        "plot_paths": plot_paths,
    }


def save_batch_plots(result: dict, settings: GuiSettings) -> list[Path]:
    """Save absmax/max/min plan plots for every load of ``result`` (pure-ish,
    no COM — calls ``plots.plot_base_reactions``; safe on a background thread).

    Target directory: the sidebar's **Batch plot dir**; when blank it falls
    back to the Output dir for an extraction result, or the Plot output dir
    (else the CSV's parent) for a CSV-loaded result.  Returns the non-empty
    written paths.
    """
    from etabs_extractor.plots import plot_base_reactions

    df = result.get("df")
    if df is None or len(df) == 0:
        raise ValueError("No extraction/CSV result loaded to plot.")

    steps = tuple(settings.plot_steps)
    if not steps:
        raise ValueError(
            "No plot steps selected — tick at least one of Abs max / Max / Min."
        )

    target = (settings.batch_plot_dir or "").strip()
    if not target:
        if result.get("output_dir"):
            # Extraction result: fall back to the extraction's output dir.
            target = (settings.output_dir or str(result["output_dir"])).strip()
        else:
            # CSV-loaded result: Plot output dir, else the CSV's parent.
            target = (settings.plot_output_dir or "").strip()
            if not target and (settings.csv_path or "").strip():
                target = str(Path(settings.csv_path.strip()).parent)
    if not target:
        raise ValueError(
            "No batch plot directory: set Batch plot dir (or Output / Plot "
            "output dir)."
        )

    paths = plot_base_reactions(
        df, target, steps=steps, **build_plot_kwargs(settings)
    )
    return [p for p in paths if str(p)]


def check_active_model(attach: bool = True, session=None) -> str:
    """Return the active model filename from a (connected or injected) ETABS
    session.

    When ``session`` is ``None`` a real COM session is attached (or launched
    when ``attach`` is False); otherwise the provided duck-typed session (e.g.
    a test fake) is used directly.  Uses ``EtabsSession.get_model_filename``;
    no model path is required.  Returns the full model path string (may be
    empty)."""
    return inspect_active_model(attach=attach, session=session)['model_path']


def inspect_active_model(attach: bool = True, session=None) -> dict:
    """Attach (or reuse) an ETABS session and return the active model's
    inventory: ``{"model_path", "combos", "cases", "sections", "frames",
    "units", "elevations"}``.

    When ``session`` is ``None`` a real COM session is attached (or launched
    when ``attach`` is False); otherwise the provided duck-typed session (e.g.
    a test fake) is used directly.  Reads ``get_model_filename`` /
    ``get_combo_names`` / ``get_case_names``, plus best-effort
    ``get_frame_section_names`` / ``get_frame_names`` / ``get_present_units``
    / :func:`~etabs_extractor.results.list_elevations` (each degrades to
    ``[]``/``{}`` rather than failing the whole check)."""
    from etabs_extractor.connection import EtabsSession

    own = session is None
    if own:
        session = EtabsSession.connect(attach=attach, launch=not attach)
    try:
        info = {
            "model_path": str(session.get_model_filename(include_path=True)),
            "combos": list(session.get_combo_names() or []),
            "cases": list(session.get_case_names() or []),
        }
        for key, meth in (
            ("sections", "get_frame_section_names"),
            ("frames", "get_frame_names"),
        ):
            try:
                info[key] = list(getattr(session, meth)() or [])
            except Exception as exc:  # noqa: BLE001 - best-effort inventory
                import logging
                logging.getLogger(__name__).debug(
                    "Could not list %s: %s", key, exc
                )
                print(f"[etabs_extractor] Could not list {key}: {exc}")
                info[key] = []
        try:
            units = session.get_present_units()
            info["units"] = {"force": units.force, "length": units.length}
        except Exception as exc:  # noqa: BLE001 - best-effort units
            import logging
            logging.getLogger(__name__).debug("Could not read present units: %s", exc)
            info["units"] = {"force": "", "length": ""}
        try:
            from etabs_extractor.results import list_elevations

            info["elevations"] = list_elevations(session)
        except Exception as exc:  # noqa: BLE001 - best-effort elevation list
            import logging
            logging.getLogger(__name__).debug("Could not list elevations: %s", exc)
            info["elevations"] = []
        return info
    except Exception as exc:
        raise RuntimeError(f"Could not inspect active model: {exc}") from exc
    finally:
        if own:
            try:
                session.helper = None
            except Exception as exc:  # noqa: BLE001 - best-effort cleanup
                import logging
                logging.getLogger(__name__).debug(
                    "Could not release ETABS helper: %s", exc
                )
