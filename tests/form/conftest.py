"""Fixtures of the Ticket G.3 tests: the synthetic plot, the K = 6 candidates and CLI runs."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAM_TESTS = Path(__file__).resolve().parent.parent / "program"
if str(_PROGRAM_TESTS) not in sys.path:
    sys.path.insert(0, str(_PROGRAM_TESTS))

import case_helpers as case  # noqa: E402
from program_helpers import program_to_xlsx  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from ale.cli import app  # noqa: E402
from ale.cli.commands.form import Candidate, build_candidates  # noqa: E402


@pytest.fixture(scope="session")
def candidates() -> list[Candidate]:
    return build_candidates(case.program(), case.site(), 6)


@pytest.fixture(scope="session")
def court_candidates() -> list[Candidate]:
    return build_candidates(case.program(), case.site(), 6, courtyard=True)


@pytest.fixture(scope="session")
def inputs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """``(programme.xlsx, site.yaml)`` of the test case."""
    d = tmp_path_factory.mktemp("g3_inputs")
    return program_to_xlsx(case.program(), d / "programme.xlsx"), case.write_site_yaml(
        d / "site.yaml"
    )


@pytest.fixture(scope="session")
def cli_out(inputs: tuple[Path, Path], tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Output folder of ``ale form`` with the default K = 6."""
    out = tmp_path_factory.mktemp("g3_out") / "forms"
    result = CliRunner().invoke(
        app, ["form", "--program", str(inputs[0]), "--site", str(inputs[1]), "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    return out
