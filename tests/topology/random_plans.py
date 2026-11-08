"""Random corridor plans obeying the contract rules (Ticket 3.2 eval T09), written
independently of ``ale.topology``: random band count, connector at the start, rooms
shuffled into room bays and finger bays, bays cut into the blocks at random points."""

from __future__ import annotations

import random

from ale.contracts.corridor_plan import (
    BandPlan,
    BlockPlan,
    CorridorPlan,
    FingerBay,
    PiecePlan,
    RoomBay,
)
from ale.program.models import PreparedInput

Bay = RoomBay | FingerBay


def random_plan(prepared: PreparedInput, rng: random.Random, max_bands: int = 3) -> CorridorPlan:
    """A random one-piece plan (rectangular footprints only)."""
    rooms = [iid for iid, _ in prepared.instances]
    rng.shuffle(rooms)
    n = rng.randint(1, max_bands)
    bays: list[Bay] = []
    i = 0
    while i < len(rooms):
        if rng.random() < 0.2 and i + 1 < len(rooms):
            k = rng.randint(2, 4)
            group = tuple(rooms[i : i + k])
            half = (len(group) + 1) // 2
            bays.append(FingerBay(left=group[:half], right=group[half:]))
            i += len(group)
        else:
            bays.append(RoomBay(room=rooms[i]))
            i += 1
    n_blocks = 2 * n
    cuts = sorted(rng.randint(0, len(bays)) for _ in range(n_blocks - 1))
    edges = [0, *cuts, len(bays)]
    blocks = [BlockPlan(bays=tuple(bays[edges[j] : edges[j + 1]])) for j in range(n_blocks)]
    bands = tuple(BandPlan(block_a=blocks[2 * j], block_b=blocks[2 * j + 1]) for j in range(n))
    return CorridorPlan(pieces=(PiecePlan(bands=bands, connector="none" if n == 1 else "start"),))
