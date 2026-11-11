"""Fixtures of the Ticket M.1 tests: the synthetic bar, its stacking run and CLI inputs."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import stack_case as case  # noqa: E402

from ale.contracts.models import Program  # noqa: E402
from ale.stack import Building, StackResult, StackRules, parse_building, parse_rules, run_stack  # noqa: E402


@pytest.fixture(scope="session")
def program() -> Program:
    return case.program()


@pytest.fixture(scope="session")
def building() -> Building:
    return parse_building(case.building_dict())


@pytest.fixture(scope="session")
def rules() -> StackRules:
    return parse_rules(case.RULES)


@pytest.fixture(scope="session")
def result(program: Program, building: Building, rules: StackRules) -> StackResult:
    return run_stack(program, building, rules)


@pytest.fixture(scope="session")
def inputs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    return case.write_inputs(tmp_path_factory.mktemp("m1_inputs"))
