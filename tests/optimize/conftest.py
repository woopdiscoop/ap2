"""Fixtures of the Ticket 3.4 tests: prepared P8 / P25 / P60 inputs, seeded plans, rulebook."""

from __future__ import annotations

import time

import pytest
from optimize_helpers import (
    ANNEAL_ITER,
    ANNEAL_SEED,
    SEED_ATTEMPTS,
    QualityRun,
    hard_codes,
    load_test_rulebook,
    prepare,
)

from ale.config import AleConfig
from ale.contracts.models import Program, Rulebook, SiteSpec
from ale.optimize import anneal
from ale.program.models import PreparedInput
from ale.topology import SeedResult, seed_plan

#: Seed of the annealing starts (seed-3 starts have hard violations, eval O03).
START_SEED = 3


@pytest.fixture(scope="session")
def rulebook() -> Rulebook:
    return load_test_rulebook()


@pytest.fixture(scope="session")
def prep_8(
    tmp_path_factory: pytest.TempPathFactory, program_8: Program, site_rect_small: SiteSpec
) -> PreparedInput:
    return prepare(tmp_path_factory.mktemp("p8"), program_8, site_rect_small)


@pytest.fixture(scope="session")
def prep_25(
    tmp_path_factory: pytest.TempPathFactory, program_25: Program, site_rect: SiteSpec
) -> PreparedInput:
    return prepare(tmp_path_factory.mktemp("p25"), program_25, site_rect)


@pytest.fixture(scope="session")
def prep_60(
    tmp_path_factory: pytest.TempPathFactory, program_60: Program, site_l: SiteSpec
) -> PreparedInput:
    return prepare(tmp_path_factory.mktemp("p60"), program_60, site_l)


@pytest.fixture(scope="session")
def seeded(
    prep_8: PreparedInput,
    prep_25: PreparedInput,
    prep_60: PreparedInput,
    rulebook: Rulebook,
) -> dict[str, tuple[PreparedInput, SeedResult]]:
    """Seed-3 start plans of the three fixtures, by name ``P8`` / ``P25`` / ``P60``."""
    cfg = AleConfig()
    out: dict[str, tuple[PreparedInput, SeedResult]] = {}
    for name, prep in (("P8", prep_8), ("P25", prep_25), ("P60", prep_60)):
        res = seed_plan(prep, rulebook, cfg, seed=START_SEED, max_attempts=SEED_ATTEMPTS)
        assert res.realization.layout is not None, (name, res.realization.failures)
        out[name] = (prep, res)
    return out


@pytest.fixture(scope="session")
def quality_runs(
    seeded: dict[str, tuple[PreparedInput, SeedResult]], rulebook: Rulebook
) -> dict[str, QualityRun]:
    """Ticket Q.3: the seed-3 starts annealed with seed 6 and :data:`ANNEAL_ITER` iterations
    (identical on any machine, with or without coverage)."""
    cfg = AleConfig()
    out: dict[str, QualityRun] = {}
    for name in ("P8", "P25", "P60"):
        prep, start = seeded[name]
        layout0 = start.realization.layout
        assert layout0 is not None
        t0 = time.monotonic()
        res = anneal(prep, rulebook, cfg, start.plan, seed=ANNEAL_SEED, max_iter=ANNEAL_ITER[name])
        seconds = time.monotonic() - t0
        run = QualityRun(prep, start, res, hard_codes(layout0), hard_codes(res.layout), seconds)
        print(f"{name}: {run.before} -> {run.after} ({res.iterations} it, {seconds:.1f} s)")
        out[name] = run
    return out
