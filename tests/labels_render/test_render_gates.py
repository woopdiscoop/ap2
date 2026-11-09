"""Ticket I.2 V210: quality gates on the I.2 code.

The static gates and ``lock --check`` are re-run here; coverage of ``ale.labels.render``
and of the VLM section of ``ale.corpus.extract`` is measured on the I.2 tests in a
subprocess (path-form ``--cov``). The whole suite is run separately and recorded in
``eval_report.md``.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ale.contracts.lock import main as lock_main

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = [
    "src/ale/labels/render.py",
    "src/ale/corpus/extract.py",
    "src/ale/cli/commands/extract.py",
]
PATHS = [*SRC, "tests/labels_render", "tests/corpus_extract/test_extract_vlm.py"]
I2_TESTS = [
    "tests/labels_render/test_render_eval.py",
    "tests/labels_render/test_render_robust.py",
    "tests/corpus_extract/test_extract_vlm.py",
]
MIN_COVERAGE = 90.0


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=550,
        check=False,
    )


def _vlm_section_lines() -> set[int]:
    """Line numbers of the VLM labelling section of ``extract.py``."""
    lines = (REPO_ROOT / "src/ale/corpus/extract.py").read_text("utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines, 1) if ln.startswith("# --") and "VLM" in ln)
    end = next(i for i, ln in enumerate(lines, 1) if ln.startswith("def _extract_unit("))
    return set(range(start, end))


def _percent(covered: set[int], missing: set[int]) -> float:
    total = len(covered) + len(missing)
    return 100.0 * len(covered) / total if total else 100.0


@pytest.mark.timeout(600)
def test_V210_gates(tmp_path: Path) -> None:
    assert lock_main(["--check"]) == 0

    if importlib.util.find_spec("ruff") is None:  # pragma: no cover - dev extra installed
        pytest.skip("ruff not installed")
    proc = _run("ruff", "check", *PATHS)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = _run("ruff", "format", "--check", *PATHS)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    if importlib.util.find_spec("mypy") is None:  # pragma: no cover - dev extra installed
        pytest.skip("mypy not installed")
    proc = _run("mypy", *SRC)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    if importlib.util.find_spec("pytest_cov") is None:  # pragma: no cover - dev extra
        pytest.skip("pytest-cov not installed")
    report = tmp_path / "cov.json"
    proc = _run(
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--cov=src/ale/labels",
        "--cov=src/ale/corpus",
        f"--cov-report=json:{report}",
        *I2_TESTS,
    )
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
    files = {
        Path(k).as_posix(): v for k, v in json.loads(report.read_text("utf-8"))["files"].items()
    }
    render = next(v for k, v in files.items() if k.endswith("ale/labels/render.py"))
    assert render["summary"]["percent_covered"] >= MIN_COVERAGE, render["summary"]
    extract = next(v for k, v in files.items() if k.endswith("ale/corpus/extract.py"))
    section = _vlm_section_lines()
    covered = set(extract["executed_lines"]) & section
    missing = set(extract["missing_lines"]) & section
    assert _percent(covered, missing) >= MIN_COVERAGE, sorted(missing)
