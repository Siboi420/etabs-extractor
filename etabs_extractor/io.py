"""CSV output helpers for etabs_extractor.

Writes one CSV per load name (combination/case) plus a consolidated
``all_forces.csv``.  Uses stdlib ``csv`` so the I/O layer is fully
dependency-free and testable without pandas; the ``DataFrame`` view is
provided by :func:`etabs_extractor.models.to_dataframe`.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Iterable, Sequence

from .models import (
    BASE_COLUMNS,
    COLUMNS,
    FrameForceRecord,
    JointReactionRecord,
    summarize_base_envelope,
    summarize_base_envelope_minmax,
    summarize_envelope,
    to_base_dataframe,
    to_dataframe,
)


def _sanitize_filename(name: str) -> str:
    """Produce a filesystem-safe name from a combo/case name."""
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if ch in bad else ch for ch in name).strip()
    cleaned = cleaned.replace(" ", "_")
    return cleaned or "unnamed"


def _append_tag(stem: str, tag: str | None) -> str:
    """Append a sanitized ``tag`` suffix to a filename ``stem``.

    Guards ``None`` / empty / whitespace-only tags (behaves as no tag) and
    sanitises the value via :func:`_sanitize_filename`.  Returns
    ``f"{stem}_{cleaned}"`` when a usable tag is present, else ``stem``.
    """
    if not tag or not tag.strip():
        return stem
    cleaned = _sanitize_filename(tag)
    return f"{stem}_{cleaned}"


def write_csv(
    records: Iterable[FrameForceRecord],
    output_dir: str | os.PathLike,
    load_name: str,
    load_kind: str = "COMBO",
    tag: str | None = None,
) -> Path:
    """Write ``records`` to ``output_dir/<load_name>.csv``.

    Returns the written path.  ``load_kind`` is embedded per-row (each
    record already carries it); the parameter here only influences the
    file name prefix for clarity.  When ``tag`` is given it is appended to
    the filename stem.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [r.to_dict() for r in records]
    prefix = "combo" if load_kind.upper() == "COMBO" else "case"
    fname = _append_tag(f"{prefix}_{_sanitize_filename(load_name)}", tag) + ".csv"
    path = out_dir / fname
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_all_forces_csv(
    records: Iterable[FrameForceRecord],
    output_dir: str | os.PathLike,
    tag: str | None = None,
) -> Path:
    """Write all records (every load name) into a single ``all_forces.csv``."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (_append_tag("all_forces", tag) + ".csv")
    rows = [r.to_dict() for r in records]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_envelope_csv(
    records: Iterable[FrameForceRecord],
    output_dir: str | os.PathLike,
    tag: str | None = None,
) -> Path:
    """Write a per-(frame, load_name) min/max envelope summary CSV.

    Uses :func:`etabs_extractor.models.summarize_envelope`, which is backed
    by pandas; this helper is therefore only invoked in production /
    the dry run, not required for basic CSV writing.
    """
    import pandas as pd  # noqa: PLC0415

    df = to_dataframe(records)
    env = summarize_envelope(df)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (_append_tag("envelope_summary", tag) + ".csv")
    env.to_csv(path, index=False, encoding="utf-8")
    return path


def write_base_csv(
    records: Iterable[JointReactionRecord],
    output_dir: str | os.PathLike,
    load_name: str,
    load_kind: str = "COMBO",
    tag: str | None = None,
) -> Path:
    """Write base-reaction ``records`` to ``output_dir/base_<load>.csv``.

    ``load_kind`` only influences the ``combo``/``case`` prefix for clarity;
    each record already carries its own kind.  Returns the written path.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [r.to_dict() for r in records]
    prefix = "combo" if load_kind.upper() == "COMBO" else "case"
    fname = _append_tag(f"base_{prefix}_{_sanitize_filename(load_name)}", tag) + ".csv"
    path = out_dir / fname
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=BASE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_all_base_csv(
    records: Iterable[JointReactionRecord],
    output_dir: str | os.PathLike,
    tag: str | None = None,
) -> Path:
    """Write all base-reaction records into a single ``all_base_reactions.csv``."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (_append_tag("all_base_reactions", tag) + ".csv")
    rows = [r.to_dict() for r in records]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=BASE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_base_step_csv(
    records: Iterable[JointReactionRecord],
    output_dir: str | os.PathLike,
    load_name: str,
    load_kind: str = "COMBO",
    step: str = "",
    tag: str | None = None,
) -> Path | None:
    """Write the records of one ETABS result step (``Min``/``Max``) of a
    load to ``base_combo_<load>_<step>.csv`` / ``base_case_<load>_<step>.csv``.

    ``step`` is lowercased and filesystem-sanitized; a ``tag`` is appended to
    the stem via :func:`_append_tag` (e.g. ``base_combo_ASD_Max_min_KM13.csv``).
    Returns ``None`` when ``records`` is empty (no split file written).  The
    written schema is the full :data:`BASE_COLUMNS` (including ``step_type``),
    so the file stays usable with ``plot_base_reactions_from_csv`` / ``--plot-csv``.
    """
    recs = list(records)
    if not recs:
        return None
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [r.to_dict() for r in recs]
    prefix = "combo" if load_kind.upper() == "COMBO" else "case"
    stem = f"base_{prefix}_{_sanitize_filename(load_name)}"
    step_part = _sanitize_filename(step.lower()) if step else ""
    if step_part:
        stem = f"{stem}_{step_part}"
    fname = _append_tag(stem, tag) + ".csv"
    path = out_dir / fname
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=BASE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_base_envelope_csv(
    records: Iterable[JointReactionRecord],
    output_dir: str | os.PathLike,
    tag: str | None = None,
) -> Path:
    """Write a per-(point, load_name) min/max envelope summary CSV."""
    import pandas as pd  # noqa: PLC0415

    df = to_base_dataframe(records)
    env = summarize_base_envelope(df)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (_append_tag("base_envelope_summary", tag) + ".csv")
    env.to_csv(path, index=False, encoding="utf-8")
    return path


def write_base_envelope_min_csv(
    records: Iterable[JointReactionRecord],
    output_dir: str | os.PathLike,
    tag: str | None = None,
) -> Path:
    """Write the per-(point, load_name) MIN envelope subset to
    ``base_envelope_min[_tag].csv``."""
    import pandas as pd  # noqa: PLC0415

    df = to_base_dataframe(records)
    min_df, _max_df = summarize_base_envelope_minmax(df)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (_append_tag("base_envelope_min", tag) + ".csv")
    min_df.to_csv(path, index=False, encoding="utf-8")
    return path


def write_base_envelope_max_csv(
    records: Iterable[JointReactionRecord],
    output_dir: str | os.PathLike,
    tag: str | None = None,
) -> Path:
    """Write the per-(point, load_name) MAX envelope subset to
    ``base_envelope_max[_tag].csv``."""
    import pandas as pd  # noqa: PLC0415

    df = to_base_dataframe(records)
    _min_df, max_df = summarize_base_envelope_minmax(df)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (_append_tag("base_envelope_max", tag) + ".csv")
    max_df.to_csv(path, index=False, encoding="utf-8")
    return path
