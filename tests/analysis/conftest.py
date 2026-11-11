"""Fixtures of the Ticket R.3 tests: the export fixture input (P8 / site_rect_small) and the
seed-3 plans of P8 / P25 / P60 (same recipe as the 3.4 optimiser tests)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _sub in ("program", "export", "optimize"):
    if str(_TESTS / _sub) not in sys.path:
        sys.path.insert(0, str(_TESTS / _sub))

from export_helpers import prepare as prepare_export  # noqa: E402
from optimize_helpers import SEED_ATTEMPTS, load_test_rulebook  # noqa: E402
from optimize_helpers import prepare as prepare_optimize  # noqa: E402

from ale.config import AleConfig  # noqa: E402
from ale.contracts.models import Layout, Program, SiteSpec  # noqa: E402
from ale.program.models import PreparedInput  # noqa: E402
from ale.topology import seed_plan  # noqa: E402


@pytest.fixture(scope="session")
def prepared(
    tmp_path_factory: pytest.TempPathFactory, program_8: Program, site_rect_small: SiteSpec
) -> PreparedInput:
    return prepare_export(tmp_path_factory.mktemp("prep"), program_8, site_rect_small)


@pytest.fixture(scope="session")
def seeded_layouts(
    tmp_path_factory: pytest.TempPathFactory,
    program_8: Program,
    program_25: Program,
    program_60: Program,
    site_rect_small: SiteSpec,
    site_rect: SiteSpec,
    site_l: SiteSpec,
) -> dict[str, tuple[PreparedInput, Layout]]:
    rulebook = load_test_rulebook()
    out: dict[str, tuple[PreparedInput, Layout]] = {}
    for name, prog, site in (
        ("P8", program_8, site_rect_small),
        ("P25", program_25, site_rect),
        ("P60", program_60, site_l),
    ):
        prep = prepare_optimize(tmp_path_factory.mktemp(name), prog, site)
        res = seed_plan(prep, rulebook, AleConfig(), seed=3, max_attempts=SEED_ATTEMPTS)
        assert res.realization.layout is not None, name
        out[name] = (prep, res.realization.layout)
    return out
