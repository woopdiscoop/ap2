"""Ticket 3.2 eval T03-T10: seeded first valid plans."""

from __future__ import annotations

import random
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from random_plans import permuted_plan, random_plan

from ale.config import AleConfig
from ale.contracts.models import Rulebook
from ale.contracts.serialization import canonical_json
from ale.geometry import check_layout, greedy_plan, realize
from ale.program.models import PreparedInput
from ale.topology import SeedResult, seed_plan

CONFIG = AleConfig()
SRC = Path(__file__).resolve().parents[2] / "src"


def _assert_valid(result: SeedResult, prepared: PreparedInput) -> None:
    real = result.realization
    assert real.failures == ()
    assert real.layout is not None
    assert check_layout(real.layout, prepared, CONFIG) == ()
    assert result.attempts >= 1


def test_T03_valid_P8(prep_8: PreparedInput, rulebook: Rulebook) -> None:
    result = seed_plan(prep_8, rulebook, CONFIG, seed=1)
    _assert_valid(result, prep_8)
    assert result.report.n_nodes == 9


def test_T04_valid_P25(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    result = seed_plan(prep_25, rulebook, CONFIG, seed=1)
    _assert_valid(result, prep_25)
    report = result.report
    assert (report.n_nodes, report.n_required, report.n_avoid) == (26, 7, 6)
    assert report.planar is True and report.conflicts == ()


@pytest.mark.timeout(120)
def test_T05_valid_P60(prep_60: PreparedInput, rulebook: Rulebook) -> None:
    result = seed_plan(prep_60, rulebook, CONFIG, seed=1, time_budget_s=20)
    _assert_valid(result, prep_60)
    assert result.elapsed_s <= 20
    assert len(result.plan.pieces) == 2


@pytest.mark.timeout(120)
def test_T06_seeds(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    plans = set()
    for seed in range(1, 6):
        result = seed_plan(prep_25, rulebook, CONFIG, seed=seed)
        _assert_valid(result, prep_25)
        plans.add(canonical_json(result.plan))
    assert len(plans) >= 2


_SCRIPT = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from ale.config import AleConfig
    from ale.contracts.models import Rulebook
    from ale.contracts.serialization import canonical_json, load_yaml
    from ale.program.models import PreparedInput
    from ale.topology import seed_plan

    prep = PreparedInput.model_validate_json(Path(sys.argv[1]).read_text("utf-8"))
    rb = load_yaml(Rulebook, Path(sys.argv[2]).read_text("utf-8"))
    res = seed_plan(prep, rb, AleConfig(), seed=3)
    sys.stdout.buffer.write(canonical_json(res.plan))
    """
)


@pytest.mark.timeout(180)
def test_T07_deterministic(prep_25: PreparedInput, tmp_path: Path) -> None:
    from topology_helpers import RULEBOOK_TEST

    prep_file = tmp_path / "prepared.json"
    prep_file.write_text(prep_25.model_dump_json(), encoding="utf-8")
    script = tmp_path / "run_seed.py"
    script.write_text(_SCRIPT, encoding="utf-8")
    outs = []
    for _ in range(2):
        proc = subprocess.run(
            [sys.executable, str(script), str(prep_file), str(RULEBOOK_TEST)],
            capture_output=True,
            timeout=150,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
        outs.append(proc.stdout)
    assert outs[0] == outs[1]
    assert outs[0].startswith(b"{")


def test_T08_never_raises(
    prep_25: PreparedInput, prep_8: PreparedInput, rulebook: Rulebook
) -> None:
    # prepare_input rejects P25 on site_rect_small (E_NOT_FEASIBLE): swap the site in.
    crammed = prep_25.model_copy(update={"site": prep_8.site, "footprint": prep_8.footprint})
    budget = 3.0
    result = seed_plan(crammed, rulebook, CONFIG, seed=1, time_budget_s=budget)
    assert result.realization.failures
    assert result.realization.layout is None
    assert result.attempts >= 1
    # One realisation may finish after the budget check: allow a small overrun.
    assert result.elapsed_s <= budget + 0.5
    ids = sorted(result.plan.room_ids())
    assert ids == sorted(iid for iid, _ in crammed.instances)


@pytest.mark.timeout(240)
def test_T09_required_adjacency(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    seeded = seed_plan(prep_25, rulebook, CONFIG, seed=1)
    assert seeded.realization.layout is not None
    ours = seeded.realization.layout.metrics.cost_breakdown["required_adjacency"]
    # Q.1: random plans almost never realise once every room must comply (geometry R02),
    # so the 50 random valid plans also include the seeded plan with its rooms shuffled
    # within size classes (always realisable); random plans that realise still count.
    rng = random.Random(20261108)
    costs: list[float] = []
    tries = 0
    while len(costs) < 50 and tries < 3000:
        tries += 1
        cand = random_plan(prep_25, rng) if tries % 2 else permuted_plan(seeded.plan, prep_25, rng)
        real = realize(prep_25, cand, rulebook, CONFIG)
        if real.layout is not None:
            costs.append(real.layout.metrics.cost_breakdown["required_adjacency"])
    assert len(costs) == 50
    assert ours <= min(costs)


@pytest.mark.timeout(180)
@pytest.mark.parametrize("name", ["prep_8", "prep_25", "prep_60"])
def test_T10_beats_greedy(name: str, rulebook: Rulebook, request: pytest.FixtureRequest) -> None:
    prepared: PreparedInput = request.getfixturevalue(name)
    seeded = seed_plan(prepared, rulebook, CONFIG, seed=1)
    assert seeded.realization.layout is not None
    greedy = realize(prepared, greedy_plan(prepared, rulebook, CONFIG), rulebook, CONFIG)
    if greedy.layout is None:
        assert greedy.failures
    else:  # pragma: no cover - greedy overflows on every fixture today
        g_cost = greedy.layout.metrics.total_cost
        assert seeded.realization.layout.metrics.total_cost <= g_cost
