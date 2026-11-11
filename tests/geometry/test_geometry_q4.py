"""Ticket Q.4 eval D03, D04: maximum depth from the façade (contracts 1.4.0).

``facade.max_depth_m`` set: a ``needs_facade`` room with façade deeper than ``dmax =
floor(max_depth_m / module)`` (``2 · dmax`` for a through room) gets a hard ``FACADE_DEPTH``;
a room with ``T > amax · dmax²`` takes ``depth <= dmax`` and its aspect above ``amax`` is
reported as the soft ``ASPECT_DEPTH``.
"""

from __future__ import annotations

from collections import Counter
from fractions import Fraction

import pytest
from geometry_helpers import (
    fb,
    load_test_rulebook,
    one_piece,
    prepared_from,
    rb,
    rect_pts,
    room,
    site_modules,
)

from ale.config import AleConfig
from ale.contracts.geometry import ModulePolygon, ModuleRect
from ale.contracts.models import GridSpec, Layout, LayoutMetrics, PlacedRoom, Program, RoomSpec
from ale.geometry import check_layout, evaluate, realize
from ale.geometry.blocks import Consts, Solver
from ale.geometry.evaluate import FACADE_CODES, SOFT_ASPECT_CODE, facade_depth
from ale.optimize.anneal import HARD_CODES, hard_count
from ale.program.models import PreparedInput

RULEBOOK = load_test_rulebook()


def arep_config(max_depth_m: float | None = 7.2, hard: bool = True) -> AleConfig:
    """Module 600 mm, area 0 / +10 % / 0 m², façade depth ``max_depth_m`` (a hard limit
    unless ``hard`` is false: the scope change made the soft rule the default)."""
    return AleConfig.model_validate(
        {
            "grid": {"module_mm": 600},
            "area": {"tol_down_pct": 0, "tol_up_pct": 10, "tol_up_abs_m2": 0},
            "facade": {"max_depth_m": max_depth_m, "max_depth_hard": hard},
        }
    )


CONFIG = arep_config()
K = Consts.from_config(CONFIG)


def prepared(w: int, h: int, rooms: list[RoomSpec], config: AleConfig = CONFIG) -> PreparedInput:
    """A ``w x h``-module rectangle at module 600 mm holding ``rooms``."""
    site = site_modules(rect_pts(w, h), module_m=0.6)
    return prepared_from(Program(rooms=tuple(rooms)), site, RULEBOOK, config)


def hand_layout(w: int, h: int, rects: dict[str, tuple[int, int, int, int]]) -> Layout:
    """A hand-made layout on a ``w x h`` rectangle (rooms only; metrics filled later)."""
    metrics = LayoutMetrics(
        total_cost=0.0,
        cost_breakdown={},
        total_overshoot_m2=0.0,
        circulation_area_m2=0.0,
        residue_area_m2=0.0,
        violations=(),
    )
    rooms = tuple(
        PlacedRoom(
            instance_id=iid,
            spec_id=iid,
            rect=ModuleRect(x=x, y=y, w=rw, h=rh),
            target_area_m2=rw * rh * 0.36,
        )
        for iid, (x, y, rw, rh) in sorted(rects.items())
    )
    return Layout(
        grid=GridSpec(module_mm=600),
        footprint=ModulePolygon(exterior=tuple(rect_pts(w, h))),
        rooms=rooms,
        circulation=(),
        seed=0,
        rulebook_version=RULEBOOK.version,
        metrics=metrics,
    )


def codes(layout: Layout) -> Counter[str]:
    return Counter(v.code for v in layout.metrics.violations)


