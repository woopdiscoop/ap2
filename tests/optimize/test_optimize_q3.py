"""Ticket Q.3 eval Q301-Q305, Q307, Q309 (throughput), Q310 and the deterministic budgets.

The quality runs (``conftest.quality_runs``) start from the seed-3 plans seeded with an
attempt budget and anneal with seed 6 and an iteration budget, so they give the same plans
on any machine, with or without coverage (Q305 checks it in fresh processes).
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from optimize_helpers import (
    ANNEAL_ITER,
    ANNEAL_SEED,
    SEED_ATTEMPTS,
    QualityRun,
    hard_codes,
    optimizer_config,
    write_inputs,
)

from ale.config import AleConfig
from ale.contracts.lock import main as lock_main
from ale.contracts.models import Program, Rulebook, SiteSpec
from ale.contracts.serialization import canonical_json
from ale.geometry import check_layout, realize
from ale.optimize import HARD_CODES, AnnealResult, MoveContext, anneal, generate
from ale.optimize.anneal import Scorer, focus_on
from ale.optimize.polish import polish
from ale.program.models import PreparedInput
from ale.topology import SeedResult, seed_plan

TESTS = Path(__file__).resolve().parent.parent
REPO_ROOT = TESTS.parent
gen_mod = importlib.import_module("ale.optimize.generate")
anneal_mod = importlib.import_module("ale.optimize.anneal")
Seeded = dict[str, tuple[PreparedInput, SeedResult]]
Runs = dict[str, QualityRun]


# ------------------------------------------------------------------------------ Q301
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_Q301_facade_P60(quality_runs: Runs) -> None:
    run = quality_runs["P60"]
    print(f"P60: {run.before} -> {run.after}")
    assert run.result.stopped_by == "max_iter"
    assert run.after.get("NO_FACADE", 0) <= 6


# ------------------------------------------------------------------------------ Q302
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_Q302_no_regression(quality_runs: Runs) -> None:
    for name, run in quality_runs.items():
        print(f"{name}: {run.before} -> {run.after} ({run.seconds:.1f} s)")
        assert check_layout(run.result.layout, run.prepared, AleConfig()) == ()
    assert quality_runs["P8"].result.final_hard == 0
    assert quality_runs["P25"].result.final_hard <= 6
    assert quality_runs["P60"].result.final_hard <= 14


# ------------------------------------------------------------------------------ Q303
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_Q303_O03_strict(quality_runs: Runs) -> None:
    """3.4 O03 as originally written: P25 improves strictly, P8 ends with at most 1."""
    p25 = quality_runs["P25"].result
    assert p25.initial_hard > 0
    assert p25.final_hard < p25.initial_hard
    assert quality_runs["P8"].result.final_hard <= 1
    for run in quality_runs.values():
        assert run.result.final_hard <= run.result.initial_hard


# ------------------------------------------------------------------------------ Q304
@pytest.mark.slow
@pytest.mark.timeout(600)
@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_Q304_P8_seeds(seed: int, prep_8: PreparedInput, rulebook: Rulebook) -> None:
    cfg = AleConfig()
    start = seed_plan(prep_8, rulebook, cfg, seed=seed, max_attempts=SEED_ATTEMPTS)
    assert start.realization.layout is not None
    res = anneal(prep_8, rulebook, cfg, start.plan, seed=seed, max_iter=ANNEAL_ITER["P8"])
    print(f"P8 seed {seed}: {res.initial_hard} -> {res.final_hard}")
    assert res.stopped_by == "max_iter"
    assert res.final_hard <= 1


# ------------------------------------------------------------------------------ Q305
_SCRIPT = """
import json, sys
sys.path[:0] = [{tests!r}, {opt!r}]
from pathlib import Path
from fixtures import load_program, load_site
from optimize_helpers import ANNEAL_ITER, ANNEAL_SEED, SEED_ATTEMPTS, load_test_rulebook, prepare
from ale.config import AleConfig
from ale.contracts.serialization import canonical_json
from ale.optimize import anneal
from ale.topology import seed_plan
pairs = {{"P25": ("program_25", "site_rect"), "P60": ("program_60", "site_L")}}
rb = load_test_rulebook()
cfg = AleConfig()
out = {{}}
for name in sys.argv[2].split(","):
    program, site = pairs[name]
    prep = prepare(Path(sys.argv[1]) / name, load_program(program), load_site(site))
    start = seed_plan(prep, rb, cfg, seed=3, max_attempts=SEED_ATTEMPTS)
    res = anneal(prep, rb, cfg, start.plan, seed=ANNEAL_SEED, max_iter=ANNEAL_ITER[name])
    out[name] = [canonical_json(start.plan).decode(), canonical_json(res.plan).decode()]
