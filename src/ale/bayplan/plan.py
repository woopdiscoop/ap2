"""Bay-first planning of one bar floor (Ticket M.4, RD section 4).

The section first (facade rows, corridors, central band), then heads (through room ``T`` and deep
rooms ``D``), then the facade rooms in whole or half bays and the band rooms. Everything is
deterministic (no randomness, no time budget). Lengths are integer modules; ``u`` runs along the
long side of the plate, ``v`` across it (a plate whose long side is ``y`` is planned transposed;
a plate whose only passing corridor is the reference one is planned mirrored).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from ale.contracts.config import AleConfig
from ale.contracts.geometry import ModuleRect
from ale.contracts.models import Layout, LayoutMetrics, PlacedRoom, RoomSpec, Rulebook
from ale.geometry.blocks import Consts
from ale.geometry.evaluate import evaluate
from ale.program.models import PreparedInput
from ale.stack.grid import Rhythm

from .catalogue import Shape, deviation, legal_aspect, rect_shape_ok

__all__ = ["BayResult", "NotEligible", "plan_bar"]

Rect = tuple[int, int, int, int]  # (u, v, du, dv)
_MAX_N = 48


class NotEligible(Exception):
    """The floor is not planned bay-first; ``reason`` is a French sentence."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


# ------------------------------------------------------------------------------ result
@dataclass(frozen=True)
class BayResult:
    """A planned floor and the figures the report needs (all lengths in metres or m2)."""

    layout: Layout
    kinds: dict[str, str]
    """Circulation instance id -> element kind (corridor, lien, palier, bout, entree, ...)."""
    tags: dict[str, str]
    """Room instance id -> shape tag (``F2``, ``D5.5``, ``B5``); reserve rooms are absent."""
    unplaced: tuple[str, ...]
    adjust: tuple[tuple[str, float, float], ...]
    """Rooms placed with a fallback shape: ``(id, target m2, placed m2)``."""
    reserve_ids: tuple[str, ...]
    section: dict[str, float]
    facade_bays_used: float
    facade_bays_available: float
    band_m_available: float
    notes: tuple[str, ...]
    groups: dict[str, str] = field(default_factory=dict)
    """Room instance id -> group (placed programme rooms)."""
    long_runs: tuple[tuple[str, int, int, int, int], ...] = ()
    """Facade runs ``(side, u0, u1, v0, v1)`` in the planning frame (for the tests)."""
    frame: dict[str, int] = field(default_factory=dict)


# ----------------------------------------------------------------------------- helpers
def _sub(r0: int, r1: int, s0: int, s1: int) -> list[tuple[int, int]]:
    """``[r0, r1]`` minus ``[s0, s1]`` as a list of intervals."""
    out: list[tuple[int, int]] = []
    if min(r1, s0) > r0:
        out.append((r0, min(r1, s0)))
    if r1 > max(r0, s1):
        out.append((max(r0, s1), r1))
    return out


