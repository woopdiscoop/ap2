"""Ticket 3.4 eval O01-O02: grammar moves G1-G7 (G8-G10: Ticket Q.2, see test_optimize_q2)."""

from __future__ import annotations

import random
from collections import Counter

import pytest

from ale.contracts.corridor_plan import (
    BandPlan,
    BlockPlan,
    CorridorPlan,
    FingerBay,
    PiecePlan,
    RoomBay,
)
from ale.contracts.footprint import decompose_footprint
from ale.contracts.geometry import ModulePolygon
from ale.optimize import MOVE_WEIGHTS, MOVES, MoveContext, propose
from ale.optimize.moves import (
    g1_swap_rooms,
    g2_move_room,
    g3_swap_bays,
    g4_swap_runs,
    g5_move_run,
    g6_flip_finger,
    g7_split_merge,
)
from ale.program.models import PreparedInput
from ale.topology import SeedResult


# ------------------------------------------------------------------ hand-made plans
def _ctx(zones: dict[str, str], areas: dict[str, float] | None = None) -> MoveContext:
    poly = ModulePolygon.model_validate({"exterior": [[0, 0], [40, 0], [40, 20], [0, 20]]})
    return MoveContext(
        instance_ids=tuple(zones),
        zone_of=zones,
        area_of=areas or dict.fromkeys(zones, 10.0),
        footprint=decompose_footprint(poly),
    )


def _plan(
    *bands: tuple[tuple[object, ...], tuple[object, ...]], connector: str = ""
) -> CorridorPlan:
    conn = connector or ("none" if len(bands) == 1 else "start")
    return CorridorPlan.model_validate(
        {
            "pieces": [
                {
                    "bands": [
                        {"block_a": {"bays": list(a)}, "block_b": {"bays": list(b)}}
                        for a, b in bands
                    ],
                    "connector": conn,
                }
            ]
        }
    )


def room(r: str) -> dict[str, str]:
    return {"kind": "room", "room": r}


def finger(left: tuple[str, ...] = (), right: tuple[str, ...] = ()) -> dict[str, object]:
    return {"kind": "finger", "left": list(left), "right": list(right)}


def _valid(new: CorridorPlan, ctx: MoveContext) -> None:
    """Contract validators (re-run from a dump) and ``check_against``."""
    again = CorridorPlan.model_validate(new.model_dump())
    assert again == new
    assert new.check_against(ctx.instance_ids, ctx.footprint) == ()


def _results(move, plan: CorridorPlan, ctx: MoveContext, n: int = 200) -> list[CorridorPlan]:
    rng = random.Random(7)
    return [r for r in (move(plan, ctx, rng) for _ in range(n)) if r is not None]


# ------------------------------------------------------------------------------ O01
def test_O01_moves_valid(seeded: dict[str, tuple[PreparedInput, SeedResult]]) -> None:
    prep, res = seeded["P25"]
    ctx = MoveContext.from_prepared(prep)
    rng = random.Random(2024)
    plan = res.plan
    zones0 = len(plan.zone_violations(ctx.zone_of))
    applied: Counter[str] = Counter()
    for _ in range(2000):
        name, new = propose(plan, ctx, rng)
        if new is None:
            continue
        _valid(new, ctx)
        assert len(new.zone_violations(ctx.zone_of)) <= zones0
        applied[name] += 1
        plan = new
    assert set(applied) == set(MOVES), applied


def test_O01_weights() -> None:
    # Ticket Q.2 rescaled the table and added G8-G10.
    assert set(MOVE_WEIGHTS) == set(MOVES) == {f"G{i}" for i in range(1, 11)}
    assert sum(MOVE_WEIGHTS.values()) == pytest.approx(1.0)
    assert MOVE_WEIGHTS == {
        "G1": 0.20,
        "G2": 0.15,
        "G3": 0.10,
        "G4": 0.08,
        "G5": 0.08,
        "G6": 0.07,
        "G7": 0.07,
        "G8": 0.08,
        "G9": 0.12,
        "G10": 0.05,
    }


