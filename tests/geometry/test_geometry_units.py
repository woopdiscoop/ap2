"""Unit tests of ale.geometry beyond the eval IDs: failure paths, checks, helpers."""

from __future__ import annotations

import importlib
import math

import pytest
from geometry_helpers import (
    fb,
    load_test_rulebook,
    one_piece,
    piece,
    prepared_poly,
    prepared_rect,
    rb,
    rect_tuple,
    room,
)
from pydantic import ValidationError

from ale.config import AleConfig
from ale.contracts.corridor_plan import CorridorPlan
from ale.contracts.enums import Bearing, MacroZone
from ale.contracts.geometry import ModulePolygon, ModuleRect
from ale.contracts.models import Layout, PlacedRoom, Rulebook
from ale.geometry import Failure, Realization, check_layout, evaluate, greedy_plan, realize
from ale.geometry.blocks import Consts, Solver, guarded_range
from ale.geometry.checks import exterior_contacts, rect_in_polygon_cells, share_length
from ale.geometry.evaluate import core_target

CONFIG = AleConfig()
RULEBOOK = load_test_rulebook()
# J1 footprint: primary (0,0,80,150) spine Y, secondary (80,0,120,60) spine X, facing B.
J1_PTS = [(0, 0), (200, 0), (200, 60), (80, 60), (80, 150), (0, 150)]
# J2 footprint (site_L in modules): primary (0,0,300,300), secondary (300,0,180,180).
J2_PTS = [(0, 0), (480, 0), (480, 180), (300, 180), (300, 300), (0, 300)]


def _e02() -> tuple[Layout, object]:
    rooms = [room("r1", 12.0), room("r2", 6.0), room("r3", 6.0), room("r4", 12.0)]
    prepared = prepared_rect(110, 52, rooms)
    real = realize(prepared, one_piece(b=[rb("r1"), fb(["r2", "r3"], ["r4"])]), RULEBOOK, CONFIG)
    assert real.layout is not None
    return real.layout, prepared


def _move(layout: Layout, iid: str, rect: ModuleRect) -> Layout:
    rooms = tuple(
        p.model_copy(update={"rect": rect}) if p.instance_id == iid else p for p in layout.rooms
    )
    return layout.model_copy(update={"rooms": rooms})


# ----------------------------------------------------------------------------- helpers


def test_share_length_cases() -> None:
    a = ModuleRect(0, 0, 10, 10)
    assert share_length(a, ModuleRect(10, 5, 4, 20)) == 5
    assert share_length(a, ModuleRect(2, 10, 4, 4)) == 4
    assert share_length(a, ModuleRect(10, 10, 4, 4)) == 0  # corner only
    assert share_length(a, ModuleRect(20, 0, 4, 4)) == 0


def test_exterior_contacts_and_clip() -> None:
    poly = ModulePolygon(exterior=tuple(J2_PTS))
    contacts = exterior_contacts(ModuleRect(280, 160, 20, 20), poly)
    assert contacts == []
    corner = exterior_contacts(ModuleRect(460, 160, 20, 20), poly)
    assert sorted(corner) == [(20, (0, 1)), (20, (1, 0))]
    assert rect_in_polygon_cells(ModuleRect(290, 170, 20, 20), poly) == 400 - 100
    assert rect_in_polygon_cells(ModuleRect(400, 200, 20, 20), poly) == 0
    assert rect_in_polygon_cells(ModuleRect(0, 0, 10, 10), poly) == 100


def test_guarded_range_and_consts() -> None:
    assert list(guarded_range(3, 0, step=-1, label="t")) == [3, 2, 1]
    k = Consts.from_config(CONFIG)
    assert (k.s, k.c, k.f, k.amax) == (12, 12, 24, 2)
    assert k.wmin(room("x", 12.0, min_width_m=1.75)) == 18
    req = k.req(room("x", 4.5))
    assert (req.target, req.lo, req.hi) == (450, 437, 570)


