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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .config import resolve_model_path, to_windows_path
from .io import (
    write_all_base_csv,
    write_all_forces_csv,
    write_base_csv,
    write_base_envelope_csv,
    write_base_envelope_max_csv,
    write_base_envelope_min_csv,
    write_base_step_csv,
    write_csv,
    write_envelope_csv,
    write_frame_step_csv,
)
from .models import (
    FrameForceRecord,
    JointReactionRecord,
    to_base_dataframe,
    to_dataframe,
)
from .units import LEGACY_FRAME, LENGTH_TO_M, UnitSystem, factors, resolve_target

if TYPE_CHECKING:
    from .connection import EtabsSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _UnitCtx:
    """Resolved unit-conversion context for one extraction run.

    ``force_factor`` / ``moment_factor`` / ``length_factor`` convert a value
    read from COM (in the model's own present units, ``src``) to the
    requested output units (``dst``): ``value_dst = value_src * factor``.
    Passed to every per-item reader so records carry both the converted
    values and the ``dst`` unit labels.
    """

    force_factor: float
    moment_factor: float
    length_factor: float
    src: UnitSystem
    dst: UnitSystem


def _source_units(session: "EtabsSession") -> UnitSystem:
    """Best-effort read of the active model's present units.

    Falls back to :data:`etabs_extractor.units.LEGACY_FRAME` (N, mm — the
    unit system this package used to hardcode) when the session has no
    ``get_present_units`` (e.g. an older test fake) or the COM call fails,
    so extraction still works, just without model-aware conversion.
    """
    try:
        return session.get_present_units()
    except Exception as exc:  # noqa: BLE001 - degrade to the legacy assumption
        logger.debug(
            "Could not read model present units, assuming legacy N/mm: %s", exc
        )
        return LEGACY_FRAME


def _resolve_unit_ctx(
    session: "EtabsSession", force_unit: str, length_unit: str
) -> _UnitCtx:
    """Resolve the source/target unit systems and conversion factors."""
    src = _source_units(session)
    dst = resolve_target(src, force_unit, length_unit)
    ff, mf, lf = factors(src, dst)
    return _UnitCtx(force_factor=ff, moment_factor=mf, length_factor=lf, src=src, dst=dst)


def _scale_opt(value: float | None, factor: float) -> float | None:
    """Scale an optional numeric value, passing ``None`` through unchanged."""
    return value * factor if value is not None else None


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


@dataclass(frozen=True)
class ExtractKind:
    """Everything that differs between extraction kinds (frame vs base).

    The shared driver :func:`_extract` owns connection, load selection, name
    filtering, reading, assembly and teardown; a kind supplies only the parts
    that genuinely differ.  Adding a new result type (e.g. wall forces) =
    add one ``ExtractKind`` (a reader + a CSV writer) and a thin public
    wrapper — ``_extract`` is untouched.
    """

    label: str            # used in the "no <label> objects" error message
    get_names: Callable   # (session) -> list[str]
    read: Callable        # (session, name, combos, cases, uctx: _UnitCtx) -> list[record]
    to_df: Callable       # (records) -> DataFrame
    write: Callable       # (records, grouped, output_dir, tag) -> None


def _select_loads(
    session: "EtabsSession",
    *,
    combos: list[str] | None,
    cases: list[str] | None,
    all_requested: bool,
) -> tuple[list[str] | None, list[str] | None]:
    """Resolve which combos/cases to extract and select them for output.

    Keeps the old per-stream dispatch semantics (combos-only / cases-only /
    both, with the same empty-list errors) but routes every branch through
    ``setup_select_loads`` — a single ``DeselectAll`` + both selections — so
    there is one COM code path.  Returns the resolved ``(combos_use,
    cases_use)``.
    """
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
        session.setup_select_loads(combos_use, [])
    elif cases_use is not None:
        if not cases_use:
            raise ExtractionError(
                "Load-case list is empty; model has no load cases "
                "(confirm cases are defined in the ETABS model)."
            )
        session.setup_select_loads([], cases_use)
    return combos_use, cases_use


