"""Area-tolerance rule (m² in, exact integer mm² / module² arithmetic inside).

Default tolerance: -3 % / +max(3 %, 1.2 m²). Architect decision D1: when choosing a
buildable rectangle, round the area up (smallest area ≥ target) whenever possible.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ale.contracts.geometry import Float, ModuleRect
from ale.contracts.models import GridSpec
from ale.contracts.units import check_module_mm, mm2_to_m2, to_decimal

__all__ = ["AreaCheck", "AreaTolerance", "area_bounds_mm2", "best_buildable_rect", "check_area"]

_CONFIG = ConfigDict(extra="forbid", frozen=True)
_MM2_PER_M2 = 1_000_000

NonNegFloat = Annotated[Float, Field(ge=0.0)]


class AreaTolerance(BaseModel):
    """Area tolerance: ``down_pct`` / ``up_pct`` in percent, ``up_abs_m2`` in m² (all ≥ 0)."""

    model_config = _CONFIG

    down_pct: NonNegFloat = 3.0
    up_pct: NonNegFloat = 3.0
    up_abs_m2: NonNegFloat = 1.2


class AreaCheck(BaseModel):
    """Result of ``check_area``: areas in m², ``delta_pct`` in percent of the target."""

    model_config = _CONFIG

    valid: StrictBool
    placed_m2: Float
    delta_m2: Float
    delta_pct: Float
    overshoot_m2: Float


def _exact(x: float) -> Fraction:
    return Fraction(to_decimal(x))


def _target_mm2(target_m2: float) -> Fraction:
    t = _exact(target_m2) * _MM2_PER_M2
    if t <= 0:
        raise ValueError(f"target_m2 must be > 0, got {target_m2!r}")
    return t


def _bounds(t_mm2: Fraction, tol: AreaTolerance) -> tuple[int, int]:
    lo = math.ceil(t_mm2 * (1 - _exact(tol.down_pct) / 100))
    up = max(t_mm2 * _exact(tol.up_pct) / 100, _exact(tol.up_abs_m2) * _MM2_PER_M2)
    hi = math.floor(t_mm2 + up)
    return lo, hi


def area_bounds_mm2(target_m2: float, tol: AreaTolerance) -> tuple[int, int]:
    """Inclusive integer bounds ``[lo, hi]`` in mm² for a target area in m².

    ``lo = ceil(T·(1 - down_pct/100))``, ``hi = floor(T + max(T·up_pct/100, up_abs_m2))``,
    with T the target in mm² (exact decimal arithmetic).
    """
    return _bounds(_target_mm2(target_m2), tol)


def check_area(rect: ModuleRect, grid: GridSpec, target_m2: float, tol: AreaTolerance) -> AreaCheck:
    """Check a placed rectangle (modules) against a target area (m²)."""
    t_mm2 = _target_mm2(target_m2)
    lo, hi = _bounds(t_mm2, tol)
    placed_mm2 = rect.area_cells() * grid.module_mm**2
    delta = Fraction(placed_mm2) - t_mm2  # mm², exact
    return AreaCheck(
        valid=lo <= placed_mm2 <= hi,
        placed_m2=mm2_to_m2(placed_mm2),
        delta_m2=float(delta / _MM2_PER_M2),
        delta_pct=float(delta / t_mm2 * 100),
        overshoot_m2=float(max(Fraction(0), delta) / _MM2_PER_M2),
    )


def _ceil_div(a: int, b: int) -> int:
    return -((-a) // b)


def best_buildable_rect(
    target_m2: float,
    grid: GridSpec,
    aspect_min: float,
    aspect_max: float,
    tol: AreaTolerance,
    min_short_side_modules: int = 1,
    max_side_modules: int | None = None,
) -> tuple[int, int] | None:
    """Best ``(short, long)`` rectangle in modules for a target area in m², or ``None``.

    Constraints: ``short ≤ long``; ``long/short`` in ``[aspect_min, aspect_max]`` (exact,
    via ``Fraction(str(aspect))``); area within ``area_bounds_mm2``; ``short ≥
    min_short_side_modules``; both sides ``≤ max_side_modules`` when given.
    Preference: smallest area ≥ target; else largest area < target; ties broken by smaller
    ``|long/short - 1|`` then smaller short side. O(√cells) iterations.
    """
    module = check_module_mm(grid.module_mm)
    cell_mm2 = module * module
    t_mm2 = _target_mm2(target_m2)
    lo_mm2, hi_mm2 = _bounds(t_mm2, tol)
    lo_cells = _ceil_div(lo_mm2, cell_mm2)
    hi_cells = hi_mm2 // cell_mm2
    t_cells = t_mm2 / cell_mm2  # exact Fraction
    a_min = Fraction(str(aspect_min))
    a_max = Fraction(str(aspect_max))

    # candidate key: (area_cells, |long/short - 1|, short) ; plus the pair
    best_up: tuple[int, Fraction, int, int] | None = None
    best_down: tuple[int, Fraction, int, int] | None = None
    s = max(1, min_short_side_modules)
    while s * s <= hi_cells:
        if max_side_modules is not None and s > max_side_modules:
            break
        l_min = max(s, math.ceil(a_min * s), _ceil_div(lo_cells, s))
        l_max = min(math.floor(a_max * s), hi_cells // s)
        if max_side_modules is not None:
            l_max = min(l_max, max_side_modules)
        if l_min <= l_max:
            l_target = math.ceil(t_cells / s)  # smallest long side with area ≥ target
            l_up = max(l_min, l_target)
            if l_up <= l_max:
                cand = (s * l_up, Fraction(l_up, s) - 1, s, l_up)
                if best_up is None or cand < best_up:
                    best_up = cand
            l_down = min(l_max, l_target - 1)
            if l_down >= l_min:
                cand = (s * l_down, Fraction(l_down, s) - 1, s, l_down)
                if best_down is None or (-cand[0], cand[1], cand[2]) < (
                    -best_down[0],
                    best_down[1],
                    best_down[2],
                ):
                    best_down = cand
        s += 1
    chosen = best_up if best_up is not None else best_down
    if chosen is None:
        return None
    return chosen[2], chosen[3]
