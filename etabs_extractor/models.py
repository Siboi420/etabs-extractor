"""Data model for frame-force and base-reaction extraction results.

Defines small, dependency-light record types plus helpers that turn a
collection of records into a pandas DataFrame with a fixed, documented
column order.  This module is pure Python (no COM / Windows imports) so it
is usable from the stub-based dry run and tests on any platform.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import TYPE_CHECKING, Any, Iterable, cast

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class FrameForceRecord:
    """One frame-object internal-force result at one output station.

    All scalar force components are kept in the model's native units
    (``N`` for axial/shear, ``N.mm`` for moments — the model is N/mm).
    No unit conversion is performed.
    """

    # Element identity
    frame: str            # frame object name (e.g. "B1", "C2")
    section: str          # assigned frame section name ("" if unknown)
    station: float        # distance from the object I-end (length units, mm)

    # Load / analysis context
    load_name: str        # load case or combination name
    load_kind: str        # "COMBO" or "CASE"

    # Internal forces (model units)
    axial: float          # P  — axial force (N), +ve tension
    shear_2: float        # V2 — shear in local 2 direction (N)
    shear_3: float        # V3 — shear in local 3 direction (N)
    torsion: float        # T  — torsional moment (N.mm)
    moment_2: float       # M2 — moment about local 2 axis (N.mm)
    moment_3: float       # M3 — moment about local 3 axis (N.mm)

    # Optional bookkeeping (element labels, not required)
    obj_sta: float | None = None
    elm: str | None = None
    elm_sta: float | None = None

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
            "P": d["axial"],
            "V2": d["shear_2"],
            "V3": d["shear_3"],
            "T": d["torsion"],
            "M2": d["moment_2"],
            "M3": d["moment_3"],
            "obj_sta": d["obj_sta"],
            "elm": d["elm"],
            "elm_sta": d["elm_sta"],
        }


# Fixed, documented column order for the consolidated DataFrame / CSVs.
COLUMNS = [
    "frame",
    "section",
    "station",
    "load_name",
    "load_kind",
    "P",
    "V2",
    "V3",
    "T",
    "M2",
    "M3",
    "obj_sta",
    "elm",
    "elm_sta",
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
        out[key] = row

    return pd.DataFrame(list(out.values()))


@dataclass
class JointReactionRecord:
    """One per-joint (point-object) reaction result from ``Results.JointReact``.

    ``F1/F2/F3`` are reaction forces and ``M1/M2/M3`` are reaction moments in
    the model's global axes (model units: N / N.mm), matching ETABS output.
    ``x/y/z`` are the point's global coordinates (length units, e.g. mm); ``z``
    is the elevation.  Coordinates are ``None`` when the point object could
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

    # Reaction forces / moments (model units, global axes)
    F1: float             # reaction force along global X (N)
    F2: float             # reaction force along global Y (N)
    F3: float             # reaction force along global Z (N)
    M1: float             # reaction moment about global X (N.mm)
    M2: float             # reaction moment about global Y (N.mm)
    M3: float             # reaction moment about global Z (N.mm)

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
            "F1": d["F1"],
            "F2": d["F2"],
            "F3": d["F3"],
            "M1": d["M1"],
            "M2": d["M2"],
            "M3": d["M3"],
        }


# Fixed, documented column order for the base-reaction DataFrame / CSVs.
BASE_COLUMNS = [
    "point",
    "x",
    "y",
    "z",
    "load_name",
    "load_kind",
    "F1",
    "F2",
    "F3",
    "M1",
    "M2",
    "M3",
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

    env = summarize_base_envelope(df)
    if len(env) == 0:
        min_cols = ["point", "load_name"] + [f"{c}_min" for c in BASE_FORCE_COLS]
        max_cols = ["point", "load_name"] + [f"{c}_max" for c in BASE_FORCE_COLS]
        return pd.DataFrame(columns=min_cols), pd.DataFrame(columns=max_cols)

    min_cols = ["point", "load_name"] + [f"{c}_min" for c in BASE_FORCE_COLS]
    max_cols = ["point", "load_name"] + [f"{c}_max" for c in BASE_FORCE_COLS]
    min_df = cast("pd.DataFrame", env[[c for c in min_cols if c in env.columns]])
    max_df = cast("pd.DataFrame", env[[c for c in max_cols if c in env.columns]])
    return min_df, max_df
