"""Plan-view plotting of extracted base reactions.

Renders x-y scatter figures of the base-reaction DataFrame (columns from
:data:`etabs_extractor.models.BASE_COLUMNS`), annotating each support point
with its reaction component values (Fx, Fy, Fz, M2, M3 by default).  This
module is **pure Python** — it never touches COM or Windows — and imports
matplotlib **lazily** (inside functions), so it remains importable on any
platform even where matplotlib is absent.

Two entry points mirror the two run modes:

* :func:`plot_base_reactions` — plot from an in-memory DataFrame (used right
  after ``--extract base``).
* :func:`plot_base_reactions_from_csv` — read a base-reaction CSV and plot,
  with **no model/COM** (usable in WSL on a machine without ETABS).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from matplotlib.figure import Figure

from .io import _append_tag, _sanitize_filename

logger = logging.getLogger(__name__)

# Default reaction components shown in each point's annotation label.
# Each maps to an ETABS base-reaction column and a display unit.
# The current default preserves the vertical reaction Fz plus the two tilting
# moments (M2, M3); the horizontal shear components Fx/Fy are intentionally
# omitted for a cleaner figure.
DEFAULT_COMPONENTS: tuple[str, ...] = ("Fz", "M2", "M3")

# Friendly component name -> DataFrame column.  Fx/Fy/Fz map to F1/F2/F3.
COMPONENT_COLUMNS: dict[str, str] = {
    "Fx": "F1",
    "Fy": "F2",
    "Fz": "F3",
    "M1": "M1",  # available for future inclusion; not in DEFAULT_COMPONENTS
    "M2": "M2",
    "M3": "M3",
}

# Friendly component name -> display unit (base reactions are exported in
# kN / kN·m, so these are the default display units; no further conversion).
COMPONENT_UNITS: dict[str, str] = {
    "Fx": "kN",
    "Fy": "kN",
    "Fz": "kN",
    "M1": "kN·m",
    "M2": "kN·m",
    "M3": "kN·m",
}

# Supported unit systems.  Each carries the display units and the divisor used
# to convert the already-exported base-reaction values (kN for forces, kN·m
# for moments, mm for coordinates) into the display units.
#   force_scale:  kN     -> target force unit   (divisor)
#   moment_scale: kN·m   -> target moment unit  (divisor)
#   length_scale: mm     -> target length unit  (divisor)
# Force/moment scaling is identity (1.0) in both systems — the values are
# already exported as kN / kN·m — so only length_scale (mm -> m) differs.
UNITS: dict[str, dict[str, object]] = {
    # Exported units (default): kN / kN·m / mm, no further conversion.
    "model": {
        "force": "kN",
        "moment": "kN·m",
        "length": "mm",
        "force_scale": 1.0,
        "moment_scale": 1.0,
        "length_scale": 1.0,
    },
    # kN / m: forces/moments already kN/kN·m (unchanged), coords mm->m (÷1000).
    "kN-m": {
        "force": "kN",
        "moment": "kN·m",
        "length": "m",
        "force_scale": 1.0,
        "moment_scale": 1.0,
        "length_scale": 1000.0,
    },
}

DEFAULT_UNITS = "model"

_REQUIRED_DATAFRAME_COLUMNS = ("x", "y", "load_name")

# Friendly component name -> dimension ("force" or "moment") for unit scaling.
_COMPONENT_DIMENSIONS: dict[str, str] = {
    "Fx": "force",
    "Fy": "force",
    "Fz": "force",
    "M1": "moment",
    "M2": "moment",
    "M3": "moment",
}


def plot_base_reactions(
    df,
    output_dir,
    *,
    components: Sequence[str] | None = None,
    load_name: str | None = None,
    fmt: str = "png",
    title: str | None = None,
    units: str = DEFAULT_UNITS,
    label_fontsize: float = 2.4,
    dynamic_size: bool = True,
    figsize: tuple[float, float] | None = None,
    dpi: int = 800,
    x_offset: float = 1.0,
    y_offset: float = 1.0,
    tag: str | None = None,
) -> list[Path]:
    """Render plan-view (x-y) figures of base reactions and save them.

    :param df: base-reaction DataFrame (``x, y, load_name`` plus the selected
        component columns; see :data:`etabs_extractor.models.BASE_COLUMNS`).
    :param output_dir: directory to write the figure(s) into.
    :param components: friendly component names to annotate (default
        :data:`DEFAULT_COMPONENTS`).  Each must be a key of
        :data:`COMPONENT_COLUMNS`.
    :param load_name: when given, plot only this single load; otherwise one
        figure is produced per unique ``load_name`` value.
    :param fmt: image format (e.g. ``png``, ``pdf``, ``svg``).
    :param title: override the figure title.  When ``None``, the title is the
        ``load_name`` (plus ``z = <value> mm`` when every point shares one ``z``).
    :param units: unit system for display — ``"model"`` (default; kN, kN·m, mm)
        or ``"kN-m"`` (kN, kN·m, m — coordinates mm→m).  Base reactions are
        already exported in kN/kN·m, so forces/moments are not rescaled; only
        the coordinate length unit differs between the two systems.  Keys must
        exist in :data:`UNITS`.
    :param label_fontsize: font size (points) for each point's annotation
        label.  Defaults to ``2.4`` (about 0.2\u00d7 the previous "small" ~10pt
        labels) for a compact figure.
    :param dynamic_size: when True (default) the figure size follows the
        plotted data's extent (see :func:`_dynamic_figsize`); when False the
        fixed ``figsize`` (in inches) is used instead.
    :param figsize: fixed figure size in inches, used only when
        ``dynamic_size=False`` (default ``(10, 8)``).
    :param dpi: save resolution in dots-per-inch (passed to ``savefig``;
        default ``800``).
    :param x_offset: edge-label padding (inches): extra room added to the x
        axis limits on each side (on top of matplotlib's normal 5% margins),
        so point labels near the plot edges render inside the axes box (the
        box border never cuts through a label).  Default ``1.0``.
    :param y_offset: edge-label padding (inches): extra room added to the y
        axis limits on each side.  Default ``1.0``.
    :param tag: optional suffix appended to each plotted file stem (e.g.
        ``KM13`` -> ``base_<load>_plan_KM13.png``).  Absent/empty = no suffix.
    :returns: the list of written :class:`Path` objects.
    """
    import matplotlib  # noqa: PLC0415
    import matplotlib.pyplot as plt  # noqa: PLC0415

    comps = tuple(components) if components is not None else DEFAULT_COMPONENTS
    _validate_components(comps)
    units_def = _resolve_units(units)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    if load_name is not None:
        single = df[df["load_name"] == load_name]
        written.append(
            _plot_one(single, out, load_name, comps, fmt=fmt, title=title,
                      units_def=units_def, label_fontsize=label_fontsize,
                      dynamic_size=dynamic_size, figsize=figsize, dpi=dpi,
                      x_offset=x_offset, y_offset=y_offset, tag=tag)
        )
        return written

    for name, grp in df.groupby("load_name", sort=True, dropna=False):
        written.append(
            _plot_one(grp, out, str(name), comps, fmt=fmt, title=title,
                      units_def=units_def, label_fontsize=label_fontsize,
                      dynamic_size=dynamic_size, figsize=figsize, dpi=dpi,
                      x_offset=x_offset, y_offset=y_offset, tag=tag)
        )
    return written


def plot_base_reactions_from_csv(
    csv_path,
    output_dir=None,
    *,
    components: Sequence[str] | None = None,
    fmt: str = "png",
    title: str | None = None,
    units: str = DEFAULT_UNITS,
    label_fontsize: float = 2.4,
    dynamic_size: bool = True,
    figsize: tuple[float, float] | None = None,
    dpi: int = 800,
    x_offset: float = 1.0,
    y_offset: float = 1.0,
    tag: str | None = None,
) -> list[Path]:
    """Read a base-reaction CSV and plot it (no model / COM required).

    :param csv_path: path to a base CSV (e.g. ``all_base_reactions.csv`` or a
        ``base_<load>.csv``).  Required columns: ``x, y, load_name`` plus the
        selected component columns.
    :param output_dir: where to write figures; defaults to the CSV's parent.
    :param units: unit system for display (see :func:`plot_base_reactions`).
    :param tag: optional suffix appended to each figure filename stem.
    :returns: the list of written :class:`Path` objects.
    :raises ValueError: when required columns are missing from the CSV.
    """
    import pandas as pd  # noqa: PLC0415

    comps = tuple(components) if components is not None else DEFAULT_COMPONENTS
    df = pd.read_csv(csv_path, encoding="utf-8")
    _validate_columns(df, comps)

    target = Path(output_dir) if output_dir is not None else Path(csv_path).parent
    return plot_base_reactions(df, target, components=comps, fmt=fmt,
                               title=title, units=units,
                               label_fontsize=label_fontsize,
                               dynamic_size=dynamic_size, figsize=figsize,
                               dpi=dpi, x_offset=x_offset, y_offset=y_offset,
                               tag=tag)


def _validate_components(comps: Sequence[str]) -> None:
    """Validate that every requested component maps to a known DataFrame column."""
    unknown = [c for c in comps if c not in COMPONENT_COLUMNS]
    if unknown:
        raise ValueError(
            f"Unknown reaction component(s): {unknown}. Known: "
            f"{', '.join(COMPONENT_COLUMNS)}."
        )


def _validate_columns(df, comps: Sequence[str]) -> None:
    """Validate that ``df`` has the coordinate/load columns plus the requested
    component columns."""
    missing = [c for c in _REQUIRED_DATAFRAME_COLUMNS if c not in df.columns]
    for comp in comps:
        col = COMPONENT_COLUMNS[comp]
        if col not in df.columns:
            missing.append(col)
    if missing:
        raise ValueError(
            f"Base DataFrame/CSV is missing required column(s): {missing}. "
            f"Expected at least {list(_REQUIRED_DATAFRAME_COLUMNS)} and the "
            f"selected component columns."
        )


def build_base_reactions_figure(
    df,
    load_name: str,
    *,
    components: Sequence[str] | None = None,
    title: str | None = None,
    units: str | dict = DEFAULT_UNITS,
    label_fontsize: float = 2.4,
    dynamic_size: bool = True,
    figsize: tuple[float, float] | None = None,
    x_offset: float = 1.0,
    y_offset: float = 1.0,
) -> "Figure | None":
    """Build (but **do not** save) one plan-view figure for a single load.

    This is the reusable drawing step shared by :func:`_plot_one` (which saves
    the figure) and the GUI preview (which embeds the figure in a canvas).  It
    draws the scatter, annotations, title and axes for ``df`` (which should
    hold exactly one ``load_name``'s rows) into a fresh :mod:`matplotlib`
    figure and returns it.  Returns ``None`` when there are no plottable
    points (unresolved x/y) for this load.  The returned figure is **open**
    and must be closed (``plt.close(fig)``) by the caller when done.

    :param df: base-reaction DataFrame for a single load.
    :param load_name: the load name used for the default title.
    :param components: friendly component names to annotate (default
        :data:`DEFAULT_COMPONENTS`).
    :param title: override the figure title; ``None`` derives it from the load
        name (plus a shared ``z`` when every point shares one).
    :param units: unit system for display (``"model"`` or ``"kN-m"``).
    :param label_fontsize: annotation font size (points).
    :param dynamic_size: when True, size the figure from the data extent;
        otherwise use the fixed ``figsize`` (inches).
    :param figsize: fixed figure size in inches for ``dynamic_size=False``
        (default ``(10, 8)``).
    :param x_offset: edge-label padding (inches): extra room added to the x
        axis limits on each side (on top of matplotlib's normal 5% margins),
        so labels near the plot edges render inside the axes box (the box
        border never cuts through a label).  Default ``1.0``; ``0`` removes
        the padding.
    :param y_offset: edge-label padding (inches): extra room added to the y
        axis limits on each side.  Default ``1.0``.
    """
    import matplotlib  # noqa: PLC0415
    import matplotlib.pyplot as plt  # noqa: PLC0415

    comps = tuple(components) if components is not None else DEFAULT_COMPONENTS
    _validate_components(comps)
    units_def = _resolve_units(units)

    # Skip points with unresolved coordinates; never crash.  (x/y come from
    # the DataFrame where unresolvable coords were kept as NaN.)
    valid = df[df["x"].notna() & df["y"].notna()]
    if len(valid) == 0:
        logger.warning("No plottable points for load %r; skipping figure.", load_name)
        return None

    # One per-point label: for envelope loads a point may appear in several
    # rows (e.g. Max/Min envelope steps).  Keep, per component, the row whose
    # value has the largest absolute magnitude (sign preserved).
    valid = _aggregate_maxabs(valid, comps)

    len_scale = _scale(units_def, "length_scale")
    len_unit = str(units_def["length"])

    base_size = (_dynamic_figsize(valid, len_scale) if dynamic_size
                 else (figsize or (10, 8)))
    # The canvas is exactly the base size — offsets never inflate it.
    fig, ax = plt.subplots(figsize=base_size)

    ax.scatter(valid["x"] / len_scale, valid["y"] / len_scale,
               s=20, color="tab:blue", zorder=3)
    ax.set_aspect("equal", adjustable="box")

    # Optional title enrichment: if every point shares one z, show it.
    used_title = title if title is not None else _build_title(
        df, load_name, units_def)
    if used_title:
        ax.set_title(used_title)

    ax.set_xlabel(f"X ({len_unit})")
    ax.set_ylabel(f"Y ({len_unit})")
    ax.grid(True, linestyle=":", alpha=0.6)

    for _, row in valid.iterrows():
        label = _format_label(row, comps, units_def)
        ax.annotate(
            label,
            (row["x"] / len_scale, row["y"] / len_scale),
            xytext=(-6, -18),
            textcoords="offset points",
            fontsize=label_fontsize,
            family="monospace",
            bbox=dict(
                boxstyle="round,pad=0.1",
                fc="white",
                ec="gray",
                alpha=0.9,
            ),
            zorder=4,
            annotation_clip=False,
            clip_on=False,
        )

    # Fixed margins: the axes box always occupies the same fraction of the
    # canvas.  Edge-label room is created by expanding the axis limits below
    # (labels live INSIDE the axes box, so the box border never cuts through
    # them), not by inflating the canvas.
    fig.subplots_adjust(left=0.1, right=0.9, bottom=0.1, top=0.9)

    # Widen xlim/ylim by x_offset/y_offset inches of whitespace on each edge
    # (converted to data units via the equal-aspect scale), on top of
    # matplotlib's normal auto margins, so labels near the plot edges render
    # inside the axes box.
    if x_offset > 0 or y_offset > 0:
        _pad_axis_limits(ax, fig, valid, x_offset, y_offset, len_scale)
    return fig


def _pad_axis_limits(ax, fig, df, x_offset: float, y_offset: float,
                     len_scale: float) -> None:
    """Expand the axes limits by ``x_offset`` / ``y_offset`` inches of
    whitespace on each edge, **on top of** matplotlib's normal auto margins.

    The offsets stay in **inches** (matching the GUI fields): the current
    equal-aspect data scale (display units per inch of the axes box) converts
    them to data units, then ``xlim`` / ``ylim`` are widened so the padding
    sits *inside* the axes box.  Edge point labels therefore render inside
    the box instead of crossing its border.
    """
    xs = df["x"] / len_scale
    ys = df["y"] / len_scale
    xmin, xmax = xs.min(), xs.max()
    ymin, ymax = ys.min(), ys.max()
    xspan = xmax - xmin
    yspan = ymax - ymin
    if not (xspan > 0 and yspan > 0):
        # Degenerate plan (all points share an x or y); leave auto limits.
        return

    # Nominal axes box (inches) from the fixed subplots_adjust margins used in
    # build_base_reactions_figure (left/right/top/bottom 0.1 -> box = 0.8 of
    # the figure in each direction).
    w, h = fig.get_size_inches()
    box_w = w * 0.8
    box_h = h * 0.8
    # Equal aspect: one shared scale, set by whichever direction is tighter.
    scale = min(box_w / xspan, box_h / yspan)  # display units per inch

    pad_x = x_offset / scale if scale > 0 else 0.0
    pad_y = y_offset / scale if scale > 0 else 0.0
    # Keep matplotlib's default 5% auto margins and add the offset padding on
    # top, so any positive offset strictly widens the limits vs. the
    # unpadded baseline.
    xmargin = 0.05 * xspan
    ymargin = 0.05 * yspan
    ax.set_xlim(xmin - xmargin - pad_x, xmax + xmargin + pad_x)
    ax.set_ylim(ymin - ymargin - pad_y, ymax + ymargin + pad_y)


def _plot_one(
    df,
    out_dir: Path,
    load_name: str,
    comps: Sequence[str],
    *,
    fmt: str,
    title: str | None,
    units_def: dict,
    label_fontsize: float,
    dynamic_size: bool = True,
    figsize: tuple[float, float] | None = None,
    dpi: int = 800,
    x_offset: float = 1.0,
    y_offset: float = 1.0,
    tag: str | None = None,
) -> Path:
    """Render one plan-view figure for a single load and save + close it."""
    import matplotlib  # noqa: PLC0415
    import matplotlib.pyplot as plt  # noqa: PLC0415

    comps_out = comps
    fig = build_base_reactions_figure(
        df, load_name, components=comps_out, title=title, units=units_def,
        label_fontsize=label_fontsize, dynamic_size=dynamic_size,
        figsize=figsize, x_offset=x_offset, y_offset=y_offset,
    )
    if fig is None:
        return Path()
    try:
        safe = _sanitize_filename(load_name)
        stem = f"base_{safe}_plan"
        # Step-aware naming: a subset with exactly one distinct non-empty step
        # (e.g. a MIN/MAX split CSV) gets ``_<step>`` before any tag, so
        # plotting both split files into one directory never overwrites
        # (``base_<load>_plan_min.png`` vs ``base_<load>_plan_max.png``).
        # Lowercased for the stem, matching the split CSV filenames.
        step = _single_step(df)
        if step:
            stem = f"{stem}_{_sanitize_filename(step.lower())}"
        path = out_dir / (_append_tag(stem, tag) + f".{fmt}")
        fig.savefig(path, dpi=dpi, bbox_inches="tight")
        return path
    finally:
        plt.close(fig)


def _dynamic_figsize(df, len_scale: float) -> tuple[float, float]:
    """Pick a figure size (inches) that follows the plotted data's extent.

    Since the plot uses ``aspect='equal'``, x and y share one scale, so the
    figure's width:height should match the data's x:y spread.  The longer
    data dimension is mapped to a base length, then scaled up as the plan
    grows, bounded so extreme shapes stay readable.

    Returns ``(width, height)`` in inches.
    """
    xs = df["x"].dropna() / len_scale
    ys = df["y"].dropna() / len_scale

    xmin, xmax = xs.min(), xs.max()
    ymin, ymax = ys.min(), ys.max()
    xspan = (xmax - xmin) or 1.0
    yspan = (ymax - ymin) or 1.0

    # Base length (inches) for the longer data axis; grows with the plan size.
    base = 8.0
    span = max(xspan, yspan)
    # Longer axis -> more inches; cap so a huge spread doesn't explode.
    longer_in = min(base * (1.0 + 0.12 * span / base), 20.0)
    ratio = yspan / xspan

    if ratio >= 1.0:
        height = longer_in
        width = longer_in / ratio
    else:
        width = longer_in
        height = longer_in * ratio

    # Enforce a minimum canvas so labels stay legible even for tiny plans.
    width = max(width, 6.0)
    height = max(height, 5.0)
    return round(width, 2), round(height, 2)


def _aggregate_maxabs(df, comps: Sequence[str]):
    """Reduce a per-point multi-row frame to one row per coordinate.

    Envelope combos emit a point several times (e.g. one row per Max/Min
    envelope step).  For each requested component, keep the value with the
    largest absolute magnitude (sign preserved), so a single label shows the
    "governing" value rather than every step.  Coordinates (x/y) survive as
    the grouping key.  Rows with the same coordinate are merged.
    """
    import pandas as pd  # noqa: PLC0415

    comp_cols = [COMPONENT_COLUMNS[c] for c in comps]
    keep = [c for c in comp_cols if c in df.columns]

    rows = []
    for (xi, yi), grp in df.groupby(["x", "y"], sort=False, dropna=False):
        rec: dict = {"x": xi, "y": yi}
        # Preserve the point name (first non-null) for label tracing.
        if "point" in df.columns:
            for v in grp["point"].tolist():
                if _isna(v):
                    continue
                rec["point"] = v
                break
        for col in keep:
            # Collect all numeric values for this component at this coordinate
            # (None/NaN handled safely).
            nums: list[float] = []
            for v in grp[col].tolist():
                if _isna(v):
                    continue
                try:
                    nums.append(float(v))
                except (TypeError, ValueError):
                    continue
            if not nums:
                # No usable value; None becomes NaN in the DataFrame.
                rec[col] = None
                continue
            # Largest absolute value, keeping its sign.
            rec[col] = max(nums, key=abs)
        rows.append(rec)

    if not rows:
        return df.iloc[0:0]
    return pd.DataFrame(rows)


def _build_title(df, load_name: str, units_def: dict) -> str:
    """Build a default figure title showing load name plus a shared z (if any).

    When the frame holds exactly one distinct non-empty ``step_type`` (e.g. a
    MIN/MAX split CSV loaded via ``--plot-csv``), the step is appended in
    parentheses (``ASD Max (Min)``)."""
    step = _single_step(df)
    base = f"{load_name} ({step})" if step else load_name
    z_vals = df["z"].dropna().unique() if "z" in df.columns else []
    if len(z_vals) == 1:
        z = z_vals[0]
        len_unit = str(units_def["length"])
        len_scale = _scale(units_def, "length_scale")
        try:
            return f"{base}  (z = {float(z) / len_scale:g} {len_unit})"
        except (TypeError, ValueError):
            return base
    return base


def _single_step(df) -> str | None:
    """Return the single distinct non-empty ``step_type`` value of ``df``.

    Makes plotting step-aware for the per-load MIN/MAX split CSVs: a subset
    holding exactly one step (e.g. a ``base_combo_<load>_min.csv`` read by
    ``plot_base_reactions_from_csv`` / ``--plot-csv``) gets the step in the
    figure title and filename stem.  Returns ``None`` for multi-step or
    stepless frames (legacy behavior, unchanged filenames)."""
    if "step_type" not in df.columns:
        return None
    steps: set[str] = set()
    for v in df["step_type"].tolist():
        if _isna(v):
            continue
        s = str(v).strip()
        if s:
            steps.add(s)
    if len(steps) == 1:
        return next(iter(steps))
    return None


def _format_label(row, comps: Sequence[str], units_def: dict) -> str:
    """Format a point's annotation text: the point name (bare number, when
    present), then one line per component ``Name=value unit`` (values scaled
    to the target unit system)."""
    lines = []
    # First line: the point/joint number for tracing (omitted defensively if
    # missing/null).
    if not _isna(row.get("point")):
        lines.append(str(row["point"]))
    for comp in comps:
        col = COMPONENT_COLUMNS[comp]
        val = row[col]
        dim = _COMPONENT_DIMENSIONS[comp]
        if dim == "force":
            unit = str(units_def["force"])
            scale = _scale(units_def, "force_scale")
        else:
            unit = str(units_def["moment"])
            scale = _scale(units_def, "moment_scale")
        if _isna(val):
            lines.append(f"{comp}=n/a")
            continue
        try:
            scaled = float(val) / scale
            lines.append(f"{comp}={_fmt_plain(scaled)} {unit}")
        except (TypeError, ValueError):
            lines.append(f"{comp}=n/a")
    return "\n".join(lines)


def _fmt_plain(value: float) -> str:
    """Format ``value`` to ~3 significant figures without scientific notation.

    The default ``:g`` / ``:.3g`` switches to exponent form (``1e+04``) for
    large or tiny magnitudes.  This formats in fixed notation so labels stay
    plain (``12300`` not ``1.23e+04``), while still trimming to a useful
    number of decimals for small values (e.g. ``0.0123``).
    """
    try:
        if value == 0:
            return "0"
        # Number of significant figures we want.
        sig = 3
        # Decimal places needed for `sig` sig-figs in fixed notation.
        import math  # noqa: PLC0415

        if value < 0:
            dec = max(0, int(math.ceil(-math.log10(abs(value)))) + sig - 1)
            return f"{value:.{dec}f}"
        dec = max(0, int(math.ceil(-math.log10(value))) + sig - 1)
        return f"{value:.{dec}f}"
    except (TypeError, ValueError, OverflowError):
        return str(value)


def _resolve_units(units: str | dict) -> dict:
    """Return the unit system dict for ``units``.

    Accepts either a unit-system name (``"model"`` / ``"kN-m"``, validated
    against :data:`UNITS`) or an already-resolved unit dict (pass-through).
    """
    if isinstance(units, dict):
        return units
    if units not in UNITS:
        raise ValueError(
            f"Unknown unit system {units!r}. Known: {', '.join(UNITS)}."
        )
    return UNITS[units]


def _scale(units_def: dict, key: str) -> float:
    """Null-safe read of a scale factor from a unit-system dict.

    Falls back to ``1.0`` (no scaling) for a missing/invalid value instead of
    raising, mirroring the ``_f`` null-safe coercion used elsewhere."""
    try:
        return float(units_def.get(key, 1.0))
    except (TypeError, ValueError):
        return 1.0


def _isna(val) -> bool:
    """Null-check a single scalar value without importing pandas eagerly.

    ``None`` and NaN-like values (float NaN / numpy nan) count as missing.
    """
    try:
        return val is None or val != val  # NaN != NaN
    except (TypeError, ValueError):
        return False


__all__ = [
    "DEFAULT_COMPONENTS",
    "COMPONENT_COLUMNS",
    "COMPONENT_UNITS",
    "DEFAULT_UNITS",
    "UNITS",
    "plot_base_reactions",
    "plot_base_reactions_from_csv",
    "build_base_reactions_figure",
]