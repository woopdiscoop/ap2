"""Fixtures of the Ticket G.2 tests: the synthetic plot, a 40-parti run and CLI runs."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import parti_case as case  # noqa: E402
from program_helpers import program_to_xlsx  # noqa: E402

from ale.contracts.models import Program, SiteSpec  # noqa: E402
from ale.parti import Dropped, Entry, run_partis  # noqa: E402


@pytest.fixture(scope="session")
def program() -> Program:
    return case.program()


@pytest.fixture(scope="session")
def site() -> SiteSpec:
    return case.site()


@pytest.fixture(scope="session")
def run(program: Program, site: SiteSpec) -> tuple[list[Entry], list[Dropped]]:
    return run_partis(program, site, floors=(3, 5), count=40)


@pytest.fixture(scope="session")
def inputs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    d = tmp_path_factory.mktemp("g2_inputs")
    return program_to_xlsx(case.program(), d / "programme.xlsx"), case.write_site_yaml(
        d / "site.yaml"
    )