def _assemble(records: list, to_df: Callable) -> tuple:
    """Consolidated DataFrame + per-load DataFrames + grouped records.

    Shared by every extraction kind; ``to_df`` is the kind's record→DataFrame
    converter (``to_dataframe`` / ``to_base_dataframe``).
    """
    grouped: dict[str, list] = {}
    for r in records:
        grouped.setdefault(r.load_name, []).append(r)
    consolidated = to_df(records)
    per_load = {name: to_df(recs) for name, recs in grouped.items()}
    return consolidated, per_load, grouped


def _extract(
    kind: ExtractKind,
    model_path: str | None = None,
    output_dir: str | None = None,
    *,
    combos: list[str] | None = None,
    cases: list[str] | None = None,
    all_requested: bool = False,
    attach: bool = True,
    launch: bool = False,
    run_analysis: bool = False,
    name_filter: list[str] | None = None,
    post_filter: Callable | None = None,
    session: "EtabsSession | None" = None,
    tag: str | None = None,
    force_unit: str = "model",
    length_unit: str = "model",
) -> tuple:
    """Shared extraction driver for every :class:`ExtractKind`.

    Owns the connection lifecycle, load selection, run-analysis, name
    filtering, per-item reads, optional post-filtering, DataFrame assembly
    and CSV writing.  ``name_filter`` restricts the object names to read
    (``--frames`` / ``--points``); ``post_filter`` optionally drops whole
    records before assembly (e.g. ``only_loaded``).  ``force_unit`` /
    ``length_unit`` select the output unit system (default ``"model"`` —
    the active model's own present units, read live via
    :meth:`EtabsSession.get_present_units`; no conversion applied). Returns
    ``(consolidated_DataFrame, {load_name: DataFrame}, list[record])`` — the
    shape every public extractor returns.
    """
    session, own_session = _connect_session(
        session, model_path, attach=attach, launch=launch
    )

    try:
        uctx = _resolve_unit_ctx(session, force_unit, length_unit)

        combos_use, cases_use = _select_loads(
            session, combos=combos, cases=cases, all_requested=all_requested
        )

        if run_analysis:
            session.run_analysis()

        names = kind.get_names(session)
        if not names:
            raise ExtractionError(
                f"Model contains no {kind.label} objects to extract."
            )
        if name_filter:
            names = [n for n in names if n in set(name_filter)]

        all_records: list = []
        for name in names:
            all_records.extend(kind.read(session, name, combos_use, cases_use, uctx))

        if post_filter is not None:
            all_records = post_filter(all_records)

        consolidated, per_load, grouped = _assemble(all_records, kind.to_df)

        if output_dir:
            kind.write(all_records, grouped, output_dir, tag)

        return consolidated, per_load, all_records

    finally:
        if own_session:
            _release_helper(session)


def _read_frame_forces(
    session: "EtabsSession",
    frame: str,
    combos: list[str] | None,
    cases: list[str] | None,
    uctx: _UnitCtx,
) -> list[FrameForceRecord]:
    """Read forces for a single frame across the selected combos/cases.

    Selection is applied per whole-model via setup calls in the caller; here
    we rely on the COM ``FrameForce`` item-type=0 (Object) returning all
    selected load names for this frame at once.  The section name is a
    best-effort per-frame lookup (one COM call per frame, as before).  Force
    /moment/length values are scaled from the model's units to ``uctx.dst``.
    """
    raw = session.frame_force(frame, item_type_elm=0)
    if raw is None:
        return []

    (
        NumberResults, Obj, ObjSta, Elm, ElmSta, LoadCase, StepType, StepNum,
        P, V2, V3, T, M2, M3,
    ) = raw

    section = session.get_section_for_frame(frame) or ""
    length_mm = _scale_opt(session.get_frame_length_mm(frame), uctx.length_factor)
    ff, mf, lf = uctx.force_factor, uctx.moment_factor, uctx.length_factor

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
                station=_f(ObjSta, i, default=0.0) * lf,
                length_mm=length_mm,
                load_name=name,
                load_kind=kind,
                axial=_f(P, i) * ff,
                shear_2=_f(V2, i) * ff,
                shear_3=_f(V3, i) * ff,
                torsion=_f(T, i) * mf,
                moment_2=_f(M2, i) * mf,
                moment_3=_f(M3, i) * mf,
                obj_sta=_scale_opt(_f_optional(ObjSta, i), lf),
                elm=str(Elm[i]) if Elm is not None and i < len(Elm) else None,
                elm_sta=_scale_opt(_f_optional(ElmSta, i), lf),
                step_type=_s(StepType, i),
                force_unit=uctx.dst.force,
                length_unit=uctx.dst.length,
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


