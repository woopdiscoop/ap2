"""Ticket 3.4 eval O03-O06: simulated annealing."""

from __future__ import annotations

import importlib
import math
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import pytest
from optimize_helpers import optimizer_config

from ale.contracts.models import Rulebook
from ale.geometry import check_layout, realize
from ale.optimize import HARD_CODES, anneal
from ale.optimize.anneal import (
    Scorer,
    accept_move,
    hard_count,
    hard_rooms,
    initial_temperature,
    metropolis_accept,
    temperature_at,
)
from ale.program.models import PreparedInput
from ale.topology import SeedResult

TESTS = Path(__file__).resolve().parent.parent
# ``ale.optimize.anneal`` the module (the package attribute is the function).
anneal_mod = importlib.import_module("ale.optimize.anneal")
Seeded = dict[str, tuple[PreparedInput, SeedResult]]


def test_hard_codes() -> None:
    assert {
        "AREA_UNDER",
        "AREA_OVER",
        "ASPECT",
        "MIN_WIDTH",
        "NO_FACADE",
        "REQUIRED_ADJ",
        "AVOID_ADJ",
        "NO_CIRCULATION_ACCESS",
    } == HARD_CODES


# ------------------------------------------------------------------------------ O03
#: Annealing seed of O03/O05 (the start plans are the seed-3 plans of ``conftest.seeded``).
ANNEAL_SEED = 6


@pytest.mark.slow
@pytest.mark.timeout(120)
@pytest.mark.parametrize("name", ["P8", "P25", "P60"])
def test_O03_improves(name: str, seeded: Seeded, rulebook: Rulebook) -> None:
    prep, start = seeded[name]
    cfg = optimizer_config(time_budget_s=15.0)
    layout0 = start.realization.layout
    assert layout0 is not None
    start_score = (hard_count(layout0), layout0.metrics.total_cost)
    res = anneal(prep, rulebook, cfg, start.plan, seed=ANNEAL_SEED)
    print(
        f"{name}: hard {res.initial_hard} -> {res.final_hard}, cost {res.initial_cost:.3f} -> "
        f"{res.final_cost:.3f}, {res.iterations} it, {res.iterations / res.elapsed_s:.0f} it/s, "
        f"{res.stopped_by}, {res.elapsed_s:.1f} s"
    )
    assert (res.initial_hard, res.initial_cost) == start_score
    # Q.1: the P8 seed-3 start's 6 hard violations were all AREA_OVER / ASPECT, which
    # realisation no longer emits: it now starts (and ends) at 0 hard.
    assert start_score[0] > 0 or name == "P8"
    # The (lexicographic) energy never increases from start to best.
    assert (res.final_hard, res.final_cost) <= start_score
    assert res.final_hard <= res.initial_hard
    assert res.final_cost == pytest.approx(res.layout.metrics.total_cost)
    assert hard_count(res.layout) == res.final_hard
    assert check_layout(res.layout, prep, cfg) == ()
    again = realize(prep, res.plan, rulebook, cfg, seed=ANNEAL_SEED)
    assert again.layout is not None
    assert again.layout.metrics.total_cost == pytest.approx(res.final_cost)
    if name == "P25":
        assert res.final_hard < res.initial_hard
    if name == "P8":
        assert res.final_hard <= 1


# ------------------------------------------------------------------------------ O04
_SCRIPT = """
import sys
sys.path[:0] = [{tests!r}, {opt!r}]
from pathlib import Path
from fixtures import load_program, load_site
from optimize_helpers import load_test_rulebook, optimizer_config, prepare
from ale.contracts.serialization import canonical_json
from ale.optimize import anneal
from ale.topology import seed_plan
prep = prepare(Path(sys.argv[1]), load_program("program_08"), load_site("site_rect_small"))
cfg = optimizer_config(max_iter=500)
rb = load_test_rulebook()
start = seed_plan(prep, rb, cfg, seed=3)
res = anneal(prep, rb, cfg, start.plan, seed=11)
sys.stdout.write(canonical_json(res.plan).decode() + "\\n")
sys.stdout.write(f"{{res.iterations}} {{res.accepted}} {{res.stopped_by}} {{res.final_cost!r}}\\n")
"""


