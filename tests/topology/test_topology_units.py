"""Ticket 3.2: unit tests of the seeding internals (J1 footprints, repair moves, embedding,
fallbacks) — supporting eval T11's coverage gate."""

from __future__ import annotations

from fractions import Fraction

from ale.config import AleConfig
from ale.contracts.corridor_plan import FingerBay, RoomBay
from ale.contracts.footprint import decompose_footprint
from ale.contracts.geometry import ModulePolygon
from ale.contracts.models import Rulebook
from ale.geometry import realize
from ale.program.models import PreparedInput
from ale.topology import build_graph, seed_plan
from ale.topology.embed import core_target_m, embed
from ale.topology.graph import CORE
from ale.topology.repair import (
    Ctx,
    Draft,
    _merge_small,
    _move_smallest,
    _rebalance_stack,
    _shift_junction,
    band_moves,
    block_depths,
    block_overflows,
    form_bays,
    repair_step,
    score,
)
from ale.topology.seed import _Search, assign, unsatisfiable

CONFIG = AleConfig()


def _ctx(prepared: PreparedInput, rulebook: Rulebook) -> Ctx:
    fp = decompose_footprint(prepared.footprint.polygon)
    return Ctx.build(prepared, rulebook, CONFIG, fp)


def test_j1_footprint_seeds(prep_25_j1: PreparedInput, rulebook: Rulebook) -> None:
    fp = decompose_footprint(prep_25_j1.footprint.polygon)
    assert fp.junction == "J1"
    result = seed_plan(prep_25_j1, rulebook, CONFIG, seed=1, time_budget_s=20)
    plan = result.plan
    assert len(plan.pieces) == 2 and len(plan.pieces[1].bands) == 1
    junctions = [
        bay
        for piece in plan.pieces
        for band in piece.bands
        for block in (band.block_a, band.block_b)
        for bay in block.bays
        if isinstance(bay, FingerBay) and bay.junction
    ]
    assert len(junctions) == 1
    assert sorted(plan.room_ids()) == sorted(iid for iid, _ in prep_25_j1.instances)
    assert not any(f.code == "PLAN_INVALID" for f in result.realization.failures)


def test_shift_junction(prep_25_j1: PreparedInput, rulebook: Rulebook) -> None:
    ctx = _ctx(prep_25_j1, rulebook)
    pos = embed(build_graph(prep_25_j1, rulebook), prep_25_j1, rulebook, seed=1)
    draft = assign(ctx, [2, 1], pos)
    moved = _shift_junction(draft, 1) or _shift_junction(draft, -1)
    assert moved is not None and moved.blocks != draft.blocks
    assert _shift_junction(draft, 10_000) is None
    assert _shift_junction(Draft([1], ["none"], {(0, 0, "A"): []}), 1) is None


def test_unsupported_footprint(prep_8: PreparedInput, rulebook: Rulebook) -> None:
    poly = ModulePolygon(
        exterior=((0, 0), (100, 0), (100, 40), (60, 40), (60, 70), (100, 70), (100, 100), (0, 100))
    )
    fp = prep_8.footprint.model_copy(update={"polygon": poly})
    odd = prep_8.model_copy(update={"footprint": fp})
    result = seed_plan(odd, rulebook, CONFIG, seed=1)
    assert [f.code for f in result.realization.failures] == ["FOOTPRINT_UNSUPPORTED"]
    assert result.attempts == 1


