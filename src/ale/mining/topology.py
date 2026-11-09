"""Room topology of one extracted plan (metres): contacts, doors and façades.

Every room polygon is first credited with half of its *local wall thickness* ``h`` (the
median thickness of the walls whose centreline lies within 1 m of the room, 0.10 m when
no such wall has a thickness). Two rooms are in contact where their boundaries face each
other across a gap of at most ``h_a + h_b + TOUCH_TOL_M`` — i.e. where the two polygons,
each buffered by its half thickness (plus half the tolerance), touch.

Shared length (the centreline length of the wall strip between the rooms) is measured on
the facing edges: for every pair of nearly parallel edges (angle ≤ 30°) the part of one
edge whose orthogonal projection falls on the other and whose distance to it is within the
gap is kept; the intervals are merged per edge and the shared length is the mean of the
two rooms' facing lengths. This equals the ``area(buffer_a ∩ buffer_b) / (2·h)`` of the
spec on the straight part of the strip, without the rounded end caps of the buffers (which
would inflate short contacts by ≈ 1.6·h). A contact is kept when the shared length is
≥ 0.6 m; it is a ``DOOR`` contact when ≥ 1 door segment midpoint lies in the shared region
(the quadrilaterals between the facing edge parts, widened by ``DOOR_TOL_M``).

Façades: the outer boundary is the exterior ring(s) of the union of the rooms grown by their
half thickness (a morphological closing bridges the wall gaps). A room's façade length is
the length of its boundary facing that outer boundary within 0.3 m (same facing-edge rule).

Public functions never raise on bad input: problems are logged as warnings.
"""

from __future__ import annotations

import logging
import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import shapely
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from ale.contracts.config import AleConfig
from ale.contracts.enums import ContactKind, Fidelity, OpeningKind, fidelity_of
from ale.contracts.geometry import to_shapely
from ale.contracts.models import PlanGeometry

__all__ = [
    "DEFAULT_WALL_THICKNESS_M",
    "EXTERIOR_TOL_M",
    "MIN_SHARED_M",
    "Contact",
    "PlanTopology",
    "extract_topology",
]

log = logging.getLogger(__name__)

#: Wall thickness assumed when no wall with a thickness lies within ``LOCAL_WALL_RADIUS_M``.
DEFAULT_WALL_THICKNESS_M = 0.10
#: Radius around a room in which walls count for its local thickness (m).
LOCAL_WALL_RADIUS_M = 1.0
#: Extra gap tolerated on top of ``h_a + h_b`` before two facing rooms stop touching (m).
TOUCH_TOL_M = 0.10
#: Minimum shared length of a contact (m).
MIN_SHARED_M = 0.6
#: Distance to the outer boundary within which a room edge is façade (m).
EXTERIOR_TOL_M = 0.3
#: Tolerance around the shared region for a door midpoint (m).
DOOR_TOL_M = 0.05
#: Two edges face each other when the angle between their lines is at most 30°.
_PARALLEL_COS = math.cos(math.radians(30.0))
#: Per-pair edge-comparison budget (bounded loops); larger pairs are skipped with a warning.
_MAX_EDGE_PAIRS = 1_000_000
_ROUND = 6
_EPS = 1e-9

_CONFIG = ConfigDict(extra="forbid", frozen=True)

Pt = tuple[float, float]
Seg = tuple[Pt, Pt]


class Contact(BaseModel):
    """A contact between two rooms (``a < b``); ``shared_m`` in metres."""

    model_config = _CONFIG

    a: StrictStr
    b: StrictStr
    kind: ContactKind
    shared_m: float
    openings: StrictInt


class PlanTopology(BaseModel):
    """Topology of one plan: rooms ``(id, type, area m²)``, contacts and façades (m)."""

    model_config = _CONFIG

    source_sha256: StrictStr
    page: StrictInt
    plan_index: StrictInt
    fidelity: Fidelity
    rooms: tuple[tuple[str, str | None, float], ...]
    contacts: tuple[Contact, ...]
    exterior: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class _Room:
    id: str
    type: str | None
    geom: shapely.Polygon
    edges: tuple[Seg, ...]
    half: float
    bounds: tuple[float, float, float, float]


# --------------------------------------------------------------------------- geometry helpers


def _ring_edges(coords: Iterable[Any]) -> list[Seg]:
    pts = [(float(c[0]), float(c[1])) for c in coords]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    n = len(pts)
    out: list[Seg] = []
    for i in range(n):
        p, q = pts[i], pts[(i + 1) % n]
        if math.hypot(q[0] - p[0], q[1] - p[1]) > _EPS:
            out.append((p, q))
    return out


