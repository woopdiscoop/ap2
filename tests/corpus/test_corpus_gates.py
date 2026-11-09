"""Ticket 1.1 eval C16: quality gates on the corpus code.

Coverage of ``ale.corpus`` (>= 90 % line) is measured by the CI ``pytest --cov=ale`` run
and recorded in ``eval_report.md``; the static gates are re-run here so a regression
shows up as a failing test too.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ale.contracts.lock import main as lock_main

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATHS = [
    "src/ale/corpus",
    "src/ale/cli/commands/ingest.py",
    "src/ale/cli/commands/status.py",
    "tests/corpus",
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
def test_C16_gates() -> None:
    assert lock_main(["--check"]) == 0

    ci = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    runs = [step.get("run", "") for job in ci["jobs"].values() for step in job["steps"]]
    assert any('pip install -e ".[dev,excel,cad,pdf,raster]"' in r.splitlines() for r in runs)

    if importlib.util.find_spec("ruff") is None:  # pragma: no cover - dev extra installed
        pytest.skip("ruff not installed")
    proc = _run("ruff", "check", *CORPUS_PATHS)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = _run("ruff", "format", "--check", *CORPUS_PATHS)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    if importlib.util.find_spec("mypy") is None:  # pragma: no cover - dev extra installed
        pytest.skip("mypy not installed")
    proc = _run("mypy", "src/ale/corpus", "src/ale/cli/commands/ingest.py")
    assert proc.returncode == 0, proc.stdout + proc.stderr
