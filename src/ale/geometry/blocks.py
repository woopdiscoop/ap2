"""Room-bay widths, stack solving and block layout (RD 3.3 sections 4, 5.2-5.4).

Everything here works in integer modules in a block-local frame: ``u`` along the spine
(from the piece's min corner) and ``t`` = distance from the spine (``0`` at the spine,
``D`` at the block's outer edge). :mod:`ale.geometry.realize` maps ``t`` to the piece's
``v`` coordinate. Areas are module² cells; targets are exact ``Fraction`` cells.

Ticket Q.1: every room placed here satisfies the area rule, ``aspect <= amax`` and its
``wmin``. A room bay or stack that cannot is a block failure (``ROOM_INFEASIBLE`` /
``STACK_INFEASIBLE``) instead of the former rule-breaking fallbacks.

Ticket Q.2 (inner connector): a block may hold one :class:`ConnectorBay` marker. Its bays
before the marker are laid out from ``u = 0``; the bays after it from ``pre + s`` (as if the
connector sat right after this block's own bays). The piece fixes the connector position
``u_c`` from all its blocks; :meth:`BlockOut.placed` then shifts the bays after the marker
to ``u_c + s`` and adds the filler strip ``[pre, u_c)`` and the end strip.

Ticket Q.3 (façade-aware widths): in an *exterior* block (its outer long side on the
footprint exterior, see :mod:`ale.geometry.realize`) a room bay holding a ``needs_facade``
room takes the **smallest** width that satisfies the area rule, ``aspect <= amax`` and
``wmin`` (raised to the façade minimum ``f`` when that width still complies), so more such
rooms fit along the frontage. Elsewhere the RD 3.3 §5.2 width is unchanged. Every block also
counts its ``needs_facade`` rooms predicted to end with less than ``f`` of façade
(:attr:`BlockOut.no_facade`, the realiser's depth-search key): a room bay has façade = its
width when the block is exterior, else none; a stack room has façade = the stack width only
when it is the outermost room of its stack (no stack-end strip) in an exterior block.

Ticket Q.4 (façade depth, contracts 1.4.0): with ``facade.max_depth_m`` set, ``dmax =
floor(max_depth_m / module)`` (:attr:`Consts.dmax`). A ``needs_facade`` room that would have
façade but whose depth exceeds ``dmax`` (a room bay deeper than ``dmax``, or the outermost
stack room taller than ``dmax``) also counts in :attr:`BlockOut.no_facade` — one predicted
``FACADE_DEPTH``, at the same key position as the Q.3 façade count. A *deep* room
(``needs_facade`` with ``T > amax · dmax²``, :attr:`RoomReq.deep`) cannot satisfy both rules:
at a depth ``<= dmax`` with no compliant width, its room bay takes the area rule's width with
``aspect > amax`` (depth wins; :mod:`ale.geometry.evaluate` reports it as a soft
``ASPECT_DEPTH``). With the rule off (``dmax is None``) nothing changes.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from fractions import Fraction
from typing import Literal, Protocol

from ale.contracts.area_rule import AreaTolerance, area_bounds_mm2
from ale.contracts.config import AleConfig
from ale.contracts.corridor_plan import ConnectorBay, FingerBay, RoomBay
from ale.contracts.models import RoomSpec
from ale.contracts.units import to_decimal
from ale.geometry.bay import BlockLattice
from ale.guards import bounded

__all__ = [
    "AnyBay",
    "BlockOut",
    "Consts",
    "Item",
    "RoomReq",
    "Solver",
    "StackSol",
    "aspect_ok",
    "guarded_range",
]

_MM2_PER_M2 = 1_000_000
_LOOP_BUDGET_S = 5.0
BAY_UNIT = 10_000
"""M.3b: area-deviation cells charged per unit of lattice cost (large against any block's
deviation, so the lattice is ranked ahead of the deviation and behind failures / façade)."""
BAY_COST = 100
"""M.3b: lattice cost of one partition off a bay line, or of one column line inside a small
room; a partition within the tolerance but off the line costs its distance in modules."""
_MAX_PLANS = 200_000
_BEAM = 3
"""M.3b: the bay-plan search keeps the states within this many lattice cost units of the best."""

ItemKind = Literal["room", "finger", "stack_strip", "end_strip", "filler"]
AnyBay = RoomBay | FingerBay | ConnectorBay


class LatticeSource(Protocol):
    """M.3b: what the realiser bound to a :class:`Solver` tells it about a block."""

    def lattice_for(self, where: str, depth: int) -> BlockLattice | None: ...

    def end_cost_for(self, where: str, depth: int, out: BlockOut) -> int: ...


BayPlan = tuple[dict[tuple[int, str], int], int]
"""M.3b: ``({(bay index, "R" room | "L" / "R" stack side): width}, lattice cost)``."""


def _ceil_div(a: int, b: int) -> int:
    return -((-a) // b)


def guarded_range(start: int, stop: int, *, label: str, step: int = 1) -> Iterator[int]:
    """``range(start, stop, step)`` iterated under :func:`ale.guards.bounded`."""
    rng = range(start, stop, step)
    with bounded(max_iter=len(rng) + 1, time_budget_s=_LOOP_BUDGET_S, label=label) as budget:
        for value in rng:
            budget.tick()
            yield value


def aspect_ok(a: int, b: int, amax: Fraction) -> bool:
    """``max(a, b) / min(a, b) <= amax`` (exact; sides ≥ 1)."""
    return max(a, b) * amax.denominator <= amax.numerator * min(a, b)


@dataclass(frozen=True)
class Consts:
    """Grammar constants in modules (RD section 4)."""

    module_mm: int
    s: int
    c: int
    f: int
    amax: Fraction
    tol: AreaTolerance
    dmax: int | None = None
    """Q.4: maximum façade depth in modules (``None``: rule off)."""
    depth_hard: bool = False
    """Q.4: ``facade.max_depth_hard`` — the depth limit is absolute (``FACADE_DEPTH`` hard,
    depth beats aspect). ``False``: the limit is soft (a cost term, aspect stays hard)."""

    @classmethod
    def from_config(cls, config: AleConfig) -> Consts:
        m = config.grid.module_mm

        def modules(length_m: float) -> int:
            return math.ceil(Fraction(to_decimal(length_m)) * 1000 / m)

        max_depth = config.facade.max_depth_m
        dmax = None if max_depth is None else math.floor(Fraction(to_decimal(max_depth)) * 1000 / m)

        return cls(
            module_mm=m,
            s=modules(config.circulation.min_width_m),
            c=modules(config.circulation.min_door_edge_m),
            f=modules(config.facade.min_facade_len_m),
            amax=Fraction(str(config.shape.aspect_max)),
            tol=AreaTolerance(
                down_pct=config.area.tol_down_pct,
                up_pct=config.area.tol_up_pct,
                up_abs_m2=config.area.tol_up_abs_m2,
            ),
            dmax=dmax,
            depth_hard=dmax is not None and config.facade.max_depth_hard,
        )

    @property
    def cell_mm2(self) -> int:
        return self.module_mm * self.module_mm

    def wmin(self, spec: RoomSpec) -> int:
        """``max(c, ceil(min_width_m / module))``."""
        if spec.min_width_m is None:
            return self.c
        own = math.ceil(Fraction(to_decimal(spec.min_width_m)) * 1000 / self.module_mm)
        return max(self.c, own)

    def req(self, spec: RoomSpec) -> RoomReq:
        """Area target / bounds (cells) and minimum width (modules) of a room."""
        cell = self.cell_mm2
        lo_mm2, hi_mm2 = area_bounds_mm2(spec.target_area_m2, self.tol)
        target = Fraction(to_decimal(spec.target_area_m2)) * _MM2_PER_M2 / cell
        return RoomReq(
            target=target,
            lo=_ceil_div(lo_mm2, cell),
            hi=hi_mm2 // cell,
            wmin=self.wmin(spec),
            facade=spec.needs_facade,
            deep=self.deep(spec.needs_facade, target),
        )

    def deep(self, facade: bool, target: Fraction) -> bool:
        """Q.4: a ``needs_facade`` room with ``T > amax · dmax²`` under a hard depth limit
        (depth beats aspect); never with the soft rule."""
        if not (facade and self.depth_hard) or self.dmax is None:
            return False
        return target > self.amax * self.dmax * self.dmax


@dataclass(frozen=True)
class RoomReq:
    """Area target ``target`` (exact cells), bounds ``[lo, hi]`` (cells), ``wmin`` (modules)."""

    target: Fraction
    lo: int
    hi: int
    wmin: int
    facade: bool = False
    """``needs_facade`` (Q.3: façade-aware width in exterior blocks)."""
    deep: bool = False
    """Q.4: ``needs_facade`` and ``T > amax · dmax²`` (see :meth:`Consts.deep`)."""
    _hash: int = field(init=False, repr=False, compare=False, default=0)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_hash",
            hash((self.target, self.lo, self.hi, self.wmin, self.facade, self.deep)),
        )

    def __hash__(self) -> int:  # cached: requirements key every solver memo
        return self._hash

    def ceil_div(self, side: int) -> int:
        """``ceil(target / side)`` in integer arithmetic."""
        t = self.target
        return -((-t.numerator) // (t.denominator * side))


@dataclass(frozen=True)
class StackSol:
    """Solved stack: width ``w``, heights from the spine outward, stack-end strip ``rest``."""

    w: int
    heights: tuple[int, ...]
    rest: int


@dataclass(frozen=True)
class Item:
    """A rectangle in block-local coordinates (``u``, ``t``) with sizes (``du``, ``dt``)."""

    kind: ItemKind
    room: str | None
    u: int
    t: int
    du: int
    dt: int


@dataclass
class BlockOut:
    """Result of laying out one block at one depth."""

    items: list[Item] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)
    area_dev: Fraction = Fraction(0)  # Σ |placed - target| cells
    strip_cells: int = 0  # stack-end strips
    end_cells: int = 0  # end strip
    junction_u: int | None = None
    depth: int = 0
    marker: int | None = None
    """Σ widths of the bays before the connector marker (``None``: no marker)."""
    post: int = 0
    """Σ widths of the bays after the marker."""
    split: int = 0
    """Index in ``items`` of the first item after the marker."""
    junction_post: bool = False
    """Whether the junction finger lies after the marker."""
    fingers: dict[int | None, tuple[int, bool]] = field(default_factory=dict)
    """G.1: ``junction_to`` → ``(finger u, after the marker)`` of every junction finger."""
    no_facade: int = 0
    """``needs_facade`` rooms predicted to end with façade ``< f`` (Q.3 depth key)."""
    bay_cost: int | None = None
    """M.3b: lattice cost of the layout (``None``: laid out without the lattice objective)."""
    _dev: Fraction | None = field(default=None, repr=False, compare=False)

    def dev(self) -> Fraction:
        """``area_dev + strip_cells`` (depth-search term), computed once the block is final."""
        if self._dev is None:
            self._dev = self.area_dev + self.strip_cells
        return self._dev

    def shift(self, u_c: int) -> int:
        """How far the bays after the marker move when the connector sits at ``u_c``."""
        return 0 if self.marker is None else max(0, u_c - self.marker)

    def junction_at(self, u_c: int | None) -> int | None:
        """Block-local ``u`` of the junction finger with the connector at ``u_c``."""
        if self.junction_u is None or u_c is None or not self.junction_post:
            return self.junction_u
        return self.junction_u + self.shift(u_c)

    def finger_at(self, child: int | None, u_c: int | None) -> int | None:
        """Block-local ``u`` of the junction finger leading to ``child`` with the connector
        at ``u_c`` (``None``: no such finger)."""
        got = self.fingers.get(child)
        if got is None:
            return None
        u, post = got
        return u + self.shift(u_c) if post and u_c is not None else u

    def placed(self, u_c: int | None, length: int, s: int) -> list[Item]:
        """Items with the connector at ``u_c`` (Q.2): bays after the marker shifted to
        ``u_c + s``, a filler strip ``[pre, u_c)`` and the end strip ``[u_c + s + post,
        length)``. Without a marker (or ``u_c``) the items as laid out."""
        if self.marker is None or u_c is None:
            return self.items
        if self.depth <= 0:
            return []
        shift = self.shift(u_c)
        out: list[Item] = []
        for i, it in enumerate(self.items):
            if it.kind == "end_strip":
                continue
            out.append(replace(it, u=it.u + shift) if i >= self.split else it)
        if shift > 0:
            out.append(Item("filler", None, self.marker, 0, shift, self.depth))
        end = self.marker + shift + s + self.post
        if end < length:
            out.append(Item("end_strip", None, end, 0, length - end, self.depth))
        return out


class Solver:
    """Memoised room-bay / stack solver for one realisation (RD 5.2-5.4)."""

    def __init__(self, consts: Consts, reqs: Mapping[str, RoomReq]) -> None:
        self.k = consts
        self.reqs = reqs
        self._bay_cache: dict[tuple[RoomReq, int, bool], int | None] = {}
        self._stack_cache: dict[tuple[tuple[RoomReq, ...], int], StackSol | None] = {}
        self.owner: LatticeSource | None = None
        self._choice_cache: dict[
            tuple[tuple[str, ...], int, bool], tuple[tuple[int, StackSol], ...] | None
        ] = {}
        self._option_cache: dict[tuple[tuple[RoomReq, ...], int], dict[int, StackSol]] = {}
        self._bay_plans: dict[
            tuple[tuple[AnyBay, ...], int, int, bool, BlockLattice], BayPlan | None
        ] = {}

    # ------------------------------------------------------------------ 5.2 room bay
    def room_bay_width(self, req: RoomReq, depth: int, exterior: bool = False) -> int | None:
        """Width of a room bay at ``depth`` satisfying the area rule, ``aspect <= amax`` and
        ``wmin`` (RD 3.3 §5.2), or ``None`` when no width does (Q.1: ``ROOM_INFEASIBLE``).

        Q.3: a ``needs_facade`` room in an ``exterior`` block takes the smallest compliant
        width instead (see :meth:`facade_width`); the set of depths with a width is the same.

        Q.4: a deep room (:attr:`RoomReq.deep`) with no compliant width at a depth ``<= dmax``
        takes :meth:`deep_width` (area rule and ``wmin`` only, ``aspect > amax`` allowed).
        """
        narrow = exterior and req.facade
        key = (req, depth, narrow)
        if key not in self._bay_cache:
            got = self._room_bay_width(req, depth)
            if narrow and got is not None:
                got = self.facade_width(req, depth)
            elif got is None and req.deep and self.k.dmax is not None and depth <= self.k.dmax:
                got = self.deep_width(req, depth, narrow)
            self._bay_cache[key] = got
        return self._bay_cache[key]

    def facade_width(self, req: RoomReq, depth: int) -> int | None:
        """Q.3: the smallest width ``w`` with ``lo <= w·D <= hi``, ``aspect <= amax`` and
        ``w >= wmin``, raised to ``f`` when ``f`` still complies (``None`` if none does)."""
        if depth < req.wmin:
            return None
        an, ad = self.k.amax.numerator, self.k.amax.denominator
        lo = max(req.wmin, _ceil_div(req.lo, depth), _ceil_div(depth * ad, an))
        hi = min(req.hi // depth, (depth * an) // ad)
        if lo > hi:
            return None
        return max(lo, self.k.f) if self.k.f <= hi else lo

    def _too_deep(self, out: BlockOut, excess: int, width: int) -> None:
        """Q.4: a predicted ``FACADE_DEPTH`` of ``excess`` modules over ``width``: one more in
        the façade key position under a hard limit; with the soft rule, the cells beyond the
        limit added to the area deviation (the cost position of the depth-search key)."""
        if self.k.depth_hard:
            out.no_facade += 1
        else:
            out.area_dev += excess * width

    def deep_width(self, req: RoomReq, depth: int, narrow: bool) -> int | None:
        """Q.4: width of a deep room's bay at ``depth`` ignoring the aspect limit: the
        smallest ``w >= wmin`` with ``lo <= w·D <= hi`` when ``narrow`` (exterior block, as
        :meth:`facade_width`), else the smallest with ``T <= w·D <= hi`` and failing that the
        smallest with ``lo <= w·D``; ``None`` if no width meets the area rule."""
        if depth < req.wmin:
            return None
        hi = req.hi // depth
        low = max(req.wmin, _ceil_div(req.lo, depth))
        if not narrow:
            up = max(req.wmin, req.ceil_div(depth))
            if up <= hi:
                return up
        return low if low <= hi else None

    def _room_bay_width(self, req: RoomReq, depth: int) -> int | None:
        if depth < req.wmin:
            return None
        an, ad = self.k.amax.numerator, self.k.amax.denominator
        # aspect_ok(w, D) <=> ceil(D / amax) <= w <= floor(D · amax) (amax >= 1): the 3.3
        # up / down scans reduce to the first / last width of that range in their window.
        a_lo, a_hi = _ceil_div(depth * ad, an), (depth * an) // ad
        w_up = max(req.wmin, req.ceil_div(depth))
        w = max(w_up, a_lo)
        if w <= min(req.hi // depth, a_hi):
            return w
        w_lo = max(req.wmin, _ceil_div(req.lo, depth))
        w = min(w_up - 1, a_hi)  # w < ceil(T / D) here, so lo <= w·D < T
        if w >= max(w_lo, a_lo):
            return w
        return None

    # ------------------------------------------------------------------ 5.3 stack
    def stack(self, reqs: tuple[RoomReq, ...], depth: int) -> StackSol | None:
        """Solved stack whose every room satisfies the area rule, ``aspect <= amax`` and its
        ``wmin``, or ``None`` when no stack width in ``[wmin_stack, 2·D]`` allows it
        (Q.1: ``STACK_INFEASIBLE``)."""
        key = (reqs, depth)
        if key not in self._stack_cache:
            self._stack_cache[key] = self._stack(reqs, depth)
        return self._stack_cache[key]

    def _stack(self, reqs: tuple[RoomReq, ...], depth: int) -> StackSol | None:
        if depth <= 0:
            return None
        wmin_s = max(r.wmin for r in reqs)
        exact = self._stack_exact(reqs, depth, wmin_s)
        if exact is not None:
            return exact
        return self._stack_under(reqs, depth, wmin_s)

    def _stack_exact(self, reqs: tuple[RoomReq, ...], depth: int, wmin_s: int) -> StackSol | None:
        """RD 3.3 §5.3: every room reaches its target (``w·h_i >= T_i``)."""
        an, ad = self.k.amax.numerator, self.k.amax.denominator
        k = len(reqs)
        total = sum(r.target for r in reqs)
        # The first criterion Σ(w·h_i - T_i) + w·R_rest equals w·D - ΣT_i (heights plus
        # rest fill the depth), strictly increasing in w: the first accepted w is optimal.
        # Widths below ΣT/D give Σh_i > D, so the scan starts there (exact pruning).
        start = max(wmin_s, math.ceil(total / depth))
        for w in guarded_range(start, 2 * depth + 1, label="stack-width"):
            need = -((-w * ad) // an)  # smallest h with w / h <= amax
            if k * need > depth or any(w * need > r.hi for r in reqs):
                break  # every accepted h_i >= need: impossible for this and wider w
            heights: list[int] = []
            for r in reqs:
                # h >= wmin_i: w >= wmin_stack >= wmin_i already, so min(w, h) >= wmin_i.
                h = max(r.wmin, r.ceil_div(w))
                if h < need:  # too flat: raise while w·(h+1) <= hi
                    h = max(h, min(need, r.hi // w))
                if h < need or h * ad > an * w or w * h > r.hi:
                    break
                heights.append(h)
            else:
                rest = depth - sum(heights)
                if rest < 0:
                    continue
                for i in range(k - 1, -1, -1):
                    hmax = min(reqs[i].hi // w, (w * an) // ad)
                    add = min(rest, max(0, hmax - heights[i]))
                    heights[i] += add
                    rest -= add
                return StackSol(w=w, heights=tuple(heights), rest=rest)
        return None

    def _stack_under(self, reqs: tuple[RoomReq, ...], depth: int, wmin_s: int) -> StackSol | None:
        """No width lets every room reach its target: allow ``lo_i <= w·h_i < T_i``.

        For each width, heights start at their compliant minimum and are raised from the
        outermost room inward, first towards ``ceil(T_i / w)``, then up to their compliant
        maximum; the rest is the stack-end strip. Keeps the width minimising
        ``(Σ |w·h_i - T_i| + w·R_rest, w)``.
        """
        an, ad = self.k.amax.numerator, self.k.amax.denominator
        k = len(reqs)
        best: StackSol | None = None
        best_key: tuple[Fraction, int] | None = None
        start = max(wmin_s, _ceil_div(sum(r.lo for r in reqs), depth))
        for w in guarded_range(start, 2 * depth + 1, label="stack-width-under"):
            need = -((-w * ad) // an)
            if k * need > depth:
                break  # need grows with w
            cap = (w * an) // ad
            lows = [max(r.wmin, need, _ceil_div(r.lo, w)) for r in reqs]
            highs = [min(r.hi // w, cap) for r in reqs]
            if sum(lows) > depth or any(lo > hi for lo, hi in zip(lows, highs, strict=True)):
                continue
            prefs = [
                min(max(r.ceil_div(w), lo), hi) for r, lo, hi in zip(reqs, lows, highs, strict=True)
            ]
            heights = list(lows)
            rest = depth - sum(heights)
            for limits in (prefs, highs):
                for i in range(k - 1, -1, -1):
                    add = min(rest, limits[i] - heights[i])
                    heights[i] += add
                    rest -= add
            dev = sum(
                (abs(w * h - r.target) for r, h in zip(reqs, heights, strict=True)), Fraction(0)
            )
            key = (dev + w * rest, w)
            if best_key is None or key < best_key:
                best, best_key = StackSol(w=w, heights=tuple(heights), rest=rest), key
        return best

    # ------------------------------------------------------------------ M.3b bay plan
    def width_window(self, req: RoomReq, depth: int, narrow: bool) -> range:
        """Every width ``w`` with ``lo <= w·D <= hi``, ``aspect <= amax`` and ``w >= wmin``
        (``w >= f`` too for a façade room in an exterior block when ``f`` still complies):
        the widths :meth:`room_bay_width` chooses among. Empty when none."""
        if depth < req.wmin:
            return range(0)
        an, ad = self.k.amax.numerator, self.k.amax.denominator
        lo = max(req.wmin, _ceil_div(req.lo, depth), _ceil_div(depth * ad, an))
        hi = min(req.hi // depth, (depth * an) // ad)
        if narrow and self.k.f <= hi:
            lo = max(lo, self.k.f)
        return range(lo, hi + 1)

    def stack_options(self, reqs: tuple[RoomReq, ...], depth: int) -> dict[int, StackSol]:
        """M.3b: every stack width ``w`` that admits a compliant stack, with its solution (the
        exact one when every room reaches its target, else the one that keeps every room inside
        its area window); :meth:`stack` returns one of them."""
        key = (reqs, depth)
        if key not in self._option_cache:
            out: dict[int, StackSol] = {}
            if depth > 0:
                wmin_s = max(r.wmin for r in reqs)
                start = max(wmin_s, _ceil_div(sum(r.lo for r in reqs), depth))
                for w in range(start, 2 * depth + 1):
                    sol = self._exact_at(reqs, depth, w) or self._under_at(reqs, depth, w)
                    if sol is not None:
                        out[w] = sol
            self._option_cache[key] = out
        return self._option_cache[key]

    def _exact_at(self, reqs: tuple[RoomReq, ...], depth: int, w: int) -> StackSol | None:
        """:meth:`_stack_exact` for one width."""
        an, ad = self.k.amax.numerator, self.k.amax.denominator
        k = len(reqs)
        need = -((-w * ad) // an)
        if k * need > depth or any(w * need > r.hi for r in reqs):
            return None
        heights: list[int] = []
        for r in reqs:
            h = max(r.wmin, r.ceil_div(w))
            if h < need:
                h = max(h, min(need, r.hi // w))
            if h < need or h * ad > an * w or w * h > r.hi:
                return None
            heights.append(h)
        rest = depth - sum(heights)
        if rest < 0:
            return None
        for i in range(k - 1, -1, -1):
            hmax = min(reqs[i].hi // w, (w * an) // ad)
            add = min(rest, max(0, hmax - heights[i]))
            heights[i] += add
            rest -= add
        return StackSol(w=w, heights=tuple(heights), rest=rest)

    def _under_at(self, reqs: tuple[RoomReq, ...], depth: int, w: int) -> StackSol | None:
        """:meth:`_stack_under` for one width."""
        an, ad = self.k.amax.numerator, self.k.amax.denominator
        k = len(reqs)
        need = -((-w * ad) // an)
        if k * need > depth:
            return None
        cap = (w * an) // ad
        lows = [max(r.wmin, need, _ceil_div(r.lo, w)) for r in reqs]
        highs = [min(r.hi // w, cap) for r in reqs]
        if sum(lows) > depth or any(lo > hi for lo, hi in zip(lows, highs, strict=True)):
            return None
        prefs = [
            min(max(r.ceil_div(w), lo), hi) for r, lo, hi in zip(reqs, lows, highs, strict=True)
        ]
        heights = list(lows)
        rest = depth - sum(heights)
        for limits in (prefs, highs):
            for i in range(k - 1, -1, -1):
                add = min(rest, limits[i] - heights[i])
                heights[i] += add
                rest -= add
        return StackSol(w=w, heights=tuple(heights), rest=rest)

    def bay_plan(
        self,
        bays: tuple[AnyBay, ...],
        depth: int,
        length: int,
        exterior: bool,
        lat: BlockLattice,
    ) -> BayPlan | None:
        """M.3b: the widths of the room bays and stacks of a block laid out at ``depth`` that
        minimise the lattice cost, or ``None`` when the block is laid out as without a
        lattice (a connector marker, a room or stack with no compliant width).

        Dynamic programme over the items in order (room bay, stack, finger strip), state =
        running position ``u`` along the spine; each room takes a width inside
        :meth:`width_window`, each stack a width of :meth:`stack_options` that lights its
        outer room as the default does. Cost, minimised in this order: the lattice cost (in an
        exterior block each room side strictly inside the block that is off a bay line by more
        than ``tol`` costs 100, within ``tol`` its distance; in any block each column line
        inside a room of less than ``small_mm2``, times the column lines across it, costs
        100), then the area deviation (with stack-end strips).
        """
        key = (bays, depth, length, exterior, lat)
        if key not in self._bay_plans:
            if len(self._bay_plans) >= _MAX_PLANS:
                self._bay_plans.clear()
            self._bay_plans[key] = self._bay_plan(bays, depth, length, exterior, lat)
        return self._bay_plans[key]

    def _stack_choices(
        self, rooms: tuple[str, ...], depth: int, exterior: bool
    ) -> tuple[tuple[int, StackSol], ...] | None:
        """Stack widths :meth:`bay_plan` may pick: those whose solution has no more predicted
        façade / depth misses than the default one (``None``: no compliant stack)."""
        key = (rooms, depth, exterior)
        if key not in self._choice_cache:
            self._choice_cache[key] = self._stack_choices_uncached(rooms, depth, exterior)
        return self._choice_cache[key]

    def _stack_choices_uncached(
        self, rooms: tuple[str, ...], depth: int, exterior: bool
    ) -> tuple[tuple[int, StackSol], ...] | None:
        reqs = tuple(self.reqs[r] for r in rooms)
        default = self.stack(reqs, depth)
        if default is None:
            return None
        options = self.stack_options(reqs, depth)

        def misses(sol: StackSol) -> tuple[int, int]:
            lit = exterior and sol.rest == 0 and sol.w >= self.k.f
            dmax = self.k.dmax
            deep = int(lit and dmax is not None and reqs[-1].facade and sol.heights[-1] > dmax)
            return int(reqs[-1].facade and not lit), deep

        base = misses(default)
        keep = [
            (w, sol)
            for w, sol in options.items()
            if all(a <= b for a, b in zip(misses(sol), base, strict=True))
        ]
        if not any(w == default.w for w, _ in keep):
            keep.append((default.w, default))
            keep.sort(key=lambda t: t[0])
        return tuple(keep)

    def _bay_plan(
        self,
        bays: tuple[AnyBay, ...],
        depth: int,
        length: int,
        exterior: bool,
        lat: BlockLattice,
    ) -> BayPlan | None:
        s = self.k.s
        # item: (slot, widths, solutions | None, req | None, start side, end side, stack reqs)
        Slot = tuple[int, str]
        items: list[
            tuple[
                Slot,
                tuple[int, ...],
                dict[int, StackSol] | None,
                RoomReq | None,
                bool,
                bool,
                tuple[RoomReq, ...],
            ]
        ] = []
        for b, bay in enumerate(bays):
            if isinstance(bay, ConnectorBay):
                return None
            if isinstance(bay, RoomBay):
                req = self.reqs[bay.room]
                found = self.room_bay_width(req, depth, exterior)
                if found is None:
                    return None
                win = tuple(self.width_window(req, depth, exterior and req.facade))
                items.append(
                    ((b, "B"), win if found in win else (found,), None, req, True, True, ())
                )
                continue
            for tag, rooms in (("L", bay.left), ("S", ()), ("R", bay.right)):
                if tag == "S":
                    items.append(((b, "S"), (s,), None, None, False, False, ()))
                    continue
                if not rooms:
                    continue
                choices = self._stack_choices(rooms, depth, exterior)
                if choices is None:
                    return None
                sols = dict(choices)
                items.append(
                    (
                        (b, tag),
                        tuple(sols),
                        sols,
                        None,
                        True,
                        True,
                        tuple(self.reqs[r] for r in rooms),
                    )
                )
        n = len(items)
        rest = [0] * (n + 1)  # least total width of items i..n-1
        for i in range(n - 1, -1, -1):
            rest[i] = rest[i + 1] + items[i][1][0]
        if rest[0] > length:
            return None
        cell = self.k.cell_mm2
        bay_p, bay_r, tol = lat.bay, lat.bay_res, lat.tol
        col, col_res, edge = lat.col, lat.col_res, lat.edge
        use_cols = col > 0 and bool(lat.cross_t)

        def side(pos: int) -> int:
            """Cost of a room side at ``pos`` (exterior blocks, strictly inside the block)."""
            if not exterior or bay_p == 0 or pos <= 0 or pos >= length:
                return 0
            r = (pos - bay_r) % bay_p
            d = min(r, bay_p - r)
            return BAY_COST if d > tol else d

        def across(t0: int, t1: int) -> int:
            return sum(1 for t in lat.cross_t if t0 + edge <= t <= t1 - edge)

        cur: dict[int, tuple[int, float]] = {0: (0, 0.0)}
        back: list[dict[int, tuple[int, int]]] = []
        for i, (_, win, i_sols, i_req, _start, end_side, sreqs) in enumerate(items):
            # per width: area deviation (float: it only breaks ties) and, for the small rooms,
            # the column lines across them
            prep: list[tuple[int, float, int]] = []
            for w in win:
                if i_req is not None:
                    dev_w = abs(w * depth - float(i_req.target))
                    cross = 0
                    if use_cols and w * depth * cell < lat.small_mm2:
                        cross = across(0, depth)
                elif i_sols is not None:
                    sol = i_sols[w]
                    dev_w = float(w * sol.rest)
                    cross = 0
                    t = 0
                    for r, h in zip(sreqs, sol.heights, strict=True):
                        dev_w += abs(w * h - float(r.target))
                        if use_cols and w * h * cell < lat.small_mm2:
                            cross += across(t, t + h)
                        t += h
                else:
                    dev_w, cross = 0.0, 0
                prep.append((w, dev_w, cross))
            nxt: dict[int, tuple[int, float]] = {}
            how: dict[int, tuple[int, int]] = {}
            start_side = items[i][4]
            prev_end = items[i - 1][5] if i else False
            room_after = rest[i + 1]
            limit = min(c for c, _ in cur.values()) + _BEAM * BAY_COST
            for pos, (cost, dev) in cur.items():
                if cost > limit:
                    continue
                base = cost + (side(pos) if start_side and not prev_end else 0)
                for w, dev_w, cross in prep:
                    end = pos + w
                    if end + room_after > length:
                        break
                    c = base + side(end) if end_side else base
                    if cross:
                        first = -((col_res - (pos + edge)) // col)  # ceil((x0 - res) / col)
                        last = (end - edge - col_res) // col
                        if last >= first:
                            c += BAY_COST * (last - first + 1) * cross
                    d = dev + dev_w
                    old = nxt.get(end)
                    if old is None or (c, d) < old:
                        nxt[end] = (c, d)
                        how[end] = (pos, w)
            if not nxt:
                return None
            back.append(how)
            cur = nxt
        pos = min(cur, key=lambda e: (cur[e], e))
        total = cur[pos][0]
        widths_out: dict[tuple[int, str], int] = {}
        for i in range(n - 1, -1, -1):
            prev, w = back[i][pos]
            if items[i][0][1] != "S":
                widths_out[items[i][0]] = w
            pos = prev
        return widths_out, total

    # ------------------------------------------------------------------ 5.4 block
    def block(
        self,
        bays: tuple[AnyBay, ...],
        depth: int,
        length: int,
        where: str,
        exterior: bool = False,
        lattice: BlockLattice | None = None,
    ) -> BlockOut:
        """Lay out ``bays`` in a block of ``depth`` x ``length``; ``where`` names it.

        A :class:`ConnectorBay` marker takes ``s`` along the spine right after the bays
        before it (the piece moves it to its connector, see :meth:`BlockOut.placed`).
        ``exterior``: the block's outer long side lies on the footprint exterior (Q.3).
        ``lattice`` (M.3b, or the one the bound realiser gives for ``where``): when the block
        lays out without failure, choose the widths of its room bays and stacks inside their
        windows for the lattice (:meth:`bay_plan`) and lay it out again with them; its
        ``area_dev`` gains the lattice cost ahead of the area deviation. ``None`` and no bound
        realiser: the widths of RD 3.3 §5.2, unchanged.
        """
        out = self._lay(bays, depth, length, where, exterior, {})
        own = self.owner if lattice is None else None
        if own is not None:
            lattice = own.lattice_for(where, depth)
        if lattice is None or out.failures or out.depth <= 0:
            return out
        plan = self.bay_plan(bays, depth, length, exterior, lattice)
        if plan is None:
            return out
        if plan[0]:
            again = self._lay(bays, depth, length, where, exterior, plan[0])
            if again.failures or again.no_facade > out.no_facade:  # pragma: no cover - guarded
                return out
            out = again
        extra = 0 if own is None else own.end_cost_for(where, depth, out)
        out.bay_cost = plan[1] + extra
        out.area_dev += BAY_UNIT * out.bay_cost
        return out

    def _lay(
        self,
        bays: tuple[AnyBay, ...],
        depth: int,
        length: int,
        where: str,
        exterior: bool,
        chosen: dict[tuple[int, str], int],
    ) -> BlockOut:
        out = BlockOut(depth=depth)
        s = self.k.s
        has_marker = any(isinstance(bay, ConnectorBay) for bay in bays)
        if all(isinstance(bay, ConnectorBay) for bay in bays):
            if has_marker:
                out.marker = 0
            if depth > 0:
                start = s if has_marker else 0
                if length > start:
                    out.items.append(Item("end_strip", None, start, 0, length - start, depth))
                    out.end_cells += (length - start) * depth
            return out
        if depth <= 0:
            out.failures.append(("BLOCK_TOO_SHALLOW", f"{where} has rooms but depth {depth}"))
            out.no_facade = sum(
                self.reqs[r].facade
                for bay in bays
                if not isinstance(bay, ConnectorBay)
                for r in ((bay.room,) if isinstance(bay, RoomBay) else (*bay.left, *bay.right))
            )
            return out
        u = 0
        for b, bay in enumerate(bays):
            if isinstance(bay, ConnectorBay):
                out.marker = u
                out.split = len(out.items)
                u += s
                continue
            if isinstance(bay, RoomBay):
                req = self.reqs[bay.room]
                found = chosen.get((b, "B"))
                if found is None:
                    found = self.room_bay_width(req, depth, exterior)
                if found is None:
                    out.failures.append(
                        (
                            "ROOM_INFEASIBLE",
                            f"{bay.room} in {where}: no compliant width at depth {depth}",
                        )
                    )
                w = max(req.wmin, req.ceil_div(depth)) if found is None else found
                if req.facade and not (exterior and w >= self.k.f):
                    out.no_facade += 1
                elif req.facade and self.k.dmax is not None and depth > self.k.dmax:
                    self._too_deep(out, depth - self.k.dmax, w)
                self._room(out, bay.room, req, u, 0, w, depth)
                u += w
                continue
            w_left = self._stack_items(
                out, bay.left, u, depth, f"{where} bay {b} left", exterior, chosen.get((b, "L"))
            )
            finger_u = u + w_left
            out.items.append(Item("finger", None, finger_u, 0, s, depth))
            if bay.junction:
                out.junction_u = finger_u
                out.junction_post = out.marker is not None
                out.fingers[bay.junction_to] = (finger_u, out.marker is not None)
            w_right = self._stack_items(
                out,
                bay.right,
                finger_u + s,
                depth,
                f"{where} bay {b} right",
                exterior,
                chosen.get((b, "R")),
            )
            u = finger_u + s + w_right
        if out.marker is not None:
            out.post = u - out.marker - s
        extra = length - u
        if extra > 0:
            out.items.append(Item("end_strip", None, u, 0, extra, depth))
            out.end_cells += extra * depth
        elif extra < 0:
            out.failures.append(("PLAN_OVERFLOW", f"{where} over by {-extra} modules"))
        return out

    def _room(
        self, out: BlockOut, room: str, req: RoomReq, u: int, t: int, du: int, dt: int
    ) -> None:
        out.items.append(Item("room", room, u, t, du, dt))
        # Depth-search area term: |placed - target| (an undershoot only arises from the
        # fallbacks, which must not look cheaper than an exact fit).
        out.area_dev += abs(du * dt - req.target)

    def _stack_items(
        self,
        out: BlockOut,
        rooms: tuple[str, ...],
        u: int,
        depth: int,
        where: str,
        exterior: bool = False,
        width: int | None = None,
    ) -> int:
        """Append a stack's rooms (and stack-end strip) at ``u``; return its width. ``width``
        (M.3b): the stack width chosen by :meth:`bay_plan`."""
        if not rooms:
            return 0
        reqs = tuple(self.reqs[r] for r in rooms)
        sol = self.stack(reqs, depth) if width is None else self.stack_options(reqs, depth)[width]
        lit = exterior and sol is not None and sol.rest == 0 and sol.w >= self.k.f
        out.no_facade += sum(r.facade for r in reqs[:-1]) + (reqs[-1].facade and not lit)
        dmax = self.k.dmax
        deep = lit and dmax is not None and reqs[-1].facade and sol is not None
        if deep and sol is not None and dmax is not None and sol.heights[-1] > dmax:
            self._too_deep(out, sol.heights[-1] - dmax, sol.w)
        if sol is None:
            out.failures.append(
                (
                    "STACK_INFEASIBLE",
                    f"{where}: no compliant stack width for {', '.join(rooms)} at depth {depth}",
                )
            )
            return max(r.wmin for r in reqs)
        t = 0
        for room, req, h in zip(rooms, reqs, sol.heights, strict=True):
            self._room(out, room, req, u, t, sol.w, h)
            t += h
        if sol.rest > 0:
            out.items.append(Item("stack_strip", None, u, t, sol.w, sol.rest))
            out.strip_cells += sol.w * sol.rest
        return sol.w
