"""Pure settings model for the etabs_extractor GUI.

This module is intentionally dependency-light (no Tk, no COM, no
matplotlib) so it is importable and unit-testable headlessly, including on a
machine with no display (e.g. WSL).  It defines the :class:`GuiSettings`
dataclass plus defaults and the value-parsing helpers used to read widget
values into a settings object / write them back to the widgets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from etabs_extractor.units import FORCE_CHOICES, LENGTH_CHOICES


@dataclass
class GuiSettings:
    """All tunable options collected from the GUI, ready to hand to the
    service layer."""

    # Model / output
    model_path: str = ""
    output_dir: str = ""
    tag: str = ""

    # Appearance
    appearance_mode: str = "System"  # "System", "Dark", "Light"

    # Load selection (multi-select checklist; empty lists = all model combos)
    selected_combos: list[str] = field(default_factory=list)
    selected_cases: list[str] = field(default_factory=list)
    elevation: str = ""         # empty = no elevation filter
    only_loaded: bool = False
    run_analysis: bool = False
    attach: bool = True

    # Output unit system ("model" = the active model's own present units,
    # read live via EtabsSession.get_present_units(); no conversion applied).
    force_unit: str = "model"
    length_unit: str = "model"

    # Extraction mode ("base" reactions vs "frame" forces) + frame selectors
    extract_mode: str = "base"
    selected_sections: list[str] = field(default_factory=list)
    selected_frames: list[str] = field(default_factory=list)

    # CSV plotting (no ETABS)
    csv_path: str = ""

    # Batch plot save target (sidebar, both modes); blank = mode fallback
    # (extraction: Output dir; CSV mode: Plot output dir, else the CSV's parent).
    batch_plot_dir: str = ""

    # Plot appearance
    plot_after_extract: bool = False
    dynamic_size: bool = True
    fig_width: float = 10.0
    fig_height: float = 8.0
    dpi: int = 800
    label_fontsize: float = 2.4
    x_offset: float = 1.0
    y_offset: float = 1.0
    units: str = "data"
    format: str = "png"

    # Plot-only output directory (CSV tab); blank = the CSV's own parent dir.
    plot_output_dir: str = ""

    # Derived/parsed values (populated by service.py)
    parsed_combos: list[str] = field(default_factory=list)
    parsed_elevation: float | None = None


DEFAULTS = GuiSettings()

# Accepted plot formats for the GUI dropdown.
FORMATS: tuple[str, ...] = ("png", "pdf", "svg")

# Accepted extraction modes for the GUI mode switch.
MODE_CHOICES: tuple[str, ...] = ("base", "frame")

# Base-preview step variants (label shown in the dropdown -> plots.STEP_VARIANTS
# entry via preview._STEP_VARIANT).  "Abs max" is today's max-|value| default.
STEP_CHOICES: tuple[str, ...] = ("Abs max", "Max", "Min")

# Accepted plot display-unit choices for the GUI dropdown ("data" displays
# the extraction's own units unconverted; the rest are named presets from
# plots.UNITS plus the plots.py-recognized "<force>-<length>" strings).
UNITS_CHOICES: tuple[str, ...] = ("data", "kN-m", "kN-mm", "N-mm", "tonf-m", "kgf-m")

# Accepted output force/length unit choices for extraction (GUI + CLI);
# "model" means "use the active model's own present units, no conversion".
FORCE_UNIT_CHOICES: tuple[str, ...] = FORCE_CHOICES
LENGTH_UNIT_CHOICES: tuple[str, ...] = LENGTH_CHOICES

# Accepted appearance modes for the GUI's theme switch.
APPEARANCE_CHOICES: tuple[str, ...] = ("System", "Light", "Dark")


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
    ``ValueError`` so the GUI can surface a clear message.  Tolerates the
    elevation combobox's labelled entries (e.g. ``"-18.55  (Base, 42 pts)"``,
    as populated by ``app._on_check_done``) by taking the leading numeric
    token and ignoring the trailing ``(...)`` label.
    """
    if raw is None or not raw.strip():
        return None
    text = raw.strip()
    match = re.match(r"^[+-]?\d+(?:\.\d+)?", text)
    if not match:
        raise ValueError(f"Invalid elevation value: {raw!r}")
    try:
        return float(match.group(0))
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