def _polygon_edges(poly: shapely.Polygon) -> tuple[Seg, ...]:
    edges = _ring_edges(poly.exterior.coords)
    for ring in poly.interiors:
        edges.extend(_ring_edges(ring.coords))
    return tuple(edges)


def _facing_interval(ea: Seg, eb: Seg, gap: float) -> tuple[float, float] | None:
    """Parameter interval (length units along ``ea``) of ``ea`` facing ``eb`` within ``gap``."""
    (ax, ay), (bx, by) = ea
    la = math.hypot(bx - ax, by - ay)
    ux, uy = (bx - ax) / la, (by - ay) / la
    (cx, cy), (dx, dy) = eb
    lb = math.hypot(dx - cx, dy - cy)
    vx, vy = (dx - cx) / lb, (dy - cy) / lb
    if abs(ux * vx + uy * vy) < _PARALLEL_COS:
        return None
    t0 = (cx - ax) * ux + (cy - ay) * uy
    t1 = (dx - ax) * ux + (dy - ay) * uy
    lo, hi = max(0.0, min(t0, t1)), min(la, max(t0, t1))
    if hi - lo <= _EPS:
        return None
    # Signed distance to eb's line is linear in s: f(s) = f0 + k s; keep |f(s)| <= gap.
    nx, ny = -vy, vx
    f0 = (ax - cx) * nx + (ay - cy) * ny
    k = ux * nx + uy * ny
    if abs(k) <= _EPS:
        if abs(f0) > gap:
            return None
    else:
        s1, s2 = (-gap - f0) / k, (gap - f0) / k
        lo, hi = max(lo, min(s1, s2)), min(hi, max(s1, s2))
        if hi - lo <= _EPS:
            return None
    return lo, hi


def _merged_length(intervals: list[tuple[float, float]]) -> float:
    total = 0.0
    cur_lo = cur_hi = None
    for lo, hi in sorted(intervals):
        if cur_hi is None or lo > cur_hi:
            if cur_hi is not None and cur_lo is not None:
                total += cur_hi - cur_lo
            cur_lo, cur_hi = lo, hi
        else:
            cur_hi = max(cur_hi, hi)
    if cur_hi is not None and cur_lo is not None:
        total += cur_hi - cur_lo
    return total


def _facing(
    edges_a: Sequence[Seg], edges_b: Sequence[Seg], gap: float, regions: list[shapely.Geometry]
) -> float:
    """Length of ``edges_a`` facing ``edges_b`` within ``gap``; appends the facing quads."""
    total = 0.0
    for ea in edges_a:
        intervals: list[tuple[float, float]] = []
        (ax, ay), (bx, by) = ea
        la = math.hypot(bx - ax, by - ay)
        ux, uy = (bx - ax) / la, (by - ay) / la
        for eb in edges_b:
            iv = _facing_interval(ea, eb, gap)
            if iv is None:
                continue
            intervals.append(iv)
            (cx, cy), (dx, dy) = eb
            lb = math.hypot(dx - cx, dy - cy)
            nx, ny = -(dy - cy) / lb, (dx - cx) / lb
            quad: list[Pt] = []
            for s in iv:
                px, py = ax + s * ux, ay + s * uy
                f = (px - cx) * nx + (py - cy) * ny
                quad.extend([(px, py), (px - f * nx, py - f * ny)])
            regions.append(shapely.MultiPoint(quad).convex_hull)
        total += _merged_length(intervals)
    return total


def _bbox_gap(
    b1: tuple[float, float, float, float], b2: tuple[float, float, float, float]
) -> float:
    dx = max(0.0, b2[0] - b1[2], b1[0] - b2[2])
    dy = max(0.0, b2[1] - b1[3], b1[1] - b2[3])
    return math.hypot(dx, dy)


# --------------------------------------------------------------------------- steps


def _local_half(geom: shapely.Polygon, walls: Sequence[tuple[shapely.Geometry, float]]) -> float:
    near = [t for line, t in walls if geom.distance(line) <= LOCAL_WALL_RADIUS_M]
    thickness = statistics.median(near) if near else DEFAULT_WALL_THICKNESS_M
    return float(thickness) / 2.0


