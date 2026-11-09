"""Ticket Q.3 eval Q306, Q308, Q309 (realise): façade-aware depths and widths.

The band depth search key is ``(n_failures, n_no_facade, cost, |D_A - D_B|, D_A)``; in an
exterior block a ``needs_facade`` room bay takes the smallest compliant width (raised to the
façade minimum ``f`` when that still complies).
"""

from __future__ import annotations

import time
from fractions import Fraction
from typing import Any

import pytest
from band_gen import band_l_cases, band_rect_cases
from geometry_helpers import (
    fb,
    fixture_prepared,
    load_test_rulebook,
    one_piece,
    prepared_poly,
    prepared_rect,
    rb,
    room,
)
from grammar_gen import l_cases, rect_cases
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from test_geometry_q2 import inner_cases

from ale.config import AleConfig
from ale.contracts.models import RoomSpec
from ale.geometry import check_layout, greedy_plan, realize
from ale.geometry.blocks import Consts, RoomReq, Solver, aspect_ok
from ale.geometry.checks import exterior_contacts

CONFIG = AleConfig()
RULEBOOK = load_test_rulebook()
K = Consts.from_config(CONFIG)
S = K.s


# ------------------------------------------------------------------------------ Q306
def _q306_rooms(needs: bool) -> list[RoomSpec]:
    # c: 7.5 m² (25 x 30 or 30 x 25), a: 6 m² (20 x 30 or 24 x 25), b: 10.5 m² (35 x 30 or
    # 30 x 35): exact at both splits D_A = 30 (D_B = 30) and D_A = 25 (D_B = 35).
    return [room("c", 7.5), room("a", 6.0, needs_facade=needs), room("b", 10.5)]


def test_Q306_depth_key() -> None:
    plan = one_piece([rb("c"), rb("a")], [rb("b")])
    prepared = prepared_rect(100, 72, _q306_rooms(True))
    depth = 72
    # The old key (3.3 §5.1: failures, deviation, |D_A - D_B|, D_A with the 3.3 widths):
    solver = Solver(K, {iid: K.req(spec) for iid, spec in prepared.instances})
    old: list[tuple[tuple[int, Fraction, int, int], int]] = []
    for d_a in range(K.c, depth - S - K.c + 1):
        d_b = depth - S - d_a
        a = solver.block(plan.pieces[0].bands[0].block_a.bays, d_a, 100, "A")
        b = solver.block(plan.pieces[0].bands[0].block_b.bays, d_b, 100, "B")
        old.append(
            ((len(a.failures) + len(b.failures), a.dev() + b.dev(), abs(d_a - d_b), d_a), d_a)
        )
    old_da = min(old)[1]
    assert old_da == 30
    shallow = solver.block(plan.pieces[0].bands[0].block_a.bays, old_da, 100, "A")
    a_item = next(it for it in shallow.items if it.room == "a")
    assert (a_item.u, a_item.du) == (25, 20)  # not at an end wall, frontage 20 < f = 24
    assert a_item.du < K.f
    # The new key gives "a" its façade, every rule still met.
    real = realize(prepared, plan, RULEBOOK, CONFIG)
    layout = real.layout
    assert layout is not None, real.failures
    assert real.depths == ((25, 35),)
    assert check_layout(layout, prepared, CONFIG) == ()
    rects = {p.instance_id: p.rect for p in layout.rooms}
    assert sum(n for n, _ in exterior_contacts(rects["a"], layout.footprint)) >= K.f
    assert "NO_FACADE" not in {v.code for v in layout.metrics.violations}
    for code in ("AREA_UNDER", "AREA_OVER", "ASPECT", "MIN_WIDTH"):
        assert code not in {v.code for v in layout.metrics.violations}
    # Without needs_facade the realiser keeps the 3.3 choice.
    plain = realize(prepared_rect(100, 72, _q306_rooms(False)), plan, RULEBOOK, CONFIG)
    assert plain.depths == ((30, 30),)


def test_facade_width_smallest_compliant() -> None:
    solver = Solver(K, {})
    office = RoomReq(target=Fraction(1200), lo=1164, hi=1236, wmin=12, facade=True)
    plain = RoomReq(target=Fraction(1200), lo=1164, hi=1236, wmin=12)
    # Depth 47: 3.3 width 26 (reaches the target), façade width 25 (1175 >= lo).
    assert solver.room_bay_width(plain, 47, exterior=True) == 26
    assert solver.room_bay_width(office, 47) == 26
    assert solver.room_bay_width(office, 47, exterior=True) == 25
    # Raised to f = 24 when it still complies: depth 25 gives 47 / 48 either way.
    small = RoomReq(target=Fraction(600), lo=582, hi=618, wmin=12, facade=True)
    assert solver.facade_width(small, 25) == 24  # ceil(582 / 25) = 24 = f
    assert solver.facade_width(small, 30) == 20  # f x 30 > hi: the smallest stays
    assert solver.room_bay_width(small, 30, exterior=True) == 20
    # Same feasibility as the 3.3 width.
    for d in range(1, 80):
        w33 = solver.room_bay_width(plain, d)
        w = solver.room_bay_width(office, d, exterior=True)
        assert (w33 is None) == (w is None)
        if w is not None:
            assert office.lo <= w * d <= office.hi
            assert aspect_ok(w, d, K.amax) and w >= office.wmin
    assert solver.facade_width(office, 11) is None  # below wmin
    assert solver.facade_width(office, 60) is None  # aspect / area window empty