# ------------------------------------------------------------------------------ D03
def test_D03_violation() -> None:
    assert K.dmax == 12  # floor(7.2 m / 0.6 m)
    assert arep_config(7.5).facade.max_depth_m == 7.5
    assert Consts.from_config(arep_config(7.5)).dmax == 12  # floor, not round
    assert Consts.from_config(arep_config(None)).dmax is None
    # A 9.6 m-deep office (16 modules) along the south façade: one FACADE_DEPTH.
    deep = {"office": (10, 0, 12, 16)}
    layout = hand_layout(40, 18, deep)
    prep = prepared(40, 18, [room("office", 12 * 16 * 0.36, needs_facade=True)])
    got = evaluate(layout, prep, RULEBOOK, CONFIG)
    depth = [v for v in got.violations if v.code == "FACADE_DEPTH"]
    assert len(depth) == 1
    assert depth[0].instance_ids == ("office",)
    assert "depth 16 > 12" in depth[0].detail
    # Exactly at the limit (7.2 m): no violation.
    at_limit = hand_layout(40, 18, {"office": (10, 0, 16, 12)})
    prep_at = prepared(40, 18, [room("office", 16 * 12 * 0.36, needs_facade=True)])
    assert "FACADE_DEPTH" not in codes(
        at_limit.model_copy(update={"metrics": evaluate(at_limit, prep_at, RULEBOOK, CONFIG)})
    )
    # Rule off: no violation for the deep office.
    off = arep_config(None)
    assert "FACADE_DEPTH" not in {v.code for v in evaluate(layout, prep, RULEBOOK, off).violations}
    # Without needs_facade: no violation.
    plain = prepared(40, 18, [room("office", 12 * 16 * 0.36)])
    plain_codes = {v.code for v in evaluate(layout, plain, RULEBOOK, CONFIG).violations}
    assert "FACADE_DEPTH" not in plain_codes
    # A through room 12 m deep (20 modules) with façades on both long sides: limit 24 -> none.
    through = hand_layout(40, 20, {"office": (10, 0, 10, 20)})
    prep_t = prepared(40, 20, [room("office", 10 * 20 * 0.36, needs_facade=True)])
    assert facade_depth(through.rooms[0].rect, through.footprint) == (20, True)
    assert "FACADE_DEPTH" not in {
        v.code for v in evaluate(through, prep_t, RULEBOOK, CONFIG).violations
    }
    # ... but 15 m deep (25 modules > 24) it is too deep even as a through room.
    deeper = hand_layout(40, 25, {"office": (10, 0, 12, 25)})
    prep_d = prepared(40, 25, [room("office", 12 * 25 * 0.36, needs_facade=True)])
    viol = [v for v in evaluate(deeper, prep_d, RULEBOOK, CONFIG).violations]
    assert [v.detail for v in viol if v.code == "FACADE_DEPTH"] == [
        "office: through room depth 25 > 24 modules"
    ]
    # A room without façade gets NO_FACADE only (never both).
    inner = hand_layout(40, 40, {"office": (10, 10, 12, 16)})
    prep_i = prepared(40, 40, [room("office", 12 * 16 * 0.36, needs_facade=True)])
    inner_codes = {v.code for v in evaluate(inner, prep_i, RULEBOOK, CONFIG).violations}
    assert "NO_FACADE" in inner_codes and "FACADE_DEPTH" not in inner_codes
    assert sorted(FACADE_CODES) == ["FACADE_DEPTH", "NO_FACADE"]
    assert "FACADE_DEPTH" in HARD_CODES and SOFT_ASPECT_CODE not in HARD_CODES


# ------------------------------------------------------------------------------ D08
def test_D08_soft_depth_unit() -> None:
    """Soft mode (default): the 9.6 m office is reported, not hard, and costs depth/limit."""
    soft = arep_config(hard=False)
    layout = hand_layout(40, 18, {"office": (10, 0, 12, 16)})
    prep = prepared(40, 18, [room("office", 12 * 16 * 0.36, needs_facade=True)], soft)
    got = evaluate(layout, prep, RULEBOOK, soft)
    assert [v.code for v in got.violations if v.code == "FACADE_DEPTH"] == ["FACADE_DEPTH"]
    # cost term: (16 - 12) / 12 over one room
    assert got.cost_breakdown["facade_depth"] == pytest.approx(4 / 12)
    base = hard_count(layout.model_copy(update={"metrics": got}))  # unrelated hard codes
    # Hard mode: counted in n_hard, no cost term.
    hard_got = evaluate(layout, prep, RULEBOOK, CONFIG)
    assert "facade_depth" not in hard_got.cost_breakdown
    assert hard_count(layout.model_copy(update={"metrics": hard_got})) == base + 1
    # Rule off: no term at all.
    off = arep_config(None)
    assert "facade_depth" not in evaluate(layout, prep, RULEBOOK, off).cost_breakdown
    # Weight 0 removes its contribution to the total.
    w0 = AleConfig.model_validate(
        {**soft.model_dump(mode="json"), "optimizer": {"weights": {"facade_depth": 0.0}}}
    )
    assert evaluate(layout, prep, RULEBOOK, w0).total_cost == pytest.approx(
        got.total_cost - got.cost_breakdown["facade_depth"]
    )