def _merge(pieces: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Merge contiguous ``(a, b, v0, v1)`` pieces with equal v ranges (sorted by a)."""
    out: list[tuple[int, int, int, int]] = []
    for a, b, v0, v1 in sorted(pieces):
        if b <= a:
            continue
        if out and out[-1][1] == a and out[-1][2:] == (v0, v1):
            out[-1] = (out[-1][0], b, v0, v1)
        else:
            out.append((a, b, v0, v1))
    return out


# ----------------------------------------------------------------------------- items
class _Item:
    def __init__(self, iid: str, spec: RoomSpec, group: str, k: Consts, g: _Geom) -> None:
        self.iid = iid
        self.spec = spec
        self.group = group
        self.k = k
        self.g = g
        self.facade = spec.needs_facade
        self.target = spec.target_area_m2
        self._f: dict[int, list[Shape]] = {}
        self._b: list[Shape] | None = None
        self._dt: list[Shape] | None = None
        self._fb: Shape | bool | None = False

    def _pref(self, s: Shape) -> tuple[float, int, int]:
        return (round(deviation(self.k, self.spec, s.w, s.d), 6), s.n % 2, s.n or s.w)

    def f_options(self, depth: int) -> list[Shape]:
        if depth not in self._f:
            half = self.g.half
            out = [
                Shape("F", n, n * half, depth)
                for n in range(1, _MAX_N)
                if rect_shape_ok(self.k, self.spec, n * half, depth)
            ]
            self._f[depth] = sorted(out, key=self._pref)
        return self._f[depth]

    def band_options(self) -> list[Shape]:
        if self._b is None:
            g = self.g
            out: list[Shape] = []
            if not self.facade:
                for w in range(6, 2 * g.band + 1, 6):
                    if rect_shape_ok(self.k, self.spec, w, g.band):
                        out.append(Shape("B", 0, w, g.band))
                if g.band >= 48 and g.band % 2 == 0:
                    for w in range(6, 2 * (g.band // 2) + 1, 6):
                        if rect_shape_ok(self.k, self.spec, w, g.band // 2):
                            out.append(Shape("b", 0, w, g.band // 2))
            self._b = sorted(out, key=lambda s: (s.kind == "b", *self._pref(s)))
        return self._b

    def head_kinds(self) -> list[tuple[str, int]]:
        """``(kind, depth)`` of the head shapes this room may take."""
        g = self.g
        out = [("D", g.mE)]
        if self.facade:
            out.append(("T", g.dp))
        return out

    def has_head_shape(self) -> bool:
        if self._dt is None:
            half = self.g.half
            self._dt = [
                Shape(kind, n, n * half, d)
                for kind, d in self.head_kinds()
                for n in range(1, _MAX_N)
                if rect_shape_ok(self.k, self.spec, n * half, d)
            ]
        return bool(self._dt)

    def admissible_any(self) -> bool:
        return bool(self.f_options(self.g.df) or self.band_options() or self.has_head_shape())

    def fallback(self) -> Shape | None:
        """Aspect-legal shape of the smallest relative area deviation (no admissible shape)."""
        if self._fb is False:
            g = self.g
            req = self.k.req(self.spec)
            best: tuple[tuple[float, int, int], Shape] | None = None
            cands: list[Shape] = []
            for n in range(1, _MAX_N):
                cands.append(Shape("F", n, n * g.half, g.df))
                cands.append(Shape("D", n, n * g.half, g.mE))
                if self.facade:
                    cands.append(Shape("T", n, n * g.half, g.dp))
            if not self.facade:
                for w in range(6, 2 * g.band + 1, 6):
                    cands.append(Shape("B", 0, w, g.band))
                    if g.band >= 48 and g.band % 2 == 0:
                        cands.append(Shape("b", 0, w, g.band // 2))
            for s in cands:
                if min(s.w, s.d) < req.wmin or not legal_aspect(self.k, s.w, s.d):
                    continue
                key = (
                    round(deviation(self.k, self.spec, s.w, s.d), 6),
                    s.n % 2,
                    "FBbDT".index(s.kind),
                )
                if best is None or key < best[0]:
                    best = (key, s)
            self._fb = None if best is None else best[1]
        return self._fb  # type: ignore[return-value]


# ------------------------------------------------------------------------------ geometry
@dataclass
class _Geom:
    transposed: bool
    mirror: bool
    x0: int
    y0: int
    L: int
    dp: int
    df: int
    c: int
    band: int
    mE: int
    half: int
    bay: int
    P: list[int]
    BL: list[int]
    minw: int
    solid: Rect  # (su0, sv0, dsu, dsv)
    col_u: list[int] = field(default_factory=list)
    col_v: list[int] = field(default_factory=list)
    small_m2: float = 30.0
    unit_m: float = 0.1
    span0: int = 0
    span1: int = 0
    cu0: int = 0
    cu1: int = 0
    parts: dict[str, list[tuple[int, int]]] = field(default_factory=dict)

    def to_xy(self, r: Rect) -> Rect:
        u, v, du, dv = r
        if self.mirror:
            v = self.dp - v - dv
        if self.transposed:
            return (self.x0 + v, self.y0 + u, dv, du)
        return (self.x0 + u, self.y0 + v, du, dv)

    def col_inside(self, u0: int, u1: int, v0: int, v1: int) -> bool:
        """A column of the grid stands inside the rectangle (farther than 0.15 m from its sides)."""
        m = 0.15 / self.unit_m
        return any(u0 + m < x < u1 - m for x in self.col_u) and any(
            v0 + m < y < v1 - m for y in self.col_v
        )

    def small_with_column(self, u0: int, u1: int, v0: int, v1: int) -> bool:
        """The rectangle is a room under 30 m2 with a column inside (to avoid)."""
        area = (u1 - u0) * (v1 - v0) * self.unit_m * self.unit_m
        return area < self.small_m2 and self.col_inside(u0, u1, v0, v1)

    def pidx(self, u: int) -> int:
        return self.P.index(u)


def _read_geometry(
    prepared: PreparedInput, rhythm: Rhythm, df: int, corridor_m: float, k: Consts
) -> _Geom:
    poly = prepared.footprint.polygon
    mm = prepared.grid.module_mm
    if poly.holes or len(poly.solids) != 1 or len(poly.exterior) != 4:
        raise NotEligible("contour non rectangulaire ou nombre de volumes pleins différent de un")
    xs = sorted({p[0] for p in poly.exterior})
    ys = sorted({p[1] for p in poly.exterior})
    sx = sorted({p[0] for p in poly.solids[0]})
    sy = sorted({p[1] for p in poly.solids[0]})
    if len(xs) != 2 or len(ys) != 2 or len(sx) != 2 or len(sy) != 2:
        raise NotEligible("contour ou volume plein non rectangulaire")
    x0, y0 = xs[0], ys[0]
    w0, h0 = xs[1] - x0, ys[1] - y0
    if (w0 * mm) % 600 or (h0 * mm) % 600:
        raise NotEligible("côtés du contour non multiples de 0,60 m")
    transposed = h0 > w0
    L, dp = (h0, w0) if transposed else (w0, h0)
    if 2 * dp > L:
        raise NotEligible("le grand côté est inférieur au double du petit côté (pas une barre)")
    su, sv = (sy, sx) if transposed else (sx, sy)
    su0, su1 = su[0] - (y0 if transposed else x0), su[1] - (y0 if transposed else x0)
    sv0, sv1 = sv[0] - (x0 if transposed else y0), sv[1] - (x0 if transposed else y0)
    c = round(corridor_m * 1000 / mm)
    band = dp - 2 * df - 2 * c
    if band < round(2400 / mm):
        raise NotEligible(
            f"profondeur {dp * mm / 1000:.1f} m : pas de bande centrale d'au moins 2,4 m entre "
            "deux couloirs (plateau à un seul couloir : hors M.4)"
        )
    bay = rhythm.bay * 600 // mm
    if bay % 2:
        raise NotEligible("travée impaire en modules : pas de demi-travée")
    half = bay // 2
    origin = prepared.footprint.origin_m
    u_abs0 = origin[1 if transposed else 0] + (y0 if transposed else x0) * mm / 1000
    lo, hi = u_abs0 - rhythm.bay_m, u_abs0 + L * mm / 1000 + rhythm.bay_m
    lines = rhythm.bay_lines_y(lo, hi) if transposed else rhythm.bay_lines_x(lo, hi)
    BL = sorted({round((a - u_abs0) * 1000 / mm) for a in lines})
    marks = sorted({x for b in BL for x in (b, b + half, b - half) if 0 < x < L})
    P = [0, *marks, L]
    while len(P) > 2 and P[1] - P[0] < half:
        del P[1]
    while len(P) > 2 and P[-1] - P[-2] < half:
        del P[-2]
    BLin = [x for x in BL if x in P]
    g = _Geom(
        transposed,
        False,
        x0,
        y0,
        L,
        dp,
        df,
        c,
        band,
        dp - df - c,
        half,
        bay,
        P,
        BLin,
        k.s,
        (su0, sv0, su1 - su0, sv1 - sv0),
    )
    g.unit_m = mm / 1000
    u_len = L * mm / 1000
    v_abs0 = origin[0 if transposed else 1] + (x0 if transposed else y0) * mm / 1000
    cu = (
        rhythm.grid_lines_y(u_abs0, u_abs0 + u_len)
        if transposed
        else rhythm.grid_lines_x(u_abs0, u_abs0 + u_len)
    )
    cv = (
        rhythm.grid_lines_x(v_abs0, v_abs0 + dp * mm / 1000)
        if transposed
        else rhythm.grid_lines_y(v_abs0, v_abs0 + dp * mm / 1000)
    )
    g.col_u = [round((a - u_abs0) * 1000 / mm) for a in cu]
    g.col_v = [round((a - v_abs0) * 1000 / mm) for a in cv]
    return g


def _core_segment(g: _Geom) -> None:
    su0, _sv0, dsu, _dsv = g.solid
    su1 = su0 + dsu
    below = [b for b in g.BL if b <= su0]
    above = [b for b in g.BL if b >= su1]
    if not below or not above:
        raise NotEligible("le noyau n'est pas encadré par des lignes de travée")
    g.span0, g.span1 = below[-1], above[0]
    lf = [b for b in g.BL if b < g.span0]
    rt = [b for b in g.BL if b > g.span1]
    if not lf or not rt:
        raise NotEligible("pas de travée de flanc de part et d'autre du noyau")
    g.cu0, g.cu1 = lf[-1], rt[0]
    for name, lo_, hi_ in (("ouest", 0, g.cu0), ("est", g.cu1, g.L)):
        ls = [b for b in g.BL if lo_ <= b <= hi_]
        whole = sum(1 for a, b in pairwise(ls) if b - a == g.bay)
        if whole < 2:
            raise NotEligible(f"l'aile {name} compte moins de deux travées entières")


# ------------------------------------------------------------------------------- runs
@dataclass
class _Run:
    side: str  # "S" | "N"
    a: int  # first unit (index in P)
    b: int  # one past the last unit
    v0: int
    v1: int
    cur: int = 0
    placed: list[tuple[_Item, Shape, int, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cur = self.a

    @property
    def depth(self) -> int:
        return self.v1 - self.v0


@dataclass
class _Band:
    side: str  # "W" | "E"
    u0: int
    u1: int
    core_at_u1: bool
    cur: list[int] = field(default_factory=lambda: [0, 0])
    occ: list[list[tuple[int, int]]] = field(default_factory=lambda: [[], []])
    placed: list[tuple[_Item, Shape, int, int, int]] = field(default_factory=list)
    # (item, shape, lane (-1 = both), t0, t1)

    @property
    def length(self) -> int:
        return self.u1 - self.u0


# -------------------------------------------------------------------------------- heads
@dataclass
class _Wing:
    name: str
    edges: list[int]  # positions from the gable inward up to the flank edge
    maxh: int  # largest head (units)
    t: tuple[_Item, int] | None = None
    ds: list[tuple[_Item, int]] = field(default_factory=list)


def _choose_heads(g: _Geom, k: Consts, wings: list[_Wing], large: list[_Item]) -> None:
    """Assign large rooms to wings as one optional T then deep rooms D (RD 4.6)."""
    if not large or not wings:
        return
    large = sorted(large, key=lambda i: (-i.target, i.iid))[:8]

    def width(w: _Wing, h: int, n: int) -> int:
        return abs(w.edges[h + n] - w.edges[h])

    def ok_rem(w: _Wing, h: int) -> bool:
        rem = abs(w.edges[-1] - w.edges[h])
        return rem == 0 or rem >= g.bay

    def shape_opts(it: _Item, w: _Wing, h: int, kind: str) -> list[tuple[int, float]]:
        depth = g.mE if kind == "D" else g.dp
        out: list[tuple[int, float]] = []
        admissible = it.has_head_shape()
        for n in range(1, w.maxh - h + 1):
            wd = width(w, h, n)
            if admissible:
                if rect_shape_ok(k, it.spec, wd, depth):
                    out.append((n, deviation(k, it.spec, wd, depth)))
            elif min(wd, depth) >= k.req(it.spec).wmin and legal_aspect(k, wd, depth):
                out.append((n, deviation(k, it.spec, wd, depth)))
        if not admissible and out:
            out = [min(out, key=lambda x: (x[1], x[0] % 2, x[0]))]
        return out

    n_items = len(large)
    memo: dict[
        tuple[int, int, int, int],
        tuple[tuple[float, int, float], tuple[tuple[int, int, int], ...]] | None,
    ] = {}

    def rec(
        i: int, hs: tuple[int, ...], used: int
    ) -> tuple[tuple[float, int, float], tuple[tuple[int, int, int], ...]] | None:
        key = (i, hs[0], hs[1] if len(hs) > 1 else 0, used)
        if key in memo:
            return memo[key]
        if i == n_items:
            res = (
                ((0.0, 0, 0.0), ())
                if all(ok_rem(w, h) for w, h in zip(wings, hs, strict=True))
                else None
            )
            memo[key] = res
            return res
        best = rec(i + 1, hs, used)
        if not (used >> i) & 1:
            it = large[i]
            for wi, w in enumerate(wings):
                for n, dev in shape_opts(it, w, hs[wi], "D"):
                    nh = list(hs)
                    nh[wi] += n
                    sub = rec(i + 1, tuple(nh), used)
                    if sub is None:
                        continue
                    val = (sub[0][0] + it.target, sub[0][1] - n, sub[0][2] - dev)
                    if best is None or val > best[0]:
                        best = (val, ((i, wi, n), *sub[1]))
        memo[key] = best
        return best

    t_opts: list[list[tuple[int, int, float] | None]] = []
    for w in wings:
        o: list[tuple[int, int, float] | None] = [None]
        for i, it in enumerate(large):
            if it.facade:
                o += [(i, n, d) for n, d in shape_opts(it, w, 0, "T")]
        t_opts.append(o)
    best_total: tuple[tuple[float, int, float], list[tuple[int, int, int, str]]] | None = None

    def combos(idx: int, chosen: list[tuple[int, int, float] | None]) -> None:
        nonlocal best_total
        if idx == len(wings):
            ids = [c[0] for c in chosen if c is not None]
            if len(set(ids)) != len(ids):
                return
            used = 0
            hs = []
            val = (0.0, 0, 0.0)
            for c in chosen:
                if c is None:
                    hs.append(0)
                else:
                    used |= 1 << c[0]
                    hs.append(c[1])
                    val = (val[0] + large[c[0]].target, val[1] - 2 * c[1], val[2] - c[2])
            memo.clear()
            sub = rec(0, tuple(hs), used)
            if sub is None:
                return
            tot = (val[0] + sub[0][0], val[1] + sub[0][1], val[2] + sub[0][2])
            if best_total is None or tot > best_total[0]:
                assign = [(c[0], wi, c[1], "T") for wi, c in enumerate(chosen) if c is not None]
                assign += [(i, wi, n, "D") for i, wi, n in sub[1]]
                best_total = (tot, assign)
            return
        for c in t_opts[idx]:
            combos(idx + 1, [*chosen, c])

    combos(0, [])
    if best_total is None:
        return
    for i, wi, n, kind in best_total[1]:
        if kind == "T":
            wings[wi].t = (large[i], n)
    # D rooms in decreasing target order from the gable inward (after the T room)
    for i, wi, n, _kind in sorted((a for a in best_total[1] if a[3] == "D"), key=lambda a: a[0]):
        wings[wi].ds.append((large[i], n))


# ------------------------------------------------------------------------------ the planner
def plan_bar(
    prepared: PreparedInput,
    rulebook: Rulebook,
    sketch: AleConfig,
    rhythm: Rhythm,
    *,
    df: int,
    corridor_m: float,
    group_of: Callable[[str, RoomSpec], str],
) -> BayResult:
    """Plan one floor bay-first; raises :class:`NotEligible` (French reason) otherwise."""
    k = Consts.from_config(sketch)
    g = _read_geometry(prepared, rhythm, df, corridor_m, k)
    mm = prepared.grid.module_mm
    if (g.df * mm) % 600 or (g.c * mm) % 600:
        raise NotEligible("profondeurs de rangée non multiples de 0,60 m")
    _core_segment(g)
    su0, sv0, dsu, dsv = g.solid
    df_, c, dp, mE, band = g.df, g.c, g.dp, g.mE, g.band

    def parts_for(sv0_: int, sv1_: int) -> dict[str, list[tuple[int, int]]]:
        return {
            "S": _sub(0, df_, sv0_, sv1_),
            "cS": _sub(df_, df_ + c, sv0_, sv1_),
            "M": _sub(df_ + c, mE, sv0_, sv1_),
            "cN": _sub(mE, mE + c, sv0_, sv1_),
            "N": _sub(dp - df_, dp, sv0_, sv1_),
        }

    parts = parts_for(sv0, sv0 + dsv)
    pass_n = any(b - a >= g.minw for a, b in parts["cN"])
    pass_s = any(b - a >= g.minw for a, b in parts["cS"])
    if not pass_n and not pass_s:
        raise NotEligible("le volume plein barre les deux couloirs : contournement hors M.4")
    if not pass_n:
        g.mirror = True
        g.col_v = [dp - y for y in g.col_v]
        g.solid = (su0, dp - sv0 - dsv, dsu, dsv)
        su0, sv0, dsu, dsv = g.solid
        parts = parts_for(sv0, sv0 + dsv)
    su1 = su0 + dsu
    g.parts = parts
    minrow = round(3600 / mm)
    minband = round(2400 / mm)

    def borders(p: tuple[int, int], corr: list[tuple[int, int]]) -> bool:
        return any((q[0] == p[1] or q[1] == p[0]) and q[1] - q[0] >= g.minw for q in corr)

    kept: dict[str, list[tuple[int, int]]] = {"S": [], "N": []}
    clipped: list[tuple[str, int, int]] = []
    palier = {"S": False, "N": False}
    for row, corr in (("S", parts["cS"]), ("N", parts["cN"])):
        for p in parts[row]:
            if p[1] - p[0] >= minrow and borders(p, corr):
                kept[row].append(p)
            else:
                clipped.append(("palier", *p))
                if (row == "S" and p[0] == 0) or (row == "N" and p[1] == dp):
                    palier[row] = True
    for p in parts["M"]:
        if p[1] - p[0] >= minband and borders(p, [*parts["cS"], *parts["cN"]]):
            raise NotEligible("partie de bande conservée à côté du noyau : hors M.4")
        clipped.append(("ecrete", *p))
    narrowed = any(b - a < c for a, b in parts["cN"] + parts["cS"] if b - a >= g.minw)

    P = g.P
    # --- items
    specs = dict(prepared.instances)
    items: list[_Item] = []
    for iid, spec in prepared.instances:
        items.append(_Item(iid, spec, group_of(iid, spec), k, g))
    unplaced: list[_Item] = []
    large: list[_Item] = []
    regular: list[_Item] = []
    for it in items:
        if it.admissible_any():
            if it.f_options(df_) or it.band_options():
                regular.append(it)
            else:
                large.append(it)
        else:
            fb = it.fallback()
            if fb is None:
                unplaced.append(it)
            elif fb.kind in "DT":
                large.append(it)
            else:
                regular.append(it)

    # --- entrances
    ent_side: list[tuple[str, int, int]] = []
    notes: list[str] = []
    origin = prepared.footprint.origin_m
    for e in prepared.site.entrances:
        ex = (e.point[0] - origin[0]) * 1000 / mm - g.x0
        ey = (e.point[1] - origin[1]) * 1000 / mm - g.y0
        eu, ev = (ey, ex) if g.transposed else (ex, ey)
        if g.mirror:
            ev = dp - ev
        tol = 2
        if abs(ev) <= tol or abs(ev - dp) <= tol:
            side = "S" if abs(ev) <= tol else "N"
            los = [b for b in g.BL if b <= eu]
            his = [b for b in g.BL if b > eu]
            lo_ = max([*los, 0]) if not los else los[-1]
            hi_ = his[0] if his else g.L
            if lo_ not in P:
                lo_ = max(p for p in P if p <= lo_)
            if hi_ not in P:
                hi_ = min(p for p in P if p >= hi_)
            ent_side.append((side, lo_, hi_))
        else:
            notes.append("entrée sur un pignon : notée seulement")

    # --- wings
    wings: list[_Wing] = []
    for name, edges in (
        ("W", [p for p in P if p <= g.cu0]),
        ("E", [p for p in reversed(P) if p >= g.cu1]),
    ):
        w = _Wing(name, edges, len(edges) - 1)
        for _side, lo_, hi_ in ent_side:
            if name == "W" and lo_ < g.cu0:
                w.maxh = min(w.maxh, edges.index(lo_))
            if name == "E" and hi_ > g.cu1:
                w.maxh = min(w.maxh, edges.index(hi_))
        wings.append(w)
    _choose_heads(g, k, wings, large)

    # --- geometry of the wings
    rooms: list[tuple[str, str | None, Rect, str, float | None]] = []
    # (id, spec_id, rect, tag, target)
    circ: list[tuple[str, Rect]] = []
    placed_large: set[str] = set()
    cs_pieces: list[tuple[int, int, int, int]] = []
    cn_pieces: list[tuple[int, int, int, int]] = []
    runs: list[_Run] = []
    bands: list[_Band] = []
    s_pieces: list[tuple[int, int, int, int]] = []
    n_pieces: list[tuple[int, int, int, int]] = []
    t_end = {"W": 0, "E": g.L}
    reg: dict[str, tuple[int, int]] = {}

    def add_room(it: _Item, sh: Shape, rect: Rect) -> None:
        rooms.append((it.iid, it.spec.id, rect, sh.tag, it.target))

    for w in wings:
        h = 0
        pos = w.edges
        sign = 1 if w.name == "W" else -1
        if w.t is not None:
            it, n = w.t
            a, b = pos[0], pos[n]
            sh = Shape("T", n, abs(b - a), dp)
            add_room(it, sh, (min(a, b), 0, abs(b - a), dp))
            placed_large.add(it.iid)
            h = n
            t_end[w.name] = b
        for it, n in w.ds:
            a, b = pos[h], pos[h + n]
            sh = Shape("D", n, abs(b - a), mE)
            add_room(it, sh, (min(a, b), 0, abs(b - a), mE))
            placed_large.add(it.iid)
            h += n
        head_end = pos[h]
        flank = pos[-1]
        r0, r1 = (head_end, flank) if sign > 0 else (flank, head_end)
        if r1 > r0:
            reg[w.name] = (r0, r1)
            s_pieces.append((r0, r1, 0, df_))
            cs_pieces.append((r0, r1, df_, df_ + c))
            if w.name == "W":
                circ.append(("bout", (r0, df_ + c, c, band)))
                bands.append(_Band("W", r0 + c, r1, True))
            else:
                circ.append(("bout", (r1 - c, df_ + c, c, band)))
                bands.append(_Band("E", r0, r1 - c, False))
        # north side: from the end of the T room to the flank edge
        n0, n1 = (t_end[w.name], flank) if sign > 0 else (flank, t_end[w.name])
        n_pieces.append((n0, n1, dp - df_, dp))
        cn_pieces.append((n0, n1, mE, mE + c))

    # --- core segment
    spanw = (g.span0, g.span1)
    for lo_, hi_ in ((g.cu0, g.span0), (g.span1, g.cu1)):
        vlo = 0 if palier["S"] else df_ + c
        vhi = dp if palier["N"] else mE
        circ.append(("lien", (lo_, vlo, hi_ - lo_, vhi - vlo)))
        if not palier["S"]:
            s_pieces.append((lo_, hi_, 0, df_))
            cs_pieces.append((lo_, hi_, df_, df_ + c))
        if not palier["N"]:
            n_pieces.append((lo_, hi_, dp - df_, dp))
            cn_pieces.append((lo_, hi_, mE, mE + c))
    for a, b in parts["cS"]:
        cs_pieces.append((spanw[0], spanw[1], a, b))
    for a, b in parts["cN"]:
        cn_pieces.append((spanw[0], spanw[1], a, b))
    for a, b in kept["S"]:
        s_pieces.append((spanw[0], spanw[1], a, b))
    for a, b in kept["N"]:
        n_pieces.append((spanw[0], spanw[1], a, b))
    for kind, a, b in clipped:
        circ.append((kind, (spanw[0], a, spanw[1] - spanw[0], b - a)))
    if su0 > g.span0:
        circ.append(("flanc", (g.span0, sv0, su0 - g.span0, dsv)))
    if su1 < g.span1:
        circ.append(("flanc", (su1, sv0, g.span1 - su1, dsv)))
    for a, b, v0, v1 in _merge(cs_pieces):
        circ.append(("couloir", (a, v0, b - a, v1 - v0)))
    for a, b, v0, v1 in _merge(cn_pieces):
        circ.append(("couloir", (a, v0, b - a, v1 - v0)))

    # --- facade runs, entrance bays
    for side, pieces in (("S", s_pieces), ("N", n_pieces)):
        for a, b, v0, v1 in _merge(pieces):
            runs.append(_Run(side, P.index(a), P.index(b), v0, v1))
    for side, lo_, hi_ in ent_side:
        for r in list(runs):
            if r.side == side and P[r.a] <= lo_ and hi_ <= P[r.b]:
                runs.remove(r)
                circ.append(("entree", (lo_, r.v0, hi_ - lo_, r.depth)))
                if P[r.a] < lo_:
                    runs.append(_Run(side, r.a, P.index(lo_), r.v0, r.v1))
                if hi_ < P[r.b]:
                    runs.append(_Run(side, P.index(hi_), r.b, r.v0, r.v1))
    runs = [r for r in runs if r.b > r.a]
    runs.sort(key=lambda r: (P[r.a], r.side != "N", r.v0))

    # --- place rooms
    groups = sorted({it.group for it in regular}, key=lambda gname: gname)

    def place_f(it: _Item) -> bool:
        best: tuple[tuple[bool, int, bool, int, int, bool], _Run, Shape] | None = None
        for ri, r in enumerate(runs):
            for sh in it.f_options(r.depth):
                new_cur = r.cur + sh.n
                if new_cur > r.b or r.b - new_cur == 1:
                    continue
                rank = (
                    g.small_with_column(P[r.cur], P[new_cur], r.v0, r.v1),
                    round(deviation(k, it.spec, sh.w, sh.d) * 1000),
                    sh.n % 2 == 1 and (r.cur - r.a) % 2 == 0,
                    P[r.cur],
                    ri,
                    r.side != "N",
                )
                if best is None or rank < best[0]:
                    best = (rank, r, sh)
                break
        if best is None:
            return False
        _, r, sh = best
        r.placed.append((it, sh, r.cur, r.cur + sh.n))
        r.cur += sh.n
        return True

    def place_fallback(it: _Item) -> bool:
        fb = it.fallback()
        if fb is None or fb.kind != "F":
            return False
        for r in runs:
            if r.depth != fb.d:
                continue
            new_cur = r.cur + fb.n
            if new_cur > r.b or r.b - new_cur == 1:
                continue
            r.placed.append((it, fb, r.cur, new_cur))
            r.cur = new_cur
            return True
        return False

    def band_u(bd: _Band, t0: int, t1: int) -> tuple[int, int]:
        return (bd.u1 - t1, bd.u1 - t0) if bd.core_at_u1 else (bd.u0 + t0, bd.u0 + t1)

    def place_band(it: _Item) -> bool:
        opts = it.band_options()
        if not opts:
            return False
        order = sorted(
            bands,
            key=lambda bd: (
                -sum(1 for p in bd.placed if p[0].group == it.group),
                -(bd.length - max(bd.cur)),
                bd.side,
            ),
        )
        best: tuple[tuple[bool, int, int], _Band, Shape, int, int] | None = None
        for oi, sh in enumerate(opts):
            for bi, bd in enumerate(order):
                if sh.kind == "B":
                    lane, t0 = -1, max(bd.cur)
                    v0, v1 = df_ + c, mE
                else:
                    lane = 0 if bd.cur[0] <= bd.cur[1] else 1
                    t0 = bd.cur[lane]
                    v0 = df_ + c if lane == 0 else mE - sh.d
                    v1 = v0 + sh.d
                if t0 + sh.w > bd.length:
                    continue
                ua, ub = band_u(bd, t0, t0 + sh.w)
                key = (g.small_with_column(ua, ub, v0, v1), oi, bi)
                if best is None or key < best[0]:
                    best = (key, bd, sh, lane, t0)
        if best is None:
            return False
        _, bd, sh, lane, t0 = best
        bd.placed.append((it, sh, lane, t0, t0 + sh.w))
        if lane < 0:
            bd.cur = [t0 + sh.w, t0 + sh.w]
            bd.occ[0].append((t0, t0 + sh.w))
            bd.occ[1].append((t0, t0 + sh.w))
        else:
            bd.cur[lane] = t0 + sh.w
            bd.occ[lane].append((t0, t0 + sh.w))
        return True

    def place(it: _Item) -> bool:
        if not it.facade and place_band(it):
            return True
        if place_f(it):
            return True
        if not it.f_options(df_) and not it.band_options():
            return place_fallback(it)
        return False

    import copy

    runs0 = copy.deepcopy(runs)
    bands0 = copy.deepcopy(bands)
    anchored = sorted(
        (i for i in regular if i.spec.anchor == "entrance"), key=lambda i: (-i.target, i.iid)
    )
    band_only = sorted(
        (
            i
            for i in regular
            if not i.facade and not i.f_options(df_) and i.spec.anchor != "entrance"
        ),
        key=lambda i: (-i.target, i.iid),
    )
    rest = [i for i in regular if i not in anchored and i not in band_only]

    def order_for(strategy: int) -> list[_Item]:
        out = [*anchored, *band_only]
        if strategy == 0:  # group by group, non-facade rooms first
            for gname in groups:
                mine = [i for i in rest if i.group == gname]
                out += sorted(mine, key=lambda i: (i.facade, -i.target, i.iid))
        elif strategy == 1:  # decreasing size, groups ignored
            out += sorted(rest, key=lambda i: (-i.target, i.group, i.iid))
        elif strategy == 2:  # group by group, facade rooms first, then the others
            for gname in groups:
                mine = [i for i in rest if i.group == gname]
                out += sorted(mine, key=lambda i: (not i.facade, -i.target, i.iid))
        else:  # facade rooms of all groups first, then the non-facade ones
            out += sorted((i for i in rest if i.facade), key=lambda i: (i.group, -i.target, i.iid))
            out += sorted((i for i in rest if not i.facade), key=lambda i: (-i.target, i.iid))
        return out

    best_run: tuple[tuple[float, int, int], int, list[_Run], list[_Band], list[_Item]] | None = None
    for strategy in range(4):
        runs[:] = copy.deepcopy(runs0)
        bands[:] = copy.deepcopy(bands0)
        failed: list[_Item] = []
        lost: list[_Item] = []
        for it in order_for(strategy):
            if not place(it):
                failed.append(it)
        for it in sorted(failed, key=lambda i: (-i.target, i.iid)):  # retry in the free runs
            if not place(it):
                lost.append(it)
        key = (
            round(sum(i.target for i in lost), 6),
            sum(r.b - r.cur for r in runs),
            strategy,
        )
        if best_run is None or key < best_run[0]:
            best_run = (key, strategy, copy.deepcopy(runs), copy.deepcopy(bands), lost)
        if not lost and strategy == 0:
            break
    assert best_run is not None
    runs[:] = best_run[2]
    bands[:] = best_run[3]
    unplaced += best_run[4]

    # a free tail of one half-bay cannot be a legal reserve room: widen a neighbour or fail
    for r in runs:
        if r.b - r.cur == 1:
            fixed = False
            for idx in range(len(r.placed) - 1, -1, -1):
                it, sh, a, b = r.placed[idx]
                alt = next((s for s in it.f_options(r.depth) if s.n == sh.n + 1), None)
                if alt is not None:
                    r.placed[idx] = (it, alt, a, b + 1)
                    for j in range(idx + 1, len(r.placed)):
                        i2, s2, a2, b2 = r.placed[j]
                        r.placed[j] = (i2, s2, a2 + 1, b2 + 1)
                    r.cur += 1
                    fixed = True
                    break
            if not fixed:
                raise NotEligible("demi-travée libre isolée impossible à résorber")

    # --- turn runs and bands into rooms
    reserve_ids: list[str] = []
    rid = 0
    kinds_extra: list[tuple[str, Rect]] = []

    def new_reserve(rect: Rect) -> None:
        nonlocal rid
        rid += 1
        name = f"reserve-{rid:03d}"
        reserve_ids.append(name)
        rooms.append((name, None, rect, "", None))

    def layout_run(r: _Run) -> tuple[list[tuple[_Item, Shape, int, int]], list[tuple[int, int]]]:
        """Positions of the rooms of a run and its reserve pieces (unit indices), chosen to
        keep columns out of rooms under 30 m2 (reserve pieces may be placed between rooms;
        a piece is 2 to 8 half-bays wide, within the aspect limit)."""
        total = r.b - r.a
        items = r.placed
        widths = [b - a for _, _, a, b in items]
        INF = 10**9

        def small(pos0: int, units: int) -> int:
            return int(g.small_with_column(P[r.a + pos0], P[r.a + pos0 + units], r.v0, r.v1))

        best: dict[tuple[int, int], tuple[int, tuple[int, int, str, int]]] = {
            (0, 0): (0, (0, 0, "", 0))
        }
        for pos in range(total + 1):
            for i in range(len(items) + 1):
                cur = best.get((i, pos))
                if cur is None:
                    continue
                if i < len(items) and pos + widths[i] <= total:
                    key = (i + 1, pos + widths[i])
                    cost = cur[0] + 1000 * small(pos, widths[i])
                    if cost < best.get(key, (INF, ()))[0]:  # type: ignore[arg-type]
                        best[key] = (cost, (i, pos, "item", 0))
                for gw in range(2, 9):
                    if pos + gw > total:
                        break
                    wd = P[r.a + pos + gw] - P[r.a + pos]
                    if not legal_aspect(k, wd, r.depth):
                        continue
                    key = (i, pos + gw)
                    cost = cur[0] + 1000 * small(pos, gw) + 1
                    if cost < best.get(key, (INF, ()))[0]:  # type: ignore[arg-type]
                        best[key] = (cost, (i, pos, "res", gw))
        end = (len(items), total)
        if end not in best:
            placed_ = list(items)
            tail: list[tuple[int, int]] = []
            a0 = r.cur
            while a0 < r.b:
                n_ = r.b - a0
                step = 3 if n_ == 3 else min(n_, 2)
                if n_ > 3 and n_ % 2:
                    step = 2
                tail.append((a0, a0 + step))
                a0 += step
            return placed_, tail
        out_items: list[tuple[_Item, Shape, int, int]] = []
        out_res: list[tuple[int, int]] = []
        state = end
        while state != (0, 0):
            _, (pi, ppos, kind, gw) = best[state]
            if kind == "item":
                it, sh, _a, _b = items[pi]
                out_items.append((it, sh, r.a + ppos, r.a + ppos + widths[pi]))
            else:
                out_res.append((r.a + ppos, r.a + ppos + gw))
            state = (pi, ppos)
        out_items.reverse()
        out_res.reverse()
        return out_items, out_res

    used_units = 0
    avail_units = 0
    for r in runs:
        avail_units += r.b - r.a
        run_items, run_res = layout_run(r)
        for it, sh, a, b in run_items:
            add_room(it, sh, (P[a], r.v0, P[b] - P[a], r.depth))
            used_units += b - a
        for a, b in run_res:
            new_reserve((P[a], r.v0, P[b] - P[a], r.depth))
    band_total = 0
    for bd in bands:
        band_total += bd.length
        lane_d = band // 2
        v_lane = (df_ + c, mE - lane_d)

        def to_u(t0: int, t1: int, bd: _Band = bd) -> tuple[int, int]:
            return (bd.u1 - t1, bd.u1 - t0) if bd.core_at_u1 else (bd.u0 + t0, bd.u0 + t1)

        for it, sh, lane, t0, t1 in bd.placed:
            ua, ub = to_u(t0, t1)
            if lane < 0:
                add_room(it, sh, (ua, df_ + c, ub - ua, band))
            else:
                add_room(it, sh, (ua, v_lane[lane], ub - ua, lane_d))
        # free pieces
        free: list[list[tuple[int, int]]] = []
        for lane in (0, 1):
            occ = sorted(bd.occ[lane])
            cur = 0
            fr: list[tuple[int, int]] = []
            for a, b in occ:
                if a > cur:
                    fr.append((cur, a))
                cur = b
            if cur < bd.length:
                fr.append((cur, bd.length))
            free.append(fr)
        cuts = sorted({x for lane in free for a, b in lane for x in (a, b)})
        segs: list[tuple[int, int, int]] = []  # (t0, t1, lanes bitmask free)
        for a, b in pairwise(cuts):
            mask = 0
            for lane in (0, 1):
                if any(x <= a and b <= y for x, y in free[lane]):
                    mask |= 1 << lane
            if mask:
                segs.append((a, b, mask))
        merged: list[list[int]] = []
        for a, b, mask in segs:
            if merged and merged[-1][1] == a and merged[-1][2] == mask:
                merged[-1][1] = b
            else:
                merged.append([a, b, mask])
        for a, b, mask in merged:
            depth = band if mask == 3 else lane_d
            v0 = df_ + c if mask in (3, 1) else v_lane[1]
            ell = b - a
            n_pc = max(1, -(-ell // (2 * depth)))
            size = ell // n_pc
            legal = size >= max(g.minw, -(-depth // 2)) and ell % 1 == 0
            if not legal or any(legal_aspect(k, size, depth) is False for _ in (0,)):
                ua, ub = to_u(a, b)
                kinds_extra.append(("reliquat", (ua, v0, ub - ua, depth)))
                continue
            t = a
            for j in range(n_pc):
                nxt = b if j == n_pc - 1 else t + size
                if not legal_aspect(k, nxt - t, depth):
                    ua, ub = to_u(t, nxt)
                    kinds_extra.append(("reliquat", (ua, v0, ub - ua, depth)))
                else:
                    ua, ub = to_u(t, nxt)
                    new_reserve((ua, v0, ub - ua, depth))
                t = nxt
    circ += kinds_extra

    # --- unplaced large rooms stay unplaced
    for it in large:
        if it.iid not in placed_large:
            unplaced.append(it)

    # --- final layout
    circ.sort(key=lambda e: (e[1][0], e[1][1], e[0]))
    placed_circ = []
    kinds: dict[str, str] = {}
    for n_, (kind, rect) in enumerate(circ, start=1):
        name = f"circ-{n_:03d}"
        kinds[name] = kind
        x, y, w_, h_ = g.to_xy(rect)
        placed_circ.append(
            PlacedRoom(
                instance_id=name,
                spec_id=None,
                rect=ModuleRect(x=x, y=y, w=w_, h=h_),
                target_area_m2=None,
            )
        )
    placed_rooms = []
    tags: dict[str, str] = {}
    adjust: list[tuple[str, float, float]] = []
    for iid, spec_id, rect, tag, target in sorted(rooms, key=lambda e: e[0]):
        x, y, w_, h_ = g.to_xy(rect)
        placed_rooms.append(
            PlacedRoom(
                instance_id=iid,
                spec_id=spec_id,
                rect=ModuleRect(x=x, y=y, w=w_, h=h_),
                target_area_m2=target,
            )
        )
        if spec_id is not None:
            tags[iid] = tag
            sp = specs[iid]
            if not rect_shape_ok(k, sp, rect[2], rect[3]):
                adjust.append((iid, sp.target_area_m2, rect[2] * rect[3] * (mm / 1000) ** 2))
    placeholder = LayoutMetrics(
        total_cost=0.0,
        cost_breakdown={},
        total_overshoot_m2=0.0,
        circulation_area_m2=0.0,
        residue_area_m2=0.0,
        violations=(),
    )
    layout = Layout(
        grid=prepared.grid,
        footprint=prepared.footprint.polygon,
        rooms=tuple(placed_rooms),
        circulation=tuple(placed_circ),
        residue=(),
        seed=0,
        rulebook_version=prepared.rulebook_version,
        metrics=placeholder,
    )
    layout = layout.model_copy(update={"metrics": evaluate(layout, prepared, rulebook, sketch)})
    unit_m = mm / 1000
    half_bay = 0.5
    return BayResult(
        layout=layout,
        kinds=kinds,
        tags=tags,
        unplaced=tuple(sorted({u.iid for u in unplaced})),
        adjust=tuple(adjust),
        reserve_ids=tuple(reserve_ids),
        section={
            "bay": g.bay * unit_m,
            "df": df_ * unit_m,
            "c": c * unit_m,
            "band": band * unit_m,
            "plate_depth": dp * unit_m,
            "length": g.L * unit_m,
            "mirror": float(g.mirror),
            "transposed": float(g.transposed),
            "narrowed": float(narrowed),
            "span0": g.span0 * unit_m,
            "span1": g.span1 * unit_m,
            "core0": g.cu0 * unit_m,
            "core1": g.cu1 * unit_m,
        },
        facade_bays_used=used_units * half_bay,
        facade_bays_available=avail_units * half_bay,
        band_m_available=band_total * unit_m,
        notes=tuple(notes),
        groups={it.iid: it.group for it in items if it.iid in tags},
        long_runs=tuple((r.side, P[r.a], P[r.b], r.v0, r.v1) for r in runs),
        frame={"L": g.L, "dp": dp},
    )


_ = (Sequence,)
