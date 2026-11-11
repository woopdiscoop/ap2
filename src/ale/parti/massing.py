"""Massing of a parti (Ticket G.2, RD section 4): wings sized from the programme, placed in
the buildable zone, one outline per floor."""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely import Polygon as ShPolygon
from shapely import box
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from ale.contracts.models import Program, SiteSpec
from ale.parti.genes import (
    GRID_M,
    Dropped,
    Parti,
)

__all__ = [
    "CIRC_SHARE",
    "CORE_H_M",
    "CORE_W_M",
    "FLOOR_H_M",
    "SIZE_TOL",
    "Massing",
    "Piece",
    "buildable_zone",
    "entrance_edge",
    "largest_polygon",
    "make_massing",
    "programme_need_m2",
    "snap",
]

CIRC_SHARE = 0.16
FLOOR_H_M = 3.5
SIZE_TOL = 0.10
CORE_W_M = 3.6
CORE_H_M = 4.8
_RATIOS = (0.5, 0.7, 0.9)
_EPS = 1e-6
Rect = tuple[float, float, float, float]


def largest_polygon(g: BaseGeometry) -> ShPolygon:
    """The largest polygon of a (multi)polygon geometry."""
    if isinstance(g, ShPolygon):
        return g
    polys = [x for x in getattr(g, "geoms", ()) if isinstance(x, ShPolygon)]
    if not polys:
        raise ValueError("no polygon in geometry")
    return max(polys, key=lambda x: x.area)


def snap(v: float) -> float:
    """``v`` rounded to the 0.60 m grid."""
    return round(round(v / GRID_M) * GRID_M, 6)


def _up(v: float) -> float:
    return round(math.ceil(v / GRID_M - 1e-9) * GRID_M, 6)


@dataclass(frozen=True)
class Piece:
    name: str
    rect: Rect  # global metres (x0, y0, x1, y1)
    dropped_on_top: bool = False

    @property
    def area(self) -> float:
        return (self.rect[2] - self.rect[0]) * (self.rect[3] - self.rect[1])

    @property
    def long_axis(self) -> str:
        w, h = self.rect[2] - self.rect[0], self.rect[3] - self.rect[1]
        return "x" if w >= h else "y"


@dataclass(frozen=True)
class Massing:
    """Sized and placed wings. ``outlines[k]`` is floor k (0 = ground); ``court`` the
    courtyard polygon(s) (open or enclosed), ``slit`` a one-cell cut used only to give the
    cell diagram a hole-free ring."""

    parti: Parti
    pieces: tuple[Piece, ...]
    outlines: tuple[ShPolygon, ...]
    zone: ShPolygon
    core: Rect
    court: BaseGeometry | None
    court_short_m: float
    forecourt: ShPolygon | None
    need_m2: float
    gross_m2: float
    slit: Rect | None
    arm_ratio: float

    @property
    def typical(self) -> ShPolygon:
        return self.outlines[0]

    @property
    def height_m(self) -> float:
        return self.parti.floors * FLOOR_H_M

    @property
    def size_error(self) -> float:
        return self.gross_m2 / self.need_m2 - 1.0


def programme_need_m2(program: Program) -> float:
    """Gross floor area implied by the programme: net / (1 - circulation share)."""
    net = sum(r.target_area_m2 * r.quantity for r in program.rooms)
    return net / (1.0 - CIRC_SHARE)


# ------------------------------------------------------------------------------- zone
def buildable_zone(site: SiteSpec) -> ShPolygon:
    """Plot minus the setback strips; party edges are built against (setback 0)."""
    ext = site.footprint.exterior
    plot = ShPolygon(ext, site.footprint.holes)
    n = len(ext)
    sb = site.setbacks or (0.0,) * n
    strips = []
    for i in range(n):
        s = 0.0 if i in site.party_edges else sb[i]
        if s <= 0:
            continue
        a, b = ext[i], ext[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy)
        nx, ny = -dy / ln * s, dx / ln * s
        strips.append(ShPolygon([a, b, (b[0] + nx, b[1] + ny), (a[0] + nx, a[1] + ny)]))
    return largest_polygon(plot.difference(unary_union(strips)) if strips else plot)