# ------------------------------------------------------------------------------ O02
def test_O02_g1_swaps_two_rooms_of_one_zone() -> None:
    zones = {"a1": "PUBLIC", "a2": "PUBLIC", "a3": "PUBLIC", "b1": "SERVICES", "b2": "SERVICES"}
    areas = {"a1": 10.0, "a2": 12.0, "a3": 30.0, "b1": 10.0, "b2": 10.0}
    ctx = _ctx(zones, areas)
    plan = _plan(((room("a1"), room("a2"), room("a3")), (finger(("b1",), ("b2",)),)))
    before = plan.room_ids()
    results = _results(g1_swap_rooms, plan, ctx)
    assert results
    for new in results:
        _valid(new, ctx)
        after = new.room_ids()
        diff = [i for i, (x, y) in enumerate(zip(before, after, strict=True)) if x != y]
        assert len(diff) == 2
        i, j = diff
        assert (after[i], after[j]) == (before[j], before[i])
        assert zones[before[i]] == zones[before[j]]
        assert {before[i], before[j]} != {"a1", "a3"}  # 10 vs 30 m²: not within 25 %
        assert {before[i], before[j]} != {"a2", "a3"}


def test_O02_g6_flips_stacks() -> None:
    zones = dict.fromkeys(("x", "y", "z"), "ADMINISTRATIVE")
    ctx = _ctx(zones)
    plan = _plan(((finger(("x", "y"), ("z",)),), ()))
    seen = set()
    for new in _results(g6_flip_finger, plan, ctx):
        _valid(new, ctx)
        bay = new.pieces[0].bands[0].block_a.bays[0]
        assert isinstance(bay, FingerBay)
        seen.add((bay.left, bay.right))
    assert (("z",), ("x", "y")) in seen  # stacks swapped
    assert (("y", "x"), ("z",)) in seen  # left stack reversed
    assert seen <= {(("z",), ("x", "y")), (("y", "x"), ("z",))}


def test_O02_g7_split_then_merge() -> None:
    zones = {f"r{i}": "ADMINISTRATIVE" for i in range(8)}
    ctx = _ctx(zones)
    bays_a = tuple(room(f"r{i}") for i in range(4))
    bays_b = (finger(("r4", "r5")), finger((), ("r6",)), room("r7"))
    plan = _plan((bays_a, bays_b))

    def bays(p: CorridorPlan) -> Counter[object]:
        return Counter(
            bay
            for band in p.pieces[0].bands
            for block in (band.block_a, band.block_b)
            for bay in block.bays
        )

    splits = [p for p in _results(g7_split_merge, plan, ctx) if len(p.pieces[0].bands) == 2]
    assert splits
    for split in splits:
        _valid(split, ctx)
        assert split.pieces[0].connector in ("start", "end")
        assert bays(split) == bays(plan)
    merged = [p for p in _results(g7_split_merge, splits[0], ctx) if len(p.pieces[0].bands) == 1]
    assert merged
    for m in merged:
        _valid(m, ctx)
        assert m.pieces[0].connector == "none"
        assert bays(m) == bays(plan)


# ------------------------------------------------------------------ further semantics
def _fingers(p: CorridorPlan) -> Counter[FingerBay]:
    return Counter(
        bay
        for band in p.pieces[0].bands
        for block in (band.block_a, band.block_b)
        for bay in block.bays
        if isinstance(bay, FingerBay)
    )


def test_g2_moves_room_between_bay_kinds() -> None:
    zones = {"a": "PUBLIC", "b": "PUBLIC", "c": "PUBLIC", "s": "SERVICES"}
    ctx = _ctx(zones)
    plan = _plan(((room("a"), finger(("b",), ("c",))), (room("s"),)))
    results = _results(g2_move_room, plan, ctx, 300)
    assert results
    for new in results:
        _valid(new, ctx)
        assert sorted(new.room_ids()) == sorted(plan.room_ids())
        kind_changed = [
            r for r in zones if (plan.locate(r).stack is None) != (new.locate(r).stack is None)
        ]
        assert len(kind_changed) <= 1
        if not kind_changed:  # stack -> stack: some stack content changed
            assert _fingers(new) != _fingers(plan)
    kinds = {(plan.locate("a").stack is None, new.locate("a").stack is None) for new in results}
    assert (True, False) in kinds  # room bay -> stack happened


def test_g2_never_leaves_an_empty_finger() -> None:
    zones = {"a": "PUBLIC", "b": "PUBLIC"}
    ctx = _ctx(zones)
    plan = _plan(((finger(("a",)), room("b")), ()))
    for new in _results(g2_move_room, plan, ctx):
        for band in new.pieces[0].bands:
            for bay in (*band.block_a.bays, *band.block_b.bays):
                if isinstance(bay, FingerBay):
                    assert bay.left or bay.right


