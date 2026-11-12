"""Ticket M.3b: the bay-aware realiser (``ale.geometry.bay``, ``Solver.bay_plan``).

B306 (byte identity without a hint) is covered here for the realiser and, for the whole
pipeline, by the M206 digests of ``test_geometry_m2.py``. The checks below use small rectangles
whose rows of rooms have width windows of a few modules, so the effect of the lattice is exact.
"""

from __future__ import annotations

import random

import pytest
from geometry_helpers import load_test_rulebook, one_piece, prepared_rect, rb, room

from ale.config import AleConfig
from ale.contracts.serialization import canonical_json
from ale.geometry import check_layout, realize
from ale.geometry.bay import (
    LATTICE_COST,
    BayHint,
    BlockLattice,
    axis_lattice,
    current_bay_hint,
    lattice_figures,
    lines_in,
    use_bay_hint,
)
from ale.geometry.blocks import BAY_UNIT, Consts, Solver
from ale.geometry.evaluate import evaluate
from ale.geometry.realize import shared_solver

CONFIG = AleConfig()
RULEBOOK = load_test_rulebook()
K = Consts.from_config(CONFIG)

# bay lines every 2.4 m (24 modules), column lines every 7.2 m, both through x = y = 0
HINT = BayHint(
    bay_x_mm=2400,
    bay_y_mm=2400,
    line_x_mm=0,
    line_y_mm=0,
    col_x_mm=7200,
    col_y_mm=7200,
    colline_x_mm=0,
    colline_y_mm=0,
)


