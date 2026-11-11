"""Ticket R.9 eval R9-07 (spring vs cells table and adoption verdict), R9-08 (the Q.4 D05
target with the cell seeder) and R9-09 (gates)."""

from __future__ import annotations

import importlib.util
import os
import re
import statistics
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest
from cellgrow_helpers import arep_config, arep_prepared
from optimize_helpers import ANNEAL_ITER, ANNEAL_SEED, SEED_ATTEMPTS

from ale.config import AleConfig
from ale.contracts.lock import main as lock_main
from ale.contracts.models import Rulebook
from ale.geometry import check_layout
from ale.optimize import anneal
from ale.program.models import PreparedInput
from ale.topology import seed_plan

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REPORT = REPO_ROOT / "specs" / "tickets" / "R.9_voronoi-seeding" / "eval_report.md"
BEGIN, END = "<!-- R9-07:begin -->", "<!-- R9-07:end -->"
SEEDS = (1, 2, 3, 4, 5)
AREP_ITER = 1500
Seeder = Literal["spring", "cells"]
CASES = ("P25", "P60", "AREP hard", "AREP soft")


@dataclass(frozen=True)
class Outcome:
    hard: int
    no_facade: int
    required_adj: int
    facade_depth: int
    cost: float
    start_hard: int


class Runner:
    """Seed-then-anneal runs with the deterministic budgets of Q.3 (attempt and iteration
    budgets, never wall clock); results are cached so R9-08 reuses the table's run."""

    def __init__(
        self, prep_25: PreparedInput, prep_60: PreparedInput, arep: PreparedInput, rb: Rulebook
    ) -> None:
        self.rb = rb
        self.cases: dict[str, tuple[PreparedInput, AleConfig, int]] = {
            "P25": (prep_25, AleConfig(), ANNEAL_ITER["P25"]),
            "P60": (prep_60, AleConfig(), ANNEAL_ITER["P60"]),
            "AREP hard": (arep, arep_config(), AREP_ITER),
            "AREP soft": (arep, arep_config(hard=False), AREP_ITER),
        }
        self.cache: dict[tuple[str, Seeder, int], Outcome] = {}

    def run(self, case: str, seeder: Seeder, seed: int) -> Outcome:
        key = (case, seeder, seed)
        if key not in self.cache:
            prep, cfg, iters = self.cases[case]
            start = seed_plan(
                prep, self.rb, cfg, seed=seed, max_attempts=SEED_ATTEMPTS, seeder=seeder
            )
            assert start.realization.layout is not None, start.realization.failures
            res = anneal(prep, self.rb, cfg, start.plan, seed=ANNEAL_SEED, max_iter=iters)
            assert check_layout(res.layout, prep, cfg) == ()
            codes = Counter(v.code for v in res.layout.metrics.violations)
            out = Outcome(
                hard=res.final_hard,
                no_facade=codes["NO_FACADE"],
                required_adj=codes["REQUIRED_ADJ"],
                facade_depth=codes["FACADE_DEPTH"],
                cost=res.final_cost,
                start_hard=res.initial_hard,
            )
            print(f"{case} {seeder} seed {seed}: {out}", flush=True)
            self.cache[key] = out
        return self.cache[key]


@pytest.fixture(scope="module")
def runner(
    tmp_path_factory: pytest.TempPathFactory,
    prep_25: PreparedInput,
    prep_60: PreparedInput,
    rulebook: Rulebook,
) -> Runner:
    arep = arep_prepared(tmp_path_factory.mktemp("arep_cmp"))
    return Runner(prep_25, prep_60, arep, rulebook)


def _mean(values: list[float]) -> float:
    return statistics.fmean(values)


