"""Openings (native units): door/window block inserts, door arcs as fallback.

* An INSERT on a DOOR/WINDOW layer is reduced to the oriented bounding box of its block
  (4 corners in WCS). The opening segment is the box side nearest to the closest wall;
  the width is the extent of the box along that wall.
* An ARC on a DOOR layer with no door insert nearby is a door of width = radius; its
  segment runs from the arc centre (hinge) to the arc end nearest to the closest wall.
* ``host_wall`` = the nearest wall within 0.6 m of the opening's centre.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import shapely

from ale.cad.walls import Pt, Seg
from ale.contracts.enums import OpeningKind
from ale.contracts.geometry import LineString
from ale.contracts.models import Opening, Wall

__all__ = [
    "HOST_WALL_MAX_M",
    "ArcDoor",
    "BlockOpening",
    "build_openings",
    "opening_closures",
]

HOST_WALL_MAX_M = 0.6


@dataclass(frozen=True)
class BlockOpening:
    """An INSERT on a DOOR/WINDOW layer: its oriented block box (4 WCS corners)."""

    kind: OpeningKind
    corners: tuple[Pt, Pt, Pt, Pt]

    @property
    def center(self) -> Pt:
        xs = [c[0] for c in self.corners]
        ys = [c[1] for c in self.corners]
        return (sum(xs) / 4.0, sum(ys) / 4.0)

    @property
    def width(self) -> float:
        """Longest side of the box (native units)."""
        return max(_dist(self.corners[i], self.corners[(i + 1) % 4]) for i in range(4))


@dataclass(frozen=True)
class ArcDoor:
    """An ARC on a DOOR layer (WCS)."""

    center: Pt
    radius: float
    start: Pt
    end: Pt


def _dist(a: Pt, b: Pt) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _wall_lines(walls: Sequence[Wall]) -> list[shapely.LineString]:
    return [shapely.LineString(w.centerline.coords) for w in walls]


def _nearest(lines: Sequence[shapely.LineString], p: Pt) -> tuple[int | None, float]:
    best: tuple[int | None, float] = (None, math.inf)
    pt = shapely.Point(p)
    for i, line in enumerate(lines):
        d = float(line.distance(pt))
        if d < best[1]:
            best = (i, d)
    return best


def _direction(wall: Wall) -> tuple[float, float]:
    (x0, y0), (x1, y1) = wall.centerline.coords[0], wall.centerline.coords[-1]
    length = math.hypot(x1 - x0, y1 - y0)
    return ((x1 - x0) / length, (y1 - y0) / length)


def _block_opening(
    op: BlockOpening, walls: Sequence[Wall], lines: Sequence[shapely.LineString], host_max: float
) -> Opening | None:
    idx, dist = _nearest(lines, op.center)
    sides = [(op.corners[i], op.corners[(i + 1) % 4]) for i in range(4)]
    sides = [s for s in sides if s[0] != s[1]]
    if not sides:
        return None
    if idx is None:
        a, b = max(sides, key=lambda s: _dist(*s))
        width = _dist(a, b)
    else:
        ux, uy = _direction(walls[idx])
        ox, oy = walls[idx].centerline.coords[0]

        def line_dist(p: Pt) -> float:
            return abs(ux * (p[1] - oy) - uy * (p[0] - ox))

        def side_key(s: tuple[Pt, Pt]) -> tuple[float, float]:
            # mean distance of the side's ends to the wall's (infinite) centreline;
            # ties (a box centred on the wall) go to the longer side
            return (round((line_dist(s[0]) + line_dist(s[1])) / 2.0, 6), -_dist(*s))

        a, b = min(sides, key=side_key)
        proj = [c[0] * ux + c[1] * uy for c in op.corners]
        width = max(proj) - min(proj)
    if width <= 0.0:
        return None
    host = idx if idx is not None and dist <= host_max else None
    return Opening(
        kind=op.kind, segment=LineString(coords=(a, b)), width_native=width, host_wall=host
    )


def _arc_opening(
    arc: ArcDoor, walls: Sequence[Wall], lines: Sequence[shapely.LineString], host_max: float
) -> Opening | None:
    if arc.radius <= 0.0:
        return None
    end = arc.start
    if lines:
        d_start = min(float(ln.distance(shapely.Point(arc.start))) for ln in lines)
        d_end = min(float(ln.distance(shapely.Point(arc.end))) for ln in lines)
        end = arc.start if d_start <= d_end else arc.end
    if end == arc.center:
        return None
    mid = ((arc.center[0] + end[0]) / 2.0, (arc.center[1] + end[1]) / 2.0)
    idx, dist = _nearest(lines, mid)
    host = idx if idx is not None and dist <= host_max else None
    return Opening(
        kind=OpeningKind.DOOR,
        segment=LineString(coords=(arc.center, end)),
        width_native=arc.radius,
        host_wall=host,
    )


def build_openings(
    blocks: Sequence[BlockOpening],
    arcs: Sequence[ArcDoor],
    walls: Sequence[Wall],
    m_per_unit: float,
) -> list[Opening]:
    """Openings of one plan; ``host_wall`` indexes ``walls``."""
    lines = _wall_lines(walls)
    host_max = HOST_WALL_MAX_M / m_per_unit
    out: list[Opening] = []
    for op in blocks:
        o = _block_opening(op, walls, lines, host_max)
        if o is not None:
            out.append(o)
    door_boxes = [shapely.Polygon(b.corners) for b in blocks if b.kind is OpeningKind.DOOR]
    for arc in arcs:
        near = any(
            float(box.distance(shapely.Point(arc.center))) <= arc.radius for box in door_boxes
        )
        if near:
            continue
        o = _arc_opening(arc, walls, lines, host_max)
        if o is not None:
            out.append(o)
    return out


def opening_closures(openings: Sequence[Opening], walls: Sequence[Wall]) -> list[Seg]:
    """Segments closing wall faces across each opening (for polygonize).

    For a hosted opening: two segments parallel to the host wall at ± thickness/2,
    spanning the opening's projection on the wall (one on the centreline when the wall
    has no thickness). Unhosted openings contribute their own segment.
    """
    out: list[Seg] = []
    for op in openings:
        a, b = op.segment.coords[0], op.segment.coords[1]
        if op.host_wall is None:
            out.append((a, b))
            continue
        wall = walls[op.host_wall]
        (x0, y0) = wall.centerline.coords[0]
        ux, uy = _direction(wall)
        nx, ny = -uy, ux
        center = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        sc = (center[0] - x0) * ux + (center[1] - y0) * uy
        half = op.width_native / 2.0
        offsets = (0.0,) if wall.thickness is None else (-wall.thickness / 2, wall.thickness / 2)
        for off in offsets:
            p = (x0 + ux * (sc - half) + nx * off, y0 + uy * (sc - half) + ny * off)
            q = (x0 + ux * (sc + half) + nx * off, y0 + uy * (sc + half) + ny * off)
            if p != q:
                out.append((p, q))
    return out
