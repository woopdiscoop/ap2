"""Filled zones as rooms (Ticket X.2): Archicad / Revit sheets draw each room as a filled polygon.

Input: filled paths with their colour (PDF points, ``Y_DOWN``) and the page texts. Steps:

1. keep rectangles and orthogonal polygons whose fill is neither white / near-white
   (every channel >= 0.96), near-black (wall material, luminance < 0.15) nor a page-sized
   background (>= 95 % of the page); drop slivers (short side < 0.3 m scaled / 2 pt) and
   fills under 0.5 m² (scaled) or 6 pt² (unscaled);
2. merge duplicates (same outline, the later one wins) and drop frames (a fill whose other
   fills inside it cover > 80 % of it, at least two of them);
3. label each zone: texts are attached to the smallest zone covering their centre; the area
   text nearest to the zone centroid gives ``area_text_m2``; the name comes from
   :func:`ale.pdfread.rooms.label_rooms`; with no name, ``raw_label`` is ``fill=#RRGGBB``.

Zones are only used by :mod:`ale.pdfread.read` when :func:`zones_credible` holds (at least
half of them carry a text), which keeps charts with coloured bars from reading as plans.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import shapely

from ale.contracts.models import LabelledPolygon
from ale.pdfread.rooms import RoomText, label_rooms, parse_area_text
from ale.pdfread.walls import Pt

__all__ = [
    "MIN_ZONES",
    "MIN_ZONE_M2",
    "MIN_ZONE_PT2",
    "ZoneFill",
    "trace_zones",
    "zones_credible",
]

MIN_ZONE_M2 = 0.5
MIN_ZONE_PT2 = 6.0
MIN_ZONES = 3
NEAR_WHITE = 0.96
NEAR_BLACK_LUMA = 0.15
FRAME_COVER = 0.8
PAGE_SHARE = 0.95
DUP_IOU = 0.98
_MIN_SIDE_M = 0.3
_MIN_SIDE_PT = 2.0
_ORTHO_TOL = 1e-3
_MAX_ZONES = 5000

_Rgb = tuple[float, float, float]
_Item = tuple[shapely.Polygon, _Rgb]


@dataclass(frozen=True)
class ZoneFill:
    """A filled closed outline (open ring, points) and its RGB fill (0..1)."""

    points: tuple[Pt, ...]
    color: _Rgb


def _orthogonal(pts: Sequence[Pt]) -> bool:
    n = len(pts)
    return n >= 4 and all(
        abs(pts[i][0] - pts[(i + 1) % n][0]) <= _ORTHO_TOL
        or abs(pts[i][1] - pts[(i + 1) % n][1]) <= _ORTHO_TOL
        for i in range(n)
    )


def _hex(c: _Rgb) -> str:
    r, g, b = (round(min(1.0, max(0.0, v)) * 255) for v in c)
    return f"#{r:02X}{g:02X}{b:02X}"


def _candidates(
    fills: Sequence[ZoneFill], m_per_unit: float | None, page_area: float | None
) -> list[_Item]:
    if m_per_unit is None:
        min_area, min_side = MIN_ZONE_PT2, _MIN_SIDE_PT
    else:
        min_area, min_side = MIN_ZONE_M2 / (m_per_unit**2), _MIN_SIDE_M / m_per_unit
    out: list[_Item] = []
    for f in fills:
        r, g, b = f.color
        if min(r, g, b) >= NEAR_WHITE or 0.299 * r + 0.587 * g + 0.114 * b < NEAR_BLACK_LUMA:
            continue
        if not _orthogonal(f.points):
            continue
        poly = shapely.Polygon(f.points)
        if not poly.is_valid or poly.area < min_area:
            continue
        x0, y0, x1, y1 = poly.bounds
        if min(x1 - x0, y1 - y0) < min_side:
            continue
        if page_area is not None and poly.area >= PAGE_SHARE * page_area:
            continue
        out.append((poly, f.color))
    return out[:_MAX_ZONES]


def _dedupe(items: list[_Item]) -> list[_Item]:
    kept: list[_Item] = []
    for poly, col in items:
        dup = next(
            (
                i
                for i, (q, _) in enumerate(kept)
                if q.intersects(poly) and q.intersection(poly).area >= DUP_IOU * q.union(poly).area
            ),
            None,
        )
        if dup is None:
            kept.append((poly, col))
        else:
            kept[dup] = (poly, col)  # the later drawn fill is the visible one
    return kept


def _drop_frames(items: list[_Item]) -> list[_Item]:
    out: list[_Item] = []
    for i, (poly, col) in enumerate(items):
        kids = [
            q for j, (q, _) in enumerate(items) if j != i and q.area < poly.area and poly.covers(q)
        ]
        if len(kids) >= 2 and shapely.unary_union(kids).area > FRAME_COVER * poly.area:
            continue
        out.append((poly, col))
    return out


def trace_zones(
    fills: Sequence[ZoneFill],
    texts: Sequence[RoomText],
    m_per_unit: float | None,
    warnings: list[str],
    *,
    page_area: float | None = None,
) -> list[LabelledPolygon]:
    """Labelled rooms from the filled zones (ids ``r001``… in reading order)."""
    items = _drop_frames(_dedupe(_candidates(fills, m_per_unit, page_area)))
    items.sort(
        key=lambda it: (
            round(it[0].representative_point().y, 6),
            round(it[0].representative_point().x, 6),
        )
    )
    owned: list[list[RoomText]] = [[] for _ in items]
    for t in texts:
        pt = shapely.Point(t.center)
        hit = [i for i, (p, _) in enumerate(items) if p.covers(pt)]
        if hit:
            owned[min(hit, key=lambda i: items[i][0].area)].append(t)
    rooms: list[LabelledPolygon] = []
    for (poly, col), inside in zip(items, owned, strict=True):
        labelled = label_rooms([poly], inside, warnings)
        if not labelled:
            continue
        room = labelled[0]
        c = poly.centroid
        areas = [
            (math.dist(t.center, (c.x, c.y)), a)
            for t in inside
            if (a := parse_area_text(t.text)) is not None
        ]
        update: dict[str, object] = {"id": f"r{len(rooms) + 1:03d}"}
        if areas:
            update["area_text_m2"] = min(areas)[1]
        if room.raw_label is None:
            update["raw_label"] = f"fill={_hex(col)}"
        rooms.append(room.model_copy(update=update))
    return rooms


def zones_credible(rooms: Sequence[LabelledPolygon]) -> bool:
    """At least :data:`MIN_ZONES` zones and half of them carry an area text or a name."""
    if len(rooms) < MIN_ZONES:
        return False
    texted = sum(
        1
        for r in rooms
        if r.area_text_m2 is not None or not (r.raw_label or "").startswith("fill=")
    )
    return 2 * texted >= len(rooms)
