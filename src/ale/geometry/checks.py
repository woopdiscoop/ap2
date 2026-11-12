"""Geometric helpers and the layout invariants of RD 3.3 section 7.

All lengths are integer modules and all areas module² cells (exact integer arithmetic).
"""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

from ale.contracts.config import AleConfig
from ale.contracts.geometry import ModulePolygon, ModuleRect
from ale.contracts.models import Layout, PlacedRoom
from ale.geometry.blocks import Consts, aspect_ok
from ale.program.models import PreparedInput

__all__ = [
    "check_layout",
    "exterior_contacts",
    "rect_in_polygon_cells",
    "share_length",
    "solid_contact",
]


def share_length(a: ModuleRect, b: ModuleRect) -> int:
    """Length of the common boundary of two rectangles (0 if they only meet at a corner)."""
    if a.x2() == b.x or b.x2() == a.x:
        return max(0, min(a.y2(), b.y2()) - max(a.y, b.y))
    if a.y2() == b.y or b.y2() == a.y:
        return max(0, min(a.x2(), b.x2()) - max(a.x, b.x))
    return 0


def _edges(poly: ModulePolygon) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Edges of the exterior ring, then of every courtyard ring."""
    out = list(poly.edges())
    for ring in poly.holes:
        n = len(ring)
        out += [(ring[i], ring[(i + 1) % n]) for i in range(n)]  # int-mod
    return out


def exterior_contacts(rect: ModuleRect, poly: ModulePolygon) -> list[tuple[int, tuple[int, int]]]:
    """``(length, outward normal)`` of every footprint edge the rectangle lies along.

    Edges are taken in polygon order; the normal is the edge's outward axis vector.
    """
    out: list[tuple[int, tuple[int, int]]] = []
    # Courtyard rings (G.1) run clockwise with the region on their left, like the exterior.
    for (ax, ay), (bx, by) in _edges(poly):
        if ay == by:  # horizontal edge; CCW: +x runs along the bottom (outward -y)
            normal = (0, -1) if bx > ax else (0, 1)
            side = rect.y if normal[1] < 0 else rect.y2()
            if side != ay:
                continue
            length = min(rect.x2(), max(ax, bx)) - max(rect.x, min(ax, bx))
        else:  # vertical edge; CCW: +y runs along the right side (outward +x)
            normal = (1, 0) if by > ay else (-1, 0)
            side = rect.x2() if normal[0] > 0 else rect.x
            if side != ax:
                continue
            length = min(rect.y2(), max(ay, by)) - max(rect.y, min(ay, by))
        if length > 0:
            out.append((length, normal))
    return out


def solid_contact(rect: ModuleRect, ring: Sequence[tuple[int, int]]) -> int:
    """Length (modules) of the boundary of a solid ring that ``rect`` lies along (Ticket M.2).

    ``rect`` is outside the solid (the tiling never overlaps it), so a coinciding side is a
    contact. Ring edges are summed in ring order.
    """
    total = 0
    n = len(ring)
    for i in range(n):
        (ax, ay), (bx, by) = ring[i], ring[(i + 1) % n]  # int-mod
        if ay == by:
            if ay in (rect.y, rect.y2()):
                total += max(0, min(rect.x2(), max(ax, bx)) - max(rect.x, min(ax, bx)))
        elif ax in (rect.x, rect.x2()):
            total += max(0, min(rect.y2(), max(ay, by)) - max(rect.y, min(ay, by)))
    return total


def _clip(
    pts: list[tuple[Fraction, Fraction]], axis: int, bound: int, keep_le: bool
) -> list[tuple[Fraction, Fraction]]:
    """Sutherland-Hodgman clip of a ring against ``coord[axis] <= bound`` (or ``>=``)."""

    def inside(p: tuple[Fraction, Fraction]) -> bool:
        return p[axis] <= bound if keep_le else p[axis] >= bound

    out: list[tuple[Fraction, Fraction]] = []
    n = len(pts)
    for i in range(n):
        cur, nxt = pts[i], pts[(i + 1) % n]  # int-mod
        if inside(cur):
            out.append(cur)
        if inside(cur) != inside(nxt):
            t = (bound - cur[axis]) / (nxt[axis] - cur[axis])
            out.append((cur[0] + t * (nxt[0] - cur[0]), cur[1] + t * (nxt[1] - cur[1])))
    return out


def rect_in_polygon_cells(rect: ModuleRect, poly: ModulePolygon) -> int:
    """Exact area of ``rect ∩ poly`` in cells (courtyards and solids subtracted)."""
    return _clipped_cells(rect, poly.exterior) - sum(
        _clipped_cells(rect, h) for h in (*poly.holes, *poly.solids)
    )


def _clipped_cells(rect: ModuleRect, ring: tuple[tuple[int, int], ...]) -> int:
    """Exact area of ``rect`` ∩ the region bounded by ``ring`` (either orientation)."""
    pts: list[tuple[Fraction, Fraction]] = [(Fraction(x), Fraction(y)) for x, y in ring]
    for axis, bound, keep_le in (
        (0, rect.x, False),
        (0, rect.x2(), True),
        (1, rect.y, False),
        (1, rect.y2(), True),
    ):
        pts = _clip(pts, axis, bound, keep_le)
        if not pts:
            return 0
    twice = Fraction(0)
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]  # int-mod
        twice += x0 * y1 - x1 * y0
    return int(abs(twice) / 2)


def _ints(p: PlacedRoom) -> bool:
    r = p.rect
    return all(type(v) is int for v in (r.x, r.y, r.w, r.h))


def _connected(rects: Sequence[ModuleRect]) -> bool:
    n = len(rects)
    if n <= 1:
        return True
    seen = {0}
    todo = [0]
    while todo:  # each index enters ``todo`` at most once
        i = todo.pop()
        for j in range(n):
            if j not in seen and share_length(rects[i], rects[j]) >= 1:
                seen.add(j)
                todo.append(j)
    return len(seen) == n


def check_layout(layout: Layout, prepared: PreparedInput, config: AleConfig) -> tuple[str, ...]:
    """Invariants of RD section 7; ``()`` when all hold, else one message per problem."""
    k = Consts.from_config(config)
    poly = layout.footprint
    rooms = layout.rooms
    circ = layout.circulation
    every: tuple[PlacedRoom, ...] = (*rooms, *circ)
    out: list[str] = []
    for p in every:
        if not _ints(p):
            out.append(f"{p.instance_id}: non-integer rectangle")
        elif rect_in_polygon_cells(p.rect, poly) != p.rect.area_cells():
            out.append(f"{p.instance_id}: outside the footprint")
    for i in range(len(every)):
        for j in range(i + 1, len(every)):
            cells = every[i].rect.intersection_cells(every[j].rect)
            if cells:
                out.append(
                    f"{every[i].instance_id} overlaps {every[j].instance_id} by {cells} cells"
                )
    total = sum(p.rect.area_cells() for p in every)
    if total != poly.area_cells():
        out.append(f"areas sum to {total} cells, footprint has {poly.area_cells()}")
    for room in rooms:
        best = max((share_length(room.rect, c.rect) for c in circ), default=0)
        if best < k.c:
            out.append(f"{room.instance_id}: circulation contact {best} < {k.c}")
    if not _connected([c.rect for c in circ]):
        out.append("circulation is not connected")
    flagged_solids = {v.code for v in layout.metrics.violations}
    for k, ring in enumerate(poly.solids):
        if (
            not any(solid_contact(c.rect, ring) >= 1 for c in circ)
            and "SOLID_NO_ACCESS" not in flagged_solids
        ):
            out.append(f"solid {k}: no circulation along its boundary")
    flagged = {(v.code, iid) for v in layout.metrics.violations for iid in v.instance_ids}
    specs = dict(prepared.instances)
    for room in rooms:
        iid = room.instance_id
        steep = not aspect_ok(room.rect.w, room.rect.h, k.amax)
        if steep and not {("ASPECT", iid), ("ASPECT_DEPTH", iid)} & flagged:
            out.append(f"{iid}: aspect above {k.amax} without an ASPECT violation")
        spec = specs.get(iid)
        if spec is None:
            continue
        req = k.req(spec)
        cells = room.rect.area_cells()
        if not req.lo <= cells <= req.hi:
            code = "AREA_UNDER" if cells < req.lo else "AREA_OVER"
            if (code, iid) not in flagged:
                out.append(f"{iid}: area outside the rule without an {code} violation")
    return tuple(out)
