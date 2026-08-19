"""Configuration, defaults, and path resolution for etabs_extractor.

The package deliberately never hardcodes any ``/mnt/d`` or ``D:\\`` path.
Model and output locations are supplied at call time (CLI) or via
environment variables with clearly non-binding defaults.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- COM / ETABS defaults -------------------------------------------------

# COM ProgID for the ETABS helper object.  ETABS v22 registers the "v1"
# interface; adjust only if targeting a different major version layout.
DEFAULT_COM_PROGID = "ETABSv1.Helper"

# Environment variables consulted for model / output locations.
DEFAULT_MODEL_VARIABLE = "ETABS_MODEL"
DEFAULT_OUTPUT_VARIABLE = "ETABS_OUTPUT"

# Non-binding fallback output directory (relative, resolved at runtime).
DEFAULT_OUTPUT_DIR = Path("output") / "etabs_forces"


def resolve_model_path(explicit: str | os.PathLike | None = None) -> Path | None:
    """Resolve the ETABS model path.

    Priority: explicit argument > ``ETABS_MODEL`` env var > None.

    Returns a :class:`Path` if a value is available, else ``None`` (meaning
    the caller should report a clear error).  The returned path is *not*
    required to exist here; that is validated by the caller.
    """
    candidate = explicit if explicit is not None else os.environ.get(DEFAULT_MODEL_VARIABLE)
    if candidate is None or str(candidate).strip() == "":
        return None
    return Path(str(candidate))


def resolve_output_dir(explicit: str | os.PathLike | None = None) -> Path:
    """Resolve the output directory.

    Priority: explicit argument > ``ETABS_OUTPUT`` env var > ``DEFAULT_OUTPUT_DIR``.
    """
    candidate = explicit if explicit is not None else os.environ.get(DEFAULT_OUTPUT_VARIABLE)
    if candidate is None or str(candidate).strip() == "":
        return DEFAULT_OUTPUT_DIR
    return Path(str(candidate))


def to_windows_path(path: str | os.PathLike) -> str:
    """Convert a POSIX ``/mnt/d/...`` path to a Windows ``D:\\...`` path.

    ETABS/OLEAPI's ``File.OpenFile`` needs a native Windows path string.
    Falls back to the input unchanged when it is already a Windows-style
    path or does not look like a WSL ``/mnt/<letter>/...`` mount.
    """
    p = str(path)
    # Already a Windows path (has a drive letter).
    if len(p) >= 2 and p[1] == ":":
        return p
    # WSL /mnt/<drive>/... mount  →  <DRIVE>:\...
    if p.startswith("/mnt/") and len(p) >= 7 and p[5] != "/" and p[6] == "/":
        drive = p[5].upper()
        rest = p[7:].replace("/", "\\")
        return f"{drive}:\\{rest}"
    return p