def entrance_edge(site: SiteSpec) -> int:
    """Plot edge of the main entrance (the access edge when none is given)."""
    from shapely import LineString, Point

    ents = [e for e in site.entrances if e.main] or list(site.entrances)
    if not ents:
        return site.access_edge
    ext = site.footprint.exterior
    pt = Point(ents[0].point)
    n = len(ext)
    d = [LineString([ext[i], ext[(i + 1) % n]]).distance(pt) for i in range(n)]
    return min(range(n), key=lambda i: (round(d[i], 9), i))


def _inward_normal(site: SiteSpec, edge: int) -> tuple[int, int]:
    ext = site.footprint.exterior
    a, b = ext[edge], ext[(edge + 1) % len(ext)]
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dx) >= abs(dy):
        return (0, 1 if dx > 0 else -1)
    return (-1 if dy > 0 else 1, 0)


# ------------------------------------------------------------------ local layouts
@dataclass(frozen=True)
class _Layout:
    pieces: list[tuple[str, Rect]]
    drop: str
    extent: tuple[float, float]
    court: list[Rect]
    court_short: float
    slit: Rect | None = None


def _layout(typ: str, length: float, arm: float, d: float, fingers: int, h_half: float) -> _Layout:
    """Pieces in the local frame (u along the long façades, v across, arms toward +v)."""
    L = length
    if typ == "bar":
        return _Layout([("bar", (0, 0, L, d))], "", (L, d), [], 1e9)
    if typ == "L":
        return _Layout(
            [("bar", (0, 0, L, d)), ("leg", (0, d, d, d + arm))], "leg", (L, d + arm), [], 1e9
        )
    if typ == "T":
        sx = snap((L - d) / 2)
        return _Layout(
            [("bar", (0, 0, L, d)), ("stem", (sx, d, sx + d, d + arm))],
            "stem",
            (L, d + arm),
            [],
            1e9,
        )
    if typ == "U":
        gap = L - 2 * d
        return _Layout(
            [("bar", (0, 0, L, d)), ("leg1", (0, d, d, d + arm)), ("leg2", (L - d, d, L, d + arm))],
            "leg2",
            (L, d + arm),
            [(d, d, L - d, d + arm)],
            min(gap, arm),
        )
    if typ == "comb":
        n = fingers
        xs = [snap(k * (L - d) / (n - 1)) for k in range(n)]
        pcs: list[tuple[str, Rect]] = [("bar", (0, 0, L, d))]
        pcs += [(f"finger{k + 1}", (x, d, x + d, d + arm)) for k, x in enumerate(xs)]
        court = [(xs[k] + d, d, xs[k + 1], d + arm) for k in range(n - 1)]
        gap = min(xs[k + 1] - xs[k] - d for k in range(n - 1))
        return _Layout(pcs, f"finger{n}", (L, d + arm), court, min(gap, arm))
    if typ == "courtyard":
        W = arm
        mid = snap(W / 2)
        return _Layout(
            [
                ("south", (0, 0, L, d)),
                ("north", (0, W - d, L, W)),
                ("west", (0, d, d, W - d)),
                ("east", (L - d, d, L, W - d)),
            ],
            "east",
            (L, W),
            [(d, d, L - d, W - d)],
            min(L - 2 * d, W - 2 * d),
            slit=(0, mid, d, mid + GRID_M),
        )
    # H: two legs and a crossbar
    M = arm
    ym = snap((M - d) / 2)
    return _Layout(
        [
            ("leg1", (0, 0, d, M)),
            ("leg2", (L - d, 0, L, M)),
            ("cross", (d, ym, L - d, ym + d)),
        ],
        "leg2",
        (L, M),
        [(d, 0, L - d, ym), (d, ym + d, L - d, M)],
        min(L - 2 * d, ym, M - ym - d),
    )


def _local_area(lay: _Layout, floors: int, terrace: bool) -> float:
    full = sum((r[2] - r[0]) * (r[3] - r[1]) for _, r in lay.pieces)
    if not terrace or not lay.drop:
        return full * floors
    drop = next(r for n, r in lay.pieces if n == lay.drop)
    return full * floors - (drop[2] - drop[0]) * (drop[3] - drop[1])


def _to_global(r: Rect, ev: float, ori: int, sv: int) -> Rect:
    """Local rect → global rect (origin at the building's lower-left corner)."""
    u0, v0, u1, v1 = r
    if sv < 0:
        v0, v1 = ev - v1, ev - v0
    return (u0, v0, u1, v1) if ori == 0 else (v0, u0, v1, u1)