def test_no_facade_counts() -> None:
    reqs = {
        "f": RoomReq(target=Fraction(1200), lo=1164, hi=1236, wmin=12, facade=True),
        "g": RoomReq(target=Fraction(600), lo=582, hi=618, wmin=12, facade=True),
        "n": RoomReq(target=Fraction(600), lo=582, hi=618, wmin=12),
    }
    solver = Solver(K, reqs)
    bays = (rb("f"), fb(left=("g", "n")), rb("n"))
    inner = solver.block((rb("f"), rb("g")), 40, 300, "x")
    assert inner.no_facade == 2  # an inner block gives no façade
    outer = solver.block((rb("f"),), 40, 300, "x", exterior=True)
    assert outer.no_facade == 0
    stacked = solver.block((fb(left=("g", "f")),), 72, 300, "x", exterior=True)
    assert stacked.strip_cells == 0
    assert stacked.no_facade == 1  # "g" is not the outermost room of its stack
    strip = solver.block((fb(left=("g", "f")),), 90, 300, "x", exterior=True)
    assert strip.strip_cells > 0 and strip.no_facade == 2  # a stack-end strip hides "f"
    mixed = solver.block(bays, 60, 400, "x", exterior=True)
    assert mixed.no_facade >= 1
    shallow = solver.block((rb("f"), rb("n")), 0, 300, "x", exterior=True)
    assert shallow.failures and shallow.no_facade == 1


def test_exterior_blocks_of_an_l() -> None:
    """Only band 0 block A and the last band's block B can be exterior; on the L both are
    (their outer sides run along the footprint edge)."""
    from ale.contracts.footprint import decompose_footprint
    from ale.geometry.realize import _Realizer

    prepared = fixture_prepared("program_60", "site_L")
    plan = greedy_plan(prepared, RULEBOOK, CONFIG)
    fp = decompose_footprint(prepared.footprint.polygon)
    real = _Realizer(prepared, plan, fp, K)
    for p, piece in enumerate(plan.pieces):
        n = len(piece.bands)
        for k in range(n):
            assert real.exterior(p, k, "A") is (k == 0)
            assert real.exterior(p, k, "B") is (k == n - 1)
    # A block whose outer side is mostly against the other piece is not exterior.
    pts = [(0, 0), (300, 0), (300, 100), (60, 100), (60, 400), (0, 400)]
    rooms = [room(f"r{i}", 12.0) for i in range(4)]
    l_prep = prepared_poly(pts, rooms, RULEBOOK)
    l_fp = decompose_footprint(l_prep.footprint.polygon)
    l_plan = greedy_plan(l_prep, RULEBOOK, CONFIG)
    l_real = _Realizer(l_prep, l_plan, l_fp, K)
    flags = {
        (p, k, side): l_real.exterior(p, k, side)
        for p, pc in enumerate(l_plan.pieces)
        for k in range(len(pc.bands))
        for side in "AB"
    }
    assert any(flags.values())
    assert l_real.exterior(0, 0, "A") is flags[(0, 0, "A")]  # memoised


# ------------------------------------------------------------------------------ Q308
SETTINGS: dict[str, Any] = {
    "max_examples": 120,
    "derandomize": True,
    "deadline": None,
    "suppress_health_check": [HealthCheck.too_slow, HealthCheck.filter_too_much],
}


@st.composite
def facade_cases(draw: st.DrawFn) -> tuple[Any, list[RoomSpec]]:
    """A valid plan (rect / L / multi-band / inner connector) whose rooms randomly need a
    façade (so exterior blocks use the Q.3 narrow widths)."""
    case = draw(
        st.one_of(
            rect_cases(),
            band_rect_cases(),
            inner_cases(),
            l_cases("J2"),
            l_cases("J1"),
            band_l_cases("j2_primary"),
            band_l_cases("j1_primary"),
        )
    )
    flags = draw(st.lists(st.booleans(), min_size=len(case.rooms), max_size=len(case.rooms)))
    rooms = [
        r.model_copy(update={"needs_facade": f}) for r, f in zip(case.rooms, flags, strict=True)
    ]
    return case, rooms


_REALISED = {"ok": 0, "all": 0}


@settings(**SETTINGS)
@given(facade_cases())
def test_Q308_invariants(drawn: tuple[Any, list[RoomSpec]]) -> None:
    case, rooms = drawn
    prepared = prepared_poly(case.points, rooms, RULEBOOK)
    real = realize(prepared, case.plan, RULEBOOK, CONFIG)
    _REALISED["all"] += 1
    if real.layout is None:
        return
    _REALISED["ok"] += 1
    assert check_layout(real.layout, prepared, CONFIG) == ()
    ids = sorted(p.instance_id for p in real.layout.rooms)
    assert ids == sorted(iid for iid, _ in prepared.instances)


def test_Q308_most_cases_realise() -> None:
    """The Hypothesis run above realised most of its cases (it ran before this test)."""
    if _REALISED["all"] == 0:  # pragma: no cover - run alone
        pytest.skip("test_Q308_invariants did not run in this session")
    assert _REALISED["all"] >= 100
    assert _REALISED["ok"] >= _REALISED["all"] // 2


# ------------------------------------------------------------------------------ Q309
@pytest.mark.timeout(300)
def test_Q309_realize_perf() -> None:
    prepared = fixture_prepared("program_60", "site_L")
    plan = greedy_plan(prepared, RULEBOOK, CONFIG)
    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        real = realize(prepared, plan, RULEBOOK, CONFIG)
        best = min(best, time.perf_counter() - start)
    print(f"Q309 P60 realize: {best:.3f} s")
    assert real.layout is not None or real.failures
    assert best <= 1.0