def test_stack_rules() -> None:
    k = Consts.from_config(CONFIG)
    solver = Solver(k, {})
    six = k.req(room("a", 6.0))
    sol = solver.stack((six, six), 40)
    assert sol is not None and (sol.w, sol.heights, sol.rest) == (30, (20, 20), 0)
    # A single 6 m² room at depth 40: w = 15..17 give h = 40, 38, 36 (aspect > 2); w = 18,
    # h = 34 (612 cells) is accepted; the rest 6 raises h to min(720 // 18, 2 x 18) = 36.
    one = solver.stack((six,), 40)
    assert one is not None and (one.w, one.heights, one.rest) == (18, (36,), 4)
    # Three rooms cannot fit a depth of 30 (3 x 12 > 30).
    assert solver.stack((six, six, six), 30) is None
    # Q.1: no compliant width (80 m² cannot reach its area at depth 30) → None, no fallback.
    huge = k.req(room("h", 80.0))
    assert solver.stack((huge, six), 30) is None
    assert solver.stack((six,), 0) is None
    # Q.1: no width reaches both targets at depth 28, but w = 28, h = 14 gives 392 cells,
    # inside the area rule of a 4 m² room (lo 388): the undershoot pass accepts it.
    four = k.req(room("f", 4.0))
    assert four.lo <= 28 * 14 < four.target
    under = solver.stack((four, four), 28)
    assert under is not None and (under.w, under.heights, under.rest) == (28, (14, 14), 0)


def test_room_bay_branches() -> None:
    k = Consts.from_config(CONFIG)
    solver = Solver(k, {})
    # Smallest w >= ceil(T / D) within hi with aspect <= 2: 12 m² at D = 41 → w = 30.
    assert solver.room_bay_width(k.req(room("a", 12.0)), 41) == 30
    # 12 m² at D = 59: w = 21 (1239) aspect 2.81 ... w = 22 (1298) aspect 2.68 fail; down
    # w = 20 (1180 >= 1164) aspect 2.95 fails → no compliant width (Q.1: None).
    assert solver.room_bay_width(k.req(room("b", 12.0)), 59) is None
    # Depth below wmin → None.
    assert solver.room_bay_width(k.req(room("c", 2.0)), 11) is None
    # Down branch (undershoot inside the tolerance) with amax 1.5: 13.8 m² at D = 30:
    # up w = 46..50 have aspect > 1.5; down w = 45 (1350 >= lo 1339) aspect 1.5 → 45.
    tight = Consts.from_config(AleConfig.model_validate({"shape": {"aspect_max": 1.5}}))
    assert Solver(tight, {}).room_bay_width(tight.req(room("e", 13.8)), 30) == 45


# ----------------------------------------------------------------------------- failures


def test_realization_validator() -> None:
    layout, _ = _e02()
    with pytest.raises(ValidationError):
        Realization(layout=None, failures=(), depths=())
    with pytest.raises(ValidationError):
        Realization(layout=layout, failures=(Failure(code="X", detail="y"),), depths=())


def test_footprint_unsupported_and_piece_too_small() -> None:
    u_shape = [
        (0, 0),
        (300, 0),
        (300, 200),
        (200, 200),
        (200, 100),
        (100, 100),
        (100, 200),
        (0, 200),
    ]
    prepared = prepared_poly(u_shape, [room("r1", 12.0)])
    real = realize(prepared, one_piece(b=[rb("r1")]), RULEBOOK, CONFIG)
    assert [f.code for f in real.failures] == ["FOOTPRINT_UNSUPPORTED"]
    prepared = prepared_rect(200, 10, [room("r1", 12.0)])
    real = realize(prepared, one_piece(b=[rb("r1")]), RULEBOOK, CONFIG)
    assert [f.code for f in real.failures] == ["PIECE_TOO_SMALL"]


def test_stack_too_shallow_and_shallow_piece() -> None:
    rooms = [room("s1", 2.0), room("s2", 2.0), room("s3", 2.0)]
    prepared = prepared_rect(100, 42, rooms)
    real = realize(prepared, one_piece(b=[fb(["s1", "s2", "s3"])]), RULEBOOK, CONFIG)
    # Q.1: a stack too shallow for its rooms is STACK_INFEASIBLE (was STACK_TOO_SHALLOW).
    assert [f.code for f in real.failures] == ["STACK_INFEASIBLE"]
    assert "s1, s2, s3" in real.failures[0].detail
    assert real.depths == ((0, 30),)
    # P - s = 18 < 2 x 12: both blocks get 9 modules < wmin → ROOM_INFEASIBLE (Q.1; was a
    # layout with MIN_WIDTH / ASPECT violations).
    prepared = prepared_rect(80, 30, [room("a", 2.0), room("b", 2.0)])
    real = realize(prepared, one_piece(a=[rb("a")], b=[rb("b")]), RULEBOOK, CONFIG)
    assert real.depths == ((9, 9),)
    assert real.layout is None
    assert [f.code for f in real.failures] == ["ROOM_INFEASIBLE", "ROOM_INFEASIBLE"]
    assert real.failures[0].detail == ("a in piece 0 band 0 block A: no compliant width at depth 9")


