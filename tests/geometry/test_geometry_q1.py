"""Ticket Q.1 eval Q101-Q103: realisation never emits rule-breaking room shapes."""

from __future__ import annotations

import random
from functools import cache

import pytest
from geometry_helpers import (
    fb,
    fixture_prepared,
    load_test_rulebook,
    one_piece,
    p25_compliant_plan,
    prepared_rect,
    random_plan,
    rb,
    room,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ale.config import AleConfig
from ale.contracts.corridor_plan import CorridorPlan
from ale.geometry import check_layout, greedy_plan, realize
from ale.geometry.blocks import Consts, RoomReq, aspect_ok
from ale.optimize.moves import MoveContext, propose
from ale.program import PreparedInput

CONFIG = AleConfig()
RULEBOOK = load_test_rulebook()
SHAPE_CODES = {"AREA_UNDER", "AREA_OVER", "ASPECT", "MIN_WIDTH"}
#: Failure codes a valid plan can produce (RD 3.3 / 3.3b / Q.1).
DOCUMENTED = {
    "PLAN_OVERFLOW",
    "JUNCTION_MISALIGNED",
    "BLOCK_TOO_SHALLOW",
    "BANDS_TOO_SHALLOW",
    "DEPTH_SEARCH_TIMEOUT",
    "ROOM_INFEASIBLE",
    "STACK_INFEASIBLE",
}
FIXTURES = {"P25": ("program_25", "site_rect"), "P60": ("program_60", "site_L")}


@cache
def _prepared(name: str) -> PreparedInput:
    program, site = FIXTURES[name]
    return fixture_prepared(program, site)  # type: ignore[arg-type]


def _walk(prepared: PreparedInput, start: CorridorPlan, seed: int, steps: int) -> CorridorPlan:
    """``steps`` random grammar moves from ``start`` (each result is a valid plan)."""
    ctx = MoveContext.from_prepared(prepared)
    rng = random.Random(seed)
    plan = start
    for _ in range(steps):
        _, new = propose(plan, ctx, rng)
        if new is not None:
            plan = new
    return plan


def _random_valid_plan(name: str, start: str, seed: int, steps: int) -> CorridorPlan:
    """A random valid plan: a random walk of grammar moves from the greedy plan or (P25
    only) a random one-piece plan or a hand-built realisable plan."""
    prepared = _prepared(name)
    if start == "random" and name == "P25":  # one-piece random plans need a rectangle
        plan = random_plan(prepared, random.Random(seed))
    elif start == "hand" and name == "P25":
        plan = p25_compliant_plan()
    else:
        plan = greedy_plan(prepared, RULEBOOK, CONFIG)
    return _walk(prepared, plan, seed, steps)


# ------------------------------------------------------------------------------ Q101
@settings(
    max_examples=200,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    name=st.sampled_from(sorted(FIXTURES)),
    seed=st.integers(0, 2**31 - 1),
    start=st.sampled_from(["greedy", "hand", "random"]),
    steps=st.integers(0, 40),
)
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_Q101_never_degenerate(name: str, start: str, seed: int, steps: int) -> None:
    prepared = _prepared(name)
    plan = _random_valid_plan(name, start, seed, steps)
    real = realize(prepared, plan, RULEBOOK, CONFIG)
    if real.layout is None:
        assert real.failures
        assert {f.code for f in real.failures} <= DOCUMENTED, real.failures
        return
    bad = [v for v in real.layout.metrics.violations if v.code in SHAPE_CODES]
    assert bad == []
    assert check_layout(real.layout, prepared, CONFIG) == ()


def test_Q101_not_vacuous() -> None:
    """Short walks from the hand-built P25 plan do realise (with compliant rooms)."""
    ok = 0
    for seed in range(10):
        plan = _random_valid_plan("P25", "hand", seed, 2)
        real = realize(_prepared("P25"), plan, RULEBOOK, CONFIG)
        if real.layout is not None:
            ok += 1
            assert not SHAPE_CODES & {v.code for v in real.layout.metrics.violations}
    assert ok > 0


# ------------------------------------------------------------------------------ Q102
def test_Q102_room_bay_infeasible() -> None:
    prepared = prepared_rect(60, 52, [room("r1", 6.0)])  # block B depth 52 - 12 = 40
    real = realize(prepared, one_piece(b=[rb("r1")]), RULEBOOK, CONFIG)
    assert real.layout is None
    assert real.depths == ((0, 40),)
    assert [(f.code, f.detail) for f in real.failures] == [
        ("ROOM_INFEASIBLE", "r1 in piece 0 band 0 block B: no compliant width at depth 40")
    ]


# ------------------------------------------------------------------------------ Q103
def _compliant(req: RoomReq, w: int, h: int, k: Consts) -> bool:
    return req.lo <= w * h <= req.hi and aspect_ok(w, h, k.amax) and min(w, h) >= req.wmin


def _brute_force_width_exists(reqs: list[RoomReq], depth: int, k: Consts) -> bool:
    """Some stack width in [wmin_stack, 2·D] admits compliant heights with Σh <= D."""
    for w in range(max(r.wmin for r in reqs), 2 * depth + 1):
        total = 0
        for r in reqs:
            hs = [h for h in range(1, depth + 1) if _compliant(r, w, h, k)]
            if not hs:
                break
            total += hs[0]
        else:
            if total <= depth:
                return True
    return False


def test_Q103_stack_solver() -> None:
    k = Consts.from_config(CONFIG)
    rooms = [room("a", 6.0), room("b", 6.0), room("c", 12.0)]
    reqs = [k.req(r) for r in rooms]
    assert _brute_force_width_exists(reqs, 70, k)
    # Block B of depth 70: P = 70 + s; a lone finger bay holding the stack (a, b, c).
    prepared = prepared_rect(120, 70 + k.s, rooms)
    real = realize(prepared, one_piece(b=[fb(["a", "b", "c"])]), RULEBOOK, CONFIG)
    assert real.failures == ()
    assert real.depths == ((0, 70),)
    layout = real.layout
    assert layout is not None
    by_id = {p.instance_id: p.rect for p in layout.rooms}
    widths = {by_id[r.id].w for r in rooms}
    assert len(widths) == 1  # one stack width
    for r, req in zip(rooms, reqs, strict=True):
        rect = by_id[r.id]
        assert _compliant(req, rect.w, rect.h, k), (r.id, rect)
    assert not SHAPE_CODES & {v.code for v in layout.metrics.violations}
    assert check_layout(layout, prepared, CONFIG) == ()

    # Five 3 m² rooms at depth 40: no width works (5 x wmin > 40) → STACK_INFEASIBLE.
    small = [room(f"s{i}", 3.0) for i in range(5)]
    assert not _brute_force_width_exists([k.req(r) for r in small], 40, k)
    prepared = prepared_rect(120, 40 + k.s, small)
    real = realize(prepared, one_piece(b=[fb([r.id for r in small])]), RULEBOOK, CONFIG)
    assert real.layout is None
    assert [f.code for f in real.failures] == ["STACK_INFEASIBLE"]
    assert "s0, s1, s2, s3, s4" in real.failures[0].detail