def test_D03_depth_from_longest_contact() -> None:
    poly = ModulePolygon(exterior=tuple(rect_pts(40, 30)))
    assert facade_depth(ModuleRect(x=5, y=5, w=4, h=4), poly) is None
    # A corner room: contact 16 on the west side, 12 on the south: depth = its width 12.
    assert facade_depth(ModuleRect(x=0, y=0, w=12, h=16), poly) == (12, False)
    # A square corner room: equal contacts, the smaller depth wins (both 10 here).
    assert facade_depth(ModuleRect(x=0, y=0, w=10, h=10), poly) == (10, False)


def test_D03_realised_deep_office() -> None:
    """A realised 1-band plan forced to a 16-module block: the office reports FACADE_DEPTH,
    and the realiser's depth key counts it (it prefers 12 when the other block allows)."""
    office = room("office", 12 * 16 * 0.36, needs_facade=True)
    filler = room("x", 10 * 16 * 0.36)  # keeps the office off the west end wall
    prep = prepared(40, 18, [filler, office])
    real = realize(prep, one_piece([rb("x"), rb("office")]), RULEBOOK, CONFIG)
    assert real.layout is not None, real.failures
    assert real.depths == ((16, 0),)
    assert codes(real.layout)["FACADE_DEPTH"] == 1
    assert check_layout(real.layout, prep, CONFIG) == ()
    # Two blocks, 26 modules deep: the 12 / 12 split has no FACADE_DEPTH.
    rooms = [room("a", 20 * 12 * 0.36, needs_facade=True), room("b", 20 * 12 * 0.36)]
    prep2 = prepared(40, 26, rooms)
    real2 = realize(prep2, one_piece([rb("a")], [rb("b")]), RULEBOOK, CONFIG)
    assert real2.layout is not None
    assert real2.depths[0][0] <= 12
    assert "FACADE_DEPTH" not in codes(real2.layout)


# ------------------------------------------------------------------------------ D04
def _big_prepared(config: AleConfig = CONFIG) -> PreparedInput:
    rooms = [
        room("big", 160.0, needs_facade=True),
        room("dir", 60.0, needs_facade=True),
        room("wc", 4.0, rtype="sanitary"),
    ]
    return prepared(60, 26, rooms, config)


def test_D04_big_room() -> None:
    prep = _big_prepared()
    req = K.req(dict(prep.instances)["big"])
    assert req.deep  # 160 m² = 444.4 cells > 2 · 12² = 288
    assert not K.req(dict(prep.instances)["dir"]).deep
    plan = one_piece([rb("big")], [rb("dir"), fb(right=("wc",))])
    real = realize(prep, plan, RULEBOOK, CONFIG)
    layout = real.layout
    assert layout is not None, real.failures
    rects = {p.instance_id: p.rect for p in layout.rooms}
    big = rects["big"]
    depth = facade_depth(big, layout.footprint)
    assert depth is not None and depth[0] <= 12  # <= 7.2 m from the façade
    assert max(big.w, big.h) * 1 > 2 * min(big.w, big.h)  # aspect > 2
    assert req.lo <= big.area_cells() <= req.hi
    found = codes(layout)
    assert found[SOFT_ASPECT_CODE] == 1
    assert found["ASPECT"] == 0 and found["FACADE_DEPTH"] == 0
    assert hard_count(layout) == sum(found[c] for c in HARD_CODES)
    assert hard_count(layout) == 0  # n_hard excludes the imposed aspect
    assert check_layout(layout, prep, CONFIG) == ()
    soft = next(v for v in layout.metrics.violations if v.code == SOFT_ASPECT_CODE)
    assert soft.instance_ids == ("big",)