def test_block_a_only() -> None:
    prepared = prepared_rect(60, 52, [room("r1", 12.0)])
    real = realize(prepared, one_piece(a=[rb("r1")]), RULEBOOK, CONFIG)
    assert real.depths == ((40, 0),)
    assert real.layout is not None
    assert rect_tuple(real.layout.rooms[0]) == (0, 0, 30, 40)
    assert check_layout(real.layout, prepared, CONFIG) == ()


def test_depth_search_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    realize_mod = importlib.import_module("ale.geometry.realize")
    monkeypatch.setattr(realize_mod, "_DEPTH_BUDGET_S", 1e-12)
    prepared = prepared_rect(60, 80, [room("a", 6.0), room("b", 6.0)])
    real = realize(prepared, one_piece(a=[rb("a")], b=[rb("b")]), RULEBOOK, CONFIG)
    assert [f.code for f in real.failures] == ["DEPTH_SEARCH_TIMEOUT"]


# ----------------------------------------------------------------------------- L shapes


def test_j1_success_and_lone_junction() -> None:
    rooms = [room("a1", 12.0), room("b1", 12.0), room("c1", 12.0)]
    prepared = prepared_poly(J1_PTS, rooms)
    plan = CorridorPlan(
        pieces=(piece(a=[rb("a1")], b=[fb(junction=True), rb("b1")]), piece(b=[rb("c1")]))
    )
    real = realize(prepared, plan, RULEBOOK, CONFIG)
    assert real.failures == ()
    assert real.layout is not None
    assert check_layout(real.layout, prepared, CONFIG) == ()
    assert real.depths[1][0] == 0
    # Facing block holding only the junction finger.
    plan = CorridorPlan(
        pieces=(piece(a=[rb("a1"), rb("b1")], b=[fb(junction=True)]), piece(b=[rb("c1")]))
    )
    real = realize(prepared, plan, RULEBOOK, CONFIG)
    assert real.layout is not None
    assert check_layout(real.layout, prepared, CONFIG) == ()


def test_j1_misaligned() -> None:
    rooms = [room("a1", 12.0), room("b1", 30.0), room("c1", 12.0)]
    prepared = prepared_poly(J1_PTS, rooms)
    plan = CorridorPlan(
        pieces=(piece(a=[rb("a1")], b=[rb("b1"), fb(junction=True)]), piece(b=[rb("c1")]))
    )
    real = realize(prepared, plan, RULEBOOK, CONFIG)
    assert real.layout is None
    assert "JUNCTION_MISALIGNED" in {f.code for f in real.failures}


def test_j2_no_aligned_depth() -> None:
    rooms = [room("a1", 12.0), room("c1", 12.0)]
    prepared = prepared_poly(J2_PTS, rooms)
    plan = CorridorPlan(pieces=(piece(a=[rb("a1")]), piece(b=[rb("c1")])))
    real = realize(prepared, plan, RULEBOOK, CONFIG)
    assert [f.code for f in real.failures] == ["JUNCTION_MISALIGNED"]


def test_greedy_j1_and_single_zone() -> None:
    rooms = [room("a1", 12.0), room("b1", 12.0), room("c1", 4.0), room("c2", 4.0)]
    prepared = prepared_poly(J1_PTS, rooms)
    plan = greedy_plan(prepared, RULEBOOK, CONFIG)
    junctions = [b for b in plan.pieces[0].bands[-1].block_b.bays if getattr(b, "junction", False)]
    assert len(junctions) == 1
    real = realize(prepared, plan, RULEBOOK, CONFIG)
    if real.layout is not None:
        assert check_layout(real.layout, prepared, CONFIG) == ()
    else:
        assert {f.code for f in real.failures} <= {"PLAN_OVERFLOW", "JUNCTION_MISALIGNED"}


# ----------------------------------------------------------------------------- checks


