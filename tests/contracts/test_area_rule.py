"""Tests A01-A10: area tolerance rule and best buildable rectangle."""

from __future__ import annotations

import time

import pytest

from ale.contracts.area_rule import (
    AreaTolerance,
    area_bounds_mm2,
    best_buildable_rect,
    check_area,
)
from ale.contracts.geometry import ModuleRect
from ale.contracts.models import GridSpec

TOL = AreaTolerance()
GRID600 = GridSpec(module_mm=600)
GRID100 = GridSpec(module_mm=100)


@pytest.mark.parametrize(
    ("target", "expected", "area"),
    [
        (3, (3, 3), 3.24),
        (4, (3, 4), 4.32),
        (6, (3, 6), 6.48),
        (8, (4, 6), 8.64),
        (12, (5, 7), 12.60),
        (7.5, (4, 6), 8.64),
    ],
)
def test_A01_directive_table(target: float, expected: tuple[int, int], area: float) -> None:
    result = best_buildable_rect(target, GRID600, 1.0, 2.0, TOL)
    assert result == expected
    check = check_area(ModuleRect(0, 0, *result), GRID600, target, TOL)
    assert check.valid
    assert check.placed_m2 == area


def test_A01_delta_7_5() -> None:
    check = check_area(ModuleRect(0, 0, 4, 6), GRID600, 7.5, TOL)
    assert check.delta_m2 == pytest.approx(1.14, abs=1e-9)


def test_A02_cap_gap() -> None:
    assert best_buildable_rect(7.43, GRID600, 1.0, 2.0, TOL) is None


def test_A03_bounds_exact() -> None:
    assert area_bounds_mm2(10, TOL) == (9_700_000, 11_200_000)
    # Rectangles exactly on the bounds are valid; one cell outside is not
    # (module 100 mm -> 1 cell = 0.01 m²).
    assert check_area(ModuleRect(0, 0, 97, 10), GRID100, 10, TOL).valid  # 9.70 m²
    assert check_area(ModuleRect(0, 0, 10, 112), GRID100, 10, TOL).valid  # 11.20 m²
    assert not check_area(ModuleRect(0, 0, 19, 51), GRID100, 10, TOL).valid  # 9.69 m²
    assert not check_area(ModuleRect(0, 0, 19, 59), GRID100, 10, TOL).valid  # 11.21 m²
    assert check_area(ModuleRect(0, 0, 19, 51), GRID100, 10, TOL).placed_m2 == 9.69


def test_A04_pct_regime() -> None:
    assert area_bounds_mm2(60, TOL)[1] == 61_800_000


def test_A05_check_fields() -> None:
    c = check_area(ModuleRect(0, 0, 4, 6), GRID600, 7.5, TOL)
    assert c.valid
    assert c.placed_m2 == 8.64
    assert c.delta_m2 == pytest.approx(1.14, abs=1e-9)
    assert c.overshoot_m2 == pytest.approx(1.14, abs=1e-9)
    assert c.delta_pct == pytest.approx(15.2)
    under = check_area(ModuleRect(0, 0, 3, 6), GRID600, 7.0, TOL)
    assert under.overshoot_m2 == 0.0
    assert under.delta_m2 < 0


def test_A06_narrow_band() -> None:
    assert best_buildable_rect(11.9, GRID600, 1.5, 2.0, TOL) is None
    assert best_buildable_rect(11.9, GRID600, 1.0, 2.0, TOL) == (5, 7)


def test_A07_min_side() -> None:
    assert best_buildable_rect(3, GRID600, 1.0, 2.0, TOL, min_short_side_modules=4) is None


def test_A08_bounded() -> None:
    t0 = time.perf_counter()
    assert best_buildable_rect(10_000, GRID600, 1.0, 1.0, TOL, max_side_modules=200) == (167, 167)
    assert time.perf_counter() - t0 < 1.0
    assert best_buildable_rect(10_000, GRID600, 1.0, 1.0, TOL, max_side_modules=160) is None


def test_A09_rounds_up() -> None:
    assert best_buildable_rect(3.3, GRID600, 1.0, 2.0, TOL) == (3, 4)


def test_A09_below_target_fallback() -> None:
    # With no upward tolerance, no square of 0.01 m² cells hits 3.30 m² exactly (330 cells),
    # so the largest square below the target (still >= -3 %) is chosen: 18 x 18 = 3.24 m².
    tol = AreaTolerance(up_pct=0.0, up_abs_m2=0.0)
    assert best_buildable_rect(3.3, GRID100, 1.0, 1.0, tol) == (18, 18)
    # In a 1:1-1:2 band the exact area exists (330 cells = 15 x 22), so it wins.
    assert best_buildable_rect(3.3, GRID100, 1.0, 2.0, tol) == (15, 22)
    # Equal areas (12 cells: 3 x 4 and 2 x 6): the squarer one wins.
    assert best_buildable_rect(4.32, GRID600, 1.0, 3.0, TOL) == (3, 4)


def test_A10_fine_grid() -> None:
    assert best_buildable_rect(7.43, GRID100, 1.0, 2.0, TOL) == (24, 31)
    assert best_buildable_rect(10_000, GRID100, 1.0, 1.0, TOL) == (1000, 1000)
    t0 = time.perf_counter()
    worst_cells = 0
    for i in range(200, 6001):  # T = 2.00 ... 60.00 m², targets in cells of 0.01 m²
        result = best_buildable_rect(i / 100, GRID100, 1.0, 2.0, TOL)
        assert result is not None, i
        cells = result[0] * result[1]
        assert cells >= i, i
        worst_cells = max(worst_cells, cells - i)
    assert worst_cells <= 11  # max overshoot <= 0.11 m²
    assert time.perf_counter() - t0 < 10.0


def test_area_rule_preconditions() -> None:
    with pytest.raises(ValueError):
        area_bounds_mm2(0, TOL)
    with pytest.raises(ValueError):
        check_area(ModuleRect(0, 0, 1, 1), GRID100, -1.0, TOL)
    with pytest.raises(ValueError):
        AreaTolerance(down_pct=-1)