def bar(n: int = 6, area: float = 14.0) -> tuple[object, object]:
    """``n`` offices of ``area`` m² on the two sides of a 240 x 80 module rectangle."""
    rooms = [room(f"O{i}", area, needs_facade=True) for i in range(n)]
    prepared = prepared_rect(240, 80, rooms)
    ids = [f"O{i}" for i in range(n)]
    plan = one_piece([rb(x) for x in ids[: n // 2]], [rb(x) for x in ids[n // 2 :]])
    return prepared, plan


# ------------------------------------------------------------------------------ B306
def test_B306_no_hint_is_the_old_path() -> None:
    prepared, plan = bar()
    plain = realize(prepared, plan, RULEBOOK, CONFIG)  # type: ignore[arg-type]
    with use_bay_hint(None):
        again = realize(prepared, plan, RULEBOOK, CONFIG)  # type: ignore[arg-type]
    assert plain.layout is not None and again.layout is not None
    assert canonical_json(plain.layout) == canonical_json(again.layout)
    assert LATTICE_COST not in plain.layout.metrics.cost_breakdown
    assert current_bay_hint() is None


def test_B306_hint_does_not_leak_into_the_next_call() -> None:
    prepared, plan = bar()
    before = realize(prepared, plan, RULEBOOK, CONFIG)  # type: ignore[arg-type]
    with use_bay_hint(HINT):
        hinted = realize(prepared, plan, RULEBOOK, CONFIG)  # type: ignore[arg-type]
    after = realize(prepared, plan, RULEBOOK, CONFIG)  # type: ignore[arg-type]
    assert before.layout is not None and after.layout is not None and hinted.layout is not None
    assert canonical_json(before.layout) == canonical_json(after.layout)
    assert LATTICE_COST in hinted.layout.metrics.cost_breakdown
    # the shared solver is not bound to a realiser any more
    reqs = {iid: K.req(spec) for iid, spec in prepared.instances}  # type: ignore[attr-defined]
    assert shared_solver(K, reqs).owner is None


def test_B306_solver_block_without_lattice_has_no_bay_cost() -> None:
    prepared, plan = bar()
    reqs = {iid: K.req(spec) for iid, spec in prepared.instances}  # type: ignore[attr-defined]
    solver = Solver(K, reqs)
    bays = plan.pieces[0].bands[0].block_a.bays  # type: ignore[attr-defined]
    out = solver.block(bays, 34, 240, "piece 0 band 0 block A", True)
    assert out.bay_cost is None


def test_hint_context_nests_and_restores() -> None:
    other = BayHint(2400, 2400, 0, 0, 7200, 7200, 0, 0)
    assert current_bay_hint() is None
    with use_bay_hint(HINT):
        assert current_bay_hint() is HINT
        with use_bay_hint(other):
            assert current_bay_hint() is other
        with use_bay_hint(None):
            assert current_bay_hint() is None
        assert current_bay_hint() is HINT
    assert current_bay_hint() is None


# ---------------------------------------------------------------------------- lattice
def test_axis_lattice_and_lines() -> None:
    assert axis_lattice(0, 2400, 0, 100) == (24, 0)
    assert axis_lattice(0, 2400, 700, 100) == (24, 17)  # u = 0 is at x = 700: lines at u = 17, 41
    assert axis_lattice(50, 2400, 0, 100) == (0, 0)  # lines not on the module grid
    assert axis_lattice(0, 0, 0, 100) == (0, 0)
    assert lines_in(0, 2400, 100, 5000) == [2400, 4800]
    assert lines_in(0, 2400, 5000, 100) == []


def _block_cost_and_off(
    solver: Solver, bays: tuple[object, ...], depth: int, length: int, lat: BlockLattice | None
) -> tuple[list[int], int | None]:
    out = solver.block(bays, depth, length, "piece 0 band 0 block A", True, lat)  # type: ignore[arg-type]
    ends = sorted(it.u + it.du for it in out.items if it.kind == "room")
    return ends, out.bay_cost


def _off(pos: int, lat: BlockLattice) -> bool:
    r = (pos - lat.bay_res) % lat.bay
    return min(r, lat.bay - r) > lat.tol


@pytest.mark.parametrize("seed", range(12))
def test_bay_plan_never_has_more_off_partitions_than_the_default(seed: int) -> None:
    rng = random.Random(seed)
    n = rng.randint(3, 8)
    areas = [rng.choice([9.0, 12.0, 15.0, 18.0, 24.0, 30.0]) for _ in range(n)]
    rooms = [room(f"R{i}", a, needs_facade=bool(rng.getrandbits(1))) for i, a in enumerate(areas)]
    prepared = prepared_rect(240, 80, rooms)
    reqs = {iid: K.req(spec) for iid, spec in prepared.instances}
    solver = Solver(K, reqs)
    bays = tuple(rb(f"R{i}") for i in range(n))
    lat = BlockLattice(
        bay=24, bay_res=rng.randrange(24), col=0, col_res=0, tol=3, edge=2, cross_t=(), small_mm2=0
    )
    for depth in range(24, 60, 3):
        plain = solver.block(bays, depth, 240, "piece 0 band 0 block A", True)
        if plain.failures:
            continue
        default_off = sum(
            _off(it.u + it.du, lat)
            for it in plain.items
            if it.kind == "room" and it.u + it.du < 240
        )
        got = solver.block(bays, depth, 240, "piece 0 band 0 block A", True, lat)
        assert not got.failures and got.no_facade <= plain.no_facade
        off = sum(
            _off(it.u + it.du, lat) for it in got.items if it.kind == "room" and it.u + it.du < 240
        )
        assert off <= default_off
        assert got.bay_cost is not None and got.bay_cost >= 100 * off
        # every room is still inside its area window, aspect and minimum width
        for it in got.items:
            if it.kind != "room":
                continue
            req = reqs[it.room]  # type: ignore[index]
            assert req.lo <= it.du * it.dt <= req.hi
            assert it.du >= req.wmin
        # the lattice cost is charged ahead of the area deviation
        assert got.area_dev >= BAY_UNIT * got.bay_cost


def test_a_window_with_a_line_in_it_puts_the_partition_on_the_line() -> None:
    # 17 m² at depth 40: widths 42..45; the default (43) ends 5 modules short of the line at
    # 48, 45 ends within the 3-module tolerance
    rooms = [room("A", 17.0), room("B", 14.0)]
    prepared = prepared_rect(120, 100, rooms)
    reqs = {iid: K.req(spec) for iid, spec in prepared.instances}
    solver = Solver(K, reqs)
    lat = BlockLattice(24, 0, 0, 0, 3, 2, (), 0)
    bays = (rb("A"), rb("B"))
    plain_ends, plain_cost = _block_cost_and_off(solver, bays, 40, 120, None)
    ends, cost = _block_cost_and_off(solver, bays, 40, 120, lat)
    assert plain_cost is None and _off(plain_ends[0], lat)
    assert cost is not None and not _off(ends[0], lat)
    assert cost == 100 * _off(ends[1], lat) + sum(
        min((e - lat.bay_res) % lat.bay, lat.bay - (e - lat.bay_res) % lat.bay)
        for e in ends
        if not _off(e, lat)
    )


# ------------------------------------------------------------------- whole realisation
@pytest.mark.parametrize("n", [4, 6, 8])
def test_hinted_realisation_is_valid_and_not_worse_on_the_lattice(n: int) -> None:
    prepared, plan = bar(n)
    plain = realize(prepared, plan, RULEBOOK, CONFIG)  # type: ignore[arg-type]
    with use_bay_hint(HINT):
        hinted = realize(prepared, plan, RULEBOOK, CONFIG)  # type: ignore[arg-type]
    assert plain.layout is not None and hinted.layout is not None
    assert check_layout(hinted.layout, prepared, CONFIG) == ()  # type: ignore[arg-type]
    area_codes = {"AREA_UNDER", "AREA_OVER", "ASPECT", "MIN_WIDTH"}
    assert not {v.code for v in hinted.layout.metrics.violations} & area_codes
    fp = lattice_figures(plain.layout, (0, 0), HINT)
    fh = lattice_figures(hinted.layout, (0, 0), HINT)
    assert fh.off + fh.small <= fp.off + fp.small
    assert HINT.stats.realisations >= 1


def test_the_lattice_term_is_in_the_cost_only_with_a_hint() -> None:
    prepared, plan = bar(4)
    plain = realize(prepared, plan, RULEBOOK, CONFIG)  # type: ignore[arg-type]
    assert plain.layout is not None
    base = evaluate(plain.layout, prepared, RULEBOOK, CONFIG)  # type: ignore[arg-type]
    assert LATTICE_COST not in base.cost_breakdown
    with use_bay_hint(HINT):
        got = evaluate(plain.layout, prepared, RULEBOOK, CONFIG)  # type: ignore[arg-type]
    fig = lattice_figures(plain.layout, (0, 0), HINT)
    n = len(plain.layout.rooms)
    assert got.cost_breakdown[LATTICE_COST] == pytest.approx((fig.off + fig.small) / n)
    assert got.total_cost == pytest.approx(base.total_cost + got.cost_breakdown[LATTICE_COST])
    assert {k: v for k, v in got.cost_breakdown.items() if k != LATTICE_COST} == base.cost_breakdown


def test_lattice_figures_on_a_known_layout() -> None:
    prepared, plan = bar(4)
    res = realize(prepared, plan, RULEBOOK, CONFIG)  # type: ignore[arg-type]
    assert res.layout is not None
    fig = lattice_figures(res.layout, (0, 0), HINT)
    # 240 x 80 modules: column lines at x = 0, 72, 144, 216 and y = 0, 72: at least the columns
    # of the lines that cross the outline
    assert fig.columns >= 2
    assert 0 <= fig.off <= fig.partitions
    # a hint whose lines are far from every room side counts every partition off
    far = BayHint(2400, 2400, 1200, 1200, 7200, 7200, 0, 0, tol_mm=0)
    assert lattice_figures(res.layout, (0, 0), far).off >= fig.off


def test_an_unrepresentable_lattice_falls_back_to_the_default_widths() -> None:
    prepared, plan = bar(4)
    odd = BayHint(2450, 2450, 0, 0, 7250, 7250, 0, 0)  # not whole modules: no lattice
    plain = realize(prepared, plan, RULEBOOK, CONFIG)  # type: ignore[arg-type]
    with use_bay_hint(odd):
        got = realize(prepared, plan, RULEBOOK, CONFIG)  # type: ignore[arg-type]
    assert plain.layout is not None and got.layout is not None
    assert [p.rect for p in got.layout.rooms] == [p.rect for p in plain.layout.rooms]
