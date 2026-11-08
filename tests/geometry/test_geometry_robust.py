"""Fixtures, robustness, determinism and performance R01-R04 (eval.md section 3)."""

from __future__ import annotations

import random
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from fixtures import DATA_DIR, ProgramName, SiteName
from geometry_helpers import fixture_prepared, load_test_rulebook, random_plan

from ale.config import AleConfig
from ale.contracts.corridor_plan import CorridorPlan
from ale.contracts.footprint import decompose_footprint
from ale.geometry import check_layout, greedy_plan, realize
from ale.program import PreparedInput

CONFIG = AleConfig()
RULEBOOK = load_test_rulebook()
ALLOWED = {"PLAN_OVERFLOW", "JUNCTION_MISALIGNED"}
SRC = Path(__file__).resolve().parents[2] / "src"


@pytest.mark.parametrize(
    ("program", "site"),
    [("program_08", "site_rect_small"), ("program_25", "site_rect"), ("program_60", "site_L")],
)
def test_R01_fixtures_never_raise(program: ProgramName, site: SiteName) -> None:
    prepared = fixture_prepared(program, site)
    plan = greedy_plan(prepared, RULEBOOK, CONFIG)
    instances = [iid for iid, _ in prepared.instances]
    assert plan.check_against(instances, decompose_footprint(prepared.footprint.polygon)) == ()
    real = realize(prepared, plan, RULEBOOK, CONFIG)
    if real.layout is not None:
        assert check_layout(real.layout, prepared, CONFIG) == ()
    else:
        assert {f.code for f in real.failures} <= ALLOWED


def test_R02_random_plans_never_raise() -> None:
    prepared = fixture_prepared("program_25", "site_rect")
    rng = random.Random(20261108)
    successes = 0
    for _ in range(200):
        plan = random_plan(prepared, rng)
        real = realize(prepared, plan, RULEBOOK, CONFIG)
        if real.layout is not None:
            successes += 1
            assert check_layout(real.layout, prepared, CONFIG) == ()
        else:
            assert real.failures
    assert successes > 0


_SCRIPT = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from ale.config import AleConfig
    from ale.contracts.corridor_plan import CorridorPlan
    from ale.contracts.models import GridSpec, Program, Rulebook, SiteSpec
    from ale.contracts.serialization import canonical_json, load_yaml
    from ale.geometry import realize
    from ale.program import PreparedInput, check_feasibility, to_module_footprint

    data, rulebook_path, plan_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    rulebook = load_yaml(Rulebook, rulebook_path.read_text(encoding="utf-8"))
    program = load_yaml(Program, (data / "program_25.yaml").read_text(encoding="utf-8"))
    site = load_yaml(SiteSpec, (data / "site_rect.yaml").read_text(encoding="utf-8"))
    config = AleConfig()
    grid = GridSpec(module_mm=100)
    fp = to_module_footprint(site, grid)
    prepared = PreparedInput(
        program=program, instances=program.instances(), site=site, footprint=fp, grid=grid,
        rulebook_version=rulebook.version,
        feasibility=check_feasibility(program, fp, rulebook, config), warnings=(),
    )
    plan = CorridorPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    real = realize(prepared, plan, rulebook, config, seed=7)
    assert real.layout is not None, real.failures
    sys.stdout.buffer.write(canonical_json(real.layout))
    """
)


def _successful_multiband_plan(prepared: PreparedInput) -> CorridorPlan:
    """The first seeded random plan with 2+ bands that realises (P25 greedy overflows)."""
    rng = random.Random(3)
    for _ in range(500):
        plan = random_plan(prepared, rng)
        multi = len(plan.pieces[0].bands) >= 2
        if multi and realize(prepared, plan, RULEBOOK, CONFIG).layout is not None:
            return plan
    raise AssertionError("no realisable multi-band plan found")  # pragma: no cover


def test_R03_deterministic(tmp_path: Path) -> None:
    script = tmp_path / "run.py"
    script.write_text(_SCRIPT, encoding="utf-8")
    prepared = fixture_prepared("program_25", "site_rect")
    plan = _successful_multiband_plan(prepared)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(), encoding="utf-8")
    rulebook = Path(__file__).resolve().parents[1] / "program" / "data" / "rulebook_test.yaml"
    outputs = []
    for _ in range(2):
        proc = subprocess.run(
            [sys.executable, str(script), str(DATA_DIR), str(rulebook), str(plan_path)],
            capture_output=True,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
        outputs.append(proc.stdout)
    assert outputs[0] == outputs[1]
    assert b'"seed":7' in outputs[0]
    # And the in-process result is the same bytes.
    from ale.contracts.serialization import canonical_json

    real = realize(prepared, plan, RULEBOOK, CONFIG, seed=7)
    assert real.layout is not None
    assert canonical_json(real.layout) == outputs[0]


def test_R04_performance() -> None:
    prepared = fixture_prepared("program_60", "site_L")
    plan = greedy_plan(prepared, RULEBOOK, CONFIG)
    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        realize(prepared, plan, RULEBOOK, CONFIG)
        best = min(best, time.perf_counter() - start)
    print(f"R04 P60 realize: {best:.3f} s")
    assert best <= 1.0
