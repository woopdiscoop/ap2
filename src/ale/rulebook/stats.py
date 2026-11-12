"""Mined statistics of the rulebook (Ticket 2.2 RD section 3), metres and m².

Every plan carries a weight (``rulebook.fidelity_weights[fidelity]``). All functions take
the plans already sorted by ``(source_sha256, page, plan_index)`` so that the float sums
are performed in a deterministic order.

Conventions (literal readings of the RD, recorded in ``eval_report.md``):

* Allowed types: typed rooms whose type is neither ``unknown`` nor of category SPECIAL /
  CIRCULATION. A same-type pair ``(a, a)`` is "contained" in a plan with ≥ 2 such rooms.
* Weighted quantiles: samples sorted by value; sample ``i`` sits at the plotting position
  ``(S_i - w_i / 2) / S`` of the weighted CDF (``S_i`` cumulative weight, ``S`` total), the
  quantile is linearly interpolated between positions and clamped to the extreme values
  outside them (with equal weights this is the Hazen definition ``(i - 0.5) / n``).
* Core offset: the footprint is the bounding box of every room of the plan (``fx, fy`` its
  centre, ``W, H`` its size); plans without a service-core room are not used.
* Façade (Ticket R.8): the façade edges of a room are its ring edges lying on the exterior
  outline (:func:`~ale.mining.topology._facing` within ``EXTERIOR_TOL_M``) over at least
  :data:`MIN_FACADE_EDGE_M`; the longest one gives the façade width (its façade length) and
  the depth (extent of the room perpendicular to it). Rooms without façade count for
  ``facade_m_per_m2 = 0`` and not for depth / width.
* Orientation: façade length per bearing (outward normal of the façade edges, binned by
  :func:`~ale.contracts.orientation.bearing_bin`); the type-independent share uses every
  room of the plan (typed or not).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import shapely
from shapely.geometry.polygon import orient

from ale.contracts.enums import Bearing, Fidelity
from ale.contracts.models import PlanGeometry
from ale.contracts.orientation import bearing_bin, compass_bearing_deg
from ale.contracts.taxonomy import UNKNOWN, load_taxonomy
from ale.mining import PlanTopology
from ale.mining.topology import (
    EXTERIOR_TOL_M,
    _facing,
    _outer_edges,
    _ring_edges,
    _rooms,
)

__all__ = [
    "BEARINGS",
    "MIN_FACADE_EDGE_M",
    "CoreStat",
    "FacadeStat",
    "OrientationStat",
    "PairStat",
    "PlanInput",
    "ShapeStat",
    "adjacency_stats",
    "allowed_type",
    "core_offset_stats",
    "facade_stats",
    "orientation_stats",
    "room_aspect",
    "room_facades",
    "shape_stats",
    "weighted_quantile",
]

#: Shortest exterior stretch (m) of a room edge that counts as a façade edge (R.8).
MIN_FACADE_EDGE_M = 0.6
BEARINGS: tuple[Bearing, ...] = (Bearing.N, Bearing.E, Bearing.S, Bearing.W)
#: Fidelities whose rooms feed the aspect / area statistics.
SHAPE_FIDELITIES = frozenset({Fidelity.CAD, Fidelity.PDF_VECTOR})
_FORBIDDEN = frozenset({"SPECIAL", "CIRCULATION"})


@dataclass(frozen=True)
class PlanInput:
    """One usable plan: its topology, its metric geometry, weight and north (degrees)."""

    topology: PlanTopology
    metric: PlanGeometry
    weight: float
    north_angle_deg: float | None = None

    @property
    def key(self) -> tuple[str, int, int]:
        t = self.topology
        return (t.source_sha256, t.page, t.plan_index)


@dataclass(frozen=True)
class PairStat:
    """Weighted support / hits of an unordered type pair (``a <= b``)."""

    support: float
    hits: float


@dataclass
class ShapeStat:
    """Weighted samples (value, weight) of aspect (unitless) and area (m²) of one type."""

    aspect: list[tuple[float, float]] = field(default_factory=list)
    area: list[tuple[float, float]] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.area)


@dataclass
class FacadeStat:
    """Weighted samples of depth (m) and façade width (m) of the rooms of one type with a
    façade, and the weighted façade length / area totals of every room of the type."""

    depth: list[tuple[float, float]] = field(default_factory=list)
    width: list[tuple[float, float]] = field(default_factory=list)
    facade_len: float = 0.0
    area: float = 0.0

    @property
    def n(self) -> int:
        return len(self.depth)

    @property
    def m_per_m2(self) -> float | None:
        return self.facade_len / self.area if self.area > 0.0 else None


@dataclass(frozen=True)
class CoreStat:
    """Weighted mean normalised core offset over ``n`` plans."""

    dx_norm: float
    dy_norm: float
    n: int


@dataclass(frozen=True)
class OrientationStat:
    """Scaled orientation preference (in [-1, 1]) of a type and its plan count."""

    values: dict[Bearing, float]
    n_plans: int


def allowed_type(key: str | None) -> bool:
    """True for a type that may appear in a rulebook (typed, not SPECIAL / CIRCULATION)."""
    if key is None or key == UNKNOWN:
        return False
    try:
        category = load_taxonomy().get(key).category
    except KeyError:
        return False
    return category.value not in _FORBIDDEN


def _is_core(key: str | None) -> bool:
    if key is None:
        return False
    try:
        return load_taxonomy().get(key).service_core
    except KeyError:
        return False


# --------------------------------------------------------------------------- adjacency


def adjacency_stats(plans: Sequence[PlanInput]) -> dict[tuple[str, str], PairStat]:
    """Weighted support and hits of every unordered pair of allowed types."""
    support: dict[tuple[str, str], float] = {}
    hits: dict[tuple[str, str], float] = {}
    for plan in plans:
        types = {rid: t for rid, t, _ in plan.topology.rooms if t is not None and allowed_type(t)}
        counts = Counter(types.values())
        keys = sorted(counts)
        present: set[tuple[str, str]] = set()
        for i, a in enumerate(keys):
            if counts[a] >= 2:
                present.add((a, a))
            for b in keys[i + 1 :]:
                present.add((a, b))
        touching: set[tuple[str, str]] = set()
        for c in plan.topology.contacts:
            ta, tb = types.get(c.a), types.get(c.b)
            if ta is None or tb is None:
                continue
            touching.add((ta, tb) if ta <= tb else (tb, ta))
        for pair in sorted(present):
            support[pair] = support.get(pair, 0.0) + plan.weight
            if pair in touching:
                hits[pair] = hits.get(pair, 0.0) + plan.weight
    return {p: PairStat(support[p], hits.get(p, 0.0)) for p in sorted(support)}


# --------------------------------------------------------------------------- aspect & area


def weighted_quantile(samples: Iterable[tuple[float, float]], q: float) -> float:
    """Weighted quantile ``q`` in [0, 1] of ``(value, weight)`` samples (see module doc).

    Samples with a non-positive weight are ignored; ``ValueError`` when none is left.
    """
    pts = sorted((v, w) for v, w in samples if w > 0.0)
    if not pts:
        raise ValueError("weighted_quantile: no sample with a positive weight")
    total = math.fsum(w for _, w in pts)
    positions: list[float] = []
    cum = 0.0
    for _, w in pts:
        cum += w
        positions.append((cum - w / 2.0) / total)
    if q <= positions[0]:
        return pts[0][0]
    if q >= positions[-1]:
        return pts[-1][0]
    for i in range(len(pts) - 1):
        lo, hi = positions[i], positions[i + 1]
        if lo <= q <= hi:
            if hi - lo <= 0.0:  # pragma: no cover - positions strictly increase
                return pts[i][0]
            t = (q - lo) / (hi - lo)
            return pts[i][0] + t * (pts[i + 1][0] - pts[i][0])
    return pts[-1][0]  # pragma: no cover - unreachable


def room_aspect(geom: shapely.Polygon) -> float | None:
    """Long / short side of the minimum rotated rectangle (``None`` when degenerate)."""
    rect = shapely.minimum_rotated_rectangle(geom)
    if not isinstance(rect, shapely.Polygon):  # pragma: no cover - contract polygons are valid
        return None
    c = list(rect.exterior.coords)
    s1 = math.dist(c[0], c[1])
    s2 = math.dist(c[1], c[2])
    short, long_ = min(s1, s2), max(s1, s2)
    if short <= 1e-9:
        return None
    return long_ / short


def shape_stats(plans: Sequence[PlanInput]) -> dict[str, ShapeStat]:
    """Aspect and area samples per allowed type, from CAD / PDF_VECTOR plans only."""
    out: dict[str, ShapeStat] = {}
    for plan in plans:
        if plan.topology.fidelity not in SHAPE_FIDELITIES:
            continue
        for r in sorted(plan.metric.rooms, key=lambda r: r.id):
            if not allowed_type(r.type) or r.type is None:
                continue
            geom = shapely.Polygon(r.polygon.exterior, r.polygon.holes)
            aspect = room_aspect(geom)
            if aspect is None:
                continue
            st = out.setdefault(r.type, ShapeStat())
            st.aspect.append((aspect, plan.weight))
            st.area.append((float(geom.area), plan.weight))
    return {k: out[k] for k in sorted(out)}


# --------------------------------------------------------------------------- core offset


def _plan_core_offset(metric: PlanGeometry) -> tuple[float, float] | None:
    if not metric.rooms:
        return None
    geoms = [
        (r.type, shapely.Polygon(r.polygon.exterior, r.polygon.holes))
        for r in sorted(metric.rooms, key=lambda r: r.id)
    ]
    x0 = min(float(g.bounds[0]) for _, g in geoms)
    y0 = min(float(g.bounds[1]) for _, g in geoms)
    x1 = max(float(g.bounds[2]) for _, g in geoms)
    y1 = max(float(g.bounds[3]) for _, g in geoms)
    w, h = x1 - x0, y1 - y0
    core = [g for t, g in geoms if _is_core(t)]
    area = math.fsum(float(g.area) for g in core)
    if w <= 0.0 or h <= 0.0 or area <= 0.0:
        return None
    cx = math.fsum(float(g.area) * float(g.centroid.x) for g in core) / area
    cy = math.fsum(float(g.area) * float(g.centroid.y) for g in core) / area
    fx, fy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    return (cx - fx) / w, (cy - fy) / h


def core_offset_stats(plans: Sequence[PlanInput]) -> CoreStat | None:
    """Weighted mean core offset over the plans that have a service core."""
    rows: list[tuple[float, float, float]] = []
    for plan in plans:
        off = _plan_core_offset(plan.metric)
        if off is not None:
            rows.append((off[0], off[1], plan.weight))
    total = math.fsum(w for _, _, w in rows)
    if not rows or total <= 0.0:
        return None
    dx = math.fsum(d * w for d, _, w in rows) / total
    dy = math.fsum(d * w for _, d, w in rows) / total
    return CoreStat(dx_norm=dx, dy_norm=dy, n=len(rows))


# --------------------------------------------------------------------------- orientation


def room_facades(metric: PlanGeometry, north_angle_deg: float) -> dict[str, dict[Bearing, float]]:
    """Façade length (m) per bearing of every room of a metric plan (rooms with façade only)."""
    rooms = _rooms(metric)
    if not rooms:
        return {}
    outer = _outer_edges(rooms)
    out: dict[str, dict[Bearing, float]] = {}
    for r in rooms:
        ccw = orient(r.geom, 1.0)
        lengths: dict[Bearing, float] = {}
        for edge in _ring_edges(ccw.exterior.coords):
            length = _facing([edge], outer, EXTERIOR_TOL_M, [])
            if length <= 0.0:
                continue
            (ax, ay), (bx, by) = edge
            b = bearing_bin(compass_bearing_deg(by - ay, -(bx - ax), north_angle_deg))
            lengths[b] = lengths.get(b, 0.0) + length
        if lengths:
            out[r.id] = lengths
    return out


def _shares(lengths: Mapping[Bearing, float]) -> dict[Bearing, float] | None:
    total = math.fsum(lengths.get(b, 0.0) for b in BEARINGS)
    if total <= 0.0:
        return None
    return {b: lengths.get(b, 0.0) / total for b in BEARINGS}


def orientation_stats(plans: Sequence[PlanInput]) -> dict[str, OrientationStat]:
    """Scaled orientation preference per allowed type, from plans with a known north."""
    per_type: dict[str, dict[Bearing, float]] = {}
    plan_count: Counter[str] = Counter()
    overall: dict[Bearing, float] = {}
    for plan in plans:
        if plan.north_angle_deg is None:
            continue
        facades = room_facades(plan.metric, plan.north_angle_deg)
        types = {r.id: r.type for r in plan.metric.rooms}
        seen: set[str] = set()
        for rid in sorted(facades):
            lengths = facades[rid]
            t = types.get(rid)
            for b in BEARINGS:
                v = lengths.get(b, 0.0) * plan.weight
                overall[b] = overall.get(b, 0.0) + v
                if t is not None and allowed_type(t):
                    acc = per_type.setdefault(t, {})
                    acc[b] = acc.get(b, 0.0) + v
            if t is not None and allowed_type(t):
                seen.add(t)
        plan_count.update(seen)
    base = _shares(overall)
    out: dict[str, OrientationStat] = {}
    for t in sorted(per_type):
        share = _shares(per_type[t])
        if share is None or base is None:
            continue
        diff = {b: share[b] - base[b] for b in BEARINGS}
        m = max(abs(v) for v in diff.values())
        values = {b: (diff[b] / m if m > 1e-12 else 0.0) for b in BEARINGS}
        out[t] = OrientationStat(values=values, n_plans=plan_count[t])
    return out


# --------------------------------------------------------------------------- façade depth / width


def facade_stats(plans: Sequence[PlanInput]) -> dict[str, FacadeStat]:
    """Depth, façade width and façade length per m² of every allowed type (R.8).

    Plans of the shape fidelities (CAD, PDF_VECTOR) contribute, as for aspect / area; rooms
    without a façade edge add their area to the type's total with a façade length of 0.
    """
    out: dict[str, FacadeStat] = {}
    for plan in plans:
        if plan.topology.fidelity not in SHAPE_FIDELITIES:
            continue
        rooms = _rooms(plan.metric)
        if not rooms:
            continue
        outer = _outer_edges(rooms)
        for r in rooms:
            if not allowed_type(r.type) or r.type is None:
                continue
            st = out.setdefault(r.type, FacadeStat())
            area = float(r.geom.area)
            if area <= 0.0:
                continue
            st.area += area * plan.weight
            ccw = orient(r.geom, 1.0)
            best: tuple[float, float, tuple[float, float]] | None = None
            total = 0.0
            for edge in _ring_edges(ccw.exterior.coords):
                length = _facing([edge], outer, EXTERIOR_TOL_M, [])
                if length < MIN_FACADE_EDGE_M:
                    continue
                (ax, ay), (bx, by) = edge
                full = math.hypot(bx - ax, by - ay)
                total += min(length, full)
                if best is None or length > best[0]:
                    # inward normal of a counter-clockwise ring: left of the edge direction
                    best = (length, full, (-(by - ay) / full, (bx - ax) / full))
            if best is None:
                continue
            st.facade_len += total * plan.weight
            nx, ny = best[2]
            proj = [x * nx + y * ny for x, y in ccw.exterior.coords]
            st.depth.append((max(proj) - min(proj), plan.weight))
            st.width.append((min(best[0], best[1]), plan.weight))
    return {k: out[k] for k in sorted(out)}
