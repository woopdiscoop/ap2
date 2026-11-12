"""Tests B204 and B206 (Ticket M.2b): ``ale stack --plans`` on the loaded M.1 bar."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import bar_case as bc
import pytest
from typer.testing import CliRunner

from ale.cli import app

BUDGET = 10.0


@pytest.fixture(scope="module")
def cli_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, Path, float]:
    d = tmp_path_factory.mktemp("m2b_cli")
    prog, bld, rules, rb = bc.write_inputs(d / "in")
    out = d / "out"
    t0 = time.monotonic()
    res = CliRunner().invoke(
        app,
        [
            "stack",
            "--program",
            str(prog),
            "--building",
            str(bld),
            "--rules",
            str(rules),
            "--out",
            str(out),
            "--plans",
            "--rulebook",
            str(rb),
            "--budget",
            str(BUDGET),
        ],
    )
    return res, out, time.monotonic() - t0


@pytest.mark.slow
@pytest.mark.timeout(400)
def test_B204_four_floors_planned_vertical_ok(cli_run: tuple[Any, Path, float]) -> None:
    res, out, _ = cli_run
    for level in range(4):
        assert (out / f"floor_{level:02d}" / "plan" / "layout.json").is_file(), (level, res.output)
    text = (out / "plans.md").read_text(encoding="utf-8")
    assert "Niveau" in text or "niveau" in text
    assert "échec" not in text.lower()


@pytest.mark.slow
@pytest.mark.timeout(400)
def test_B206_plans_time(cli_run: tuple[Any, Path, float]) -> None:
    assert cli_run[2] <= 90.0
