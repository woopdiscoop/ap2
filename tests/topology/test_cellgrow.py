"""Ticket R.9 eval R9-01 to R9-05: the cell-growth diagram, its anchors and façade shares,
the corridor plan built from it and the unchanged default seeder."""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cellgrow_helpers import anchor_prepared, arep_config, arep_prepared
from optimize_helpers import SEED_ATTEMPTS

from ale.config import AleConfig
from ale.contracts.footprint import decompose_footprint
from ale.contracts.models import CoreSpec, Rulebook
from ale.contracts.serialization import canonical_json
from ale.geometry import check_layout
from ale.program.models import PreparedInput
from ale.topology import seed_plan
from ale.topology.cellgrow import CORE_CELL, FREE, CellDiagram, grow
from ale.topology.fromdiagram import diagram_positions, plan_from_diagram
from ale.topology.graph import REQUIRED, build_graph, edges_of_kind
from ale.topology.repair import Ctx

TESTS = Path(__file__).resolve().parent.parent
HELPERS = Path(__file__).resolve().parent


@pytest.fixture(scope="session")
def arep(tmp_path_factory: pytest.TempPathFactory) -> PreparedInput:
    return arep_prepared(tmp_path_factory.mktemp("arep"))


@pytest.fixture(scope="session")
def anchored(tmp_path_factory: pytest.TempPathFactory) -> PreparedInput:
    return anchor_prepared(tmp_path_factory.mktemp("anchors"))


def _cases(
    prep_25: PreparedInput, prep_60: PreparedInput, arep: PreparedInput
) -> dict[str, tuple[PreparedInput, AleConfig]]:
    return {
        "P25": (prep_25, AleConfig()),
        "P60": (prep_60, AleConfig()),
        "AREP": (arep, arep_config()),
    }


def _digest(diagram: CellDiagram) -> str:
    return hashlib.sha256(repr((diagram.owner, diagram.cells)).encode()).hexdigest()


# ------------------------------------------------------------------------------ R9-01
def test_R9_01_diagram_counts(
    prep_25: PreparedInput, prep_60: PreparedInput, arep: PreparedInput, rulebook: Rulebook
) -> None:
    for name, (prep, cfg) in _cases(prep_25, prep_60, arep).items():
        d = grow(prep, rulebook, cfg)
        assert d.rooms == tuple(iid for iid, _ in prep.instances), name
        assert d.checks.area == {}, (name, d.checks.area)  # space allows: no shortfall
        for room in d.rooms:
            assert len(d.cells[room]) == d.targets[room], (name, room)
        # every cell has one owner: the cell lists partition the claimed cells
        claimed = [c for room in d.rooms for c in d.cells[room]]
        assert len(claimed) == len(set(claimed))
        n_free = sum(v == FREE for row in d.owner for v in row)
        assert d.reserve == n_free > 0  # unclaimed = circulation reserve
        for room in d.rooms:
            assert all(d.owner[y][x] == d.rooms.index(room) for x, y in d.cells[room])


