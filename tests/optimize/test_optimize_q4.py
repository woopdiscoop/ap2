"""Ticket Q.4 eval D02, D05, D06, D07: façade depth rule in the optimiser.

D02 compares the Q.3 quality runs (rule off) with SHA-256 digests of the canonical layouts
produced by the code before Q.4 (``origin/claude/new-session-2hmd3s`` at ``12b59b0``, same
seeds and iteration budgets). D05 rebuilds the AREP-MS top-floor demo programme
synthetically and runs it with the deterministic budgets of Q.3 (seed attempts, annealing
iterations), never wall-clock budgets.
"""

from __future__ import annotations

import hashlib
import importlib.util
from collections import Counter
from pathlib import Path

import pytest
from optimize_helpers import (
    ANNEAL_ITER,
    ANNEAL_SEED,
    RULEBOOK_TEST,
    SEED_ATTEMPTS,
    QualityRun,
    write_inputs,
)
from test_optimize_q3 import PATHS, _run

from ale.config import AleConfig
from ale.contracts.lock import main as lock_main
from ale.contracts.models import Program, RoomSpec, Rulebook, SiteSpec
from ale.contracts.serialization import canonical_json
from ale.geometry import check_layout, realize
from ale.geometry.blocks import Consts
from ale.geometry.evaluate import SOFT_ASPECT_CODE, hard_codes_of
from ale.optimize import HARD_CODES, anneal
from ale.program import prepare_input
from ale.program.models import PreparedInput
from ale.topology import SeedResult, seed_plan

Seeded = dict[str, tuple[PreparedInput, SeedResult]]
Runs = dict[str, QualityRun]

#: SHA-256 of ``canonical_json`` of the seed-3 start and the annealed final layout of each
#: quality run, computed with the pre-Q.4 code (12b59b0).
BEFORE_Q4 = {
    "P8": (
        "78f40d05384edec3886a7bf7972dabe81e25ca17d85fbfecdf89e09d25b07641",
        "0bf4b64382f2209566f2a0ebe2025ec3cdd7e5e5618deb2bf8c81a6431ebc787",
    ),
    "P25": (
        "c5e26ca4d9b7f3f40ad2b4927e17ded2e4caa99bacc6b6d2f9cb09274875df4f",
        "a71ed5b1c114125da5e75d235781e98c6a5a3ec698eaed09766fe3ec77d24886",
    ),
    "P60": (
        "51b34cc2586f05ae6176f03bf794ba9f3b1216a133fba143dd91d5fe763f4c60",
        "e397b4469752f3a3ede3d1b59e6f07543d06078cf93e2302390723bbf969d0e9",
    ),
}


def _digest(model: object) -> str:
    return hashlib.sha256(canonical_json(model)).hexdigest()  # type: ignore[arg-type]


# ------------------------------------------------------------------------------ D02
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_D02_off_by_default(quality_runs: Runs, seeded: Seeded, rulebook: Rulebook) -> None:
    assert AleConfig().facade.max_depth_m is None
    assert Consts.from_config(AleConfig()).dmax is None
    for name, (start, final) in BEFORE_Q4.items():
        run = quality_runs[name]
        layout0 = run.start.realization.layout
        assert layout0 is not None
        assert run.result.stopped_by == "max_iter"
        assert (_digest(layout0), _digest(run.result.layout)) == (start, final), name
    # An explicit ``max_depth_m = None`` is the default: same realisation, byte for byte.
    explicit = AleConfig.model_validate({"facade": {"max_depth_m": None}})
    assert explicit == AleConfig()
    for name in ("P25", "P60"):
        prep, start_res = seeded[name]
        a = realize(prep, start_res.plan, rulebook, AleConfig())
        b = realize(prep, start_res.plan, rulebook, explicit)
        assert a.layout is not None and b.layout is not None
        assert canonical_json(a.layout) == canonical_json(b.layout)


