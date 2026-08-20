"""Pure settings model for the etabs_extractor GUI.

This module is intentionally dependency-light (no Tk, no COM, no
matplotlib) so it is importable and unit-testable headlessly, including on a
machine with no display (e.g. WSL).  It defines the :class:`GuiSettings`
dataclass plus defaults and the value-parsing helpers used to read widget
values into a settings object / write them back to the widgets.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GuiSettings:
    """All tunable options collected from the GUI, ready to hand to the
    service layer."""

    # Model / output
    model_path: str = ""
    output_dir: str = ""
    tag: str = ""

    # Load selection
    combos: str = ""            # comma/space-separated names; empty = all
    elevation: str = ""         # empty = no elevation filter
    only_loaded: bool = False
    run_analysis: bool = False
    attach: bool = True

    # CSV plotting (no ETABS)
    csv_path: str = ""

    # Plot appearance
    plot_after_extract: bool = False
    dynamic_size: bool = True
    fig_width: float = 10.0
    fig_height: float = 8.0
    dpi: int = 800
    label_fontsize: float = 2.4
    units: str = "model"
    format: str = "png"

    # Derived/parsed values (populated by service.py)
    parsed_combos: list[str] = field(default_factory=list)
    parsed_elevation: float | None = None


DEFAULTS = GuiSettings()

# Accepted plot formats for the GUI dropdown.
FORMATS: tuple[str, ...] = ("png", "pdf", "svg")

# Accepted unit systems for the GUI dropdown (must match plots.UNITS keys).
UNITS_CHOICES: tuple[str, ...] = ("model", "kN-m")


def parse_combos(raw: str) -> list[str]:
    """Split a free-text combo field into a list of names.

    Combo names themselves may contain spaces (e.g. ``"ASD 1"``, ``"LRFD
    Max"``), so **commas** are the separator: each comma-separated segment
    (trimmed) is one name.  Empty/whitespace input yields an empty list
    (which the service treats as "all model combos").  A segment that is
    only whitespace is dropped.
    """
    if raw is None:
        return []
    parts = [seg.strip() for seg in raw.split(",")]
    return [seg for seg in parts if seg]


def parse_elevation(raw: str) -> float | None:
    """Parse an optional elevation value from a text field.

    Empty/whitespace returns ``None`` (no filter); invalid text raises
    ``ValueError`` so the GUI can surface a clear message.
    """
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw.strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid elevation value: {raw!r}") from exc


def parse_float(raw: str, default: float) -> float:
    """Parse a float widget value, falling back to ``default`` on empty/invalid."""
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        return default


def parse_int(raw: str, default: int) -> int:
    """Parse an integer widget value, falling back to ``default`` on invalid."""
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default