def test_R9_01_cores_untouched(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    core = CoreSpec(id="C1", rect=(10.0, 8.0, 3.0, 3.0), kind="stair")
    site = prep_25.site.model_copy(update={"cores": (core,)})
    prep = prep_25.model_copy(update={"site": site})
    d = grow(prep, rulebook, AleConfig())
    assert d.cores
    k = d.step * d.module_m
    ox, oy = prep.footprint.origin_m
    assert len(d.cores) >= 9
    for x, y in d.cores:
        assert d.owner[y][x] == CORE_CELL
        assert abs((x + 0.5) * k - (10.0 - ox + 1.5)) <= 2.0
        assert abs((y + 0.5) * k - (8.0 - oy + 1.5)) <= 2.0
    assert all(c not in set(d.cores) for room in d.rooms for c in d.cells[room])
    assert d.checks.area == {}


def test_R9_01_shortfall_reported(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    """When the programme does not fit, the shortfall is reported (no exception)."""
    small = prep_25.model_copy(
        update={
            "instances": tuple(
                (iid, spec.model_copy(update={"target_area_m2": spec.target_area_m2 * 3}))
                for iid, spec in prep_25.instances
            )
        }
    )
    d = grow(small, rulebook, AleConfig())
    assert d.checks.area
    assert d.reserve == 0
    assert all(missing > 0 for missing in d.checks.area.values())
    for room, missing in d.checks.area.items():
        assert len(d.cells[room]) + missing == d.targets[room]


_SCRIPT = """
import hashlib, sys
sys.path[:0] = [{tests!r}, {helpers!r}, {program!r}]
from pathlib import Path
from fixtures import load_program, load_site
from topology_helpers import load_test_rulebook, prepare
from ale.config import AleConfig
from ale.topology.cellgrow import grow
prep = prepare(Path(sys.argv[1]), load_program("program_25"), load_site("site_rect"))
d = grow(prep, load_test_rulebook(), AleConfig())
print(hashlib.sha256(repr((d.owner, d.cells)).encode()).hexdigest())
"""


@pytest.mark.timeout(300)
def test_R9_01_deterministic_fresh_processes(tmp_path: Path) -> None:
    script = tmp_path / "grow.py"
    script.write_text(
        _SCRIPT.format(tests=str(TESTS), helpers=str(HELPERS), program=str(TESTS / "program")),
        encoding="utf-8",
    )
    digests = []
    for k, hash_seed in enumerate((1, 12345)):
        env = {**os.environ, "PYTHONHASHSEED": str(hash_seed)}
        env.pop("COV_CORE_SOURCE", None)
        proc = subprocess.run(
            [sys.executable, str(script), str(tmp_path / f"w{k}")],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        digests.append(proc.stdout.strip())
    assert digests[0] == digests[1] and len(digests[0]) == 64


def test_R9_01_seed_and_jitter(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    a = grow(prep_25, rulebook, AleConfig())
    assert _digest(a) == _digest(grow(prep_25, rulebook, AleConfig()))
    j1 = grow(prep_25, rulebook, AleConfig(), seed=7, jitter=0.5)
    j2 = grow(prep_25, rulebook, AleConfig(), seed=7, jitter=0.5)
    j3 = grow(prep_25, rulebook, AleConfig(), seed=8, jitter=0.5)
    assert _digest(j1) == _digest(j2)
    assert _digest(j1) != _digest(a) or _digest(j3) != _digest(a)
    assert j1.checks.area == {}


# ------------------------------------------------------------------------------ R9-02
def test_R9_02_anchors(anchored: PreparedInput, rulebook: Rulebook) -> None:
    d = grow(anchored, rulebook, AleConfig())
    assert d.checks.ok, d.checks
    assert d.checks.corner == () and d.checks.entrance == () and d.checks.core == ()
    w, h = d.width, d.height
    corners = {(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)}
    assert set(d.cells["O01"]) & corners  # the corner office owns a corner cell
    # the entrance hall touches the main entrance (south side, middle)
    assert d.entrance is not None
    ex, ey = d.entrance
    assert ey == 0 and abs(ex - w // 2) <= 1
    near = {(ex, ey), (ex + 1, ey), (ex - 1, ey), (ex, ey + 1)}
    assert near & set(d.cells["E01"])
    # REQUIRED pairs share a cell side
    graph = build_graph(anchored, rulebook)
    pairs = edges_of_kind(graph, REQUIRED)
    assert pairs
    for a, b in pairs:
        cb = set(d.cells[b])
        assert any(
            (x + dx, y + dy) in cb
            for x, y in d.cells[a]
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
        ), (a, b)
    # service rooms are next to the core
    core = set(d.cores)
    assert core
    for room in ("S01", "S02"):
        assert any(
            (x + dx, y + dy) in core
            for x, y in d.cells[room]
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
        ), room


def test_R9_02_entrance_follows_site(anchored: PreparedInput, rulebook: Rulebook) -> None:
    """The main entrance of the site decides where the entrance room goes."""
    site = anchored.site.model_copy(
        update={
            "entrances": (anchored.site.entrances[0].model_copy(update={"point": (30.0, 9.0)}),)
        }
    )
    d = grow(anchored.model_copy(update={"site": site}), rulebook, AleConfig())
    assert d.entrance is not None and d.entrance[0] == d.width - 1
    assert d.checks.entrance == ()  # still anchored, now on the east side


# ------------------------------------------------------------------------------ R9-03
def test_R9_03_facade_share(
    prep_25: PreparedInput, prep_60: PreparedInput, arep: PreparedInput, rulebook: Rulebook
) -> None:
    for name, (prep, cfg) in _cases(prep_25, prep_60, arep).items():
        d = grow(prep, rulebook, cfg)
        assert d.checks.facade == (), (name, d.checks.facade)


def test_R9_03_facade_shortage_named(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    """Every room wants a façade: the perimeter cannot hold them and the report names the
    rooms without one (exactly those that own no cell on the façade line)."""
    greedy = prep_25.model_copy(
        update={
            "instances": tuple(
                (
                    f"{iid}~{k}",
                    spec.model_copy(
                        update={"needs_facade": True, "target_area_m2": spec.target_area_m2 / 8}
                    ),
                )
                for k in range(8)
                for iid, spec in prep_25.instances
            )
        }
    )
    d = grow(greedy, rulebook, AleConfig())
    assert d.checks.facade  # 200 façade rooms, 140 cells of perimeter
    assert set(d.checks.facade) <= set(d.rooms)
    on_edge = {
        (x, y)
        for y in range(d.height)
        for x in range(d.width)
        if d.owner[y][x] >= 0
        and (
            x in (0, d.width - 1)
            or y in (0, d.height - 1)
            or -2 in (d.owner[y][x - 1], d.owner[y][x + 1], d.owner[y - 1][x], d.owner[y + 1][x])
        )
    }
    for room in d.rooms:
        touches = bool(set(d.cells[room]) & on_edge)
        assert touches == (room not in d.checks.facade), room


# ------------------------------------------------------------------------------ R9-04
def test_R9_04_plan_check_against(
    prep_25: PreparedInput, prep_60: PreparedInput, prep_8: PreparedInput, rulebook: Rulebook
) -> None:
    cfg = AleConfig()
    for name, prep in (("P8", prep_8), ("P25", prep_25), ("P60", prep_60)):
        fp = decompose_footprint(prep.footprint.polygon)
        ctx = Ctx.build(prep, rulebook, cfg, fp)
        d = grow(prep, rulebook, cfg)
        pos = diagram_positions(d)
        assert set(pos) == set(d.rooms)
        for counts in ([1] * len(fp.pieces), [2] * len(fp.pieces)):
            plan = plan_from_diagram(ctx, d, counts)
            ids = [iid for iid, _ in prep.instances]
            assert not plan.check_against(ids, fp), name


@pytest.mark.slow
@pytest.mark.timeout(900)
@pytest.mark.parametrize("name", ["P8", "P25", "P60"])
def test_R9_04_plan_realises(
    name: str,
    prep_8: PreparedInput,
    prep_25: PreparedInput,
    prep_60: PreparedInput,
    rulebook: Rulebook,
) -> None:
    prep = {"P8": prep_8, "P25": prep_25, "P60": prep_60}[name]
    cfg = AleConfig()
    res = seed_plan(prep, rulebook, cfg, seed=3, max_attempts=SEED_ATTEMPTS, seeder="cells")
    layout = res.realization.layout
    assert layout is not None, res.realization.failures
    assert check_layout(layout, prep, cfg) == ()
    fp = decompose_footprint(prep.footprint.polygon)
    assert not res.plan.check_against([iid for iid, _ in prep.instances], fp)


def test_R9_04_fallback_recorded(
    prep_8: PreparedInput,
    rulebook: Rulebook,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A diagram that cannot be realised falls back to the spring seeder, and says so."""
    import ale.topology.seed as seed_mod

    def bad(search: object, k: int) -> dict[str, tuple[float, float]]:
        return {iid: (0.0, 0.0) for iid, _ in prep_8.instances}

    monkeypatch.setattr(seed_mod, "_cells_positions", bad)
    with caplog.at_level(logging.INFO, logger="ale.topology.seed"):
        res = seed_plan(prep_8, rulebook, AleConfig(), seed=3, max_attempts=2, seeder="cells")
    assert res.realization.layout is not None
    assert any("spring fallback" in r.message for r in caplog.records)


# ------------------------------------------------------------------------------ R9-05
#: SHA-256 of ``canonical_json`` of the seed-3 start layouts (Q.4 D02, computed before Q.4).
SPRING_START = {
    "P8": "78f40d05384edec3886a7bf7972dabe81e25ca17d85fbfecdf89e09d25b07641",
    "P25": "c5e26ca4d9b7f3f40ad2b4927e17ded2e4caa99bacc6b6d2f9cb09274875df4f",
    "P60": "51b34cc2586f05ae6176f03bf794ba9f3b1216a133fba143dd91d5fe763f4c60",
}


@pytest.mark.slow
@pytest.mark.timeout(900)
@pytest.mark.parametrize("name", ["P8", "P25", "P60"])
def test_R9_05_unchanged(
    name: str,
    prep_8: PreparedInput,
    prep_25: PreparedInput,
    prep_60: PreparedInput,
    rulebook: Rulebook,
) -> None:
    prep = {"P8": prep_8, "P25": prep_25, "P60": prep_60}[name]
    default = seed_plan(prep, rulebook, AleConfig(), seed=3, max_attempts=SEED_ATTEMPTS)
    explicit = seed_plan(
        prep, rulebook, AleConfig(), seed=3, max_attempts=SEED_ATTEMPTS, seeder="spring"
    )
    for res in (default, explicit):
        assert res.realization.layout is not None
        digest = hashlib.sha256(canonical_json(res.realization.layout)).hexdigest()
        assert digest == SPRING_START[name]
    assert canonical_json(default.plan) == canonical_json(explicit.plan)
