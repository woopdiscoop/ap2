"""Test N06 (Ticket G.1): annealing on a U footprint (three pieces, two junctions)."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _sub in ("geometry", "."):
    if str(_TESTS / _sub) not in sys.path:
        sys.path.insert(0, str(_TESTS / _sub))

from g1_shapes import U, p25  # noqa: E402
from geometry_helpers import load_test_rulebook  # noqa: E402

from ale.config import AleConfig  # noqa: E402
from ale.geometry import realize  # noqa: E402
from ale.geometry.checks import check_layout  # noqa: E402
from ale.optimize import anneal  # noqa: E402
from ale.optimize.anneal import hard_count  # noqa: E402
from ale.optimize.moves import MoveContext, propose  # noqa: E402
from ale.topology import seed_plan  # noqa: E402

RULEBOOK = load_test_rulebook()
CFG = AleConfig()
ITERATIONS = 600


@pytest.mark.timeout(300)
def test_N06_anneal() -> None:
    prep = p25(U)
    start = seed_plan(prep, RULEBOOK, CFG, seed=3, max_attempts=40)
    layout0 = start.realization.layout
    assert layout0 is not None and check_layout(layout0, prep, CFG) == ()
    res = anneal(prep, RULEBOOK, CFG, start.plan, seed=6, max_iter=ITERATIONS)
    assert check_layout(res.layout, prep, CFG) == ()
    assert hard_count(res.layout) <= hard_count(layout0)
    assert res.final_hard <= res.initial_hard
    assert res.iterations == ITERATIONS
    # deterministic for the seed
    again = anneal(prep, RULEBOOK, CFG, start.plan, seed=6, max_iter=ITERATIONS)
    assert again.plan == res.plan
    # the annealed plan still has one junction finger per J1 child, named in the plan
    fingers = sorted(
        bay.junction_to
        for piece in res.plan.pieces
        for band in piece.bands
        for block in (band.block_a, band.block_b)
        for bay in block.bays
        if getattr(bay, "junction", False)
    )
    assert fingers == [1, 2]


@pytest.mark.timeout(300)
def test_N06_moves_keep_junction_targets_and_work_across_pieces() -> None:
    """Every proposed plan keeps its junction fingers (``junction_to``) and the moves move
    rooms between pieces (G5) of the footprint."""
    prep = p25(U)
    start = seed_plan(prep, RULEBOOK, CFG, seed=3, max_attempts=40)
    ctx = MoveContext.from_prepared(prep)
    rng = random.Random(1)
    pieces_touched: set[int] = set()
    proposals = 0
    for _ in range(400):
        name, cand = propose(start.plan, ctx, rng)
        if cand is None:
            continue
        proposals += 1
        fingers = sorted(
            bay.junction_to
            for piece in cand.pieces
            for band in piece.bands
            for block in (band.block_a, band.block_b)
            for bay in block.bays
            if getattr(bay, "junction", False)
        )
        assert fingers == [1, 2], name
        if name.startswith("G5"):
            old = start.plan.room_ids()
            moved = [
                r for r in cand.room_ids() if cand.locate(r).piece != start.plan.locate(r).piece
            ]
            pieces_touched.update(cand.locate(r).piece for r in moved)
            assert sorted(old) == sorted(cand.room_ids())
        real = realize(prep, cand, RULEBOOK, CFG)
        assert real.layout is None or check_layout(real.layout, prep, CFG) == ()
    assert proposals > 100
    assert pieces_touched, "no G5 move changed a room's piece"
