"""Ticket 3.4 throughput support: the memoised realisation equals ``ale.geometry.realize``."""

from __future__ import annotations

import random

import pytest

from ale.config import AleConfig
from ale.contracts.models import Rulebook
from ale.geometry import realize
from ale.optimize import MoveContext, propose
from ale.optimize.fastreal import RealizeCache
from ale.program.models import PreparedInput
from ale.topology import SeedResult

Seeded = dict[str, tuple[PreparedInput, SeedResult]]


@pytest.mark.timeout(120)
@pytest.mark.parametrize(("name", "count"), [("P8", 120), ("P25", 80), ("P60", 25)])
def test_cached_realize_matches_geometry(
    name: str, count: int, seeded: Seeded, rulebook: Rulebook
) -> None:
    prep, start = seeded[name]
    cfg = AleConfig()
    ctx = MoveContext.from_prepared(prep)
    rng = random.Random(17)
    cache = RealizeCache(prep, cfg)
    plan = start.plan
    checked = failed = 0
    for _ in range(20 * count):
        if checked >= count:
            break
        _, cand = propose(plan, ctx, rng)
        if cand is None:
            continue
        ref = realize(prep, cand, rulebook, cfg, seed=4)
        got = cache.realize(cand, rulebook, seed=4)
        assert got == ref
        checked += 1
        if ref.layout is None:
            failed += 1
        elif rng.random() < 0.5:
            plan = cand
    # The start plan once more, now from a warm cache.
    assert cache.realize(start.plan, rulebook, seed=3) == realize(
        prep, start.plan, rulebook, cfg, seed=3
    )
    assert checked == count
    assert failed < checked


def test_cached_realize_invalid_plan(seeded: Seeded, rulebook: Rulebook) -> None:
    prep, start = seeded["P8"]
    cfg = AleConfig()
    piece = start.plan.pieces[0]
    band = piece.bands[0]
    dropped = band.block_a.model_copy(update={"bays": band.block_a.bays[1:]})
    bad = start.plan.model_copy(
        update={
            "pieces": (
                piece.model_copy(update={"bands": (band.model_copy(update={"block_a": dropped}),)}),
            )
        }
    )
    got = RealizeCache(prep, cfg).realize(bad, rulebook)
    assert got == realize(prep, bad, rulebook, cfg)
    assert got.failures[0].code == "PLAN_INVALID"
