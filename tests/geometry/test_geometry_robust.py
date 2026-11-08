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
from geometry_helpers import AnyBay, fb, fixture_prepared, load_test_rulebook, piece, rb

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


def _random_plan(prepared: PreparedInput, rng: random.Random) -> CorridorPlan:
    ids = [iid for iid, _ in prepared.instances]
    rng.shuffle(ids)
    blocks: list[list[AnyBay]] = [[], []]
    i = 0
    while i < len(ids):  # consumes at least one id per iteration
        target = blocks[rng.randrange(2)]
        if rng.random() < 0.5:
            target.append(rb(ids[i]))
            i += 1
            continue
        nl, nr = rng.randint(0, 3), rng.randint(0, 3)
        if nl + nr == 0:
            nl = 1
        left = ids[i : i + nl]
        right = ids[i + nl : i + nl + nr]
        i += nl + nr
        target.append(fb(left, right) if left or right else rb(ids[i - 1]))
    return CorridorPlan(pieces=(piece(blocks[0], blocks[1]),))


def test_R02_random_plans_never_raise() -> None:
    prepared = fixture_prepared("program_25", "site_rect")
    rng = random.Random(20261108)
    successes = 0
    for _ in range(200):
        plan = _random_plan(prepared, rng)
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
    from ale.contracts.models import GridSpec, Program, Rulebook, SiteSpec
    from ale.contracts.serialization import canonical_json, load_yaml
    from ale.geometry import greedy_plan, realize
    from ale.program import PreparedInput, check_feasibility, to_module_footprint

    data, rulebook_path = Path(sys.argv[1]), Path(sys.argv[2])
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
    real = realize(prepared, greedy_plan(prepared, rulebook, config), rulebook, config, seed=7)
    assert real.layout is not None, real.failures
    sys.stdout.buffer.write(canonical_json(real.layout))
    """
)


def test_R03_deterministic(tmp_path: Path) -> None:
    script = tmp_path / "run.py"
    script.write_text(_SCRIPT, encoding="utf-8")
    rulebook = Path(__file__).resolve().parents[1] / "program" / "data" / "rulebook_test.yaml"
    outputs = []
    for _ in range(2):
        proc = subprocess.run(
            [sys.executable, str(script), str(DATA_DIR), str(rulebook)],
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

    prepared = fixture_prepared("program_25", "site_rect")
    real = realize(prepared, greedy_plan(prepared, RULEBOOK, CONFIG), RULEBOOK, CONFIG, seed=7)
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
