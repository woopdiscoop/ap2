"""Ticket Q.1 §4: depth-interval-aware assignment and the repair moves (e) (f) (g)."""

from __future__ import annotations

from fractions import Fraction

from ale.config import AleConfig
from ale.contracts.corridor_plan import FingerBay, RoomBay
from ale.contracts.footprint import decompose_footprint
from ale.contracts.models import Rulebook
from ale.geometry import Failure, Realization, realize
from ale.program.models import PreparedInput
from ale.topology import build_graph
from ale.topology.depth import depth_groups, form_depth_bays, room_depths
from ale.topology.embed import embed
from ale.topology.repair import (
    Ctx,
    Draft,
    bay_rooms,
    infeasible_rooms,
    move_to_compatible,
    move_to_stack,
    repair_step,
)
from ale.topology.seed import _repack, _resplit, assign

CONFIG = AleConfig()
SHAPE_CODES = {"AREA_UNDER", "AREA_OVER", "ASPECT", "MIN_WIDTH"}


def _ctx(prepared: PreparedInput, rulebook: Rulebook) -> Ctx:
    return Ctx.build(prepared, rulebook, CONFIG, decompose_footprint(prepared.footprint.polygon))


def _rooms(draft: Draft) -> list[str]:
    return sorted(r for bays in draft.blocks.values() for b in bays for r in bay_rooms(b))


