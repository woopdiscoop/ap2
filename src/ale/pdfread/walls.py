"""Walls and door arcs of a vector-PDF page (PDF points, ``Y_DOWN``).

Walls come from three sources (all thresholds in points):

* **Parallel pairs**: stroked line segments, parallel within 1°, overlapping by ≥ 50 % of
  the shorter one, 2-25 pt apart, give one wall on the midline of the overlap with
  thickness = the distance (greedy, nearest pairs first; a segment may pair with several
  partners on disjoint parts of its length). Collinear pieces are *not* merged.
* **Filled shapes**: filled rectangles / quads / closed polygons whose minimum rotated
  rectangle has a short side of 2-25 pt and a long side ≥ 5x the short side give one wall
  (centreline = long axis, thickness = short side).
* **Thick strokes**: an unpaired segment whose stroke width is ≥ 1.5 x the median stroke
  width gives a wall (centreline = the segment, thickness = the stroke width).

Walls shorter than 15 pt are dropped. Unpaired thin segments are *not* walls (furniture,
hatching, dimensions). The wall *faces* used to polygonize rooms are the paired parts of
the segments (extended by 0.5 pt at both ends so that corners still node), the outline
of the union of filled walls and the outline of thick-stroke bands.

Door arcs: a chain of cubic Béziers approximating a circular arc of 80-100° sweep with
radius 15-60 pt whose centre (the hinge) lies within 25 pt of a wall centreline is a
door of width = radius. Its segment runs from the hinge to the arc end nearest to a
wall; ``host_wall`` = the wall nearest to the segment's midpoint (within one radius).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import shapely

from ale.contracts.enums import OpeningKind
from ale.contracts.geometry import LineString
from ale.contracts.models import Opening, Wall
from ale.guards import bounded

__all__ = [
    "ARC_MAX_PT",
    "ARC_MIN_PT",
    "MIN_WALL_LENGTH_PT",
    "PAIR_ANGLE_DEG",
    "PAIR_MAX_PT",
    "PAIR_MIN_OVERLAP",
    "PAIR_MIN_PT",
    "THICK_STROKE_FACTOR",
    "ArcDoor",
    "Bezier",
    "FilledShape",
    "Pt",
    "Seg",
    "StrokeSeg",
    "WallResult",
    "build_doors",
    "door_closures",
    "extract_walls",
    "fit_arc",
    "merged_wall_count",
]

Pt = tuple[float, float]
Seg = tuple[Pt, Pt]
Bezier = tuple[Pt, Pt, Pt, Pt]

PAIR_ANGLE_DEG = 1.0
PAIR_MIN_PT = 2.0
PAIR_MAX_PT = 25.0
PAIR_MIN_OVERLAP = 0.5
FILLED_ASPECT_MIN = 5.0
THICK_STROKE_FACTOR = 1.5
MIN_WALL_LENGTH_PT = 15.0
ARC_MIN_PT = 15.0
ARC_MAX_PT = 60.0
ARC_SWEEP_DEG = (80.0, 100.0)
ARC_RADIAL_TOL = 0.03  # max |d - r| / r of the sampled Bézier points
FACE_EXTENSION_PT = 0.5
_OCCUPIED_TOL = 0.1
_TIME_BUDGET_S = 10.0
_ANGLE_BINS = 180
_MAX_CANDIDATES = 2_000_000


@dataclass(frozen=True)
class StrokeSeg:
    """A stroked line segment and its stroke width (points)."""

    seg: Seg
    width: float


@dataclass(frozen=True)
class FilledShape:
    """A filled closed outline (points, open ring)."""

    points: tuple[Pt, ...]


@dataclass(frozen=True)
class ArcDoor:
    """A circular arc fitted to a Bézier chain (points)."""

    center: Pt
    radius: float
    start: Pt
    end: Pt
    sweep_deg: float


@dataclass
class WallResult:
    """Walls, the face linework for polygonize and the wall material (for face filtering)."""

    walls: list[Wall] = field(default_factory=list)
    face_lines: list[Seg] = field(default_factory=list)
    material: list[shapely.Geometry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _len(a: Pt, b: Pt) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _extend(seg: Seg, d: float) -> Seg:
    (ax, ay), (bx, by) = seg
    n = _len(seg[0], seg[1])
    if n == 0.0:
        return seg
    ux, uy = (bx - ax) / n * d, (by - ay) / n * d
    return ((ax - ux, ay - uy), (bx + ux, by + uy))


def _add_wall(out: WallResult, a: Pt, b: Pt, thickness: float) -> bool:
    if _len(a, b) < MIN_WALL_LENGTH_PT or not (math.isfinite(thickness) and thickness > 0.0):
        return False
    out.walls.append(Wall(centerline=LineString(coords=(a, b)), thickness=thickness))
    return True


def _band(a: Pt, b: Pt, thickness: float) -> shapely.Geometry:
    return shapely.LineString([a, b]).buffer(thickness / 2.0, cap_style="flat")


def _outline_segments(geom: shapely.Geometry) -> list[Seg]:
    out: list[Seg] = []
    if shapely.is_empty(geom):
        return out
    boundary = shapely.boundary(geom)
    for part in getattr(boundary, "geoms", [boundary]):
        coords = [(float(c[0]), float(c[1])) for c in part.coords]
        out.extend((p, q) for p, q in itertools.pairwise(coords) if p != q)
    return out


# --------------------------------------------------------------------------- pairing


def _candidate_pairs(p0: np.ndarray, p1: np.ndarray, lines: np.ndarray) -> np.ndarray:
    """(k, 2) index pairs i != j of segments within PAIR_MAX_PT and in adjacent angle bins."""
    vec = p1 - p0
    ang = np.degrees(np.arctan2(vec[:, 1], vec[:, 0])) % 180.0
    bins = np.floor(ang).astype(np.int64) % _ANGLE_BINS
    members = [np.flatnonzero(bins == b) for b in range(_ANGLE_BINS)]
    chunks: list[np.ndarray] = []
    total = 0
    for b in range(_ANGLE_BINS):
        own = members[b]
        if own.size == 0:
            continue
        nxt = members[(b + 1) % _ANGLE_BINS]
        pool = np.concatenate([own, nxt]) if nxt.size else own
        tree = shapely.STRtree(lines[pool])
        qi, qj = tree.query(lines[own], predicate="dwithin", distance=PAIR_MAX_PT)
        gi, gj = own[qi], pool[qj]
        keep = (gi != gj) & ((bins[gj] != b) | (gi < gj))
        pair = np.stack([gi[keep], gj[keep]], axis=1)
        total += len(pair)
        if total > _MAX_CANDIDATES:
            break
        chunks.append(pair)
    if not chunks:
        return np.zeros((0, 2), dtype=np.int64)
    return np.concatenate(chunks)


def _interval_free(occupied: list[tuple[float, float]], lo: float, hi: float) -> bool:
    used = sum(max(0.0, min(b, hi) - max(a, lo)) for a, b in occupied)
    return used <= _OCCUPIED_TOL * (hi - lo)


Intervals = list[list[tuple[float, float]]]


def _pair(segs: Sequence[Seg], out: WallResult) -> tuple[list[tuple[Pt, Pt, float]], Intervals]:
    """Paired walls ``(a, b, thickness)`` and, per segment, its paired parts (arc length)."""
    n = len(segs)
    occupied: Intervals = [[] for _ in range(n)]
    if n < 2:
        return [], occupied
    p0 = np.array([s[0] for s in segs], dtype=float)
    p1 = np.array([s[1] for s in segs], dtype=float)
    vec = p1 - p0
    length = np.hypot(vec[:, 0], vec[:, 1])
    u = vec / length[:, None]
    lines = shapely.linestrings(np.stack([p0, p1], axis=1))
    cand = _candidate_pairs(p0, p1, np.asarray(lines))
    if len(cand) >= _MAX_CANDIDATES:
        out.warnings.append("wall pairing truncated: too many candidate pairs")
    if len(cand) == 0:
        return [], occupied
    qi, qj = cand[:, 0], cand[:, 1]
    cross_u = np.abs(u[qi, 0] * u[qj, 1] - u[qi, 1] * u[qj, 0])
    ok = cross_u <= math.sin(math.radians(PAIR_ANGLE_DEG))
    qi, qj = qi[ok], qj[ok]
    swap = length[qi] < length[qj]
    li = np.where(swap, qj, qi)
    si = np.where(swap, qi, qj)
    ul = u[li]
    rel = (p0[si] + p1[si]) / 2.0 - p0[li]
    signed_d = ul[:, 0] * rel[:, 1] - ul[:, 1] * rel[:, 0]
    dist = np.abs(signed_d)
    t0 = np.einsum("ij,ij->i", p0[si] - p0[li], ul)
    t1 = np.einsum("ij,ij->i", p1[si] - p0[li], ul)
    lo = np.maximum(np.minimum(t0, t1), 0.0)
    hi = np.minimum(np.maximum(t0, t1), length[li])
    overlap = hi - lo
    ok = (
        (dist >= PAIR_MIN_PT)
        & (dist <= PAIR_MAX_PT)
        & (overlap >= PAIR_MIN_OVERLAP * length[si])
        & (overlap > 0.0)
    )
    order = np.lexsort((si[ok], li[ok], dist[ok]))
    li, si, sd, lo, hi = (
        li[ok][order],
        si[ok][order],
        signed_d[ok][order],
        lo[ok][order],
        hi[ok][order],
    )
    paired: list[tuple[Pt, Pt, float]] = []
    with bounded(
        len(li) + 1, _TIME_BUDGET_S, label="pdfread.walls.pair", on_exhaust="stop"
    ) as budget:
        for k in range(len(li)):
            if not budget.tick():
                out.warnings.append("wall pairing stopped: budget exhausted")
                break
            il, is_, a, b = int(li[k]), int(si[k]), float(lo[k]), float(hi[k])
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
            shift = np.array([-u[il, 1], u[il, 0]]) * (float(sd[k]) / 2.0)
            ca, cb = pa + shift, pb + shift
            paired.append(
                ((float(ca[0]), float(ca[1])), (float(cb[0]), float(cb[1])), abs(float(sd[k])))
            )
    return paired, occupied


def _paired_faces(seg: Seg, intervals: list[tuple[float, float]]) -> list[Seg]:
    """The paired parts of ``seg`` (merged intervals), each extended at both ends."""
    (ax, ay), (bx, by) = seg
    n = _len(seg[0], seg[1])
    ux, uy = (bx - ax) / n, (by - ay) / n
    merged: list[list[float]] = []
    for lo, hi in sorted(intervals):
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    d = FACE_EXTENSION_PT
    return [
        ((ax + ux * (lo - d), ay + uy * (lo - d)), (ax + ux * (hi + d), ay + uy * (hi + d)))
        for lo, hi in merged
    ]


# --------------------------------------------------------------------------- filled shapes


def _filled_wall(shape: FilledShape) -> tuple[Pt, Pt, float, shapely.Polygon] | None:
    if len(shape.points) < 3:
        return None
    poly = shapely.Polygon(shape.points)
    if not poly.is_valid or poly.area <= 0.0:
        return None
    mrr = poly.minimum_rotated_rectangle
    if not isinstance(mrr, shapely.Polygon):
        return None
    c = [(float(x), float(y)) for x, y in mrr.exterior.coords[:4]]
    s01, s12 = _len(c[0], c[1]), _len(c[1], c[2])
    width, length = min(s01, s12), max(s01, s12)
    if not (PAIR_MIN_PT <= width <= PAIR_MAX_PT) or length < FILLED_ASPECT_MIN * width:
        return None
    if s01 >= s12:  # long sides are c0-c1 and c2-c3
        a = ((c[0][0] + c[3][0]) / 2.0, (c[0][1] + c[3][1]) / 2.0)
        b = ((c[1][0] + c[2][0]) / 2.0, (c[1][1] + c[2][1]) / 2.0)
    else:
        a = ((c[0][0] + c[1][0]) / 2.0, (c[0][1] + c[1][1]) / 2.0)
        b = ((c[3][0] + c[2][0]) / 2.0, (c[3][1] + c[2][1]) / 2.0)
    return a, b, width, poly


def extract_walls(strokes: Sequence[StrokeSeg], filled: Sequence[FilledShape]) -> WallResult:
    """Walls of a page (see module docstring)."""
    out = WallResult()
    segs = [
        s
        for s in strokes
        if s.seg[0] != s.seg[1] and all(map(math.isfinite, (*s.seg[0], *s.seg[1])))
    ]
    paired, occupied = _pair([s.seg for s in segs], out)
    for a, b, t in paired:
        if _add_wall(out, a, b, t):
            out.material.append(_band(a, b, t))
    for s, iv in zip(segs, occupied, strict=True):
        out.face_lines.extend(_paired_faces(s.seg, iv))

    widths = sorted(s.width for s in segs)
    median = widths[len(widths) // 2] if widths else 0.0
    thick_bands: list[shapely.Geometry] = []
    for s, iv in zip(segs, occupied, strict=True):
        if iv or s.width <= 0.0 or s.width < THICK_STROKE_FACTOR * median:
            continue
        if _add_wall(out, s.seg[0], s.seg[1], s.width):
            thick_bands.append(_band(s.seg[0], s.seg[1], s.width))

    fills: list[shapely.Geometry] = []
    for shape in filled:
        fw = _filled_wall(shape)
        if fw is not None and _add_wall(out, fw[0], fw[1], fw[2]):
            fills.append(fw[3])
    for group in (thick_bands, fills):
        if group:
            union = shapely.unary_union(group)
            out.material.append(union)
            out.face_lines.extend(_outline_segments(union))
    return out


# --------------------------------------------------------------------------- door arcs


def _bezier_point(bz: Bezier, t: float) -> Pt:
    m = 1.0 - t
    w = (m * m * m, 3 * m * m * t, 3 * m * t * t, t * t * t)
    return (
        sum(wi * p[0] for wi, p in zip(w, bz, strict=True)),
        sum(wi * p[1] for wi, p in zip(w, bz, strict=True)),
    )


def _circumcircle(a: Pt, b: Pt, c: Pt) -> tuple[Pt, float] | None:
    d = 2.0 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-12:
        return None
    a2, b2, c2 = a[0] ** 2 + a[1] ** 2, b[0] ** 2 + b[1] ** 2, c[0] ** 2 + c[1] ** 2
    ux = (a2 * (b[1] - c[1]) + b2 * (c[1] - a[1]) + c2 * (a[1] - b[1])) / d
    uy = (a2 * (c[0] - b[0]) + b2 * (a[0] - c[0]) + c2 * (b[0] - a[0])) / d
    return (ux, uy), _len((ux, uy), a)


def fit_arc(chain: Sequence[Bezier]) -> ArcDoor | None:
    """Circular arc through a chain of Béziers (``None`` if it is not one)."""
    if not chain:
        return None
    samples: list[Pt] = [chain[0][0]]
    for bz in chain:
        samples.extend(_bezier_point(bz, t) for t in (0.25, 0.5, 0.75, 1.0))
    fit = _circumcircle(samples[0], samples[len(samples) // 2], samples[-1])
    if fit is None:
        return None
    (cx, cy), r = fit
    if not (math.isfinite(r) and r > 0.0):
        return None
    if any(abs(_len((cx, cy), p) - r) > ARC_RADIAL_TOL * r for p in samples):
        return None
    sweep = 0.0
    prev = math.atan2(samples[0][1] - cy, samples[0][0] - cx)
    for p in samples[1:]:
        cur = math.atan2(p[1] - cy, p[0] - cx)
        step = (cur - prev + math.pi) % (2.0 * math.pi) - math.pi
        sweep += step
        prev = cur
    return ArcDoor(
        center=(cx, cy),
        radius=r,
        start=samples[0],
        end=samples[-1],
        sweep_deg=abs(math.degrees(sweep)),
    )


def _is_door_arc(arc: ArcDoor) -> bool:
    return (
        ARC_MIN_PT <= arc.radius <= ARC_MAX_PT
        and ARC_SWEEP_DEG[0] <= arc.sweep_deg <= ARC_SWEEP_DEG[1]
    )


def build_doors(chains: Sequence[Sequence[Bezier]], walls: Sequence[Wall]) -> list[Opening]:
    """Door openings from Bézier chains next to a wall; ``host_wall`` indexes ``walls``."""
    if not walls:
        return []
    lines = [shapely.LineString(w.centerline.coords) for w in walls]

    def nearest(p: Pt) -> tuple[int, float]:
        pt = shapely.Point(p)
        dists = [float(ln.distance(pt)) for ln in lines]
        k = min(range(len(dists)), key=dists.__getitem__)
        return k, dists[k]

    out: list[Opening] = []
    for chain in chains:
        arc = fit_arc(chain)
        if arc is None or not _is_door_arc(arc):
            continue
        if nearest(arc.center)[1] > PAIR_MAX_PT:
            continue
        end = arc.start if nearest(arc.start)[1] <= nearest(arc.end)[1] else arc.end
        if end == arc.center:
            continue  # pragma: no cover - radius > 0 makes this impossible
        mid = ((arc.center[0] + end[0]) / 2.0, (arc.center[1] + end[1]) / 2.0)
        k, d = nearest(mid)
        out.append(
            Opening(
                kind=OpeningKind.DOOR,
                segment=LineString(coords=(arc.center, end)),
                width_native=arc.radius,
                host_wall=k if d <= arc.radius else None,
            )
        )
    return out


def door_closures(openings: Sequence[Opening], walls: Sequence[Wall]) -> list[Seg]:
    """Segments closing the wall faces across each door (for polygonize).

    Hosted door: two segments parallel to the host wall at ± thickness/2 spanning the
    door's projection on the wall, extended by 0.5 pt; unhosted: the door segment itself.
    """
    out: list[Seg] = []
    for op in openings:
        a, b = op.segment.coords[0], op.segment.coords[1]
        if op.host_wall is None:
            out.append(_extend((a, b), FACE_EXTENSION_PT))
            continue
        wall = walls[op.host_wall]
        (x0, y0), (x1, y1) = wall.centerline.coords[0], wall.centerline.coords[-1]
        n = _len((x0, y0), (x1, y1))
        ux, uy = (x1 - x0) / n, (y1 - y0) / n
        nx, ny = -uy, ux
        cx, cy = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
        sc = (cx - x0) * ux + (cy - y0) * uy
        half = op.width_native / 2.0 + FACE_EXTENSION_PT
        t = wall.thickness or 0.0
        for off in (0.0,) if t == 0.0 else (-t / 2.0, t / 2.0):
            p = (x0 + ux * (sc - half) + nx * off, y0 + uy * (sc - half) + ny * off)
            q = (x0 + ux * (sc + half) + nx * off, y0 + uy * (sc + half) + ny * off)
            out.append((p, q))
    return out


# --------------------------------------------------------------------------- merged count

MERGE_GAP_EXTRA_PT = 1.0


def _collinear_touching(a: Wall, b: Wall) -> bool:
    """Parallel within 1°, on one line (offset ≤ half the thicker wall + 1 pt), and
    overlapping or end to end with a gap ≤ the thicker wall's thickness + 1 pt."""
    (ax, ay), (bx, by) = a.centerline.coords[0], a.centerline.coords[-1]
    (cx, cy), (dx, dy) = b.centerline.coords[0], b.centerline.coords[-1]
    la, lb = _len((ax, ay), (bx, by)), _len((cx, cy), (dx, dy))
    if la == 0.0 or lb == 0.0:
        return False
    ux, uy = (bx - ax) / la, (by - ay) / la
    vx, vy = (dx - cx) / lb, (dy - cy) / lb
    if abs(ux * vy - uy * vx) > math.sin(math.radians(PAIR_ANGLE_DEG)):
        return False
    t = max(a.thickness or 0.0, b.thickness or 0.0)
    for px, py in ((cx, cy), (dx, dy)):
        if abs(ux * (py - ay) - uy * (px - ax)) > t / 2.0 + MERGE_GAP_EXTRA_PT:
            return False
    s0 = (cx - ax) * ux + (cy - ay) * uy
    s1 = (dx - ax) * ux + (dy - ay) * uy
    gap = max(min(s0, s1) - la, -max(s0, s1), 0.0)
    return gap <= t + MERGE_GAP_EXTRA_PT


def merged_wall_count(walls: Sequence[Wall]) -> int:
    """Number of walls once collinear touching pieces are merged (connected components)."""
    n = len(walls)
    if n == 0:
        return 0
    lines = [shapely.LineString(w.centerline.coords) for w in walls]
    tree = shapely.STRtree(lines)
    qi, qj = tree.query(lines, predicate="dwithin", distance=PAIR_MAX_PT + MERGE_GAP_EXTRA_PT)
    parent = list(range(n))

    def find(i: int) -> int:
        root = i
        for _ in range(n):  # bounded: a parent chain is at most n long
            if parent[root] == root:
                break
            root = parent[root]
        parent[i] = root
        return root

    for i, j in zip(qi.tolist(), qj.tolist(), strict=True):
        if i < j and _collinear_touching(walls[i], walls[j]):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[max(ri, rj)] = min(ri, rj)
    return len({find(i) for i in range(n)})