@pytest.mark.timeout(120)
def test_O04_deterministic(tmp_path: Path) -> None:
    script = _SCRIPT.format(tests=str(TESTS), opt=str(TESTS / "optimize"))
    outs = []
    for k in range(2):
        proc = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path / f"run{k}")],
            capture_output=True,
            text=True,
            timeout=110,
            env={**os.environ, "PYTHONHASHSEED": str(k)},
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        outs.append(proc.stdout)
    assert outs[0] == outs[1]
    assert outs[0].splitlines()[-1].split()[2] in ("max_iter", "converged")


# ------------------------------------------------------------------------------ O05
@pytest.mark.slow
@pytest.mark.timeout(120)
def test_O05_budget(seeded: Seeded, rulebook: Rulebook) -> None:
    prep, start = seeded["P60"]
    cfg = optimizer_config(time_budget_s=30.0)
    t0 = time.monotonic()
    res = anneal(prep, rulebook, cfg, start.plan, seed=ANNEAL_SEED)
    wall = time.monotonic() - t0
    print(f"P60: stopped_by={res.stopped_by} after {res.iterations} it, {wall:.1f} s")
    assert wall <= 31.0
    assert res.elapsed_s <= 31.0
    assert res.stopped_by in ("time_budget", "converged", "max_iter")


# ------------------------------------------------------------------------------ O06
@pytest.mark.parametrize(("delta", "temperature"), [(1.0, 2.0), (3.0, 1.5), (0.2, 0.1)])
def test_O06_metropolis(delta: float, temperature: float) -> None:
    def stub_energy(state: int) -> float:
        return delta * state  # state 1 is uphill of state 0 by delta

    rng = random.Random(5)
    n = 10_000
    hits = sum(
        metropolis_accept(stub_energy(1) - stub_energy(0), temperature, rng) for _ in range(n)
    )
    p = math.exp(-delta / temperature)
    sigma = math.sqrt(n * p * (1 - p))
    assert abs(hits - n * p) <= 3 * sigma


def test_O06_lexicographic_acceptance() -> None:
    rng = random.Random(9)
    n = 10_000
    assert all(accept_move(-1, 1e9, 1e-9, 1e-9, rng) for _ in range(100))  # fewer hard
    # More hard by 2 at T_h = 1.5: exp(-2 / 1.5), whatever the cost change.
    hits = sum(accept_move(2, -100.0, 1.5, 1e9, rng) for _ in range(n))
    p = math.exp(-2 / 1.5)
    assert abs(hits - n * p) <= 3 * math.sqrt(n * p * (1 - p))
    # Equal hard: Metropolis on cost with T_c.
    hits = sum(accept_move(0, 0.3, 1e9, 0.5, rng) for _ in range(n))
    p = math.exp(-0.3 / 0.5)
    assert abs(hits - n * p) <= 3 * math.sqrt(n * p * (1 - p))
    assert accept_move(0, -0.1, 0.0, 0.0, rng)


def test_temperature_schedule() -> None:
    assert temperature_at(0.5, 0.0) == pytest.approx(0.5)
    assert temperature_at(0.5, 1.0) == pytest.approx(0.5e-3)
    assert temperature_at(2.0, 0.5) == pytest.approx(2.0 * math.sqrt(1e-3))
    assert temperature_at(2.0, 7.0) == pytest.approx(2e-3)  # clamped
    assert temperature_at(2.0, -1.0) == pytest.approx(2.0)


