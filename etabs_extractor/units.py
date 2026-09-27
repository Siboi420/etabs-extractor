"""Model-aware unit resolution and conversion.

Pure Python (no COM, no pandas) so it stays importable on any platform.
ETABS reports its "present units" (force/length/temperature) via
``SapModel.GetPresentUnits`` / ``GetPresentUnits_2``; this module converts
between that model unit system and whatever unit system the user asked the
extraction/plot to be reported in.

Everything here works in plain multiplicative factors relative to a common
base (newtons for force, metres for length) so any force/length combination
converts to any other without special-casing pairs.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Conversion factors to a common base (N, m) -----------------------------

FORCE_TO_N: dict[str, float] = {
    "N": 1.0,
    "kN": 1.0e3,
    "kgf": 9.80665,
    "tonf": 9806.65,
    "lb": 4.4482216152605,
    "kip": 4448.2216152605,
}

LENGTH_TO_M: dict[str, float] = {
    "mm": 1.0e-3,
    "cm": 1.0e-2,
    "m": 1.0,
    "in": 0.0254,
    "ft": 0.3048,
    "micron": 1.0e-6,
}

# GUI/CLI choice lists ("model" means: use the source/model unit unchanged).
FORCE_CHOICES: tuple[str, ...] = ("model", "N", "kN", "kgf", "tonf", "lb", "kip")
LENGTH_CHOICES: tuple[str, ...] = ("model", "mm", "cm", "m", "in", "ft")

# --- ETABS eForce / eLength / eUnits enum values (from the CSI OAPI) --------
# See ETABSv1 typelib: eForce_*, eLength_*, eUnits_* (values fixed by CSI, not
# generated dynamically — safe to hardcode as documented API constants).

ETABS_FORCE_ENUM: dict[int, str] = {
    1: "lb",
    2: "kip",
    3: "N",
    4: "kN",
    5: "kgf",
    6: "tonf",
}

ETABS_LENGTH_ENUM: dict[int, str] = {
    1: "in",
    2: "ft",
    3: "micron",
    4: "mm",
    5: "cm",
    6: "m",
}

# eUnits_* (the legacy combined-unit-system enum, ``GetPresentUnits()``):
# value -> (force, length).
ETABS_EUNITS: dict[int, tuple[str, str]] = {
    1: ("lb", "in"),
    2: ("lb", "ft"),
    3: ("kip", "in"),
    4: ("kip", "ft"),
    5: ("kN", "mm"),
    6: ("kN", "m"),
    7: ("kgf", "mm"),
    8: ("kgf", "m"),
    9: ("N", "mm"),
    10: ("N", "m"),
    11: ("tonf", "mm"),
    12: ("tonf", "m"),
    13: ("kN", "cm"),
    14: ("kgf", "cm"),
    15: ("N", "cm"),
    16: ("tonf", "cm"),
}


@dataclass(frozen=True)
class UnitSystem:
    """A force + length unit pair (moment is force·length)."""

    force: str
    length: str

    @property
    def moment(self) -> str:
        return f"{self.force}·{self.length}"

    def label(self) -> str:
        return f"{self.force}, {self.moment}, {self.length}"


# Fallback unit systems for legacy data with no unit columns / no unit API
# available (best-effort — matches the assumptions the package used to hardcode).
LEGACY_BASE = UnitSystem("kN", "mm")   # old base-reaction export default
LEGACY_FRAME = UnitSystem("N", "mm")   # ETABS model-unit default (N, mm)


def resolve_target(source: UnitSystem, force: str = "model", length: str = "model") -> UnitSystem:
    """Return the target :class:`UnitSystem` given a source and requested units.

    ``"model"`` (the default for both) means "keep the source unit" for that
    dimension — i.e. no conversion is applied to it.
    """
    out_force = source.force if force in (None, "", "model") else force
    out_length = source.length if length in (None, "", "model") else length
    if out_force not in FORCE_TO_N:
        raise ValueError(f"Unknown force unit {out_force!r}. Known: {', '.join(FORCE_TO_N)}.")
    if out_length not in LENGTH_TO_M:
        raise ValueError(f"Unknown length unit {out_length!r}. Known: {', '.join(LENGTH_TO_M)}.")
    return UnitSystem(out_force, out_length)


def factors(src: UnitSystem, dst: UnitSystem) -> tuple[float, float, float]:
    """Return ``(force_factor, moment_factor, length_factor)`` multipliers that
    convert a value expressed in ``src`` units to the equivalent ``dst`` value.

    ``value_dst = value_src * factor``.
    """
    length_factor = LENGTH_TO_M[src.length] / LENGTH_TO_M[dst.length]
    force_factor = FORCE_TO_N[src.force] / FORCE_TO_N[dst.force]
    moment_factor = force_factor * length_factor
    return force_factor, moment_factor, length_factor


__all__ = [
    "FORCE_TO_N",
    "LENGTH_TO_M",
    "FORCE_CHOICES",
    "LENGTH_CHOICES",
    "ETABS_FORCE_ENUM",
    "ETABS_LENGTH_ENUM",
    "ETABS_EUNITS",
    "UnitSystem",
    "LEGACY_BASE",
    "LEGACY_FRAME",
    "resolve_target",
    "factors",
]