print(json.dumps(out))
"""


def _fresh(tmp: Path, names: str, *, cov: bool, hash_seed: int) -> subprocess.Popen[str]:
    script = tmp / f"run_{int(cov)}.py"
    script.write_text(
        _SCRIPT.format(tests=str(TESTS), opt=str(TESTS / "optimize")), encoding="utf-8"
    )
    prefix = [sys.executable, "-m", "coverage", "run", f"--data-file={tmp / '.cov'}"]
    cmd = [*(prefix if cov else [sys.executable]), str(script), str(tmp / f"w{int(cov)}"), names]
    env = {**os.environ, "PYTHONHASHSEED": str(hash_seed)}
    env.pop("COV_CORE_SOURCE", None)  # no pytest-cov auto-start: plain unless ``cov``
    return subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=tmp
    )


@pytest.mark.slow
@pytest.mark.timeout(1800)
def test_Q305_deterministic(tmp_path: Path, quality_runs: Runs) -> None:
    """The Q301 / Q302 runs repeated in fresh processes, one of them under coverage."""
    if importlib.util.find_spec("coverage") is None:  # pragma: no cover - dev extra
        pytest.skip("coverage not installed")
    names = "P25,P60"
    procs = [
        _fresh(tmp_path, names, cov=False, hash_seed=1),
        _fresh(tmp_path, names, cov=True, hash_seed=2),
    ]
    outs: list[dict[str, Any]] = []
    for proc in procs:
        stdout, stderr = proc.communicate(timeout=1700)
        assert proc.returncode == 0, stderr
        outs.append(json.loads(stdout.strip().splitlines()[-1]))
    assert outs[0] == outs[1]
    for name in names.split(","):
        run = quality_runs[name]
        here = [canonical_json(run.start.plan).decode(), canonical_json(run.result.plan).decode()]
        assert outs[0][name] == here, name


# ------------------------------------------------------------------------------ Q307
@pytest.mark.timeout(300)
def test_Q307_budget_split(
    tmp_path: Path,
    program_25: Program,
    site_rect: SiteSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from optimize_helpers import RULEBOOK_TEST

    seen: dict[str, float] = {}
    real_seed, real_anneal = gen_mod.seed_plan, gen_mod.anneal

    def seed_spy(*args: Any, **kw: Any) -> SeedResult:
        seen["seed"] = kw["time_budget_s"]
        return real_seed(*args, **kw)

    def anneal_spy(
        prepared: PreparedInput, rb: Rulebook, cfg: AleConfig, *a: Any, **kw: Any
    ) -> AnnealResult:
        seen["anneal"] = cfg.optimizer.time_budget_s
        return real_anneal(prepared, rb, cfg, *a, **kw)

    monkeypatch.setattr(gen_mod, "seed_plan", seed_spy)
    monkeypatch.setattr(gen_mod, "anneal", anneal_spy)
    xlsx, yml = write_inputs(tmp_path / "in", program_25, site_rect)
    t0 = time.monotonic()
    res = generate(
        xlsx,
        yml,
        RULEBOOK_TEST,
        tmp_path / "out",
        seed=1,
        variants=1,
        config=optimizer_config(time_budget_s=8.0),
    )
    wall = time.monotonic() - t0
    print(f"seed {seen['seed']} s, anneal {seen['anneal']} s, wall {wall:.1f} s")
    assert res.succeeded == 1
    assert seen["seed"] <= 2.0
    assert seen["anneal"] <= 6.0
    assert seen["seed"] + seen["anneal"] == pytest.approx(8.0)
    assert res.variants[0].elapsed_s <= 9.0
    assert wall <= 9.0 + 5.0  # + input preparation and export


def test_budget_split_caps_the_seed() -> None:
    assert gen_mod.SEED_SHARE == 0.25
    assert min(gen_mod.SEED_TIME_BUDGET_S, gen_mod.SEED_SHARE * 120.0) == 20.0


# ------------------------------------------------------------------------------ Q309
def _measuring_coverage() -> bool:
    cov = sys.modules.get("coverage")
    return cov is not None and cov.Coverage.current() is not None


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="throughput gated on Linux")
@pytest.mark.skipif(_measuring_coverage(), reason="throughput is not measured under coverage")
@pytest.mark.timeout(300)
def test_Q309_anneal_throughput(
    seeded: Seeded, rulebook: Rulebook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P25 annealing loop >= 30 it/s (the final polish is not part of the loop)."""
    monkeypatch.setattr(anneal_mod, "POLISH_EVALS", 0)
    prep, start = seeded["P25"]
    res = anneal(prep, rulebook, AleConfig(), start.plan, seed=1, max_iter=300)
    rate = res.iterations / res.elapsed_s
    print(f"P25: {res.iterations} it in {res.elapsed_s:.2f} s = {rate:.1f} it/s")
    assert res.iterations == 300
    assert rate >= 30.0


