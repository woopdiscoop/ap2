"""Fixtures of the Ticket M.4 tests: the cases A, B, C planned bay-first, once per session."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import bay_cases as bc  # noqa: E402
from bay_cases import CaseRun  # noqa: E402


@pytest.fixture(scope="session")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, CaseRun]:
    out: dict[str, CaseRun] = {}
    for name in "ABC":
        d = tmp_path_factory.mktemp(f"m4_{name}")
        pr, used, rb, prog = bc.run_case(name, d)
        out[name] = CaseRun(name, pr, used, rb, prog, d)
    return out