def make_massing(
    p: Parti, site: SiteSpec, program: Program, zone: ShPolygon | None = None
) -> Massing | Dropped:
    """Size, place and check the massing of ``p``; ``Dropped`` (with the reason) if it fails."""
    zone = zone if zone is not None else buildable_zone(site)
    need = programme_need_m2(program)
    zx0, zy0, zx1, zy1 = zone.bounds
    ori = p.orientation_deg
    lim_u, lim_v = (zx1 - zx0, zy1 - zy0) if ori == 0 else (zy1 - zy0, zx1 - zx0)
    height = p.floors * FLOOR_H_M
    d = p.wing_depth_m
    n_in = _inward_normal(site, p.entrance_side)
    # arms point away from the entrance street when it faces the across-axis
    if ori == 0:
        sv = 1 if n_in[1] >= 0 else -1
        across_axis = n_in[1] != 0
    else:
        sv = 1 if n_in[0] >= 0 else -1
        across_axis = n_in[0] != 0
    if not across_axis:
        sv = 1
    reason = "aucune taille ne tient dans la zone constructible"
    for ratio in _RATIOS:
        best: tuple[float, _Layout] | None = None
        n_steps = int(lim_u / GRID_M)
        for k in range(int(2 * d / GRID_M), n_steps + 1):
            length = round(k * GRID_M, 6)
            arm = snap(max(d, ratio * length)) if p.typology != "bar" else 0.0
            if p.typology == "courtyard":
                arm = snap(max(2 * d + GRID_M, ratio * length + d))
            if p.typology == "H":
                arm = snap(max(d + 2 * GRID_M, ratio * length + d))
            lay = _layout(p.typology, length, arm, d, p.fingers, 0.0)
            if lay.extent[0] > lim_u + _EPS or lay.extent[1] > lim_v + _EPS:
                continue
            area = _local_area(lay, p.floors, p.terrace)
            err = abs(area / need - 1.0)
            if lay.court_short + _EPS < height / 2:
                reason = (
                    f"cour trop étroite : petit côté {lay.court_short:.1f} m < H/2 = "
                    f"{height / 2:.1f} m"
                )
                continue
            if best is None or err < best[0] - 1e-12:
                best = (err, lay)
            if area > need * (1 + SIZE_TOL) * 1.5:
                break
        if best is None:
            continue
        if best[0] > SIZE_TOL:
            reason = f"surface hors de ±{SIZE_TOL:.0%} du besoin (meilleur écart {best[0]:+.1%})"
            continue
        return _place(p, site, zone, best[1], sv, need, ratio) or Dropped(
            p, "ne tient pas dans la zone constructible"
        )
    return Dropped(p, reason)


def _place(
    p: Parti, site: SiteSpec, zone: ShPolygon, lay: _Layout, sv: int, need: float, ratio: float
) -> Massing | None:
    zx0, zy0, zx1, zy1 = zone.bounds
    ori = p.orientation_deg
    eu, ev = lay.extent
    gx, gy = (eu, ev) if ori == 0 else (ev, eu)
    n_in = _inward_normal(site, p.entrance_side)
    fc_edge = p.forecourt_edge
    push = {(0, 1): 0.0, (0, -1): 0.0, (1, 0): 0.0, (-1, 0): 0.0}
    if fc_edge is not None:
        push[_inward_normal(site, fc_edge)] = p.forecourt_m

    def axis(
        lo: float, hi: float, g: float, n_min: tuple[int, int], n_max: tuple[int, int]
    ) -> float:
        # flush against the entrance street (n_in points inward from it) plus forecourt
        if n_in == n_min:
            return _up(lo + push[n_min])
        if n_in == n_max:
            return round(math.floor((hi - g - push[n_max]) / GRID_M + 1e-9) * GRID_M, 6)
        lo_f, hi_f = _up(lo + push[n_min]), hi - push[n_max] - g
        return round(math.floor((lo_f + hi_f) / 2 / GRID_M) * GRID_M, 6)

    ox = axis(zx0, zx1, gx, (1, 0), (-1, 0))
    oy = axis(zy0, zy1, gy, (0, 1), (0, -1))

    def g(r: Rect) -> Rect:
        a, b, c, d_ = _to_global(r, ev, ori, sv)
        return (round(a + ox, 6), round(b + oy, 6), round(c + ox, 6), round(d_ + oy, 6))

    pieces = tuple(Piece(n, g(r), n == lay.drop and p.terrace) for n, r in lay.pieces)
    full = _union(pieces, False)
    if not zone.buffer(_EPS).covers(full):
        return None
    top = _union(pieces, True) if p.terrace else full
    outlines = tuple(full if k < p.floors - 1 else top for k in range(p.floors))
    for upper, lower in zip(outlines[1:], outlines[:-1], strict=False):
        if not lower.buffer(_EPS).covers(upper):
            return None
    gross = sum(o.area for o in outlines)
    core = _core(p, pieces, lay)
    if core is None:
        return None
    court: BaseGeometry | None = None
    if lay.court:
        court = unary_union([box(*g(r)) for r in lay.court])
    slit = g(lay.slit) if lay.slit else None
    forecourt = _forecourt(p, site, zone, full)
    if p.forecourt_m > 0 and forecourt is None:
        return None
    return Massing(
        p, pieces, outlines, zone, core, court, lay.court_short, forecourt, need, gross, slit, ratio
    )