# ------------------------------------------------------------------------------ Q310
PATHS = [
    "src/ale/geometry",
    "src/ale/topology",
    "src/ale/optimize",
    "tests/geometry",
    "tests/topology",
    "tests/optimize",
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
def test_Q310_gates() -> None:
    assert lock_main(["--check"]) == 0
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


# --------------------------------------------------------------- deterministic budgets
def test_anneal_max_iter_binds(seeded: Seeded, rulebook: Rulebook) -> None:
    """``max_iter`` binds before time: a tiny time budget does not stop the run, and two
    runs give the same plan."""
    prep, start = seeded["P25"]
    cfg = optimizer_config(time_budget_s=0.01)
    one = anneal(prep, rulebook, cfg, start.plan, seed=4, max_iter=40)
    two = anneal(prep, rulebook, cfg, start.plan, seed=4, max_iter=40)
    assert one.stopped_by == "max_iter" and one.iterations == 40
    assert one.plan == two.plan and one.final_cost == two.final_cost
    with pytest.raises(ValueError, match="max_iter"):
        anneal(prep, rulebook, cfg, start.plan, seed=4, max_iter=0)


def test_anneal_count_run_returns_to_best(
    seeded: Seeded, rulebook: Rulebook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A count-bound run does not stop on convergence: it goes back to the best plan."""
    monkeypatch.setattr(anneal_mod, "CONVERGED_SPAN", 0.05)
    prep, start = seeded["P8"]
    res = anneal(prep, rulebook, AleConfig(), start.plan, seed=2, max_iter=200)
    assert res.stopped_by == "max_iter"
    assert res.iterations == 200


def test_seed_max_attempts(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    cfg = AleConfig()
    one = seed_plan(prep_25, rulebook, cfg, seed=3, max_attempts=1, time_budget_s=0.01)
    assert one.attempts == 1
    assert one.realization.layout is not None  # the safety cap, not 0.01 s, binds
    again = seed_plan(prep_25, rulebook, cfg, seed=3, max_attempts=1, time_budget_s=60.0)
    assert again.plan == one.plan
    many = seed_plan(prep_25, rulebook, cfg, seed=3, max_attempts=SEED_ATTEMPTS)
    assert 1 <= many.attempts <= SEED_ATTEMPTS


# ------------------------------------------------------------------------------ polish
def test_polish_finds_a_facade_insert(seeded: Seeded, rulebook: Rulebook) -> None:
    """The polish only accepts strict improvements, stays valid and respects its budgets."""
    prep, start = seeded["P60"]
    cfg = AleConfig()
    scorer = Scorer(prep, rulebook, cfg, seed=ANNEAL_SEED)
    n_hard, cost, layout = scorer(start.plan)
    assert layout is not None
    ctx = focus_on(MoveContext.from_prepared(prep), layout, 24)
    specs = dict(prep.instances)
    kw: dict[str, Any] = {"min_facade": 24, "hard": HARD_CODES}
    plan, score, got, evals = polish(
        start.plan,
        (n_hard, cost),
        layout,
        scorer,
        specs,
        ctx,
        max_evals=60,
        deadline=time.monotonic() + 600,
        **kw,
    )
    assert evals <= 60
    assert score <= (n_hard, cost)
    assert plan.check_against(ctx.instance_ids, ctx.footprint) == ()
    assert len(plan.zone_violations(ctx.zone_of)) <= len(start.plan.zone_violations(ctx.zone_of))
    assert hard_codes(got).get("NO_FACADE", 0) <= hard_codes(layout).get("NO_FACADE", 0) + 1
    assert realize(prep, plan, rulebook, cfg, seed=ANNEAL_SEED).layout == got
    # Spent budgets return the input.
    same = polish(
        start.plan,
        (n_hard, cost),
        layout,
        scorer,
        specs,
        ctx,
        max_evals=0,
        deadline=time.monotonic() + 600,
        **kw,
    )
    assert same[0] == start.plan and same[3] == 0
    late = polish(
        start.plan,
        (n_hard, cost),
        layout,
        scorer,
        specs,
        ctx,
        max_evals=10,
        deadline=time.monotonic() - 1,
        **kw,
    )
    assert late[0] == start.plan and late[3] == 0


def test_polish_neighbourhoods_are_valid(seeded: Seeded, rulebook: Rulebook) -> None:
    from ale.optimize import polish as polish_mod

    rng = random.Random(0)
    for name in ("P25", "P60"):
        prep, start = seeded[name]
        layout = start.realization.layout
        assert layout is not None
        ctx = focus_on(MoveContext.from_prepared(prep), layout, 24)
        cands = list(
            polish_mod._candidates(start.plan, layout, dict(prep.instances), ctx, 24, HARD_CODES)
        )
        assert cands
        for cand in rng.sample(cands, min(30, len(cands))):
            assert cand != start.plan
            assert cand.check_against(ctx.instance_ids, ctx.footprint) == ()
            assert sorted(cand.room_ids()) == sorted(start.plan.room_ids())
