"""Helpers of the Ticket 3.4 tests (written independently of ``ale.optimize``)."""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PROGRAM_TESTS = Path(__file__).resolve().parent.parent / "program"
if str(_PROGRAM_TESTS) not in sys.path:
    sys.path.insert(0, str(_PROGRAM_TESTS))

from program_helpers import (  # noqa: E402
    RULEBOOK_TEST,
    load_test_rulebook,
    program_to_xlsx,
    site_to_yaml,
)

from ale.config import AleConfig  # noqa: E402
from ale.contracts.models import Layout, Program, SiteSpec  # noqa: E402
from ale.optimize import HARD_CODES, AnnealResult  # noqa: E402
from ale.program import prepare_input  # noqa: E402
from ale.program.models import PreparedInput  # noqa: E402
from ale.topology import SeedResult  # noqa: E402

__all__ = [
    "ANNEAL_ITER",
    "ANNEAL_SEED",
    "RULEBOOK_TEST",
    "SEED_ATTEMPTS",
    "QualityRun",
    "hard_codes",
    "load_test_rulebook",
    "optimizer_config",
    "prepare",
    "write_inputs",
]


def write_inputs(tmp: Path, program: Program, site: SiteSpec) -> tuple[Path, Path]:
    """``programme.xlsx`` and ``site.yaml`` of ``program`` / ``site`` written into ``tmp``."""
    tmp.mkdir(parents=True, exist_ok=True)
    return program_to_xlsx(program, tmp / "programme.xlsx"), site_to_yaml(site, tmp / "site.yaml")


def prepare(tmp: Path, program: Program, site: SiteSpec) -> PreparedInput:
    """``prepare_input`` on ``program`` / ``site`` written into ``tmp``."""
    xlsx, yml = write_inputs(tmp, program, site)
    return prepare_input(xlsx, yml, RULEBOOK_TEST, AleConfig())


def optimizer_config(**optimizer: Any) -> AleConfig:
    """``AleConfig()`` with ``[optimizer]`` fields overridden."""
    cfg = AleConfig()
    return cfg.model_copy(update={"optimizer": cfg.optimizer.model_copy(update=optimizer)})


#: Ticket Q.3: attempt budget of the seeded starts (binds before time: same plan on any
#: machine, with or without coverage).
SEED_ATTEMPTS = 50
#: Annealing seed of the quality runs (3.4 O03, Q.2 G804/G805, Q.3 Q301-Q305).
ANNEAL_SEED = 6
#: Ticket Q.3: iteration budgets of the quality runs (each run <= 60 s on one core without
#: coverage; see specs/tickets/Q.3_cache-and-reliability/eval_report.md).
ANNEAL_ITER = {"P8": 1500, "P25": 1500, "P60": 1100}


def hard_codes(layout: Layout) -> dict[str, int]:
    """Hard violations of ``layout`` by code (sorted)."""
    return dict(
        sorted(Counter(v.code for v in layout.metrics.violations if v.code in HARD_CODES).items())
    )


@dataclass(frozen=True)
class QualityRun:
    """A deterministic quality run: the seed-3 start, its annealing and the hard counts."""

    prepared: PreparedInput
    start: SeedResult
    result: AnnealResult
    before: dict[str, int]
    after: dict[str, int]
    seconds: float