# --- Per-kind CSV writers --------------------------------------------------


def _write_frame_csvs(records, grouped, output_dir, tag) -> None:
    """Per-load (+ MIN/MAX step splits) + consolidated + envelope CSVs for
    frame forces.

    Each load's rows are partitioned by ETABS StepType ("Max"/"Min"); rows
    with any other step stay only in the mixed per-load file.  A split file is
    written only when it has rows.
    """
    for name, recs in grouped.items():
        kind = recs[0].load_kind if recs else "COMBO"
        write_csv(recs, output_dir, name, load_kind=kind, tag=tag)
        for step_key in ("min", "max"):
            split = [r for r in recs if _step_key(r.step_type) == step_key]
            if split:
                write_frame_step_csv(
                    split, output_dir, name, load_kind=kind, step=step_key, tag=tag
                )
    write_all_forces_csv(records, output_dir, tag=tag)
    write_envelope_csv(records, output_dir, tag=tag)


def _write_base_csvs(records, grouped, output_dir, tag) -> None:
    """Per-load (+ MIN/MAX step splits) + consolidated + envelope CSVs for
    base reactions."""
    for name, recs in grouped.items():
        kind = recs[0].load_kind if recs else "COMBO"
        write_base_csv(recs, output_dir, name, load_kind=kind, tag=tag)
        # Per-load MIN/MAX split files: partition this load's rows by ETABS
        # StepType ("Max"/"Min"); rows with any other step stay only in the
        # mixed per-load file.  A split file is written only when it has rows.
        for step_key in ("min", "max"):
            split = [r for r in recs if _step_key(r.step_type) == step_key]
            if split:
                write_base_step_csv(
                    split, output_dir, name, load_kind=kind, step=step_key, tag=tag
                )
    write_all_base_csv(records, output_dir, tag=tag)
    write_base_envelope_csv(records, output_dir, tag=tag)
    write_base_envelope_min_csv(records, output_dir, tag=tag)
    write_base_envelope_max_csv(records, output_dir, tag=tag)


_FRAME_KIND = ExtractKind(
    label="frame",
    get_names=lambda s: s.get_frame_names(),
    read=_read_frame_forces,
    to_df=to_dataframe,
    write=_write_frame_csvs,
)


def _make_frame_reader(sections: "set[str] | None"):
    """Return a per-frame reader for :class:`ExtractKind` (frame forces).

    Captures an optional ``sections`` filter: a frame whose section (via
    ``get_section_for_frame``) is not in the filter is skipped entirely (no
    force read), mirroring :func:`_make_point_reader`.  ``None`` / empty
    sections means no filter (all sections).
    """

    def _read(session, frame, combos, cases, uctx) -> list[FrameForceRecord]:
        if sections is not None and len(sections) > 0:
            try:
                sec = session.get_section_for_frame(frame) or ""
            except Exception as exc:  # noqa: BLE001 - section lookup best-effort
                logger.debug("Section lookup failed for %r: %s", frame, exc)
                return []
            if sec not in sections:
                return []
        return _read_frame_forces(session, frame, combos, cases, uctx)

    return _read


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
    sections: list[str] | None = None,
    session: "EtabsSession | None" = None,
    tag: str | None = None,
    force_unit: str = "model",
    length_unit: str = "model",
) -> tuple:
    """Extract frame-element forces and (optionally) write CSVs.

    Returns ``(consolidated_DataFrame, {load_name: DataFrame}, list[record])``.
    When ``output_dir`` is provided, per-load CSVs and ``all_forces.csv``
    (plus an envelope summary) are written to it; per-load MIN/MAX split files
    (``combo_<load>_min.csv`` / ``combo_<load>_max.csv``) are added when a load
    is an envelope combo (Max/Min steps).

    ``frames`` restricts the frame *objects* by name; ``sections`` restricts
    by assigned section name (AND-combined when both given, each optional).
    An empty/None section selection means no section filter.

    ``force_unit`` / ``length_unit`` select the output unit system (default
    ``"model"`` — the active model's own present units; see
    :func:`_source_units` / :mod:`etabs_extractor.units`).

    If a ``session`` is passed (e.g. the test fake), it is used directly and
    no COM connection is attempted; otherwise one is created.
    """
    kind = _FRAME_KIND
    if sections:
        kind = ExtractKind(
            label="frame",
            get_names=lambda s: s.get_frame_names(),
            read=_make_frame_reader(set(sections)),
            to_df=to_dataframe,
            write=_write_frame_csvs,
        )
    return _extract(
        kind,
        model_path,
        output_dir,
        combos=combos,
        cases=cases,
        all_requested=all_requested,
        attach=attach,
        launch=launch,
        run_analysis=run_analysis,
        name_filter=frames,
        session=session,
        tag=tag,
        force_unit=force_unit,
        length_unit=length_unit,
    )