def test_depth_sets_and_groups(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    ctx = _ctx(prep_25, rulebook)
    # B02: 60 m², min width 4.8 m (48 modules) → only deep blocks.
    b02 = room_depths(ctx, "B02", 168)
    assert b02 and b02[0] >= 48
    office = room_depths(ctx, "B01#01", 168)
    assert office and office[-1] < b02[0]  # no common depth with B02
    assert all(ctx.bay_ok("B02", d) for d in b02)
    assert not ctx.bay_ok("B02", office[0])
    assert not ctx.bay_ok("B02", 0)
    groups = depth_groups(ctx, [iid for iid, _ in prep_25.instances], 168)
    assert len(groups) >= 2
    assert all(lo <= hi for lo, hi in groups)
    assert [g[0] for g in groups] == sorted(g[0] for g in groups)


def test_exact_widths(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    ctx = _ctx(prep_25, rulebook)
    assert ctx.exact_room_width("B01#01", 0) is None
    assert ctx.exact_room_width("B01#01", 40) == 30
    assert ctx.exact_stack_width([], 40) == 0
    assert ctx.exact_stack_width(["T01#1"], 0) is None
    assert ctx.exact_stack_width(["T01#1", "T01#2"], 40) is not None
    finger = FingerBay(left=("T01#1",), right=("T01#2",))
    w = ctx.exact_bay_width(finger, 40)
    assert w is not None and w > ctx.k.s
    assert ctx.exact_bay_width(FingerBay(left=("B02",)), 20) is None
    assert ctx.exact_bay_width(RoomBay(room="B02"), 20) is None


def test_form_depth_bays(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    ctx = _ctx(prep_25, rulebook)
    rooms = ["T01#1", "T01#2", "T03", "S02", "B01#01"]
    bays = form_depth_bays(ctx, rooms, {"T01#1", "T01#2", "T03", "S02"}, 60)
    assert sorted(r for b in bays for r in bay_rooms(b)) == sorted(rooms)
    fingers = [b for b in bays if isinstance(b, FingerBay)]
    assert fingers
    for f in fingers:  # every stack complies at that depth
        assert ctx.exact_bay_width(f, 60) is not None


def test_assign_depth_aware(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    ctx = _ctx(prep_25, rulebook)
    pos = embed(build_graph(prep_25, rulebook), prep_25, rulebook, seed=3)
    draft = assign(ctx, [2], pos)
    assert _rooms(draft) == sorted(iid for iid, _ in prep_25.instances)
    assert set(draft.depths) == set(draft.slots())
    s = ctx.k.s
    assert sum(draft.depths.values()) + 2 * s == 180
    # Room bays only where their block's target depth is compliant.
    for slot, bays in draft.blocks.items():
        for bay in bays:
            if isinstance(bay, RoomBay):
                assert ctx.bay_ok(bay.room, draft.depths[slot]), (slot, bay)
    real = realize(prep_25, draft.to_plan(), rulebook, CONFIG)
    if real.layout is not None:
        assert not SHAPE_CODES & {v.code for v in real.layout.metrics.violations}
    # A forced split is honoured.
    forced = assign(ctx, [2], pos, fixed={(0, 0): 60})
    assert forced.depths[(0, 0, "A")] == 60
    assert forced.depths[(0, 0, "B")] == 90 - s - 60


def test_infeasible_rooms_parsing() -> None:
    real = Realization(
        layout=None,
        failures=(
            Failure(code="ROOM_INFEASIBLE", detail="a in piece 0 band 1 block A: no compliant"),
            Failure(
                code="STACK_INFEASIBLE",
                detail="piece 0 band 0 block B bay 2 left: no compliant stack width for b, c "
                "at depth 30",
            ),
            Failure(code="ROOM_INFEASIBLE", detail="a in piece 0 band 1 block B: again"),
            Failure(code="PLAN_OVERFLOW", detail="piece 0 band 0 block A over by 3 modules"),
        ),
        depths=(),
    )
    assert infeasible_rooms(real) == ["a", "c"]


def test_moves_e_f_g(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    ctx = _ctx(prep_25, rulebook)
    others = [iid for iid, _ in prep_25.instances if iid not in {"B02", "T01#1"}]
    draft = Draft(
        [2],
        ["start"],
        {
            (0, 0, "A"): [RoomBay(room="B02")],
            (0, 0, "B"): [RoomBay(room="T01#1")],
            (0, 1, "A"): [RoomBay(room=r) for r in others[:12]],
            (0, 1, "B"): [RoomBay(room=r) for r in others[12:]],
        },
    )
    depths = {
        (0, 0, "A"): Fraction(24),
        (0, 0, "B"): Fraction(54),
        (0, 1, "A"): Fraction(39),
        (0, 1, "B"): Fraction(39),
    }
    # (e) B02 (needs >= 48) moves to the only compatible block, 54 deep.
    moved = move_to_compatible(ctx, draft, "B02", depths)
    assert moved is not None
    assert moved.find("B02")[0] == (0, 0, "B")
    assert move_to_compatible(ctx, draft, "nope", depths) is None
    # No compatible block at all → None.
    shallow = {sl: Fraction(13) for sl in depths}
    assert move_to_compatible(ctx, draft, "B02", shallow) is None
    # (f) T01#1 goes into a stack (its own block first).
    stacked = move_to_stack(ctx, draft, "T01#1", depths)
    assert stacked is not None
    slot, i = stacked.find("T01#1")
    assert isinstance(stacked.blocks[slot][i], FingerBay)
    assert move_to_stack(ctx, draft, "nope", depths) is None
    assert move_to_stack(ctx, draft, "B02", shallow) is None
    # ... and joins a same-zone finger with room left.
    two = Draft(
        [1],
        ["none"],
        {(0, 0, "A"): [], (0, 0, "B"): [FingerBay(left=("T01#2",)), RoomBay(room="T01#1")]},
    )
    joined = move_to_stack(ctx, two, "T01#1", {(0, 0, "A"): Fraction(70), (0, 0, "B"): 70})
    assert joined is not None
    assert len(joined.blocks[(0, 0, "B")]) == 1
    assert set(bay_rooms(joined.blocks[(0, 0, "B")][0])) == {"T01#1", "T01#2"}
    # (g) resplit / repack re-assign the draft with fixed splits.
    pos = embed(build_graph(prep_25, rulebook), prep_25, rulebook, seed=3)
    base = assign(ctx, [2], pos)
    resplit = _resplit(ctx, base, (0, 0, "A"), "B02", pos)
    if resplit is not None:
        assert _rooms(resplit) == _rooms(base)
    # 3 bands of P25: inner depth 48, so B02 (>= 48) cannot fit beside a >= 12 block.
    three = assign(ctx, [3], pos)
    assert _resplit(ctx, three, (0, 0, "A"), "B02", pos) is None
    real = realize(prep_25, base.to_plan(), rulebook, CONFIG)
    repacked = _repack(ctx, base, real, pos)
    if repacked is not None:
        assert _rooms(repacked) == _rooms(base)
    wrong = Realization(layout=None, failures=(Failure(code="X", detail="y"),), depths=())
    assert _repack(ctx, base, wrong, pos) is None


def test_repair_step_uses_q1_moves(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    ctx = _ctx(prep_25, rulebook)
    others = [iid for iid, _ in prep_25.instances if iid != "B02"]
    draft = Draft(
        [1],
        ["none"],
        {
            (0, 0, "A"): [RoomBay(room="B02"), *(RoomBay(room=r) for r in others[:8])],
            (0, 0, "B"): [RoomBay(room=r) for r in others[8:]],
        },
    )
    real = realize(prep_25, draft.to_plan(), rulebook, CONFIG)
    calls: list[str] = []

    def resplit(d: Draft, slot: tuple[int, int, str], room: str) -> Draft | None:
        calls.append(f"resplit {room}")
        return None

    def repack(d: Draft, r: Realization) -> Draft | None:
        calls.append("repack")
        return None

    def realise(d: Draft) -> Realization:
        return realize(prep_25, d.to_plan(), rulebook, CONFIG)

    repair_step(ctx, draft, real, realise, lambda c: None, [[1]], lambda: True, resplit, repack)
    assert calls and calls[0] == "repack"