# ------------------------------------------------------------------------------ D05
#: AREP-MS top floor (Présidence / DAP / DGS), 16 programme lines, 649 m². The test rulebook
#: has no ``waiting_area`` / ``cleaning_room`` types: the salon is a ``reception`` and the
#: cleaning room a ``storage`` room (same shape role for this test).
_ADMIN = "ADMINISTRATIVE"


def _arep_rooms() -> list[RoomSpec]:
    def line(rid: str, name: str, rtype: str, area: float, qty: int = 1, **kw: object) -> RoomSpec:
        zone = "SERVICES" if rtype in ("sanitary", "storage") else _ADMIN
        return RoomSpec.model_validate(
            {
                "id": rid,
                "name": name,
                "type": rtype,
                "target_area_m2": area,
                "macro_zone": zone,
                "quantity": qty,
                **kw,
            }
        )

    office = {"needs_facade": True}
    return [
        line("P01", "Bureau du Président", "office", 160, **office),
        line("P02", "Bureau du Directeur DAP", "office", 80, **office),
        line("P03", "Bureau du Directeur DGS", "office", 60, **office),
        line("P04", "Vice-président 1", "office", 30, **office),
        line("P05", "Vice-président 2", "office", 30, **office),
        line("P06", "Chargé de mission 1", "office", 25, **office),
        line("P07", "Chargé de mission 2", "office", 25, **office),
        line("P08", "Arrière bureau", "office", 30, adjacent_to=["P01"], **office),
        line("P09", "Salon / Attente", "reception", 25, adjacent_to=["P01"], **office),
        line("P10", "Chef de service", "office", 16, qty=6, **office),
        line("P11", "Secrétariat DAP", "office", 16, adjacent_to=["P02"], **office),
        line("P12", "Secrétariat DGS", "office", 16, adjacent_to=["P03"], **office),
        line("S01", "Sanitaires", "sanitary", 4, qty=3),
        line("S02", "Sanitaires H/F + PMR 1", "sanitary", 20),
        line("S03", "Sanitaires H/F + PMR 2", "sanitary", 20),
        line("S04", "Local ménage", "storage", 4),
    ]


def arep_config(max_depth_m: float | None = 7.2, hard: bool = True) -> AleConfig:
    """The AREP configuration; D05 runs with the hard limit (``max_depth_hard``), D08 with
    the soft rule (the default) and with the rule off."""
    return AleConfig.model_validate(
        {
            "grid": {"module_mm": 600},
            "area": {"tol_down_pct": 0, "tol_up_pct": 10, "tol_up_abs_m2": 0},
            "facade": {"max_depth_m": max_depth_m, "max_depth_hard": hard},
        }
    )


#: Deterministic budgets of D05 (the Q.3 quality-run convention: seed-3 start with an
#: attempt budget, annealing seed 6 with an iteration budget).
AREP_SEED = 3
AREP_ITER = 1500


def arep_prepared(tmp: Path) -> PreparedInput:
    program = Program(rooms=tuple(_arep_rooms()))
    site = SiteSpec.model_validate(
        {
            "footprint": {"exterior": [[0, 0], [54, 0], [54, 15.6], [0, 15.6]], "holes": []},
            "north_angle_deg": 0.0,
            "access_edge": 0,
        }
    )
    xlsx, yml = write_inputs(tmp, program, site)
    return prepare_input(xlsx, yml, RULEBOOK_TEST, arep_config())


@pytest.mark.slow
@pytest.mark.timeout(900)
def test_D05_arep_floor(tmp_path: Path, rulebook: Rulebook) -> None:
    prep = arep_prepared(tmp_path)
    assert len(prep.program.rooms) == 16
    assert sum(spec.target_area_m2 for _, spec in prep.instances) == pytest.approx(649.0)
    cfg = arep_config()
    start = seed_plan(prep, rulebook, cfg, seed=AREP_SEED, max_attempts=SEED_ATTEMPTS)
    layout0 = start.realization.layout
    assert layout0 is not None, start.realization.failures
    res = anneal(prep, rulebook, cfg, start.plan, seed=ANNEAL_SEED, max_iter=AREP_ITER)
    assert res.stopped_by == "max_iter"
    final = Counter(v.code for v in res.layout.metrics.violations)
    hard = {c: n for c, n in sorted(final.items()) if c in HARD_CODES}
    print(f"AREP floor: start {Counter(v.code for v in layout0.metrics.violations)}")
    print(f"AREP floor: final hard {hard}, soft {final[SOFT_ASPECT_CODE]} {SOFT_ASPECT_CODE}")
    assert check_layout(res.layout, prep, cfg) == ()
    # The 160 m² office is at most 7.2 m deep; its aspect > 2 is soft.
    assert final["FACADE_DEPTH"] == 0
    # Router amendment 2026-11-11: <= 1 is out of reach of the corridor grammar
    # (eval_report §3); the target moves to R.9. Regression guard at the measured value.
    assert final["NO_FACADE"] <= 3