def test_g3_g4_g5_reorder() -> None:
    zones = {"a1": "PUBLIC", "a2": "PUBLIC", "b1": "SERVICES", "c1": "ADMINISTRATIVE"}
    ctx = _ctx(zones)
    plan = _plan(((room("a1"), room("a2"), room("b1")), (room("c1"),)))
    g3 = _results(g3_swap_bays, plan, ctx)
    assert {p.room_ids() for p in g3} == {("a2", "a1", "b1", "c1")}
    g4 = _results(g4_swap_runs, plan, ctx)
    assert {p.room_ids() for p in g4} == {("b1", "a1", "a2", "c1")}
    g5 = _results(g5_move_run, plan, ctx)
    assert g5
    for new in g5:
        _valid(new, ctx)
        assert Counter(new.room_ids()) == Counter(plan.room_ids())
    # The PUBLIC run moves as a whole: a1 and a2 stay adjacent in one block.
    moved = [p for p in g5 if p.locate("a1").block == "B"]
    assert moved and all(p.locate("a2").block == "B" for p in moved)


def test_moves_not_applicable() -> None:
    ctx = _ctx({"a": "PUBLIC"})
    plan = _plan(((room("a"),), ()))
    rng = random.Random(0)
    for move in (g1_swap_rooms, g3_swap_bays, g4_swap_runs, g6_flip_finger):
        assert move(plan, ctx, rng) is None
    # G5: the only target leaves block A empty and is valid; G2 needs a finger target.
    assert all(isinstance(p, CorridorPlan) for p in _results(g2_move_room, plan, ctx, 20))


def test_moves_reject_zone_splits() -> None:
    zones = {"a1": "PUBLIC", "a2": "PUBLIC", "b1": "SERVICES"}
    ctx = _ctx(zones)
    plan = _plan(((room("a1"), room("b1")), (room("a2"),)))
    # G5 moving b1 into block B between nothing splits nothing; moving a2 next to b1 must not
    # create "zone PUBLIC split".
    for new in _results(g5_move_run, plan, ctx):
        assert len(new.zone_violations(ctx.zone_of)) <= len(plan.zone_violations(ctx.zone_of))


def test_g7_on_six_bands_only_merges() -> None:
    zones = {f"r{i}": "PUBLIC" for i in range(12)}
    ctx = _ctx(zones)
    bands = tuple(((room(f"r{2 * k}"),), (room(f"r{2 * k + 1}"),)) for k in range(6))
    plan = _plan(*bands)
    for new in _results(g7_split_merge, plan, ctx, 50):
        assert len(new.pieces[0].bands) == 5


def test_move_context_shapes() -> None:
    ctx = _ctx({"a": "PUBLIC"})
    plan = CorridorPlan(
        pieces=(
            PiecePlan(
                bands=(BandPlan(block_a=BlockPlan(bays=(RoomBay(room="a"),)), block_b=BlockPlan()),)
            ),
        )
    )
    assert plan.check_against(ctx.instance_ids, ctx.footprint) == ()


def test_g2_fold_run_into_one_stack() -> None:
    zones = {"a1": "SERVICES", "a2": "SERVICES", "a3": "SERVICES", "b": "PUBLIC"}
    ctx = _ctx(zones)
    plan = _plan(((room("b"), room("a1"), room("a2"), room("a3")), ()))
    folded = []
    for new in _results(g2_move_room, plan, ctx, 400):
        _valid(new, ctx)
        bays = new.pieces[0].bands[0].block_a.bays
        stacks = [st for bay in bays if isinstance(bay, FingerBay) for st in (bay.left, bay.right)]
        if ("a1", "a2", "a3") in stacks:
            folded.append(new)
            assert bays[0] == RoomBay(room="b") and len(bays) == 2
    assert folded


def test_g2_fold_needs_a_run() -> None:
    zones = {"a1": "SERVICES", "b": "PUBLIC"}
    ctx = _ctx(zones)
    plan = _plan(((room("b"), room("a1")), ()))
    for new in _results(g2_move_room, plan, ctx, 200):
        _valid(new, ctx)
        for bay in new.pieces[0].bands[0].block_a.bays:
            if isinstance(bay, FingerBay):
                assert len(bay.left) + len(bay.right) == 1


def test_focus_biases_room_choice() -> None:
    zones = {f"r{i}": "PUBLIC" for i in range(8)}
    ctx = _ctx(zones)
    plan = _plan(
        (tuple(room(f"r{i}") for i in range(4)), tuple(room(f"r{i}") for i in range(4, 8)))
    )
    focused = ctx.with_focus({"r0", "zzz"})
    assert focused.focus == ("r0",)
    assert focused.with_focus({"r0"}) is focused

    def share(c: MoveContext) -> float:
        res = _results(g1_swap_rooms, plan, c, 600)
        return sum(1 for p in res if p.room_ids()[0] != "r0") / len(res)

    assert share(focused) > 0.4 > share(ctx)