def test_check_layout_detects_problems() -> None:
    layout, prepared = _e02()
    assert check_layout(layout, prepared, CONFIG) == ()  # type: ignore[arg-type]
    moved = _move(layout, "r4", ModuleRect(60, 12, 30, 40))
    assert any("overlaps" in m for m in check_layout(moved, prepared, CONFIG))  # type: ignore[arg-type]
    outside = _move(layout, "r4", ModuleRect(100, 12, 30, 40))
    msgs = check_layout(outside, prepared, CONFIG)  # type: ignore[arg-type]
    assert any("outside the footprint" in m for m in msgs)
    no_spine = layout.model_copy(update={"circulation": layout.circulation[1:]})
    msgs = check_layout(no_spine, prepared, CONFIG)  # type: ignore[arg-type]
    assert "circulation is not connected" in msgs
    assert any("areas sum to" in m for m in msgs)
    assert any("circulation contact" in m for m in msgs)
    big = _move(layout, "r1", ModuleRect(0, 12, 40, 40))
    assert any("AREA_OVER" in m for m in check_layout(big, prepared, CONFIG))  # type: ignore[arg-type]
    small = _move(layout, "r1", ModuleRect(0, 12, 19, 40))
    msgs = check_layout(small, prepared, CONFIG)  # type: ignore[arg-type]
    assert any("AREA_UNDER" in m for m in msgs)
    assert any("ASPECT" in m for m in msgs)
    extra = PlacedRoom(
        instance_id="zz", spec_id="zz", rect=ModuleRect(102, 12, 8, 12), target_area_m2=1.0
    )
    stray = layout.model_copy(update={"rooms": (*layout.rooms, extra)})
    assert any("zz" in m for m in check_layout(stray, prepared, CONFIG))  # type: ignore[arg-type]


# ----------------------------------------------------------------------------- evaluate


def test_evaluate_core_hint_override_and_missing_type() -> None:
    rooms = [
        room("r1", 12.0, rtype="sanitary", orientation_override={Bearing.W: 1.0}),
        room("r2", 12.0, min_width_m=4.5, rtype="open_office"),
    ]
    data = RULEBOOK.model_dump(mode="json")
    del data["types"]["open_office"]
    rulebook = Rulebook.model_validate(data)
    prepared = prepared_rect(80, 52, rooms, rulebook, core_hint=(1.5, 2.6))
    # Q.1: realize no longer emits r2 narrower than its 4.5 m minimum (depth 40 < 45), so
    # the layout is realised without the minimum width and evaluated against it.
    loose = [rooms[0], room("r2", 12.0, rtype="open_office")]
    real = realize(
        prepared_rect(80, 52, loose, rulebook, core_hint=(1.5, 2.6)),
        one_piece(b=[rb("r1"), rb("r2")]),
        rulebook,
        CONFIG,
    )
    assert real.layout is not None
    strict = realize(prepared, one_piece(b=[rb("r1"), rb("r2")]), rulebook, CONFIG)
    assert [f.code for f in strict.failures] == ["ROOM_INFEASIBLE"]
    real = real.model_copy(
        update={
            "layout": real.layout.model_copy(
                update={"metrics": evaluate(real.layout, prepared, rulebook, CONFIG)}
            )
        }
    )
    assert real.layout is not None
    assert core_target(real.layout, prepared, rulebook) == pytest.approx((15.0, 26.0))
    m = real.layout.metrics
    # r1 at (0,12,30,40): longest contact west (40) → override W = 1.0; r2 type unknown → 0.
    assert m.cost_breakdown["facade_orientation"] == pytest.approx(-0.5)
    expected = math.hypot(15 - 15, 32 - 26) / math.hypot(80, 52)
    assert m.cost_breakdown["core_distance"] == pytest.approx(expected)
    assert ("MIN_WIDTH", ("r2",)) in {(v.code, v.instance_ids) for v in m.violations}


def test_evaluate_plan_with_unknown_room_and_no_rooms() -> None:
    layout, prepared = _e02()
    other = one_piece(b=[rb("zz")])
    metrics = evaluate(layout, prepared, RULEBOOK, CONFIG, other)  # type: ignore[arg-type]
    assert any(v.code == "ZONE_SPLIT" and "zz" in v.detail for v in metrics.violations)
    empty = layout.model_copy(update={"rooms": ()})
    metrics = evaluate(empty, prepared, RULEBOOK, CONFIG)  # type: ignore[arg-type]
    assert metrics.cost_breakdown["aspect"] == 0.0
    assert metrics.cost_breakdown["area_overshoot"] == 0.0
    assert metrics.cost_breakdown["core_distance"] == 0.0


def test_greedy_single_zone_rect() -> None:
    rooms = [room(f"o{i}", 12.0, zone=MacroZone.ADMINISTRATIVE) for i in range(3)]
    # Q.1: a 60-module piece leaves no depth where every 12 m² room bay complies (the
    # greedy plan puts 2 rooms in block A, 1 in B); 64 modules does (26 / 26).
    prepared = prepared_rect(120, 64, rooms)
    plan = greedy_plan(prepared, RULEBOOK, CONFIG)
    assert sorted(plan.room_ids()) == ["o0", "o1", "o2"]
    real = realize(prepared, plan, RULEBOOK, CONFIG)
    assert real.layout is not None
    assert check_layout(real.layout, prepared, CONFIG) == ()