def _table(runner: Runner) -> tuple[str, bool, list[str]]:
    """The markdown table, the adoption verdict and its reasons."""
    rows = [
        "| case | seeder | final hard (per seed 1-5) | mean hard | mean NO_FACADE "
        "| mean REQUIRED_ADJ | mean cost |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    mean_hard: dict[tuple[str, Seeder], float] = {}
    for case in CASES:
        for seeder in ("spring", "cells"):
            outs = [runner.run(case, seeder, s) for s in SEEDS]
            mean_hard[(case, seeder)] = _mean([o.hard for o in outs])
            rows.append(
                f"| {case} | {seeder} | {', '.join(str(o.hard) for o in outs)} "
                f"| {mean_hard[(case, seeder)]:.1f} "
                f"| {_mean([o.no_facade for o in outs]):.1f} "
                f"| {_mean([o.required_adj for o in outs]):.1f} "
                f"| {_mean([o.cost for o in outs]):.1f} |"
            )

    def lower(case: str) -> bool:
        return mean_hard[(case, "cells")] < mean_hard[(case, "spring")]

    reasons = [
        f"P60 lower: {lower('P60')}",
        f"AREP hard lower: {lower('AREP hard')}",
        f"AREP soft lower: {lower('AREP soft')}",
        f"P25 not higher: {mean_hard[('P25', 'cells')] <= mean_hard[('P25', 'spring')]}",
    ]
    adopt = (
        lower("P60")
        and lower("AREP hard")
        and lower("AREP soft")
        and mean_hard[("P25", "cells")] <= mean_hard[("P25", "spring")]
    )
    return "\n".join(rows), adopt, reasons


# ------------------------------------------------------------------------------ R9-07
@pytest.mark.slow
@pytest.mark.timeout(14400)
def test_R9_07_comparison(runner: Runner) -> None:
    table, adopt, reasons = _table(runner)
    verdict = "ADOPT `cells` as the default" if adopt else "DO NOT ADOPT (keep `spring`)"
    block = f"{BEGIN}\n{table}\n\nVerdict: **{verdict}** ({'; '.join(reasons)}).\n{END}"
    text = REPORT.read_text(encoding="utf-8") if REPORT.exists() else "# R.9 eval report\n\n"
    if BEGIN in text and END in text:
        text = re.sub(re.escape(BEGIN) + ".*?" + re.escape(END), lambda _: block, text, flags=re.S)
    else:
        text += f"\n## Comparison table (R9-07)\n\n{block}\n"
    REPORT.write_text(text, encoding="utf-8")
    print(table)
    print(f"verdict: adopt={adopt} {reasons}")
    # the table is complete: 4 cases x 2 seeders x 5 seeds, same budgets
    assert len(runner.cache) >= len(CASES) * 2 * len(SEEDS)
    assert "adopt" in verdict.lower() or "keep" in verdict.lower()


# ------------------------------------------------------------------------------ R9-08
@pytest.mark.slow
@pytest.mark.timeout(1800)
def test_R9_08_D05_target(runner: Runner) -> None:
    """Q.4 D05 as originally written: AREP top floor, hard depth mode, ``cells`` seeder
    (seed 3, annealing seed 6, 1500 iterations): NO_FACADE <= 1 and FACADE_DEPTH = 0."""
    out = runner.run("AREP hard", "cells", 3)
    print(f"R9-08: {out}")
    assert out.no_facade <= 1
    assert out.facade_depth == 0


# ------------------------------------------------------------------------------ R9-09
NEW_SRC = [
    "src/ale/topology/cellgrow.py",
    "src/ale/topology/fromdiagram.py",
    "src/ale/export/diagram.py",
]


def _run(*args: str, timeout: int = 1500) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env={k: v for k, v in os.environ.items() if not k.startswith("COV_CORE")},
    )


@pytest.mark.timeout(2000)
def test_R9_09_gates() -> None:
    assert lock_main(["--check"]) == 0
    paths = [
        "src/ale/topology",
        "src/ale/export/diagram.py",
        "tests/topology",
        "tests/export/test_export_diagram.py",
    ]
    if importlib.util.find_spec("ruff") is None:  # pragma: no cover - dev extra installed
        pytest.skip("ruff not installed")
    proc = _run("ruff", "check", *paths)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = _run("ruff", "format", "--check", *paths)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    if importlib.util.find_spec("mypy") is None:  # pragma: no cover - dev extra installed
        pytest.skip("mypy not installed")
    proc = _run("mypy", "src/ale/topology", "src/ale/export/diagram.py")
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.timeout(2000)
def test_R9_09_coverage(tmp_path: Path) -> None:
    """The new modules are covered at 90 % or more by their own fast tests (path-form)."""
    if importlib.util.find_spec("coverage") is None:  # pragma: no cover - dev extra
        pytest.skip("coverage not installed")
    data = tmp_path / ".cov"
    env_args = [f"--data-file={data}"]
    proc = _run(
        "coverage",
        "run",
        *env_args,
        "--include=" + ",".join(str(REPO_ROOT / p) for p in NEW_SRC),
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "-m",
        "not slow",
        "-k",
        "not R9_09",
        "tests/topology/test_cellgrow.py",
        "tests/export/test_export_diagram.py",
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-2000:]
    rep = _run(
        "coverage",
        "report",
        *env_args,
        "--include=" + ",".join(str(REPO_ROOT / p) for p in NEW_SRC),
        "--fail-under=90",
    )
    print(rep.stdout)
    assert rep.returncode == 0, rep.stdout + rep.stderr