def _read_point_reactions(
    session: "EtabsSession",
    point: str,
    combos: list[str] | None,
    cases: list[str] | None,
    coords: tuple,
    uctx: _UnitCtx,
) -> list[JointReactionRecord]:
    """Read per-joint reactions for a single point across the selected loads.

    ``combos``/``cases`` discriminate each row's ``load_kind`` exactly as in
    ``_read_frame_forces`` (by membership in the resolved lists).  Force
    /moment/coordinate values are scaled from the model's units to
    ``uctx.dst``.
    """
    raw = session.joint_react(point, item_type_elm=0)
    if raw is None:
        return []

    (
        NumberResults, Obj, Elm, LoadCase, StepType, StepNum,
        F1, F2, F3, M1, M2, M3,
    ) = raw

    ff, mf, lf = uctx.force_factor, uctx.moment_factor, uctx.length_factor
    x, y, z = coords
    x, y, z = _scale_opt(x, lf), _scale_opt(y, lf), _scale_opt(z, lf)
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
                F1=_f(F1, i) * ff,
                F2=_f(F2, i) * ff,
                F3=_f(F3, i) * ff,
                M1=_f(M1, i) * mf,
                M2=_f(M2, i) * mf,
                M3=_f(M3, i) * mf,
                force_unit=uctx.dst.force,
                length_unit=uctx.dst.length,
            )
        )
    return records


def _make_point_reader(elevation: float | None):
    """Return a per-point reader for :class:`ExtractKind` (base reactions).

    Captures the optional ``elevation`` filter (in the *output* length unit,
    i.e. the same unit the extraction was asked for): a point whose ``z``
    does not match is skipped entirely (no reaction read), and unresolvable
    coordinates degrade to ``None`` slots instead of raising — mirroring the
    pre-refactor behavior of ``extract_base_reactions``.
    """

    def _read(session, point, combos, cases, uctx: _UnitCtx) -> list[JointReactionRecord]:
        try:
            coords = session.get_point_coords(point)
        except Exception as exc:  # noqa: BLE001 - coordinates are best-effort
            logger.debug("Point coordinate lookup failed for %r: %s", point, exc)
            coords = (None, None, None)
        if elevation is not None:
            z = coords[2]  # raw, model-unit z (not yet scaled)
            # Convert the requested (output-unit) elevation into model units
            # to compare against the raw COM coordinate; tolerance is ~1mm
            # expressed in the model's own length unit.
            elevation_model = elevation / uctx.length_factor if uctx.length_factor else elevation
            tol_model = 0.001 / LENGTH_TO_M[uctx.src.length]
            if z is None or not _z_match(z, elevation_model, tol=tol_model):
                return []
        return _read_point_reactions(session, point, combos, cases, coords, uctx)

    return _read


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
    force_unit: str = "model",
    length_unit: str = "model",
) -> tuple:
    """Extract per-joint (base) reactions and (optionally) write CSVs.

    Reports restrained point objects. By default every point at any elevation
    is reported; pass ``elevation`` to restrict to points whose ``z``
    coordinate matches that elevation, **expressed in the output length
    unit** (``length_unit``, e.g. metres if that's the model/output unit),
    which skips reading any other level.  Pass ``only_loaded=True`` to drop
    points where all six reaction components are zero (i.e. only supports that
    actually carry load).  Returns
    ``(consolidated_DataFrame, {load_name: DataFrame}, list[record])`` mirroring
    :func:`extract_forces`.  When ``output_dir`` is provided, per-load CSVs
    (``base_<load>.csv``), ``all_base_reactions.csv``, ``base_envelope_summary.csv``
    and the separated ``base_envelope_min.csv`` / ``base_envelope_max.csv``.  A
    ``tag`` appends a suffix to every output filename.

    ``force_unit`` / ``length_unit`` select the output unit system (default
    ``"model"`` — the active model's own present units; see
    :func:`_source_units` / :mod:`etabs_extractor.units`).
    """
    kind = ExtractKind(
        label="point",
        get_names=lambda s: s.get_point_names(),
        read=_make_point_reader(elevation),
        to_df=to_base_dataframe,
        write=_write_base_csvs,
    )
    post_filter = (
        (lambda recs: [r for r in recs if not _is_null_reaction(r)])
        if only_loaded
        else None
    )
    return _extract(
        kind,
        model_path,
        output_dir,
        combos=combos,
        cases=cases,
        all_requested=all_requested,
        attach=attach,
        launch=launch,
        run_analysis=run_analysis,
        name_filter=points,
        post_filter=post_filter,
        session=session,
        tag=tag,
        force_unit=force_unit,
        length_unit=length_unit,
    )


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
        try:
            info["section_names"] = session.get_frame_section_names()
        except Exception as exc:  # noqa: BLE001 - best-effort section inventory
            logger.debug("Could not list frame sections: %s", exc)
            info["section_names"] = []
        try:
            units = _source_units(session)
            info["units"] = {"force": units.force, "length": units.length}
        except Exception as exc:  # noqa: BLE001 - best-effort units
            logger.debug("Could not read model present units: %s", exc)
            info["units"] = {"force": "", "length": ""}
        try:
            info["elevations"] = list_elevations(session)
        except Exception as exc:  # noqa: BLE001 - best-effort elevation list
            logger.debug("Could not list model elevations: %s", exc)
            info["elevations"] = []
        return info
    finally:
        if own_session:
            # Best-effort release of the helper we created (no-op on fakes).
            _release_helper(session)