def test_embed_deterministic(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    g = build_graph(prep_25, rulebook)
    a = embed(g, prep_25, rulebook, seed=7)
    assert a == embed(g, prep_25, rulebook, seed=7)
    assert a != embed(g, prep_25, rulebook, seed=8)
    assert a[CORE] == core_target_m(prep_25, rulebook)
    for x, y in a.values():
        assert 0.0 <= x <= 24.0 and 0.0 <= y <= 18.0


def test_core_hint(prep_60: PreparedInput, rulebook: Rulebook) -> None:
    assert core_target_m(prep_60, rulebook) == (12.0, 15.0)


def _overflowing(prep_25: PreparedInput, rulebook: Rulebook) -> tuple[Ctx, Draft]:
    """Every room in band 0 block A of a 2-band plan: a large overflow."""
    ctx = _ctx(prep_25, rulebook)
    rooms = [iid for iid, _ in prep_25.instances]
    depth = Fraction(78, 2)
    draft = Draft([2], ["start"])
    for slot in draft.slots():
        draft.blocks[slot] = []
    draft.blocks[(0, 0, "A")] = form_bays(ctx, rooms, depth)
    return ctx, draft


def test_repair_moves(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    ctx, draft = _overflowing(prep_25, rulebook)
    real = realize(prep_25, draft.to_plan(), rulebook, CONFIG)
    over = block_overflows(real)
    assert over[(0, 0, "A")] > 0
    depths = block_depths(ctx, draft, real)
    moved = _move_smallest(ctx, draft, (0, 0, "A"), depths)
    assert moved is not None
    assert len(moved.to_plan().room_ids()) == 25
    assert _move_smallest(ctx, draft, (0, 1, "B"), depths) is None  # empty block

    merged = _merge_small(ctx, draft, (0, 0, "A"), Fraction(39))
    assert merged is not None
    n_before = len(draft.blocks[(0, 0, "A")])
    assert len(merged.blocks[(0, 0, "A")]) == n_before - 1
    shallow = _merge_small(ctx, draft, (0, 0, "A"), Fraction(10))
    assert shallow is not None
    assert _merge_small(ctx, draft, (0, 1, "B"), Fraction(39)) is None

    stacked = Draft([1], ["none"], {(0, 0, "A"): [FingerBay(left=("B01#01", "B01#02"))]})
    rebalanced = _rebalance_stack(stacked, (0, 0, "A"))
    assert rebalanced is not None
    assert rebalanced.blocks[(0, 0, "A")] == [FingerBay(left=("B01#01",), right=("B01#02",))]
    back = Draft([1], ["none"], {(0, 0, "A"): [FingerBay(right=("B01#01", "B01#02"))]})
    assert _rebalance_stack(back, (0, 0, "A")) is not None
    assert _rebalance_stack(rebalanced, (0, 0, "A")) is None

    assert band_moves(draft, 0, [1, 2, 3]) == [[1], [3]]
    assert band_moves(Draft([1], ["none"]), 0, [1, 2]) == [[2]]


def test_repair_step_improves(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    ctx, draft = _overflowing(prep_25, rulebook)
    search = _Search(prep_25, rulebook, CONFIG, ctx.fp, 1)
    real = search.realise(draft)
    pos = embed(search.graph, prep_25, rulebook, seed=1)
    step = repair_step(
        ctx, draft, real, search.realise, lambda c: assign(ctx, c, pos), [[1, 2, 3]], lambda: True
    )
    assert step is not None
    assert score(step[1]) < score(real)
    # An exhausted budget stops the step.
    assert (
        repair_step(ctx, draft, real, search.realise, lambda c: None, [[2]], lambda: False) is None
    )
    # A valid realisation has nothing to repair.
    valid = seed_plan(prep_25, rulebook, CONFIG, seed=1)
    assert unsatisfiable(search, draft, real) == unsatisfiable(search, draft, real)
    assert valid.report.unsatisfiable_required == tuple(sorted(valid.report.unsatisfiable_required))


def test_remove_and_insert_paths(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    from ale.topology.repair import move_room

    ctx = _ctx(prep_25, rulebook)
    draft = Draft(
        [1],
        ["none"],
        {
            (0, 0, "A"): [FingerBay(left=("T01#1", "T01#2"), right=("S02",)), RoomBay(room="H01")],
            (0, 0, "B"): [FingerBay(left=("T03",), right=("T02",))],
        },
    )
    # Small room into a same-zone finger with a free stack slot.
    out = move_room(ctx, draft, "S02", (0, 0, "B"), Fraction(40))
    assert out.blocks[(0, 0, "A")][0] == FingerBay(left=("T01#1", "T01#2"))
    assert out.blocks[(0, 0, "B")][0] == FingerBay(left=("T03", "S02"), right=("T02",))
    # A finger left with one room becomes a room bay; a big room goes after its zone.
    out2 = move_room(ctx, draft, "T03", (0, 0, "A"), Fraction(5))
    assert out2.blocks[(0, 0, "B")] == [RoomBay(room="T02")]
    out3 = move_room(ctx, out2, "T02", (0, 0, "A"), Fraction(5))
    assert out3.blocks[(0, 0, "B")] == []
    full = Draft(
        [1],
        ["none"],
        {
            (0, 0, "A"): [RoomBay(room="T03")],
            (0, 0, "B"): [FingerBay(left=("T01#1", "T01#2"), right=("S02", "T02"))],
        },
    )
    out4 = move_room(ctx, full, "T03", (0, 0, "B"), Fraction(40))
    assert out4.blocks[(0, 0, "B")][-1] == RoomBay(room="T03")
    right = Draft(
        [1],
        ["none"],
        {
            (0, 0, "A"): [RoomBay(room="T03")],
            (0, 0, "B"): [FingerBay(left=("T01#1", "T01#2"), right=("S02",))],
        },
    )
    out5 = move_room(ctx, right, "T03", (0, 0, "B"), Fraction(40))
    assert out5.blocks[(0, 0, "B")][0] == FingerBay(left=("T01#1", "T01#2"), right=("S02", "T03"))
