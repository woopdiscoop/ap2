"""Drawing units of a DXF: ``$INSUNITS`` → metres per unit, inference from door blocks.

Precedence (RD 1.2 section 3): ``$INSUNITS`` (1 in, 2 ft, 4 mm, 5 cm, 6 m), else the
median door-block width, else the caller's override, else unknown.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from ale.contracts.enums import ScaleMethod

__all__ = [
    "INSUNITS_M",
    "UNITS_INFERRED_WARNING",
    "UNITS_UNKNOWN_WARNING",
    "UNIT_LABEL_M",
    "UnitsInfo",
    "infer_from_door_widths",
    "resolve_units",
]

#: ``$INSUNITS`` code → (label, metres per unit).
INSUNITS_M: dict[int, tuple[str, float]] = {
    1: ("in", 0.0254),
    2: ("ft", 0.3048),
    4: ("mm", 0.001),
    5: ("cm", 0.01),
    6: ("m", 1.0),
}
#: Unit label → metres per unit (accepted values of ``units_override``).
UNIT_LABEL_M: dict[str, float] = {label: m for label, m in INSUNITS_M.values()}

UNITS_INFERRED_WARNING = "units inferred from doors"
UNITS_UNKNOWN_WARNING = "units unknown: no $INSUNITS, no door blocks, no override"

#: Door width ranges (native units) → unit label.
_DOOR_RANGES: tuple[tuple[float, float, str], ...] = (
    (700.0, 1100.0, "mm"),
    (70.0, 110.0, "cm"),
    (0.7, 1.1, "m"),
)


@dataclass(frozen=True)
class UnitsInfo:
    """Resolved units of a drawing."""

    label: str | None
    m_per_unit: float | None
    method: ScaleMethod
    confidence: float
    warnings: tuple[str, ...] = ()


def infer_from_door_widths(widths: Sequence[float]) -> str | None:
    """Unit label from the median door-block width (native units), or ``None``."""
    usable = [w for w in widths if w > 0.0]
    if not usable:
        return None
    med = statistics.median(usable)
    for lo, hi, label in _DOOR_RANGES:
        if lo <= med <= hi:
            return label
    return None


def resolve_units(
    insunits: int | None,
    door_widths: Sequence[float],
    units_override: str | None,
) -> UnitsInfo:
    """Apply the precedence of RD 1.2 section 3 (never raises)."""
    if insunits is not None and insunits in INSUNITS_M:
        label, m = INSUNITS_M[insunits]
        return UnitsInfo(label, m, ScaleMethod.DRAWING_UNITS, 1.0)
    inferred = infer_from_door_widths(door_widths)
    if inferred is not None:
        return UnitsInfo(
            inferred,
            UNIT_LABEL_M[inferred],
            ScaleMethod.DRAWING_UNITS,
            0.6,
            (UNITS_INFERRED_WARNING,),
        )
    if units_override is not None:
        key = units_override.strip().lower()
        if key in UNIT_LABEL_M:
            return UnitsInfo(key, UNIT_LABEL_M[key], ScaleMethod.DRAWING_UNITS, 1.0)
        return UnitsInfo(
            None,
            None,
            ScaleMethod.UNKNOWN,
            0.0,
            (f"unknown units_override {units_override!r}", UNITS_UNKNOWN_WARNING),
        )
    return UnitsInfo(None, None, ScaleMethod.UNKNOWN, 0.0, (UNITS_UNKNOWN_WARNING,))