def _union(pieces: tuple[Piece, ...], top: bool) -> ShPolygon:
    parts = [box(*pc.rect) for pc in pieces if not (top and pc.dropped_on_top)]
    poly = largest_polygon(unary_union(parts))
    return orient(
        largest_polygon(ShPolygon(poly.exterior, [r.coords for r in poly.interiors]).simplify(0)),
        1.0,
    )


def _core(p: Parti, pieces: tuple[Piece, ...], lay: _Layout) -> Rect | None:
    kept = [pc for pc in pieces if not pc.dropped_on_top]
    union_kept = unary_union([box(*pc.rect) for pc in kept])
    if p.core_position == "junction":
        pt = None
        for i, a in enumerate(kept):
            for b in kept[i + 1 :]:
                inter = box(*a.rect).buffer(1e-4).intersection(box(*b.rect).buffer(1e-4))
                if not inter.is_empty:
                    pt = (inter.centroid.x, inter.centroid.y)
                    break
            if pt:
                break
        if pt is None:
            return None
    else:
        main = max(
            kept,
            key=lambda pc: (max(pc.rect[2] - pc.rect[0], pc.rect[3] - pc.rect[1]), -len(pc.name)),
        )
        x0, y0, x1, y1 = main.rect
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if p.core_position == "end":
            if main.long_axis == "x":
                cx = x1 - CORE_W_M / 2 - GRID_M
            else:
                cy = y1 - CORE_W_M / 2 - GRID_M
        pt = (cx, cy)
    rect = (
        snap(pt[0] - CORE_W_M / 2),
        snap(pt[1] - CORE_H_M / 2),
        0.0,
        0.0,
    )
    rect = (rect[0], rect[1], round(rect[0] + CORE_W_M, 6), round(rect[1] + CORE_H_M, 6))
    if not union_kept.buffer(_EPS).covers(box(*rect)):
        # try the other orientation of the core, then give up
        alt = (snap(pt[0] - CORE_H_M / 2), snap(pt[1] - CORE_W_M / 2))
        rect2 = (alt[0], alt[1], round(alt[0] + CORE_H_M, 6), round(alt[1] + CORE_W_M, 6))
        if not union_kept.buffer(_EPS).covers(box(*rect2)):
            return None
        return rect2
    return rect


def _forecourt(p: Parti, site: SiteSpec, zone: ShPolygon, full: ShPolygon) -> ShPolygon | None:
    edge = p.forecourt_edge
    if edge is None:
        return None
    zx0, zy0, zx1, zy1 = zone.bounds
    bx0, by0, bx1, by1 = full.bounds
    n = _inward_normal(site, edge)
    if n == (0, 1):
        r = box(bx0, zy0, bx1, by0)
    elif n == (0, -1):
        r = box(bx0, by1, bx1, zy1)
    elif n == (1, 0):
        r = box(zx0, by0, bx0, by1)
    else:
        r = box(bx1, by0, zx1, by1)
    inter = r.intersection(zone)
    if inter.is_empty or inter.area < 1.0:
        return None
    return largest_polygon(inter)
