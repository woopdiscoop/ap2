"""Greedy baseline corridor plan (RD 3.3 §8 as amended by RD 3.3b §1.6) — not optimised.

Bands per piece: ``n = max(1, round((P - s) / (2·D_t + s)))`` capped at ``MAX_BANDS``, with
``D_t = ceil(sqrt(1.4 x median target cells))``; a multi-band piece gets the connector at
``"start"``, or on its cut side where the contract requires it (J2). Rooms are taken zone
by zone (PUBLIC, ADMINISTRATIVE, SERVICES), each zone by descending target. Rooms below
``0.5 x D_est²`` (``D_est = (P_band - s) / 2``) go into finger-bay stacks (two rooms per
stack, left then right), the others into room bays. Bays fill the blocks in order (piece 0
band 0 A, band 0 B, band 1 A, ..., piece 1 ...): a block is closed when the next bay's
estimated width would exceed the band length (the last block takes the rest). A J1
footprint gets an empty junction finger in the facing block of the primary band adjacent
to the cut, placed where its estimated position falls inside the secondary piece. The plan
may overflow.
"""

from __future__ import annotations

import math
import statistics
from fractions import Fraction
from typing import Literal

from ale.contracts.config import AleConfig
from ale.contracts.corridor_plan import (
    MAX_BANDS,
    BandPlan,
    BlockPlan,
    CorridorPlan,
    FingerBay,
    PiecePlan,
    RoomBay,
)
from ale.contracts.enums import MacroZone
from ale.contracts.footprint import FootprintPieces, decompose_footprint
from ale.contracts.models import Rulebook
from ale.geometry.blocks import Consts, RoomReq
from ale.geometry.junction import across_origin, along_origin, cut_side, frame
from ale.program.models import PreparedInput

__all__ = ["band_count", "greedy_plan"]

_ZONES = (MacroZone.PUBLIC, MacroZone.ADMINISTRATIVE, MacroZone.SERVICES)
_D_T_FACTOR = Fraction(7, 5)

AnyBay = RoomBay | FingerBay
Connector = Literal["none", "start", "end"]


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


def _ceil_sqrt(x: Fraction) -> int:
    """Smallest integer ``d >= 0`` with ``d² >= x`` (exact)."""
    d = math.isqrt(math.floor(x))
    while d * d < x:
        d += 1
    return d


def band_count(depth: int, targets: list[Fraction], s: int) -> int:
    """RD 3.3b §1.6: ``max(1, round((P - s) / (2·D_t + s)))``, capped at ``MAX_BANDS``.

    ``round`` is Python's (half to even); ``D_t = ceil(sqrt(median x 1.4))``.
    """
    if not targets:
        return 1
    d_t = _ceil_sqrt(statistics.median(targets) * _D_T_FACTOR)
    n = round(Fraction(depth - s, 2 * d_t + s))
    return max(1, min(MAX_BANDS, n))


def _connectors(fp: FootprintPieces, counts: list[int]) -> list[Connector]:
    out: list[Connector] = ["none" if n == 1 else "start" for n in counts]
    if fp.junction == "J2" and any(n >= 2 for n in counts):
        for p, n in enumerate(counts):
            if n >= 2:  # the cut side satisfies the contract and links the two pieces
                side = cut_side(fp, p)
                out[p] = "start" if side == "none" else side
    return out


def greedy_plan(prepared: PreparedInput, rulebook: Rulebook, config: AleConfig) -> CorridorPlan:
    """A simple deterministic plan for ``prepared`` (``rulebook`` is not used)."""
    del rulebook
    k = Consts.from_config(config)
    fp = decompose_footprint(prepared.footprint.polygon)
    if len(fp.pieces) > 2:  # G.1: trees of pieces are planned by ``ale.topology.seed_plan``
        raise ValueError("greedy_plan supports footprints of one or two pieces only")
    reqs = {iid: k.req(spec) for iid, spec in prepared.instances}
    order = {iid: i for i, (iid, _) in enumerate(prepared.instances)}
    targets = [r.target for r in reqs.values()]
    counts = [band_count(frame(pc)[1], targets, k.s) for pc in fp.pieces]
    if fp.junction == "J1":
        counts[1] = 1  # contract: the J1 secondary has exactly one band
    connectors = _connectors(fp, counts)

    def band_depths(p: int) -> list[int]:
        depth, n = frame(fp.pieces[p])[1], counts[p]
        out = [depth // n] * n
        out[-1] += depth - n * (depth // n)
        return out

    def band_length(p: int) -> int:
        length = frame(fp.pieces[p])[0]
        return length if connectors[p] == "none" else length - k.s

    slots = [
        (p, b, side) for p in range(len(fp.pieces)) for b in range(counts[p]) for side in ("A", "B")
    ]
    depth_of = {(p, b): d for p in range(len(fp.pieces)) for b, d in enumerate(band_depths(p))}
    bays: list[list[AnyBay]] = [[] for _ in slots]
    used = [0] * len(slots)

    def d_est(slot: int) -> Fraction:
        p, b, _ = slots[slot]
        return Fraction(max(1, depth_of[(p, b)] - k.s), 2)

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
            length = band_length(slots[cur][0])
            if bays[cur] and used[cur] + w > length and cur + 1 < len(slots):
                cur += 1
                w = _width(bay, reqs, d_est(cur), k.s)
            bays[cur].append(bay)
            used[cur] += w

    if fp.junction == "J1":
        primary, secondary = fp.pieces
        band = 0 if fp.facing_block == "A" else counts[0] - 1
        slot = slots.index((0, band, fp.facing_block or "A"))
        u0 = k.s if connectors[0] == "start" else 0
        start = across_origin(secondary) - along_origin(primary) - u0
        cum = 0
        index = len(bays[slot])
        for i, bay in enumerate(bays[slot]):
            if cum >= start:
                index = i
                break
            cum += _width(bay, reqs, d_est(slot), k.s)
        bays[slot].insert(index, FingerBay(junction=True))

    def block(p: int, b: int, side: str) -> BlockPlan:
        return BlockPlan(bays=tuple(bays[slots.index((p, b, side))]))

    pieces = tuple(
        PiecePlan(
            bands=tuple(
                BandPlan(block_a=block(p, b, "A"), block_b=block(p, b, "B"))
                for b in range(counts[p])
            ),
            connector=connectors[p],
        )
        for p in range(len(fp.pieces))
    )
    return CorridorPlan(pieces=pieces)
