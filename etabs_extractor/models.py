"""Data model for frame-force and base-reaction extraction results.

Defines small, dependency-light record types plus helpers that turn a
collection of records into a pandas DataFrame with a fixed, documented
column order.  This module is pure Python (no COM / Windows imports) so it
is usable from the stub-based dry run and tests on any platform.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Iterable, cast

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class FrameForceRecord:
    """One frame-object internal-force result at one output station.

    Force/length values are reported in whatever unit system the extraction
    was asked for (``force_unit`` / ``length_unit``, e.g. ``"kN"`` /
    ``"mm"``); by default that is the active ETABS model's own present
    units, read live via ``EtabsSession.get_present_units()`` (see
    ``results._source_units`` / ``etabs_extractor.units``) — **not** a
    hardcoded assumption. Moments share the length unit (e.g. ``"kN·m"``).
    """

    # Element identity
    frame: str            # frame object name (e.g. "B1", "C2")
    section: str          # assigned frame section name ("" if unknown)
    station: float        # distance from the object I-end (length units, mm)

    # Load / analysis context
    load_name: str        # load case or combination name
    load_kind: str        # "COMBO" or "CASE"

    # Internal forces (``force_unit``/``length_unit`` below)
    axial: float          # P  — axial force, +ve tension
    shear_2: float        # V2 — shear in local 2 direction
    shear_3: float        # V3 — shear in local 3 direction
    torsion: float        # T  — torsional moment
    moment_2: float       # M2 — moment about local 2 axis
    moment_3: float       # M3 — moment about local 3 axis

    # Optional bookkeeping (element labels, not required)
    length_mm: float | None = None  # Euclidean length of the frame object (length_unit); None when unknown
    obj_sta: float | None = None
    elm: str | None = None
    elm_sta: float | None = None

    # ETABS result step ("Max"/"Min" for envelope combos, "" for plain loads)
    step_type: str = ""

    # Unit system these force/length values were converted to (e.g. "kN" /
    # "mm"); "" only for records built before unit-awareness (legacy CSVs).
    force_unit: str = ""
    length_unit: str = ""

    def to_dict(self) -> dict:
        """Return an ordered dict suitable for CSV/DataFrame rows."""
        d = asdict(self)
        # Reorder: identity + load first, then forces, then optional columns.
        return {
            "frame": d["frame"],
            "section": d["section"],
            "station": d["station"],
            "load_name": d["load_name"],
            "load_kind": d["load_kind"],
            "step_type": d["step_type"],
            "P": d["axial"],
            "V2": d["shear_2"],
            "V3": d["shear_3"],
            "T": d["torsion"],
            "M2": d["moment_2"],
            "M3": d["moment_3"],
            "length_mm": d["length_mm"],
            "obj_sta": d["obj_sta"],
            "elm": d["elm"],
            "elm_sta": d["elm_sta"],
            "force_unit": d["force_unit"],
            "length_unit": d["length_unit"],
        }


# Fixed, documented column order for the consolidated DataFrame / CSVs.
COLUMNS = [
    "frame",
    "section",
    "station",
    "load_name",
    "load_kind",
    "step_type",
    "P",
    "V2",
    "V3",
    "T",
    "M2",
    "M3",
    "length_mm",
    "obj_sta",
    "elm",
    "elm_sta",
    "force_unit",
    "length_unit",
]


def to_dataframe(records: Iterable[FrameForceRecord]) -> "pd.DataFrame":
    """Convert records to a pandas DataFrame. Imports pandas lazily so the
    module stays importable where pandas is unavailable."""
    import pandas as pd  # noqa: PLC0415

    rows = [r.to_dict() for r in records]
    df = pd.DataFrame(rows, columns=COLUMNS)
    # Normalise dtypes where the columns exist and are numeric.
    for col in ("station", "P", "V2", "V3", "T", "M2", "M3", "obj_sta", "elm_sta"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def summarize_envelope(df: "pd.DataFrame") -> "pd.DataFrame":
    """Return per-(frame, load_name) min/max envelope columns for the force
    components in ``df``.  The source DataFrame is untouched."""
    import pandas as pd  # noqa: PLC0415

    if df is None or len(df) == 0:
        return pd.DataFrame([])

    force_cols = ["P", "V2", "V3", "T", "M2", "M3"]
    keys = ["frame", "load_name"]
    out: dict[tuple, dict] = {}

    for key_tuple, grp in df.groupby(keys, dropna=False):
        # ``key_tuple`` is the (frame, load_name) group key in ``keys`` order.
        frame, load_name = cast(tuple[Any, Any], key_tuple)
        key = (frame, load_name)
        row: dict = {"frame": frame, "load_name": load_name}
        for col in force_cols:
            if col in grp.columns:
                row[f"{col}_min"] = grp[col].min()
                row[f"{col}_max"] = grp[col].max()
        for col in ("force_unit", "length_unit"):
            if col in grp.columns:
                row[col] = grp[col].iloc[0]
        out[key] = row

    return pd.DataFrame(list(out.values()))


@dataclass
class JointReactionRecord:
    """One per-joint (point-object) reaction result from ``Results.JointReact``.

    ``F1/F2/F3`` are reaction forces and ``M1/M2/M3`` are reaction moments in
    the model's global axes, converted to whatever unit system the extraction
    was asked for (``force_unit`` / ``length_unit``, e.g. ``"kN"`` / ``"m"``)
    — by default the active model's own present units (see
    ``results._source_units``), not a hardcoded assumption.  ``x/y/z`` are
    the point's global coordinates in ``length_unit``; ``z`` is the
    elevation.  Coordinates are ``None`` when the point object could
    not be resolved (kept as ``NaN`` in the DataFrame rather than raising).
    """

    # Reaction point identity
    point: str            # point/joint object name (e.g. "1", "2", ...)
    x: float | None       # global X coordinate (length units)
    y: float | None       # global Y coordinate (length units)
    z: float | None       # global Z coordinate / elevation (length units)

    # Load / analysis context
    load_name: str        # load case or combination name
    load_kind: str        # "COMBO" or "CASE"

    # Reaction forces / moments (``force_unit``/``length_unit`` below, global axes)
    F1: float             # reaction force along global X
    F2: float             # reaction force along global Y
    F3: float             # reaction force along global Z
    M1: float             # reaction moment about global X
    M2: float             # reaction moment about global Y
    M3: float             # reaction moment about global Z

    # ETABS result step ("Max"/"Min" for envelope combos, "" for plain loads)
    step_type: str = ""

    # Unit system these force/length values were converted to (e.g. "kN" /
    # "m"); "" only for records built before unit-awareness (legacy CSVs).
    force_unit: str = ""
    length_unit: str = ""

    def to_dict(self) -> dict:
        """Return an ordered dict suitable for CSV/DataFrame rows."""
        d = asdict(self)
        return {
            "point": d["point"],
            "x": d["x"],
            "y": d["y"],
            "z": d["z"],
            "load_name": d["load_name"],
            "load_kind": d["load_kind"],
            "step_type": d["step_type"],
            "F1": d["F1"],
            "F2": d["F2"],
            "F3": d["F3"],
            "M1": d["M1"],
            "M2": d["M2"],
            "M3": d["M3"],
            "force_unit": d["force_unit"],
            "length_unit": d["length_unit"],
        }


# Fixed, documented column order for the base-reaction DataFrame / CSVs.
BASE_COLUMNS = [
    "point",
    "x",
    "y",
    "z",
    "load_name",
    "load_kind",
    "step_type",
    "F1",
    "F2",
    "F3",
    "M1",
    "M2",
    "M3",
    "force_unit",
    "length_unit",
]

BASE_FORCE_COLS = ["F1", "F2", "F3", "M1", "M2", "M3"]

BASE_COORD_COLS = ["x", "y", "z"]


def to_base_dataframe(records: Iterable[JointReactionRecord]) -> "pd.DataFrame":
    """Convert base-reaction records to a pandas DataFrame (lazy pandas)."""
    import pandas as pd  # noqa: PLC0415

    rows = [r.to_dict() for r in records]
    df = pd.DataFrame(rows, columns=BASE_COLUMNS)
    # Force/moment columns are always numeric; coordinates may be NaN where a
    # point coordinate could not be resolved, kept nullable for downstream
    # filtering on "known z" rather than coerced to 0.0.
    for col in BASE_FORCE_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in BASE_COORD_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def summarize_base_envelope(df: "pd.DataFrame") -> "pd.DataFrame":
    """Return per-(point, load_name) min/max envelope for F/M components.

    Groups the reaction DataFrame by ``(point, load_name)`` and emits one row
    per group with ``_min``/``_max`` columns for each force/moment component.
    The source DataFrame is untouched.
    """
    import pandas as pd  # noqa: PLC0415

    if df is None or len(df) == 0:
        return pd.DataFrame([])

    force_cols = BASE_FORCE_COLS
    keys = ["point", "load_name"]
    out: dict[tuple, dict] = {}

    for key_tuple, grp in df.groupby(keys, dropna=False):
        point, load_name = cast(tuple[Any, Any], key_tuple)
        key = (point, load_name)
        row: dict = {"point": point, "load_name": load_name}
        for col in force_cols:
            if col in grp.columns:
                row[f"{col}_min"] = grp[col].min()
                row[f"{col}_max"] = grp[col].max()
        for col in ("force_unit", "length_unit"):
            if col in grp.columns:
                row[col] = grp[col].iloc[0]
        out[key] = row

    return pd.DataFrame(list(out.values()))


def summarize_base_envelope_minmax(df: "pd.DataFrame") -> tuple["pd.DataFrame", "pd.DataFrame"]:
    """Return separated per-(point, load_name) MIN and MAX envelope DataFrames.

    Calls :func:`summarize_base_envelope` once and splits the result into the
    ``_min``-column subset and the ``_max``-column subset.  Columns are
    ``["point", "load_name"] + [f"{c}_min", ...]`` and the ``_max`` analogue.
    Empty input yields two empty DataFrames with the correct columns.
    """
    import pandas as pd  # noqa: PLC0415

    unit_cols = ["force_unit", "length_unit"]
    env = summarize_base_envelope(df)
    if len(env) == 0:
        min_cols = ["point", "load_name"] + [f"{c}_min" for c in BASE_FORCE_COLS] + unit_cols
        max_cols = ["point", "load_name"] + [f"{c}_max" for c in BASE_FORCE_COLS] + unit_cols
        return pd.DataFrame(columns=min_cols), pd.DataFrame(columns=max_cols)

    min_cols = ["point", "load_name"] + [f"{c}_min" for c in BASE_FORCE_COLS] + unit_cols
    max_cols = ["point", "load_name"] + [f"{c}_max" for c in BASE_FORCE_COLS] + unit_cols
    min_df = cast("pd.DataFrame", env[[c for c in min_cols if c in env.columns]])
    max_df = cast("pd.DataFrame", env[[c for c in max_cols if c in env.columns]])
    return min_df, max_df