"""Room-bay widths, stack solving and block layout (RD 3.3 sections 4, 5.2-5.4).

Everything here works in integer modules in a block-local frame: ``u`` along the spine
(from the piece's min corner) and ``t`` = distance from the spine (``0`` at the spine,
``D`` at the block's outer edge). :mod:`ale.geometry.realize` maps ``t`` to the piece's
``v`` coordinate. Areas are module² cells; targets are exact ``Fraction`` cells.

Ticket Q.1: every room placed here satisfies the area rule, ``aspect <= amax`` and its
``wmin``. A room bay or stack that cannot is a block failure (``ROOM_INFEASIBLE`` /
``STACK_INFEASIBLE``) instead of the former rule-breaking fallbacks.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal

from ale.contracts.area_rule import AreaTolerance, area_bounds_mm2
from ale.contracts.config import AleConfig
from ale.contracts.corridor_plan import FingerBay, RoomBay
from ale.contracts.models import RoomSpec
from ale.contracts.units import to_decimal
from ale.guards import bounded

__all__ = [
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

ItemKind = Literal["room", "finger", "stack_strip", "end_strip"]


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

    @classmethod
    def from_config(cls, config: AleConfig) -> Consts:
        m = config.grid.module_mm

        def modules(length_m: float) -> int:
            return math.ceil(Fraction(to_decimal(length_m)) * 1000 / m)

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
            target=target, lo=_ceil_div(lo_mm2, cell), hi=hi_mm2 // cell, wmin=self.wmin(spec)
        )


@dataclass(frozen=True)
class RoomReq:
    """Area target ``target`` (exact cells), bounds ``[lo, hi]`` (cells), ``wmin`` (modules)."""

    target: Fraction
    lo: int
    hi: int
    wmin: int

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


class Solver:
    """Memoised room-bay / stack solver for one realisation (RD 5.2-5.4)."""

    def __init__(self, consts: Consts, reqs: Mapping[str, RoomReq]) -> None:
        self.k = consts
        self.reqs = reqs
        self._bay_cache: dict[tuple[RoomReq, int], int | None] = {}
        self._stack_cache: dict[tuple[tuple[RoomReq, ...], int], StackSol | None] = {}

    # ------------------------------------------------------------------ 5.2 room bay
    def room_bay_width(self, req: RoomReq, depth: int) -> int | None:
        """Width of a room bay at ``depth`` satisfying the area rule, ``aspect <= amax`` and
        ``wmin`` (RD 3.3 §5.2), or ``None`` when no width does (Q.1: ``ROOM_INFEASIBLE``)."""
        key = (req, depth)
        if key not in self._bay_cache:
            self._bay_cache[key] = self._room_bay_width(req, depth)
        return self._bay_cache[key]

    def _room_bay_width(self, req: RoomReq, depth: int) -> int | None:
        if depth < req.wmin:
            return None
        amax = self.k.amax
        w_up = max(req.wmin, req.ceil_div(depth))
        for w in guarded_range(w_up, req.hi // depth + 1, label="room-bay-width"):
            if aspect_ok(w, depth, amax):
                return w
        w_lo = max(req.wmin, _ceil_div(req.lo, depth))
        for w in guarded_range(w_up - 1, w_lo - 1, step=-1, label="room-bay-width-down"):
            if aspect_ok(w, depth, amax):  # w < ceil(T / D) here, so lo <= w·D < T
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

    # ------------------------------------------------------------------ 5.4 block
    def block(
        self,
        bays: tuple[RoomBay | FingerBay, ...],
        depth: int,
        length: int,
        where: str,
    ) -> BlockOut:
        """Lay out ``bays`` in a block of ``depth`` x ``length``; ``where`` names it."""
        out = BlockOut()
        if not bays:
            if depth > 0:
                out.items.append(Item("end_strip", None, 0, 0, length, depth))
                out.end_cells += length * depth
            return out
        if depth <= 0:
            out.failures.append(("BLOCK_TOO_SHALLOW", f"{where} has rooms but depth {depth}"))
            return out
        u = 0
        for b, bay in enumerate(bays):
            if isinstance(bay, RoomBay):
                req = self.reqs[bay.room]
                found = self.room_bay_width(req, depth)
                if found is None:
                    out.failures.append(
                        (
                            "ROOM_INFEASIBLE",
                            f"{bay.room} in {where}: no compliant width at depth {depth}",
                        )
                    )
                w = max(req.wmin, req.ceil_div(depth)) if found is None else found
                self._room(out, bay.room, req, u, 0, w, depth)
                u += w
                continue
            w_left = self._stack_items(out, bay.left, u, depth, f"{where} bay {b} left")
            finger_u = u + w_left
            out.items.append(Item("finger", None, finger_u, 0, self.k.s, depth))
            if bay.junction:
                out.junction_u = finger_u
            w_right = self._stack_items(
                out, bay.right, finger_u + self.k.s, depth, f"{where} bay {b} right"
            )
            u = finger_u + self.k.s + w_right
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
        self, out: BlockOut, rooms: tuple[str, ...], u: int, depth: int, where: str
    ) -> int:
        """Append a stack's rooms (and stack-end strip) at ``u``; return its width."""
        if not rooms:
            return 0
        reqs = tuple(self.reqs[r] for r in rooms)
        sol = self.stack(reqs, depth)
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
