"""Ticket Q.3 eval Q311: ``seed_plan`` keeps its time budget, also under coverage.

Every post-processing step of the seeder (extra attempts, repair, adjacency swaps, façade
pull, ``"inner"`` trials) starts only while the time left covers it, and the run works to a
deadline ``min(1 s, 10 %)`` before the budget, so ``elapsed_s <= time_budget_s``.
"""

from __future__ import annotations

import time

import pytest

from ale.config import AleConfig
from ale.contracts.models import Rulebook
from ale.geometry import check_layout
from ale.program.models import PreparedInput
from ale.topology import seed_plan

CONFIG = AleConfig()


@pytest.mark.timeout(120)
@pytest.mark.parametrize("seed", [1, 3])
def test_Q311_short_budget_P60(seed: int, prep_60: PreparedInput, rulebook: Rulebook) -> None:
    t0 = time.monotonic()
    result = seed_plan(prep_60, rulebook, CONFIG, seed=seed, time_budget_s=3.0)
    wall = time.monotonic() - t0
    print(f"P60 seed {seed}: {result.elapsed_s:.2f} s, {result.attempts} attempt(s)")
    assert result.elapsed_s <= 3.0
    assert wall <= 3.0 + 0.1  # the result is built right after ``elapsed_s`` is read
    assert result.attempts >= 1
    if result.realization.layout is not None:
        assert check_layout(result.realization.layout, prep_60, CONFIG) == ()


@pytest.mark.timeout(120)
def test_Q311_budget_P25(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    # Seed 5 needs a restart (about 2 s, 3-4x more under coverage): the budget binds.
    result = seed_plan(prep_25, rulebook, CONFIG, seed=5, time_budget_s=2.0)
    assert result.elapsed_s <= 2.0
    assert result.attempts >= 1
