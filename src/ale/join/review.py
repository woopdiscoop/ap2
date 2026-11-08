"""Review flags of a ``PlanGeometry`` (ticket 1.6).

:func:`review_flags` returns, in the fixed order of :data:`REVIEW_FLAGS`, the reasons why a
plan should go to ``ale review``:

- ``scale_unknown``: no scale;
- ``scale_low_confidence``: a scale whose confidence is below ``extract.review_confidence``;
- ``area_mismatch``: a room whose ``area_text_m2`` differs by more than 5 % from its metric
  polygon area;
- ``many_untyped``: more than 30 % of the rooms have no type;
- ``tiny_rooms``: a room whose metric area is below 1 m².

Area based flags need a scale and are not raised for a plan whose scale is unknown.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from ale.contracts.config import AleConfig
from ale.contracts.geometry import Point2, Polygon
from ale.contracts.models import PlanGeometry

__all__ = [
    "AREA_MISMATCH_REL",
    "MANY_UNTYPED_SHARE",
    "REVIEW_FLAGS",
    "TINY_ROOM_M2",
    "polygon_area",
    "review_flags",
]

#: All flags, in the order :func:`review_flags` reports them.
REVIEW_FLAGS: tuple[str, ...] = (
    "scale_unknown",
    "scale_low_confidence",
    "area_mismatch",
    "many_untyped",
    "tiny_rooms",
)

AREA_MISMATCH_REL = 0.05
MANY_UNTYPED_SHARE = 0.30
TINY_ROOM_M2 = 1.0


def _ring_area(ring: Sequence[Point2]) -> float:
    n = len(ring)
    twice = 0.0
    for k in range(n):
        x1, y1 = ring[k]
        x2, y2 = ring[(k + 1) % n]
        twice += x1 * y2 - x2 * y1
    return abs(twice) / 2.0


def polygon_area(polygon: Polygon) -> float:
    """Area of a contract polygon (exterior minus holes) in squared native units."""
    return _ring_area(polygon.exterior) - sum(_ring_area(h) for h in polygon.holes)


def review_flags(plan: PlanGeometry, config: AleConfig | None = None) -> tuple[str, ...]:
    """Flags of ``plan`` (subset of :data:`REVIEW_FLAGS`, in that order). Never raises."""
    cfg = config if config is not None else AleConfig()
    flags: set[str] = set()
    try:
        scale = plan.scale_m_per_unit
        if scale is None:
            flags.add("scale_unknown")
        elif plan.scale_confidence < cfg.extract.review_confidence:
            flags.add("scale_low_confidence")
        rooms = plan.rooms
        if rooms:
            untyped = sum(1 for r in rooms if r.type is None)
            if untyped > MANY_UNTYPED_SHARE * len(rooms):
                flags.add("many_untyped")
        if scale is not None:
            for room in rooms:
                area_m2 = polygon_area(room.polygon) * scale * scale
                if area_m2 < TINY_ROOM_M2:
                    flags.add("tiny_rooms")
                text = room.area_text_m2
                if (
                    text is not None
                    and math.isfinite(text)
                    and abs(area_m2 - text) > AREA_MISMATCH_REL * abs(text)
                ):
                    flags.add("area_mismatch")
    except Exception:  # public API never raises; report what was established
        pass
    return tuple(f for f in REVIEW_FLAGS if f in flags)
