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

    # Load selection (multi-select checklist; empty lists = all model combos)
    selected_combos: list[str] = field(default_factory=list)
    selected_cases: list[str] = field(default_factory=list)
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
    x_offset: float = 1.0
    y_offset: float = 1.0
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


class _LoadItem:
    """A single load item in the checklist: its name, kind (``combos`` or
    ``cases``) and selected flag."""

    __slots__ = ("name", "kind", "selected")

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
    ) -> None:
        self._items: list[_LoadItem] = []
        if combos:
            self._items.extend(_LoadItem(name=n, kind="combo") for n in combos)
        if cases:
            self._items.extend(_LoadItem(name=n, kind="case") for n in cases)

    # ------------------------------------------------------------------ rows
    def set_items(self, combos: list[str], cases: list[str]) -> None:
        """Replace the item list with distinct combo + case lists.

        Selection flags are dropped on re-populate (a fresh model)."""
        self._items = []
        if combos:
            self._items.extend(_LoadItem(name=n, kind="combo") for n in combos)
        if cases:
            self._items.extend(_LoadItem(name=n, kind="case") for n in cases)

    def items(self):
        """Return all items (raw, unfiltered)."""
        return list(self._items)

    @property
    def all_combos(self) -> list[str]:
        return [it.name for it in self._items if it.kind == "combo"]

    @property
    def all_cases(self) -> list[str]:
        return [it.name for it in self._items if it.kind == "case"]

    # ---------------------------------------------------------------- filter
    def matches(self, query: str):
        """Return the items whose display label matches ``query`` as a
        case-insensitive substring.  An empty/whitespace query returns all
        items."""
        q = (query or "").strip().lower()
        if not q:
            return [it for it in self._items]
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
        """Return ``(selected_combos, selected_cases)`` from the model."""
        combos = [it.name for it in self._items if it.kind == "combo" and it.selected]
        cases = [it.name for it in self._items if it.kind == "case" and it.selected]
        return combos, cases

    def clear(self) -> None:
        for it in self._items:
            it.selected = False