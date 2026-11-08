"""Fixtures of the Ticket 3.2 tests: prepared P8 / P25 / P60 inputs and the test rulebook."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAM_TESTS = Path(__file__).resolve().parent.parent / "program"
if str(_PROGRAM_TESTS) not in sys.path:
    sys.path.insert(0, str(_PROGRAM_TESTS))

from topology_helpers import load_test_rulebook, prepare  # noqa: E402

from ale.contracts.models import Program, Rulebook, SiteSpec  # noqa: E402
from ale.program.models import PreparedInput  # noqa: E402


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
def prep_25_j1(tmp_path_factory: pytest.TempPathFactory, program_25: Program) -> PreparedInput:
    """P25 on a 30 x 24 m L (12 x 6 m notch top right): a J1 footprint."""
    site = SiteSpec.model_validate(
        {
            "footprint": {
                "exterior": [[0, 0], [30, 0], [30, 18], [18, 18], [18, 24], [0, 24]],
                "holes": [],
            },
            "north_angle_deg": 0.0,
            "access_edge": 0,
        }
    )
    return prepare(tmp_path_factory.mktemp("p25j1"), program_25, site)
