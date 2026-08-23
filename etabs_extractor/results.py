"""Core extraction orchestration for etabs_extractor.

This module ties together the connection and data-model layers: it talks to
an :class:`~etabs_extractor.connection.EtabsSession` (a real COM session on
Windows, or a fake in tests), selects the requested load combinations / load
cases, walks every frame object, reads internal forces via
``FrameForce``, and assembles :class:`FrameForceRecord` objects.

The orchestrating functions here are deliberately written against the small
duck-typed surface of :class:`EtabsSession` so the same code path runs
against a live ETABS instance and against the synthetic test stub.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Iterable

from .config import resolve_model_path, to_windows_path
from .models import FrameForceRecord, JointReactionRecord

if TYPE_CHECKING:
    from .connection import EtabsSession

logger = logging.getLogger(__name__)

# Base-reaction export unit conversion.  ETABS reports reaction forces in N and
# reaction moments in N·mm (model units); the base-reaction export converts
# them to kN (÷1000) and kN·m (÷1e6) at record construction so the DataFrame
# and every CSV carry the converted values.  Coordinates (x/y/z) are NOT
# converted and stay in the model's length units (mm).
BASE_FORCE_SCALE = 1000.0   # N   -> kN
BASE_MOMENT_SCALE = 1e6     # N·mm -> kN·m


class ExtractionError(RuntimeError):
    """Raised for user-facing extraction failures (missing model, no names)."""


def _connect_session(
    session: "EtabsSession | None",
    model_path: str | None,
    *,
    attach: bool,
    launch: bool,
) -> tuple["EtabsSession", bool]:
    """Resolve the model path and establish (or reuse) an ETABS session.

    Returns ``(session, own_session)`` where ``own_session`` is True when this
    helper created the session (so the caller must tear it down).  When a
    ``session`` is passed (e.g. the test fake), it is used directly and no
    COM connection is attempted.
    """
    from .connection import EtabsSession

    model = resolve_model_path(model_path)
    if model is None:
        raise ExtractionError(
            "No model path given. Pass model_path / --model or set the "
            "ETABS_MODEL environment variable."
        )

    own_session = session is None
    if own_session:
        session = EtabsSession.connect(
            attach=attach,
            launch=launch,
            model_path=to_windows_path(str(model)),
        )

    if session is None:  # pragma: no cover - defensive
        raise ExtractionError("Failed to establish an ETABS session.")
    return session, own_session


# Optional per-combo extraction is grouped by load_name for the dict output.
def _release_helper(session: "EtabsSession | None") -> None:
    """Best-effort tear-down of a session helper we created (no-op on fakes).

    Attribute removal on a COM wrapper can raise transiently (e.g. connection
    already closed); we intentionally swallow that so cleanup is never fatal.
    """
    if session is None:
        return
    try:
        session.helper = None
    except Exception as exc:  # noqa: BLE001 - best-effort cleanup
        # Attribute removal on a COM wrapper can raise transiently (e.g. the
        # connection is already closed); log instead of silently swallowing.
        logger.debug("Could not release ETABS session helper: %s", exc)


def _records_where(records: Iterable[FrameForceRecord], load_name: str) -> list[FrameForceRecord]:
    return [r for r in records if r.load_name == load_name]


def _resolve_names(
    *,
    combos: list[str] | None,
    cases: list[str] | None,
    session: "EtabsSession",
    all_requested: bool,
) -> tuple[list[str] | None, list[str] | None]:
    """Resolve which combos/cases to extract.

    * ``all_requested`` → both all combos and all cases.
    * ``combos`` set → combos only (default scope per project decision).
    * ``cases`` set → cases only.
    * otherwise (neither set, not all) → combinations only (model default).

    Returns ``(combos_to_use, cases_to_use)``.  ``None`` for a stream means
    that stream is skipped.
    """
    if all_requested:
        return (session.get_combo_names(), session.get_case_names())
    if cases is not None and combos is not None:
        # Both streams explicitly requested: extract both (previously cases
        # superseded combos).
        return (combos, cases)
    if cases is not None:
        return (None, cases)
    # Default scope: combinations only.
    if combos is None:
        combos = session.get_combo_names()
    return (combos, None)


def _read_frame_forces(
    session: "EtabsSession",
    frame: str,
    combos: list[str] | None,
    cases: list[str] | None,
    section_map: dict,
) -> list[FrameForceRecord]:
    """Read forces for a single frame across the selected combos/cases.

    Selection is applied per whole-model via setup calls in the caller; here
    we rely on the COM ``FrameForce`` item-type=0 (Object) returning all
    selected load names for this frame at once.
    """
    raw = session.frame_force(frame, item_type_elm=0)
    if raw is None:
        return []

    (
        NumberResults, Obj, ObjSta, Elm, ElmSta, LoadCase, StepType, StepNum,
        P, V2, V3, T, M2, M3,
    ) = raw

    section = section_map.get(frame, "")

    records: list[FrameForceRecord] = []
    # NumberResults is a COM by-ref scalar; coerce via len for list-like
    # values (safety) and int otherwise.
    n = _to_int(NumberResults, default=0)
    for i in range(max(0, n)):
        name = str(LoadCase[i])
        # Distinguish combo vs case by membership in the resolved lists.
        if combos is not None and name in combos:
            kind = "COMBO"
        elif cases is not None and name in cases:
            kind = "CASE"
        else:
            # Fall back to the default kind by which stream is active.
            kind = "COMBO" if combos is not None else "CASE"

        records.append(
            FrameForceRecord(
                frame=frame,
                section=section,
                station=_f(ObjSta, i, default=0.0),
                load_name=name,
                load_kind=kind,
                axial=_f(P, i),
                shear_2=_f(V2, i),
                shear_3=_f(V3, i),
                torsion=_f(T, i),
                moment_2=_f(M2, i),
                moment_3=_f(M3, i),
                obj_sta=_f_optional(ObjSta, i),
                elm=str(Elm[i]) if Elm is not None and i < len(Elm) else None,
                elm_sta=_f_optional(ElmSta, i),
            )
        )
    return records


def _to_int(value, default: int = 0) -> int:
    """Null-safe coercion of a COM by-ref count to ``int``.

    ``NumberResults`` is a COM by-ref scalar that may come back as an int,
    a one-element sequence, ``None``, or (defensively) a non-numeric string.
    Any of those coerce to ``default`` rather than raising.
    """
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        if len(value) == 0:
            return default
        value = value[0]
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _f(seq, i, default: float = 0.0) -> float:
    """Null-safe numeric coercion of ``seq[i]`` to ``float``.

    COM output arrays may contain Python ``None`` for missing stations;
    those coerce to ``default`` rather than raising.
    """
    if seq is None or i >= len(seq):
        return default
    try:
        val = seq[i]
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError, IndexError):
        return default


def _f_optional(seq, i) -> "float | None":
    """Nullable variant: returns ``None`` when the slot is absent/missing."""
    if seq is None or i >= len(seq):
        return None
    try:
        val = seq[i]
        if val is None:
            return None
        return float(val)
    except (TypeError, ValueError, IndexError):
        return None


def _s(seq, i) -> str:
    """Null-safe string coercion of ``seq[i]`` to ``str``.

    COM output arrays may contain ``None`` / short segments for missing
    stations; those coerce to ``""`` rather than raising (mirrors ``_f``).
    """
    if seq is None or i >= len(seq):
        return ""
    try:
        val = seq[i]
        if val is None:
            return ""
        return str(val)
    except (TypeError, ValueError, IndexError):
        return ""


def _step_key(step_type: str) -> str:
    """Normalise an ETABS StepType value for Min/Max split-file partitioning.

    Returns ``"max"`` / ``"min"`` (lowercased, stripped) for envelope steps;
    any other value (``""``, ``"Step By Step"``, ...) returns ``""`` so the
    row stays only in the mixed per-load file.
    """
    key = (step_type or "").strip().lower()
    return key if key in ("max", "min") else ""


def _z_match(z: float, target: float, tol: float = 1.0) -> bool:
    """Return True when a coordinate ``z`` equals ``target`` within tolerance.

    ETABS coordinates can carry tiny floating-point noise (e.g.
    ``4210.0000000002``), and combo names are exact, so we compare with a small
    absolute tolerance rather than exact equality.  ``tol`` is in the model's
    length units (mm for this project).
    """
    try:
        return abs(float(z) - float(target)) <= tol
    except (TypeError, ValueError):
        return False


def _is_null_reaction(r: JointReactionRecord, tol: float = 1e-9) -> bool:
    """Return True when a reaction record carries no load in any component.

    Used by ``only_loaded`` filtering to drop supports whose six reaction
    components are all (effectively) zero.  ``tol`` is in the model's force /
    moment units and defaults small to tolerate float noise while still
    treating genuinely-null supports as zero.
    """
    return all(
        abs(getattr(r, attr)) <= tol
        for attr in ("F1", "F2", "F3", "M1", "M2", "M3")
    )


def extract_forces(
    model_path: str | None = None,
    output_dir: str | None = None,
    *,
    combos: list[str] | None = None,
    cases: list[str] | None = None,
    all_requested: bool = False,
    attach: bool = True,
    launch: bool = False,
    run_analysis: bool = False,
    frames: list[str] | None = None,
    session: "EtabsSession | None" = None,
    tag: str | None = None,
) -> tuple:
    """Extract frame-element forces and (optionally) write CSVs.

    Returns ``(consolidated_DataFrame, {load_name: DataFrame}, list[record])``.
    When ``output_dir`` is provided, per-load CSVs and ``all_forces.csv``
    (plus an envelope summary) are written to it.

    If a ``session`` is passed (e.g. the test fake), it is used directly and
    no COM connection is attempted; otherwise one is created.
    """
    import pandas as pd  # noqa: PLC0415

    from .io import write_all_forces_csv, write_csv, write_envelope_csv
    from .models import to_dataframe

    session, own_session = _connect_session(
        session, model_path, attach=attach, launch=launch
    )

    try:
        combos_use, cases_use = _resolve_names(
            combos=combos,
            cases=cases,
            session=session,
            all_requested=all_requested,
        )

        if combos_use is None and cases_use is None:
            raise ExtractionError("Nothing selected to extract (enable combos and/or cases).")

        if combos_use is not None and cases_use is not None:
            if not combos_use and not cases_use:
                raise ExtractionError(
                    "Nothing selected to extract (enable combos and/or cases)."
                )
            session.setup_select_loads(combos_use, cases_use)
        elif combos_use is not None:
            if not combos_use:
                raise ExtractionError(
                    "Combination list is empty; model has no load combinations "
                    "(confirm combos are defined in the ETABS model)."
                )
            session.setup_select_combos(combos_use)
        elif cases_use is not None:
            if not cases_use:
                raise ExtractionError(
                    "Load-case list is empty; model has no load cases "
                    "(confirm cases are defined in the ETABS model)."
                )
            session.setup_select_cases(cases_use)

        if run_analysis:
            session.run_analysis()

        frame_names = session.get_frame_names()
        if not frame_names:
            raise ExtractionError("Model contains no frame objects to extract.")
        # Optional filter.
        if frames:
            frame_names = [f for f in frame_names if f in set(frames)]

        section_map = {f: session.get_section_for_frame(f) for f in frame_names}

        all_records: list[FrameForceRecord] = []
        for frame in frame_names:
            all_records.extend(
                _read_frame_forces(session, frame, combos_use, cases_use, section_map)
            )

        consolidated = to_dataframe(all_records)

        # Group by load_name for the dict output.
        grouped: dict[str, list[FrameForceRecord]] = {}
        for r in all_records:
            grouped.setdefault(r.load_name, []).append(r)

        per_load: dict[str, object] = {}
        for name, recs in grouped.items():
            per_load[name] = to_dataframe(recs)

        if output_dir:
            for name, recs in grouped.items():
                kind = recs[0].load_kind if recs else "COMBO"
                write_csv(recs, output_dir, name, load_kind=kind, tag=tag)
            write_all_forces_csv(all_records, output_dir, tag=tag)
            write_envelope_csv(all_records, output_dir, tag=tag)

        return consolidated, per_load, all_records

    finally:
        if own_session:
            # Tear down the helper we created (best effort; no-op on fakes).
            _release_helper(session)


def _read_point_reactions(
    session: "EtabsSession",
    point: str,
    combos: list[str] | None,
    cases: list[str] | None,
    coords: tuple,
) -> list[JointReactionRecord]:
    """Read per-joint reactions for a single point across the selected loads.

    ``combos``/``cases`` discriminate each row's ``load_kind`` exactly as in
    ``_read_frame_forces`` (by membership in the resolved lists).
    """
    raw = session.joint_react(point, item_type_elm=0)
    if raw is None:
        return []

    (
        NumberResults, Obj, Elm, LoadCase, StepType, StepNum,
        F1, F2, F3, M1, M2, M3,
    ) = raw

    x, y, z = coords
    records: list[JointReactionRecord] = []
    n = _to_int(NumberResults, default=0)
    for i in range(max(0, n)):
        name = str(LoadCase[i])
        if combos is not None and name in combos:
            kind = "COMBO"
        elif cases is not None and name in cases:
            kind = "CASE"
        else:
            kind = "COMBO" if combos is not None else "CASE"

        records.append(
            JointReactionRecord(
                point=point,
                x=x,
                y=y,
                z=z,
                load_name=name,
                load_kind=kind,
                step_type=_s(StepType, i),
                # Convert model units (N / N·mm) to exported units (kN / kN·m).
                F1=_f(F1, i) / BASE_FORCE_SCALE,
                F2=_f(F2, i) / BASE_FORCE_SCALE,
                F3=_f(F3, i) / BASE_FORCE_SCALE,
                M1=_f(M1, i) / BASE_MOMENT_SCALE,
                M2=_f(M2, i) / BASE_MOMENT_SCALE,
                M3=_f(M3, i) / BASE_MOMENT_SCALE,
            )
        )
    return records


def extract_base_reactions(
    model_path: str | None = None,
    output_dir: str | None = None,
    *,
    combos: list[str] | None = None,
    cases: list[str] | None = None,
    all_requested: bool = False,
    attach: bool = True,
    launch: bool = False,
    run_analysis: bool = False,
    points: list[str] | None = None,
    elevation: float | None = None,
    only_loaded: bool = False,
    session: "EtabsSession | None" = None,
    tag: str | None = None,
) -> tuple:
    """Extract per-joint (base) reactions and (optionally) write CSVs.

    Reports restrained point objects. By default every point at any elevation
    is reported; pass ``elevation`` to restrict to points whose ``z``
    coordinate matches that elevation (model length units, e.g. ``-16000``),
    which skips reading any other level.  Pass ``only_loaded=True`` to drop
    points where all six reaction components are zero (i.e. only supports that
    actually carry load).  Returns
    ``(consolidated_DataFrame, {load_name: DataFrame}, list[record])`` mirroring
    :func:`extract_forces`.  When ``output_dir`` is provided, per-load CSVs
    (``base_<load>.csv``), ``all_base_reactions.csv``, ``base_envelope_summary.csv``
    and the separated ``base_envelope_min.csv`` / ``base_envelope_max.csv``.  A
    ``tag`` appends a suffix to every output filename.
    """
    import pandas as pd  # noqa: PLC0415

    from .io import (
        write_all_base_csv,
        write_base_csv,
        write_base_envelope_csv,
        write_base_envelope_max_csv,
        write_base_envelope_min_csv,
    )
    from .models import to_base_dataframe

    session, own_session = _connect_session(
        session, model_path, attach=attach, launch=launch
    )

    try:
        combos_use, cases_use = _resolve_names(
            combos=combos,
            cases=cases,
            session=session,
            all_requested=all_requested,
        )

        if combos_use is None and cases_use is None:
            raise ExtractionError("Nothing selected to extract (enable combos and/or cases).")

        if combos_use is not None and cases_use is not None:
            if not combos_use and not cases_use:
                raise ExtractionError(
                    "Nothing selected to extract (enable combos and/or cases)."
                )
            session.setup_select_loads(combos_use, cases_use)
        elif combos_use is not None:
            if not combos_use:
                raise ExtractionError(
                    "Combination list is empty; model has no load combinations "
                    "(confirm combos are defined in the ETABS model)."
                )
            session.setup_select_combos(combos_use)
        elif cases_use is not None:
            if not cases_use:
                raise ExtractionError(
                    "Load-case list is empty; model has no load cases "
                    "(confirm cases are defined in the ETABS model)."
                )
            session.setup_select_cases(cases_use)

        if run_analysis:
            session.run_analysis()

        point_names = session.get_point_names()
        if not point_names:
            raise ExtractionError("Model contains no point objects to extract.")
        # Optional name filter.
        if points:
            point_names = [p for p in point_names if p in set(points)]

        all_records: list[JointReactionRecord] = []
        for point in point_names:
            try:
                coords = session.get_point_coords(point)
            except Exception as exc:  # noqa: BLE001 - coordinates are best-effort
                logger.debug("Point coordinate lookup failed for %r: %s", point, exc)
                coords = (None, None, None)
            # Optional elevation filter — skip points not on the requested level
            # (avoids reading reactions for every other joint).
            if elevation is not None:
                z = coords[2]
                if z is None or not _z_match(z, elevation):
                    continue
            recs = _read_point_reactions(session, point, combos_use, cases_use, coords)
            all_records.extend(recs)

        # Optional: keep only points that carry load (any component non-zero).
        if only_loaded:
            all_records = [
                r for r in all_records
                if not _is_null_reaction(r)
            ]

        consolidated = to_base_dataframe(all_records)

        # Group by load_name for the dict output.
        grouped: dict[str, list[JointReactionRecord]] = {}
        for r in all_records:
            grouped.setdefault(r.load_name, []).append(r)

        per_load: dict[str, object] = {}
        for name, recs in grouped.items():
            per_load[name] = to_base_dataframe(recs)

        if output_dir:
            from .io import write_base_step_csv

            for name, recs in grouped.items():
                kind = recs[0].load_kind if recs else "COMBO"
                write_base_csv(recs, output_dir, name, load_kind=kind, tag=tag)
                # Per-load MIN/MAX split files: partition this load's rows by
                # ETABS StepType ("Max"/"Min"); rows with any other step stay
                # only in the mixed per-load file.  A split file is written
                # only when it has at least one row.
                for step_key in ("min", "max"):
                    split = [r for r in recs if _step_key(r.step_type) == step_key]
                    if split:
                        write_base_step_csv(
                            split, output_dir, name, load_kind=kind, step=step_key, tag=tag
                        )
            write_all_base_csv(all_records, output_dir, tag=tag)
            write_base_envelope_csv(all_records, output_dir, tag=tag)
            write_base_envelope_min_csv(all_records, output_dir, tag=tag)
            write_base_envelope_max_csv(all_records, output_dir, tag=tag)

        return consolidated, per_load, all_records

    finally:
        if own_session:
            # Best-effort release of the helper we created (no-op on fakes).
            _release_helper(session)


def list_available(
    model_path: str | None = None,
    *,
    attach: bool = True,
    launch: bool = False,
    session: "EtabsSession | None" = None,
) -> dict:
    """Attach (or use a provided session) and return model inventory.

    Returns a dict with ``frame_names``, ``combos``, ``cases``, and the
    resolved model path.  Used chiefly as a COM connectivity check.
    """
    session, own_session = _connect_session(
        session, model_path, attach=attach, launch=launch
    )

    try:
        info = {
            "model_path": str(resolve_model_path(model_path)),
            "frame_names": session.get_frame_names(),
            "combos": session.get_combo_names(),
            "cases": session.get_case_names(),
        }
        try:
            info["point_names"] = session.get_point_names()
        except Exception as exc:  # noqa: BLE001 - best-effort point inventory
            logger.debug("Could not list point objects: %s", exc)
            info["point_names"] = []
        return info
    finally:
        if own_session:
            # Best-effort release of the helper we created (no-op on fakes).
            _release_helper(session)