# ------------------------------------------------------------------------------ O11
def _measuring_coverage() -> bool:
    """Whether coverage.py is recording this run (its tracing slows Python down ~3x)."""
    cov = sys.modules.get("coverage")
    return cov is not None and cov.Coverage.current() is not None


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="throughput gated on Linux")
@pytest.mark.skipif(_measuring_coverage(), reason="throughput is not measured under coverage")
@pytest.mark.timeout(120)
def test_O11_throughput(
    seeded: Seeded, rulebook: Rulebook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(anneal_mod, "CONVERGED_SPAN", 2.0)  # measure over the full 5 s
    prep, start = seeded["P25"]
    res = anneal(prep, rulebook, optimizer_config(time_budget_s=5.0), start.plan, seed=1)
    rate = res.iterations / res.elapsed_s
    print(f"P25: {res.iterations} it in {res.elapsed_s:.2f} s = {rate:.1f} it/s ({res.stopped_by})")
    assert rate >= 30.0


def test_metropolis_edges() -> None:
    rng = random.Random(0)
    assert metropolis_accept(0.0, 1.0, rng)
    assert metropolis_accept(-5.0, 0.0, rng)
    assert not metropolis_accept(math.inf, 1e9, rng)
    assert not metropolis_accept(math.nan, 1.0, rng)
    assert not metropolis_accept(1.0, 0.0, rng)


def test_initial_temperature_median_rule() -> None:
    t0 = initial_temperature([1.0, 2.0, 3.0, math.inf, -1.0], 0.8)
    assert math.exp(-2.0 / t0) == pytest.approx(0.8)
    assert initial_temperature([], 0.8) == 1.0
    assert initial_temperature([0.0, math.inf], 0.5) == 1.0
    assert math.isfinite(initial_temperature([1.0], 1.0))
    assert initial_temperature([1.0], 0.0) > 0.0


# ------------------------------------------------------------------- other behaviour
def test_stop_by_max_iter(
    seeded: Seeded, rulebook: Rulebook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(anneal_mod, "CONVERGED_SPAN", 2.0)  # never converge
    prep, start = seeded["P8"]
    res = anneal(prep, rulebook, optimizer_config(max_iter=5), start.plan, seed=1)
    assert res.stopped_by == "max_iter"
    assert res.iterations == 5
    assert res.final_hard <= res.initial_hard


def test_stop_by_convergence(seeded: Seeded, rulebook: Rulebook) -> None:
    prep, start = seeded["P8"]
    res = anneal(prep, rulebook, optimizer_config(max_iter=20_000), start.plan, seed=1)
    assert res.stopped_by == "converged"
    assert res.iterations < 20_000


def test_stop_by_time(seeded: Seeded, rulebook: Rulebook, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(anneal_mod, "CONVERGED_SPAN", 2.0)  # never converge
    prep, start = seeded["P25"]
    res = anneal(prep, rulebook, optimizer_config(time_budget_s=0.5), start.plan, seed=1)
    assert res.stopped_by == "time_budget"
    assert res.elapsed_s < 2.0


def test_start_must_realise(seeded: Seeded, rulebook: Rulebook) -> None:
    prep, start = seeded["P8"]
    piece = start.plan.pieces[0]
    band = piece.bands[0]
    # Every bay in block A, block B empty: the block overflows.
    bays = tuple(b for bd in piece.bands for blk in (bd.block_a, bd.block_b) for b in blk.bays)
    crowded = start.plan.model_copy(
        update={
            "pieces": (
                piece.model_copy(
                    update={
                        "bands": (
                            band.model_copy(
                                update={
                                    "block_a": band.block_a.model_copy(update={"bays": bays}),
                                    "block_b": band.block_b.model_copy(update={"bays": ()}),
                                }
                            ),
                        ),
                        "connector": "none",
                    }
                ),
            )
        }
    )
    cfg = optimizer_config()
    assert realize(prep, crowded, rulebook, cfg).layout is None
    assert Scorer(prep, rulebook, cfg, seed=0)(crowded)[1] == math.inf
    with pytest.raises(ValueError, match="does not realise"):
        anneal(prep, rulebook, cfg, crowded, seed=0)


def test_hard_rooms(seeded: Seeded) -> None:
    _, start = seeded["P8"]
    layout = start.realization.layout
    assert layout is not None
    rooms = hard_rooms(layout)
    assert rooms
    assert rooms <= {iid for v in layout.metrics.violations for iid in v.instance_ids}
