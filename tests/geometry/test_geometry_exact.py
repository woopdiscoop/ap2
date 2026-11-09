"""Exact cases E01-E06 (eval.md section 1)."""

from __future__ import annotations

from geometry_helpers import (
    fb,
    load_test_rulebook,
    one_piece,
    prepared_rect,
    rb,
    rect_tuple,
    room,
)

from ale.config import AleConfig
from ale.contracts.corridor_plan import CorridorPlan
from ale.geometry import check_layout, realize
from ale.geometry.blocks import Consts, Solver

CONFIG = AleConfig()
RULEBOOK = load_test_rulebook()


def _e02_rooms() -> list:  # type: ignore[type-arg]
    return [room("r1", 12.0), room("r2", 6.0), room("r3", 6.0), room("r4", 12.0)]


def _e02_plan() -> CorridorPlan:
    return one_piece(b=[rb("r1"), fb(["r2", "r3"], ["r4"])])


def test_E01_single_room_bay() -> None:
    prepared = prepared_rect(60, 52, [room("r1", 12.0)])
    real = realize(prepared, one_piece(b=[rb("r1")]), RULEBOOK, CONFIG)
    assert real.failures == ()
    assert real.depths == ((0, 40),)
    layout = real.layout
    assert layout is not None
    assert [rect_tuple(p) for p in layout.rooms] == [(0, 12, 30, 40)]
    assert [rect_tuple(p) for p in layout.circulation] == [(0, 0, 60, 12), (30, 12, 30, 40)]
    assert len(layout.circulation) == 2
    assert check_layout(layout, prepared, CONFIG) == ()
    assert layout.seed == 0
    assert layout.rulebook_version == prepared.rulebook_version
    assert layout.residue == ()


def test_E02_finger_bay() -> None:
    prepared = prepared_rect(110, 52, _e02_rooms())
    real = realize(prepared, _e02_plan(), RULEBOOK, CONFIG)
    assert real.failures == ()
    layout = real.layout
    assert layout is not None
    rooms = {p.instance_id: rect_tuple(p) for p in layout.rooms}
    assert rooms == {
        "r1": (0, 12, 30, 40),
        "r2": (30, 12, 30, 20),
        "r3": (30, 32, 30, 20),
        "r4": (72, 12, 30, 40),
    }
    assert sorted(rect_tuple(p) for p in layout.circulation) == sorted(
        [(0, 0, 110, 12), (60, 12, 12, 40), (102, 12, 8, 40)]
    )
    # Stack widths: left stack spans x 30..60, right stack x 72..102.
    assert rooms["r2"][2] == 30
    assert rooms["r4"][2] == 30
    assert check_layout(layout, prepared, CONFIG) == ()


def test_E03_overflow() -> None:
    prepared = prepared_rect(100, 52, _e02_rooms())
    real = realize(prepared, _e02_plan(), RULEBOOK, CONFIG)
    assert real.layout is None
    assert len(real.failures) == 1
    assert real.failures[0].code == "PLAN_OVERFLOW"
    assert "over by 2" in real.failures[0].detail


def test_E04_axis_Y() -> None:
    prepared = prepared_rect(52, 60, [room("r1", 12.0)])
    real = realize(prepared, one_piece(b=[rb("r1")]), RULEBOOK, CONFIG)
    assert real.failures == ()
    layout = real.layout
    assert layout is not None
    assert [rect_tuple(p) for p in layout.rooms] == [(12, 0, 40, 30)]
    assert rect_tuple(layout.circulation[0]) == (0, 0, 12, 60)
    assert [rect_tuple(p) for p in layout.circulation] == [(0, 0, 12, 60), (12, 30, 40, 30)]
    assert check_layout(layout, prepared, CONFIG) == ()


def test_E05_room_bay_rules() -> None:
    k = Consts.from_config(CONFIG)
    big, small = room("a", 12.0), room("b", 6.0)
    solver = Solver(k, {"a": k.req(big), "b": k.req(small)})
    assert solver.room_bay_width(k.req(big), 40) == 30
    # Q.1 (Q102): a 6 m² room cannot be compliant at depth 40 (w = 15 → aspect 2.67;
    # w <= 18 by the area rule; w = 14 is under the area rule) → no width.
    assert solver.room_bay_width(k.req(small), 40) is None
    prepared = prepared_rect(60, 52, [room("r1", 6.0)])
    real = realize(prepared, one_piece(b=[rb("r1")]), RULEBOOK, CONFIG)
    assert real.layout is None
    assert [(f.code, f.detail) for f in real.failures] == [
        ("ROOM_INFEASIBLE", "r1 in piece 0 band 0 block B: no compliant width at depth 40")
    ]


def test_E06_plan_invalid() -> None:
    prepared = prepared_rect(110, 52, _e02_rooms())
    plan = one_piece(b=[rb("r1"), fb(["r2", "r3"])])  # r4 missing
    real = realize(prepared, plan, RULEBOOK, CONFIG)
    assert real.layout is None
    assert [f.code for f in real.failures] == ["PLAN_INVALID"]
    assert "missing room r4" in real.failures[0].detail
    assert real.depths == ()
