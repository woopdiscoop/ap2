"""Greedy baseline corridor plan (RD 3.3 section 8) — deterministic, not optimised.

Rooms are taken zone by zone (PUBLIC, ADMINISTRATIVE, SERVICES), each zone by descending
target. Rooms below ``0.5 x D_est²`` (``D_est = (P - s) / 2``) go into finger-bay stacks
(two rooms per stack, left then right), the others into room bays. Bays fill the blocks in
order (piece 0 A, piece 0 B, piece 1 A, ...): a block is closed when the next bay's
estimated width would exceed the piece length (the last block takes the rest). A J1
footprint gets an empty junction finger in the primary's facing block, placed where its
estimated position falls inside the secondary piece. The plan may overflow.
"""

from __future__ import annotations

import math
from fractions import Fraction

from ale.contracts.config import AleConfig
from ale.contracts.corridor_plan import BlockPlan, CorridorPlan, FingerBay, PiecePlan, RoomBay
from ale.contracts.enums import MacroZone
from ale.contracts.footprint import decompose_footprint
from ale.contracts.models import Rulebook
from ale.geometry.blocks import Consts, RoomReq
from ale.geometry.junction import across_origin, along_origin, frame
from ale.program.models import PreparedInput

__all__ = ["greedy_plan"]

_ZONES = (MacroZone.PUBLIC, MacroZone.ADMINISTRATIVE, MacroZone.SERVICES)

AnyBay = RoomBay | FingerBay


def _width(bay: AnyBay, reqs: dict[str, RoomReq], d_est: Fraction, s: int) -> int:
    def stack(rooms: tuple[str, ...]) -> int:
        if not rooms:
            return 0
        total = sum(reqs[r].target for r in rooms)
        return max(max(reqs[r].wmin for r in rooms), math.ceil(total / d_est))

    if isinstance(bay, RoomBay):
        req = reqs[bay.room]
        return max(req.wmin, math.ceil(req.target / d_est))
    return stack(bay.left) + s + stack(bay.right)


def greedy_plan(prepared: PreparedInput, rulebook: Rulebook, config: AleConfig) -> CorridorPlan:
    """A simple deterministic plan for ``prepared`` (``rulebook`` is not used)."""
    del rulebook
    k = Consts.from_config(config)
    fp = decompose_footprint(prepared.footprint.polygon)
    reqs = {iid: k.req(spec) for iid, spec in prepared.instances}
    order = {iid: i for i, (iid, _) in enumerate(prepared.instances)}
    slots = [(p, side) for p in range(len(fp.pieces)) for side in ("A", "B")]
    bays: list[list[AnyBay]] = [[] for _ in slots]
    used = [0] * len(slots)

    def d_est(slot: int) -> Fraction:
        return Fraction(max(1, frame(fp.pieces[slots[slot][0]])[1] - k.s), 2)

    cur = 0
    for zone in _ZONES:
        rooms = sorted(
            (iid for iid, spec in prepared.instances if spec.macro_zone == zone),
            key=lambda r: (-reqs[r].target, order[r]),
        )
        if not rooms:
            continue
        est = d_est(cur)
        big = [r for r in rooms if reqs[r].target >= est * est / 2]
        small = [r for r in rooms if reqs[r].target < est * est / 2]
        zone_bays: list[AnyBay] = [RoomBay(room=r) for r in big]
        for i in range(0, len(small), 4):
            group = small[i : i + 4]
            zone_bays.append(FingerBay(left=tuple(group[:2]), right=tuple(group[2:])))
        for bay in zone_bays:
            w = _width(bay, reqs, d_est(cur), k.s)
            length = frame(fp.pieces[slots[cur][0]])[0]
            if bays[cur] and used[cur] + w > length and cur + 1 < len(slots):
                cur += 1
                w = _width(bay, reqs, d_est(cur), k.s)
            bays[cur].append(bay)
            used[cur] += w

    if fp.junction == "J1":
        primary, secondary = fp.pieces
        slot = 0 if fp.facing_block == "A" else 1
        start = across_origin(secondary) - along_origin(primary)
        cum = 0
        index = len(bays[slot])
        for i, bay in enumerate(bays[slot]):
            if cum >= start:
                index = i
                break
            cum += _width(bay, reqs, d_est(slot), k.s)
        bays[slot].insert(index, FingerBay(junction=True))

    pieces = tuple(
        PiecePlan(
            block_a=BlockPlan(bays=tuple(bays[2 * p])),
            block_b=BlockPlan(bays=tuple(bays[2 * p + 1])),
        )
        for p in range(len(fp.pieces))
    )
    return CorridorPlan(pieces=pieces)
