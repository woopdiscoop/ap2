"""Room shapes of the bay-first planner (Ticket M.4, RD section 4.5) and the facade-row depth.

All lengths are integer modules (0.10 m). Shapes are rectangles ``w`` (along the bar) by ``d``
(across it). A shape is *admissible* for a room when its area is in the room's sketch window,
its aspect is within ``aspect_max`` and it meets the room's minimum width.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from ale.contracts.models import RoomSpec, Rulebook
from ale.geometry.blocks import Consts, aspect_ok

__all__ = [
    "REF_DEPTH_M",
    "Shape",
    "admissible",
    "choose_facade_depth",
    "deviation",
    "legal_aspect",
    "rect_shape_ok",
]

REF_DEPTH_M = 5.4
DEPTH_CANDIDATES_M = (3.6, 4.2, 4.8, 5.4, 6.0, 6.6, 7.2)


@dataclass(frozen=True)
class Shape:
    """A candidate rectangle: ``kind`` is F, D, T, B or b; ``n`` its width in half-bays (F, D, T)
    or 0 (B, b); ``w`` and ``d`` in modules."""

    kind: str
    n: int
    w: int
    d: int

    @property
    def cells(self) -> int:
        return self.w * self.d

    @property
    def tag(self) -> str:
        if self.n:
            k = self.n / 2
            return f"{self.kind}{k:g}"
        return f"{self.kind}{self.w / 10:g}"


def legal_aspect(k: Consts, w: int, d: int) -> bool:
    return aspect_ok(w, d, k.amax)


def deviation(k: Consts, spec: RoomSpec, w: int, d: int) -> float:
    """Relative area deviation of a ``w`` x ``d`` rectangle from the room's target."""
    target = k.req(spec).target
    return float(abs(Fraction(w * d) - target) / target)


def rect_shape_ok(k: Consts, spec: RoomSpec, w: int, d: int, *, window: bool = True) -> bool:
    """Aspect, minimum width and (with ``window``) the sketch area window; with the hard facade
    depth limit also the depth of a facade room."""
    req = k.req(spec)
    if min(w, d) < req.wmin or not legal_aspect(k, w, d):
        return False
    return not window or req.lo <= w * d <= req.hi


def admissible(k: Consts, spec: RoomSpec, w: int, d: int) -> bool:
    return rect_shape_ok(k, spec, w, d)


def choose_facade_depth(
    specs: Sequence[RoomSpec],
    k: Consts,
    bay: int,
    *,
    rulebook: Rulebook | None = None,
    max_depth_m: float | None = None,
) -> tuple[int, float]:
    """The facade-row depth ``d_f`` (modules) of the building and the target area of the facade
    rooms it serves. Candidates 3.6 .. 7.2 m (at most ``max_depth_m``, at most ``aspect_max`` x
    the bay); maximise the target area of the ``needs_facade`` rooms that have an in-window
    shape ``k * bay`` x ``d`` (k a multiple of 0.5, aspect within the limit); ties: nearest to
    the reference depth (the learned ``office`` median, else 5.4 m), then the smaller."""
    ref = REF_DEPTH_M
    if rulebook is not None:
        office = rulebook.types.get("office")
        if office is not None and office.depth_m is not None:
            ref = float(office.depth_m.p50)
    unit = k.module_mm / 1000.0
    half = bay // 2
    best: tuple[tuple[float, float, int], int, float] | None = None
    for d_m in DEPTH_CANDIDATES_M:
        d = round(d_m / unit)
        if max_depth_m is not None and d_m > max_depth_m + 1e-9:
            continue
        if not aspect_ok(bay, d, k.amax) and d > bay:
            continue
        total = 0.0
        for spec in specs:
            if not spec.needs_facade:
                continue
            for n in range(1, 41):
                if rect_shape_ok(k, spec, n * half, d):
                    total += spec.target_area_m2
                    break
        key = (-total, abs(d_m - ref), d)
        if best is None or key < best[0]:
            best = (key, d, total)
    if best is None:
        raise ValueError("aucune profondeur de rangée de façade candidate")
    return best[1], best[2]