def test_D04_rule_off_big_room_is_infeasible_at_depth_12() -> None:
    """Without the rule the Q.1 solver never breaks the aspect limit: the 160 m² room has
    no width at depth 12, and the realiser picks a deeper block for it."""
    off = arep_config(None)
    k = Consts.from_config(off)
    prep = _big_prepared(off)
    solver = Solver(k, {iid: k.req(spec) for iid, spec in prep.instances})
    assert solver.room_bay_width(k.req(dict(prep.instances)["big"]), 12, True) is None
    plan = one_piece([rb("big")], [rb("dir"), fb(right=("wc",))])
    real = realize(prep, plan, RULEBOOK, off)
    # The bar is too shallow for it at aspect <= 2 next to the 60 m² office: no layout.
    assert real.layout is None
    assert real.depths[0][0] > 12
    assert {f.code for f in real.failures} == {"ROOM_INFEASIBLE"}


def test_D04_solver_widths() -> None:
    prep = _big_prepared()
    reqs = {iid: K.req(spec) for iid, spec in prep.instances}
    solver = Solver(K, reqs)
    big = reqs["big"]
    # Exterior (narrow): smallest width with lo <= w·D <= hi; else the target width.
    assert solver.room_bay_width(big, 12, True) == 38  # 456 cells >= lo 445
    assert solver.room_bay_width(big, 12, False) == 38  # ceil(444.4 / 12)
    assert solver.room_bay_width(big, 10, False) == 45
    assert solver.deep_width(big, 10, True) == 45
    assert solver.deep_width(big, 1, True) is None  # depth below wmin
    # Deeper than dmax: the ordinary rules (aspect 2: 15 x 30 = 450 cells).
    assert solver.room_bay_width(big, 15, True) == 30
    assert solver.room_bay_width(big, 13, True) is None  # 13 x 26 = 338 < lo
    # A depth where even the area rule cannot hold: none.
    tight = K.req(room("t", 160.0, needs_facade=True, min_width_m=30.0))
    assert tight.deep and solver.deep_width(tight, 12, False) is None
    # Not deep (rule off): no relaxation.
    off = Consts.from_config(arep_config(None))
    assert not off.req(dict(prep.instances)["big"]).deep


def test_D04_block_depth_counts() -> None:
    """The block's façade count includes predicted FACADE_DEPTH rooms (Q.3 key position)."""
    rooms = [
        room("a", 20 * 16 * 0.36, needs_facade=True),
        room("s1", 16.0, needs_facade=True),
        room("s2", 16.0, needs_facade=True),
    ]
    prep = prepared(60, 30, rooms)
    reqs = {iid: K.req(spec) for iid, spec in prep.instances}
    solver = Solver(K, reqs)
    deep_block = solver.block((rb("a"),), 16, 60, "A", exterior=True)
    assert deep_block.no_facade == 1
    ok_block = solver.block((rb("a"),), 12, 60, "A", exterior=True)
    assert ok_block.no_facade == 0
    # A stack whose outermost room is taller than dmax: one predicted FACADE_DEPTH (plus
    # the inner room's missing façade).
    one = solver.block((fb(right=("s1",)),), 13, 60, "A", exterior=True)
    stack = solver.stack((reqs["s1"],), 13)
    assert stack is not None
    tall = stack.rest == 0 and stack.w >= K.f and stack.heights[-1] > 12
    assert one.no_facade == (1 if tall or stack.rest > 0 or stack.w < K.f else 0)
    two = solver.block((fb(right=("s1", "s2")),), 12, 60, "A", exterior=True)
    assert two.no_facade == 1  # only the inner room lacks façade (heights 6 + 6)
    # Rule off: no depth count.
    k_off = Consts.from_config(arep_config(None))
    off = Solver(k_off, {iid: k_off.req(spec) for iid, spec in prep.instances})
    assert off.block((rb("a"),), 16, 60, "A", exterior=True).no_facade == 0
    assert K.deep(True, Fraction(289)) and not K.deep(True, Fraction(288))
    assert not K.deep(False, Fraction(10_000))