def list_elevations(session: "EtabsSession") -> list[dict]:
    """Return the model's distinct point elevations, labelled by story.

    Reads every point object's ``z`` coordinate (one COM call via
    ``get_all_point_coords``) plus the story table (``get_story_elevations``,
    best-effort — an empty story table just means unlabelled elevations), and
    groups points into elevations within a ~1mm-equivalent tolerance of each
    other, **expressed in the model's own length unit** (not hardcoded mm —
    a model reported in metres needs a ~0.001 tolerance, not 1.0, or distinct
    story elevations less than a metre apart wrongly merge). Returns a list
    of ``{"z": float, "label": str, "n_points": int}`` dicts sorted by ``z``
    ascending, in the model's own length unit — callers convert for display.
    ``label`` is the matching story name, ``"Base"`` for the model's base
    elevation, or ``""`` when no story matches within tolerance.
    """
    coords = session.get_all_point_coords()
    zs = sorted({z for (_x, _y, z) in coords.values() if z is not None})
    if not zs:
        return []

    try:
        story_info = session.get_story_elevations()
    except Exception as exc:  # noqa: BLE001 - labelling is best-effort
        logger.debug("Could not read story elevations: %s", exc)
        story_info = {"base": None, "stories": []}

    base = story_info.get("base")
    stories = story_info.get("stories") or []
    src = _source_units(session)
    tol = 0.001 / LENGTH_TO_M[src.length]

    def _label(z: float) -> str:
        if base is not None and _z_match(z, base, tol=tol):
            return "Base"
        for name, elev in stories:
            if elev is not None and _z_match(z, elev, tol=tol):
                return name
        return ""

    # Group raw z-values within tolerance of each other into one elevation
    # entry (COM coordinates can carry tiny float noise).
    groups: list[list[float]] = []
    for z in zs:
        if groups and _z_match(z, groups[-1][-1], tol=tol):
            groups[-1].append(z)
        else:
            groups.append([z])

    result: list[dict] = []
    for group in groups:
        z_repr = sum(group) / len(group)
        n_points = sum(
            1 for (_x, _y, pz) in coords.values()
            if pz is not None and _z_match(pz, z_repr, tol=tol)
        )
        result.append({"z": z_repr, "label": _label(z_repr), "n_points": n_points})
    return result