# ------------------------------------------------------------------------------ D08
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_D08_soft_depth(tmp_path: Path, rulebook: Rulebook) -> None:
    """Soft mode (the default): FACADE_DEPTH is reported but not hard, the cost term
    ``facade_depth`` is in the breakdown, and ASPECT stays hard (no ASPECT_DEPTH)."""
    cfg = arep_config(hard=False)
    assert cfg.facade.max_depth_hard is False
    prep = arep_prepared(tmp_path)
    start = seed_plan(prep, rulebook, cfg, seed=AREP_SEED, max_attempts=SEED_ATTEMPTS)
    assert start.realization.layout is not None, start.realization.failures
    res = anneal(prep, rulebook, cfg, start.plan, seed=ANNEAL_SEED, max_iter=AREP_ITER)
    assert res.stopped_by == "max_iter"
    metrics = res.layout.metrics
    final = Counter(v.code for v in metrics.violations)
    hard_set = hard_codes_of(metrics, HARD_CODES)
    hard = {c: n for c, n in sorted(final.items()) if c in hard_set}
    print(f"AREP soft: final {dict(final)}, hard {hard}, depth {metrics.cost_breakdown}")
    assert "facade_depth" in metrics.cost_breakdown
    assert metrics.cost_breakdown["facade_depth"] >= 0.0
    assert SOFT_ASPECT_CODE not in final  # ASPECT stays hard in soft mode
    assert "FACADE_DEPTH" not in hard
    assert res.final_hard == sum(hard.values())
    assert check_layout(res.layout, prep, cfg) == ()


# ------------------------------------------------------------------------------ D06
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_D06_no_regression(quality_runs: Runs) -> None:
    """Q301-Q304 thresholds with the rule off (the tests themselves still run unchanged)."""
    for run in quality_runs.values():
        assert run.result.stopped_by == "max_iter"
        assert "FACADE_DEPTH" not in run.after
        assert check_layout(run.result.layout, run.prepared, AleConfig()) == ()
    assert quality_runs["P60"].after.get("NO_FACADE", 0) <= 6  # Q301
    assert quality_runs["P8"].result.final_hard == 0  # Q302
    assert quality_runs["P25"].result.final_hard <= 6
    assert quality_runs["P60"].result.final_hard <= 14
    p25 = quality_runs["P25"].result  # Q303
    assert p25.final_hard < p25.initial_hard
    assert ANNEAL_ITER == {"P8": 1500, "P25": 1500, "P60": 1100}


# ------------------------------------------------------------------------------ D07
def test_D07_gates() -> None:
    assert lock_main(["--check"]) == 0
    paths = [
        *PATHS,
        "src/ale/contracts",
        "src/ale/export/report.py",
        "tests/contracts",
        "tests/export",
    ]
    if importlib.util.find_spec("ruff") is None:  # pragma: no cover - dev extra installed
        pytest.skip("ruff not installed")
    proc = _run("ruff", "check", *paths)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = _run("ruff", "format", "--check", *paths)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    if importlib.util.find_spec("mypy") is None:  # pragma: no cover - dev extra installed
        pytest.skip("mypy not installed")
    proc = _run("mypy", "src/ale/contracts", "src/ale/export/report.py", *PATHS[:3])
    assert proc.returncode == 0, proc.stdout + proc.stderr