def _rooms(metric: PlanGeometry) -> list[_Room]:
    walls: list[tuple[shapely.Geometry, float]] = [
        (to_shapely(w.centerline), w.thickness)
        for w in metric.walls
        if w.thickness is not None and math.isfinite(w.thickness) and w.thickness > 0.0
    ]
    out: list[_Room] = []
    for r in sorted(metric.rooms, key=lambda r: r.id):
        geom = shapely.Polygon(r.polygon.exterior, r.polygon.holes)  # valid by contract
        x0, y0, x1, y1 = (float(v) for v in geom.bounds)
        out.append(
            _Room(
                id=r.id,
                type=r.type,
                geom=geom,
                edges=_polygon_edges(geom),
                half=_local_half(geom, walls),
                bounds=(x0, y0, x1, y1),
            )
        )
    return out


def _contacts(rooms: Sequence[_Room], doors: Sequence[shapely.Point]) -> list[Contact]:
    out: list[Contact] = []
    for i, ra in enumerate(rooms):
        for rb in rooms[i + 1 :]:
            gap = ra.half + rb.half + TOUCH_TOL_M
            if _bbox_gap(ra.bounds, rb.bounds) > gap:
                continue
            if len(ra.edges) * len(rb.edges) > _MAX_EDGE_PAIRS:
                log.warning("topology: rooms %r/%r too detailed; contact skipped", ra.id, rb.id)
                continue
            regions: list[shapely.Geometry] = []
            la = _facing(ra.edges, rb.edges, gap, regions)
            lb = _facing(rb.edges, ra.edges, gap, regions)
            shared = round((la + lb) / 2.0, _ROUND)
            if shared < MIN_SHARED_M:
                continue
            region = shapely.union_all(regions)
            n_doors = sum(1 for p in doors if region.distance(p) <= DOOR_TOL_M)
            a, b = (ra.id, rb.id) if ra.id < rb.id else (rb.id, ra.id)
            out.append(
                Contact(
                    a=a,
                    b=b,
                    kind=ContactKind.DOOR if n_doors else ContactKind.WALL,
                    shared_m=shared,
                    openings=n_doors,
                )
            )
    out.sort(key=lambda c: (c.a, c.b))
    return out


def _outer_edges(rooms: Sequence[_Room]) -> list[Seg]:
    grown = [r.geom.buffer(r.half + TOUCH_TOL_M, join_style="mitre") for r in rooms]
    union = shapely.union_all(grown).buffer(-TOUCH_TOL_M, join_style="mitre")
    edges: list[Seg] = []
    for part in getattr(union, "geoms", [union]):
        if isinstance(part, shapely.Polygon) and not part.is_empty:
            edges.extend(_ring_edges(part.exterior.coords))
    return edges


def _exterior(rooms: Sequence[_Room]) -> list[tuple[str, float]]:
    outer = _outer_edges(rooms)
    out: list[tuple[str, float]] = []
    for r in rooms:
        if len(r.edges) * len(outer) > _MAX_EDGE_PAIRS:
            log.warning("topology: room %r too detailed for the façade test; skipped", r.id)
            continue
        length = round(_facing(r.edges, outer, EXTERIOR_TOL_M, []), _ROUND)
        if length > 0.0:
            out.append((r.id, length))
    return out


# --------------------------------------------------------------------------- public API


def extract_topology(plan: PlanGeometry, config: AleConfig) -> PlanTopology | None:
    """Topology of ``plan`` in metres; ``None`` when its scale is unknown (or unusable).

    ``config`` is accepted for interface stability; no setting currently affects the result.
    """
    del config  # no tunable setting in v1 (thresholds are module constants)
    if plan.scale_m_per_unit is None:
        return None
    try:
        metric = plan.to_metric()
    except ValueError as exc:
        log.warning(
            "topology: plan %s p%d cannot be converted: %s", plan.source_sha256[:12], plan.page, exc
        )
        return None
    rooms = _rooms(metric)
    doors = [
        shapely.Point(
            (o.segment.coords[0][0] + o.segment.coords[1][0]) / 2.0,
            (o.segment.coords[0][1] + o.segment.coords[1][1]) / 2.0,
        )
        for o in metric.openings
        if o.kind is OpeningKind.DOOR
    ]
    return PlanTopology(
        source_sha256=plan.source_sha256,
        page=plan.page,
        plan_index=plan.plan_index,
        fidelity=fidelity_of(plan.source_kind),
        rooms=tuple((r.id, r.type, round(float(r.geom.area), _ROUND)) for r in rooms),
        contacts=tuple(_contacts(rooms, doors)),
        exterior=tuple(_exterior(rooms)) if rooms else (),
    )
