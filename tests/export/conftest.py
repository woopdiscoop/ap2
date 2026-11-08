"""Fixtures of the Ticket 3.5 tests: a ``PreparedInput`` (P8 / site_rect_small) and a
hand-built valid tiling ``Layout`` of the 10 x 10 m footprint."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAM_TESTS = Path(__file__).resolve().parent.parent / "program"
if str(_PROGRAM_TESTS) not in sys.path:
    sys.path.insert(0, str(_PROGRAM_TESTS))

from export_helpers import make_layout, prepare  # noqa: E402

from ale.contracts.models import Layout, Program, SiteSpec  # noqa: E402
from ale.program.models import PreparedInput  # noqa: E402


@pytest.fixture(scope="session")
def prepared(
    tmp_path_factory: pytest.TempPathFactory, program_8: Program, site_rect_small: SiteSpec
) -> PreparedInput:
    return prepare(tmp_path_factory.mktemp("prep"), program_8, site_rect_small)


@pytest.fixture(scope="session")
def layout() -> Layout:
    return make_layout()