class _LoadItem:
    """A single load item in the checklist: its name, kind (``combos`` or
    ``cases``) and selected flag."""

    __slots__ = ("kind", "name", "selected")

    def __init__(self, name: str, kind: str, selected: bool = False) -> None:
        self.name = name
        self.kind = kind
        self.selected = selected

    @property
    def display(self) -> str:
        """The label shown in the checklist, e.g. ``(combo) ASD 1``."""
        return f"({self.kind}) {self.name}"


class LoadSelectionModel:
    """Headless selection model backing the multi-select load checklist.

    Holds a distinct list of combo and case items (each with a ``selected``
    flag), a substring ``matches(query)`` filter, and ``get_selected() ->
    (combos, cases)``.  Keeps all filtering logic pure so it is unit-testable
    without Tk.
    """

    def __init__(
        self,
        combos: list[str] | None = None,
        cases: list[str] | None = None,
        kind_a: str = "combo",
        kind_b: str = "case",
    ) -> None:
        self._kind_a = kind_a
        self._kind_b = kind_b
        self._items: list[_LoadItem] = []
        if combos:
            self._items.extend(_LoadItem(name=n, kind=kind_a) for n in combos)
        if cases:
            self._items.extend(_LoadItem(name=n, kind=kind_b) for n in cases)

    # ------------------------------------------------------------------ rows
    def set_items(
        self,
        combos: list[str],
        cases: list[str],
        kind_a: str | None = None,
        kind_b: str | None = None,
    ) -> None:
        """Replace the item list with distinct group-a + group-b lists.

        ``kind_a``/``kind_b`` may override the group kinds (defaults kept
        when passed as ``None``). Selection flags are dropped on
        re-populate (a fresh model)."""
        if kind_a is not None:
            self._kind_a = kind_a
        if kind_b is not None:
            self._kind_b = kind_b
        self._items = []
        if combos:
            self._items.extend(
                _LoadItem(name=n, kind=self._kind_a) for n in combos
            )
        if cases:
            self._items.extend(
                _LoadItem(name=n, kind=self._kind_b) for n in cases
            )

    def items(self):
        """Return all items (raw, unfiltered)."""
        return list(self._items)

    @property
    def all_combos(self) -> list[str]:
        return [it.name for it in self._items if it.kind == self._kind_a]

    @property
    def all_cases(self) -> list[str]:
        return [it.name for it in self._items if it.kind == self._kind_b]

    # ---------------------------------------------------------------- filter
    def matches(self, query: str):
        """Return the items whose display label matches ``query`` as a
        case-insensitive substring.  An empty/whitespace query returns all
        items."""
        q = (query or "").strip().lower()
        if not q:
            return list(self._items)
        return [it for it in self._items if q in it.display.lower()]

    # ------------------------------------------------------------ selection
    def toggle(self, index: int, selected: bool) -> None:
        """Set the selected flag of the item at ``index`` (into ``_items``)."""
        if 0 <= index < len(self._items):
            self._items[index].selected = bool(selected)

    def set_selected(self, names: list[str]) -> None:
        """Mark exactly the given names (matching combo-or-case name) selected."""
        target = set(names)
        for it in self._items:
            it.selected = it.name in target

    def is_selected(self, index: int) -> bool:
        if 0 <= index < len(self._items):
            return self._items[index].selected
        return False

    def get_selected(self) -> tuple[list[str], list[str]]:
        """Return ``(selected_a, selected_b)`` from the model (the two configured
        groups, e.g. combos/cases or sections/frames)."""
        a = [it.name for it in self._items if it.kind == self._kind_a and it.selected]
        b = [it.name for it in self._items if it.kind == self._kind_b and it.selected]
        return a, b

    def clear(self) -> None:
        for it in self._items:
            it.selected = False
