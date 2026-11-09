"""Ticket Q.2 §2.2: façade-aware seeding (inner connector trial, façade pull, best of a few
valid attempts)."""

from __future__ import annotations

from collections import Counter

import pytest

import ale.topology.seed as seed_mod
from ale.config import AleConfig
from ale.contracts.corridor_plan import (
    BandPlan,
    BlockPlan,
    ConnectorBay,
    CorridorPlan,
    PiecePlan,
    RoomBay,
)
from ale.contracts.footprint import decompose_footprint
from ale.contracts.models import Rulebook
from ale.geometry import check_layout, realize
from ale.program.models import PreparedInput
from ale.topology import seed_plan
from ale.topology.seed import (
    HARD_CODES,
    _cut_side_required,
    _marker_at,
    _rank,
    _Search,
    _try_inner,
    with_inner,
)

CONFIG = AleConfig()


def _search(prepared: PreparedInput, rulebook: Rulebook, seed: int = 3) -> _Search:
    fp = decompose_footprint(prepared.footprint.polygon)
    return _Search(prepared, rulebook, CONFIG, fp, seed)


def _no_facade(prepared: PreparedInput, plan: CorridorPlan, rulebook: Rulebook) -> int:
    real = realize(prepared, plan, rulebook, CONFIG)
    assert real.layout is not None
    return sum(1 for v in real.layout.metrics.violations if v.code == "NO_FACADE")


def _two_band_p25() -> CorridorPlan:
    """A compliant 2-band plan of program_25 on site_rect (as in the Q.1 geometry tests)."""
    offices = [f"B01#{i:02d}" for i in range(1, 11)]

    def blk(*ids: str) -> BlockPlan:
        return BlockPlan(bays=tuple(RoomBay(room=r) for r in ids))

    b0 = BandPlan(block_a=blk("B02", "H01", "M01#1", "M01#2"), block_b=blk("V01", *offices[:6]))
    b1 = BandPlan(
        block_a=blk(*offices[6:], "S01#1", "S02"),
        block_b=blk("H02", "S01#2", "K01", "T02", "T01#1", "T01#2", "T03", "V02"),
    )
    return CorridorPlan(pieces=(PiecePlan(bands=(b0, b1), connector="start"),))


def test_with_inner_markers(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    ctx = _search(prep_25, rulebook).ctx
    plan = _two_band_p25()
    inner = with_inner(plan, [0], ctx)
    assert inner.pieces[0].connector == "inner"
    for band in inner.pieces[0].bands:
        for block in (band.block_a, band.block_b):
            assert sum(isinstance(b, ConnectorBay) for b in block.bays) == 1
    # Same rooms, same order; markers at the capacity midpoint.
    assert inner.room_ids() == plan.room_ids()
    real = realize(prep_25, inner, rulebook, CONFIG)
    if real.layout is not None:
        assert check_layout(real.layout, prep_25, CONFIG) == ()
    assert _marker_at([], ctx) == 0
    assert with_inner(plan, [], ctx) == plan


def test_try_inner_keeps_the_better(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    search = _search(prep_25, rulebook)
    plan = _two_band_p25()
    real = realize(prep_25, plan, rulebook, CONFIG, seed=3)
    assert real.layout is not None
    got_plan, got_real = _try_inner(search, plan, real)
    assert got_real.layout is not None
    assert _rank(got_real) <= _rank(real)
    assert got_plan in (plan, with_inner(plan, [0], search.ctx))


def test_cut_side_required(
    prep_25: PreparedInput, prep_60: PreparedInput, rulebook: Rulebook
) -> None:
    res = seed_plan(prep_60, rulebook, CONFIG, seed=3)
    fp60 = decompose_footprint(prep_60.footprint.polygon)
    assert fp60.junction == "J2"
    assert _cut_side_required(fp60, res.plan, 0) is (len(res.plan.pieces[0].bands) >= 2)
    assert _cut_side_required(fp60, res.plan, 1) is (len(res.plan.pieces[0].bands) < 2)
    fp25 = decompose_footprint(prep_25.footprint.polygon)
    assert _cut_side_required(fp25, _two_band_p25(), 0) is False


def test_facade_pull_does_not_hurt(
    prep_60: PreparedInput, rulebook: Rulebook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seeding with the façade pull ends with no more hard violations than without."""
    with_pull = seed_plan(prep_60, rulebook, CONFIG, seed=3)
    assert with_pull.realization.layout is not None
    monkeypatch.setattr(seed_mod, "_improve_facade", lambda s, d, r, t0, b: (d, r))
    without = seed_plan(prep_60, rulebook, CONFIG, seed=3)
    assert without.realization.layout is not None
    assert _rank(with_pull.realization) <= _rank(without.realization)
    lay = with_pull.realization.layout
    counts = Counter(v.code for v in lay.metrics.violations if v.code in HARD_CODES)
    print(f"P60 seed 3: {dict(counts)}")


def test_seed_facade_baseline(prep_60: PreparedInput, rulebook: Rulebook) -> None:
    """Q.2: the seed-3 P60 start has fewer NO_FACADE than before Q.2 (15)."""
    res = seed_plan(prep_60, rulebook, CONFIG, seed=3)
    assert _no_facade(prep_60, res.plan, rulebook) < 15


def test_facade_pull_budget(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    """A spent budget returns the input unchanged."""
    search = _search(prep_25, rulebook)
    res = seed_plan(prep_25, rulebook, CONFIG, seed=3)
    draft = seed_mod.Draft([1], ["none"])
    draft.blocks = {
        (0, 0, "A"): list(res.plan.pieces[0].bands[0].block_a.bays),  # type: ignore[arg-type]
        (0, 0, "B"): list(res.plan.pieces[0].bands[0].block_b.bays),  # type: ignore[arg-type]
    }
    if len(res.plan.pieces[0].bands) != 1:  # pragma: no cover - seed-3 P25 is one band
        pytest.skip("multi-band seed")
    real = res.realization
    assert seed_mod._improve_facade(search, draft, real, 0.0, 1.0) == (draft, real)
