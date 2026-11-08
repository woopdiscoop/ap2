"""Wall extraction (native units): width polylines and parallel-pair centrelines.

* An LWPOLYLINE/POLYLINE with a constant width > 0 gives one wall per segment
  (centreline = the polyline segment, thickness = the width).
* LINE / polyline segments on WALL layers are paired: parallel (≤ 1°), overlapping by
  ≥ 50 % of the shorter one, 0.05-0.60 m apart. A pair gives one wall on the midline of
  the overlap with thickness = the distance. A segment may pair with several partners on
  disjoint parts of its length (a long outer face against inner faces split by a
  partition). Collinear paired walls of equal thickness separated by ≤ 0.60 m are merged.
* Unpaired segments become walls with thickness ``None``; the unpaired leftovers of a
  partly paired segment are kept only when ≥ 0.60 m long (shorter ones are corner and
  junction artefacts).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import shapely

from ale.contracts.geometry import LineString
from ale.contracts.models import Wall
from ale.guards import bounded

__all__ = [
    "PAIR_ANGLE_DEG",
    "PAIR_MAX_M",
    "PAIR_MIN_M",
    "Pt",
    "Seg",
    "WallResult",
    "WidthPolyline",
    "extract_walls",
]

Pt = tuple[float, float]
Seg = tuple[Pt, Pt]

PAIR_ANGLE_DEG = 1.0
PAIR_MIN_M = 0.05
PAIR_MAX_M = 0.60
PAIR_MIN_OVERLAP = 0.5
_MERGE_OFFSET_M = 0.01
_MERGE_THICKNESS_M = 0.01
_OCCUPIED_TOL = 0.1  # share of a new overlap that may already be occupied
_TIME_BUDGET_S = 30.0
_MAX_MERGE_WALLS = 5000


@dataclass(frozen=True)
class WidthPolyline:
    """A polyline drawn with a constant width > 0 (native units)."""

    points: tuple[Pt, ...]
    closed: bool
    width: float


@dataclass
class WallResult:
    """Walls plus the face linework used to polygonize rooms."""

    walls: list[Wall] = field(default_factory=list)
    face_lines: list[Seg] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _wall(a: Pt, b: Pt, thickness: float | None) -> Wall | None:
    if a == b:
        return None
    return Wall(centerline=LineString(coords=(a, b)), thickness=thickness)


def _width_walls(polys: Sequence[WidthPolyline], out: WallResult) -> None:
    bands: list[shapely.Geometry] = []
    for wp in polys:
        pts = list(wp.points)
        if wp.closed and len(pts) > 2 and pts[0] != pts[-1]:
            pts.append(pts[0])
        for a, b in itertools.pairwise(pts):
            w = _wall(a, b, wp.width)
            if w is not None:
                out.walls.append(w)
        dedup = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
        if len(dedup) < 2:
            continue
        line = shapely.LineString(dedup)
        if wp.closed and len(dedup) >= 4 and dedup[0] == dedup[-1]:
            line = shapely.LinearRing(dedup)
        bands.append(line.buffer(wp.width / 2.0, cap_style="flat", join_style="mitre"))
    if not bands:
        return
    union = shapely.unary_union(bands)
    boundary = union.boundary
    for geom in getattr(boundary, "geoms", [boundary]):
        coords = list(geom.coords)
        for a, b in itertools.pairwise(coords):
            pa, pb = (float(a[0]), float(a[1])), (float(b[0]), float(b[1]))
            if pa != pb:
                out.face_lines.append((pa, pb))


def _interval_free(occupied: list[tuple[float, float]], lo: float, hi: float) -> bool:
    length = hi - lo
    used = 0.0
    for a, b in occupied:
        used += max(0.0, min(b, hi) - max(a, lo))
    return used <= _OCCUPIED_TOL * length


def _leftovers(occupied: list[tuple[float, float]], length: float) -> list[tuple[float, float]]:
    pieces: list[tuple[float, float]] = []
    cursor = 0.0
    for a, b in sorted(occupied):
        if a > cursor:
            pieces.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < length:
        pieces.append((cursor, length))
    return pieces


def _pair_segments(
    segs: Sequence[Seg], m_per_unit: float, out: WallResult
) -> tuple[list[tuple[Pt, Pt, float]], list[Seg]]:
    """Return (paired walls as (a, b, thickness), unpaired pieces)."""
    n = len(segs)
    p0 = np.array([s[0] for s in segs], dtype=float).reshape(n, 2)
    p1 = np.array([s[1] for s in segs], dtype=float).reshape(n, 2)
    vec = p1 - p0
    length = np.hypot(vec[:, 0], vec[:, 1])
    u = vec / length[:, None]
    dmin, dmax = PAIR_MIN_M / m_per_unit, PAIR_MAX_M / m_per_unit
    lines = shapely.linestrings(np.stack([p0, p1], axis=1))
    tree = shapely.STRtree(np.asarray(lines))
    qi, qj = tree.query(lines, predicate="dwithin", distance=dmax)
    keep = qi < qj
    qi, qj = qi[keep], qj[keep]
    sin_tol = math.sin(math.radians(PAIR_ANGLE_DEG))
    cross_u = np.abs(u[qi, 0] * u[qj, 1] - u[qi, 1] * u[qj, 0])
    ok = cross_u <= sin_tol
    qi, qj = qi[ok], qj[ok]
    # long / short of each candidate pair
    swap = length[qi] < length[qj]
    li = np.where(swap, qj, qi)
    si = np.where(swap, qi, qj)
    ul = u[li]
    mid_s = (p0[si] + p1[si]) / 2.0
    rel = mid_s - p0[li]
    signed_d = ul[:, 0] * rel[:, 1] - ul[:, 1] * rel[:, 0]
    dist = np.abs(signed_d)
    t0 = np.einsum("ij,ij->i", p0[si] - p0[li], ul)
    t1 = np.einsum("ij,ij->i", p1[si] - p0[li], ul)
    lo = np.maximum(np.minimum(t0, t1), 0.0)
    hi = np.minimum(np.maximum(t0, t1), length[li])
    overlap = hi - lo
    ok = (dist >= dmin) & (dist <= dmax) & (overlap >= PAIR_MIN_OVERLAP * length[si])
    order = np.lexsort((qj[ok], qi[ok], dist[ok]))
    cand = [
        (int(li[ok][k]), int(si[ok][k]), float(signed_d[ok][k]), float(lo[ok][k]), float(hi[ok][k]))
        for k in order
    ]
    occupied: list[list[tuple[float, float]]] = [[] for _ in range(n)]
    paired: list[tuple[Pt, Pt, float]] = []
    with bounded(
        max(1, len(cand)) + 1, _TIME_BUDGET_S, label="cad.walls.pair", on_exhaust="stop"
    ) as budget:
        for il, is_, sd, a, b in cand:
            if not budget.tick():
                out.warnings.append("wall pairing stopped: budget exhausted")
                break
            pa = p0[il] + u[il] * a
            pb = p0[il] + u[il] * b
            sa = float(np.dot(pa - p0[is_], u[is_]))
            sb = float(np.dot(pb - p0[is_], u[is_]))
            s_lo, s_hi = max(0.0, min(sa, sb)), min(float(length[is_]), max(sa, sb))
            if s_hi <= s_lo:
                continue
            if not (
                _interval_free(occupied[il], a, b) and _interval_free(occupied[is_], s_lo, s_hi)
            ):
                continue
            occupied[il].append((a, b))
            occupied[is_].append((s_lo, s_hi))
            normal = np.array([-u[il, 1], u[il, 0]])
            shift = normal * (sd / 2.0)
            ca, cb = pa + shift, pb + shift
            paired.append(((float(ca[0]), float(ca[1])), (float(cb[0]), float(cb[1])), abs(sd)))
    unpaired: list[Seg] = []
    for k in range(n):
        if not occupied[k]:
            unpaired.append(segs[k])
            continue
        for a, b in _leftovers(occupied[k], float(length[k])):
            if b - a >= dmax:
                pa = p0[k] + u[k] * a
                pb = p0[k] + u[k] * b
                unpaired.append(((float(pa[0]), float(pa[1])), (float(pb[0]), float(pb[1]))))
    return paired, unpaired


def _try_merge(
    w1: tuple[Pt, Pt, float], w2: tuple[Pt, Pt, float], m_per_unit: float
) -> tuple[Pt, Pt, float] | None:
    (a1, b1, t1), (a2, b2, t2) = w1, w2
    if abs(t1 - t2) > _MERGE_THICKNESS_M / m_per_unit:
        return None
    dx, dy = b1[0] - a1[0], b1[1] - a1[1]
    l1 = math.hypot(dx, dy)
    ex, ey = b2[0] - a2[0], b2[1] - a2[1]
    l2 = math.hypot(ex, ey)
    if l1 == 0.0 or l2 == 0.0:
        return None
    ux, uy = dx / l1, dy / l1
    if abs(ux * ey / l2 - uy * ex / l2) > math.sin(math.radians(PAIR_ANGLE_DEG)):
        return None
    tol = _MERGE_OFFSET_M / m_per_unit
    for p in (a2, b2):
        if abs(ux * (p[1] - a1[1]) - uy * (p[0] - a1[0])) > tol:
            return None
    s_a = (a2[0] - a1[0]) * ux + (a2[1] - a1[1]) * uy
    s_b = (b2[0] - a1[0]) * ux + (b2[1] - a1[1]) * uy
    lo2, hi2 = min(s_a, s_b), max(s_a, s_b)
    gap = max(lo2 - l1, 0.0 - hi2)
    if gap > PAIR_MAX_M / m_per_unit:
        return None
    lo, hi = min(0.0, lo2), max(l1, hi2)
    pa = (a1[0] + ux * lo, a1[1] + uy * lo)
    pb = (a1[0] + ux * hi, a1[1] + uy * hi)
    thickness = (t1 * l1 + t2 * l2) / (l1 + l2)
    return (pa, pb, thickness)


def _merge_collinear(
    walls: list[tuple[Pt, Pt, float]], m_per_unit: float, out: WallResult
) -> list[tuple[Pt, Pt, float]]:
    if len(walls) > _MAX_MERGE_WALLS:
        out.warnings.append(f"collinear wall merge skipped ({len(walls)} paired walls)")
        return walls
    items = list(walls)
    with bounded(len(items) + 1, _TIME_BUDGET_S, label="cad.walls.merge", on_exhaust="stop") as b:
        changed = True
        while changed and b.tick():
            changed = False
            i = 0
            while i < len(items):
                j = i + 1
                while j < len(items):
                    merged = _try_merge(items[i], items[j], m_per_unit)
                    if merged is None:
                        j += 1
                        continue
                    items[i] = merged
                    del items[j]
                    changed = True
                i += 1
    return items


def extract_walls(
    segments: Sequence[Seg], width_polylines: Sequence[WidthPolyline], m_per_unit: float
) -> WallResult:
    """Extract walls; ``m_per_unit`` converts the metric thresholds to native units."""
    out = WallResult()
    _width_walls(width_polylines, out)
    segs = [s for s in segments if s[0] != s[1]]
    out.face_lines.extend(segs)
    if segs:
        paired, unpaired = _pair_segments(segs, m_per_unit, out)
        for a, b, t in _merge_collinear(paired, m_per_unit, out):
            w = _wall(a, b, t)
            if w is not None:
                out.walls.append(w)
        for a, b in unpaired:
            w = _wall(a, b, None)
            if w is not None:
                out.walls.append(w)
    return out
