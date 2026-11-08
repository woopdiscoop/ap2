"""Ticket 1.2c eval W09: quality gates on the extract code.

Coverage of ``ale.corpus.extract`` (>= 90 %) is measured by the ``pytest --cov`` run and
recorded in ``eval_report.md``; the static gates are re-run here so a regression shows
up as a failing test too.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from ale.contracts.lock import main as lock_main

REPO_ROOT = Path(__file__).resolve().parents[2]
PATHS = [
    "src/ale/corpus/extract.py",
    "src/ale/cli/commands/layers.py",
    "src/ale/cli/commands/extract.py",
    "tests/corpus_extract",
]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=550,
        check=False,
    )


@pytest.mark.timeout(600)
def test_W09_gates() -> None:
    assert lock_main(["--check"]) == 0
    surface = (REPO_ROOT / "tests" / "cli" / "test_cli_surface.py").read_text("utf-8")
    stub_list = surface.split("STUB_TICKETS", 1)[1].split("}", 1)[0]
    assert '"extract"' not in stub_list and '"layers"' not in stub_list

    if importlib.util.find_spec("ruff") is None:  # pragma: no cover - dev extra installed
        pytest.skip("ruff not installed")
    proc = _run("ruff", "check", *PATHS)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = _run("ruff", "format", "--check", *PATHS)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    if importlib.util.find_spec("mypy") is None:  # pragma: no cover - dev extra installed
        pytest.skip("mypy not installed")
    proc = _run("mypy", *PATHS[:3])
    assert proc.returncode == 0, proc.stdout + proc.stderr
