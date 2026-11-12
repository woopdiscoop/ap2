"""Tests M308 (Ticket M.3): ``cellgrow`` with no prior is byte-identical to R.9 / M.2b, and the
prior steers a floor onto the cells that carried the same room types below."""

from __future__ import annotations

import hashlib

import pytest
from cellgrow_helpers import anchor_prepared, arep_config, arep_prepared

from ale.config import AleConfig
from ale.contracts.models import Rulebook
from ale.program.models import PreparedInput
from ale.topology import seed_plan
from ale.topology.cellgrow import CellDiagram, grow
from ale.topology.cellprior import Prior

#: sha256 prefixes of ``(owner, cells, checks)`` computed with ``cellgrow.py`` of ``e03a2a3``
#: (before M.3) on the R.9 anchor fixture and the AREP programme.
BASE_DIGESTS = {
    ("anchor", 0, 0.0): "61343f4b8800a65c",
    ("anchor", 3, 0.5): "d7126fe39f3cbe09",
    ("arep", 0, 0.0): "65c221f4d0057066",
    ("arep", 3, 0.5): "9d9ecf01e9419811",
}


def digest(d: CellDiagram) -> str:
    return hashlib.sha256(repr((d.owner, d.cells, d.checks)).encode()).hexdigest()[:16]


@pytest.fixture(scope="module")
def cases(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, tuple[PreparedInput, AleConfig]]:
    return {
        "anchor": (anchor_prepared(tmp_path_factory.mktemp("m3_anchor")), AleConfig()),
        "arep": (arep_prepared(tmp_path_factory.mktemp("m3_arep")), arep_config()),
    }


@pytest.mark.parametrize(("name", "seed", "jitter"), sorted(BASE_DIGESTS))
def test_M308_no_prior_byte_identical(
    cases: dict[str, tuple[PreparedInput, AleConfig]],
    rulebook: Rulebook,
    name: str,
    seed: int,
    jitter: float,
) -> None:
    prep, cfg = cases[name]
    want = BASE_DIGESTS[(name, seed, jitter)]
    assert digest(grow(prep, rulebook, cfg, seed=seed, jitter=jitter)) == want
    assert digest(grow(prep, rulebook, cfg, seed=seed, jitter=jitter, prior=None)) == want
    assert digest(grow(prep, rulebook, cfg, seed=seed, jitter=jitter, prior={})) == want


def _layer(d: CellDiagram) -> dict[tuple[int, int], str]:
    return {c: d.types[r] for r in d.rooms for c in d.cells[r]}


def test_M3_prior_steers_rooms_onto_their_type(
    cases: dict[str, tuple[PreparedInput, AleConfig]], rulebook: Rulebook
) -> None:
    prep, cfg = cases["anchor"]
    plain = grow(prep, rulebook, cfg, seed=0)
    prior = _layer(plain)
    # the prior of a floor laid out otherwise (another seed) pulls the rooms back to the cells
    # of their types: the overlap with the prior rises
    other = grow(prep, rulebook, cfg, seed=0, jitter=1.0)
    steered = grow(prep, rulebook, cfg, seed=0, jitter=1.0, prior=prior)

    def overlap(d: CellDiagram) -> int:
        return sum(1 for c, t in _layer(d).items() if prior.get(c) == t)

    assert overlap(steered) > overlap(other)
    assert not steered.checks.area  # every room still reaches its cell count


def test_M3_prior_ignores_cells_outside_the_footprint(
    cases: dict[str, tuple[PreparedInput, AleConfig]], rulebook: Rulebook
) -> None:
    prep, cfg = cases["anchor"]
    plain = grow(prep, rulebook, cfg, seed=0)
    far = {(10_000, 10_000): "office", (-5, -5): "office"}
    assert digest(grow(prep, rulebook, cfg, seed=0, prior=far)) == digest(plain)


def test_M3_prior_unit_methods(cases: dict[str, tuple[PreparedInput, AleConfig]]) -> None:
    pr = Prior({}, {})
    assert pr.ribbon_span("office", [False] * 4, 2) == []
    assert pr.bonus("office", {"office"}) == {}
    pr2 = Prior({5: "office", 6: "storage"}, {"office": [0, 2, 3]})
    assert pr2.ribbon_span("office", [False, False, True, False], 5) == [0, 3]
    assert pr2.bonus("office", {"office", "storage"}) == {5: -4.0, 6: 3.0}
    assert pr2.bonus("office", {"office"}) == {5: -4.0}


def test_M3_seed_plan_prior_is_a_position_override(
    cases: dict[str, tuple[PreparedInput, AleConfig]], rulebook: Rulebook
) -> None:
    prep, cfg = cases["anchor"]
    base = seed_plan(prep, rulebook, cfg, seed=1, max_attempts=2)
    same = seed_plan(prep, rulebook, cfg, seed=1, max_attempts=2, prior=None)
    assert base.plan == same.plan
    first = prep.instances[0][0]
    moved = seed_plan(prep, rulebook, cfg, seed=1, max_attempts=2, prior={first: (1.0, 1.0)})
    assert moved.plan is not None  # a prior never raises, whatever the positions
    unknown = seed_plan(prep, rulebook, cfg, seed=1, max_attempts=2, prior={"ZZ": (0.0, 0.0)})
    assert unknown.plan == base.plan  # rooms the floor does not have are ignored
