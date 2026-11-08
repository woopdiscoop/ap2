"""Ticket 2.1 evaluation T1-T6: topology of synthetic plans with known ground truth."""

from __future__ import annotations

import random

import pytest
from mining_helpers import grid_plan, grid_truth, thin_touch_plan

from ale.contracts.config import AleConfig
from ale.contracts.enums import ContactKind, Fidelity, Frame
from ale.mining import PlanTopology, extract_topology

CFG = AleConfig()


def _topo(plan: object) -> PlanTopology:
    out = extract_topology(plan, CFG)  # type: ignore[arg-type]
    assert out is not None
    return out


def _precision_recall(
    found: set[tuple[str, str]], truth: set[tuple[str, str]]
) -> tuple[float, float]:
    tp = len(found & truth)
    precision = tp / len(found) if found else 1.0
    recall = tp / len(truth) if truth else 1.0
    return precision, recall


def test_T1_grid_plan() -> None:
    shared, doors, _ = grid_truth()
    topo = _topo(grid_plan())
    found = {(c.a, c.b): c for c in topo.contacts}
    assert len(topo.contacts) == 7
    assert _precision_recall(set(found), set(shared)) == (1.0, 1.0)
    for pair, length in shared.items():
        assert found[pair].shared_m == pytest.approx(length, rel=0.02), pair
    door_pairs = {p for p, c in found.items() if c.kind is ContactKind.DOOR}
    assert door_pairs == doors
    assert all(found[p].openings == 1 for p in doors)
    assert all(c.openings == 0 for p, c in found.items() if p not in doors)
    assert topo.fidelity is Fidelity.CAD
    assert [c.a < c.b for c in topo.contacts] == [True] * 7
    assert [(c.a, c.b) for c in topo.contacts] == sorted((c.a, c.b) for c in topo.contacts)


@pytest.mark.parametrize("frame", [Frame.Y_UP, Frame.Y_DOWN])
def test_T1_grid_plan_millimetres(frame: Frame) -> None:
    shared, doors, facade = grid_truth()
    topo = _topo(grid_plan(scale=0.001, frame=frame))
    found = {(c.a, c.b): c for c in topo.contacts}
    assert set(found) == set(shared)
    assert {p for p, c in found.items() if c.kind is ContactKind.DOOR} == doors
    for pair, length in shared.items():
        assert found[pair].shared_m == pytest.approx(length, rel=0.02)
    for rid_, length in topo.exterior:
        assert length == pytest.approx(facade[rid_], rel=0.02)


def test_T2_thin_touch() -> None:
    topo = _topo(thin_touch_plan(0.4))
    assert topo.contacts == ()
    # Control: the same configuration facing on 1.0 m is a contact of ~1.0 m.
    ctrl = _topo(thin_touch_plan(1.0))
    assert len(ctrl.contacts) == 1
    assert ctrl.contacts[0].shared_m == pytest.approx(1.0, rel=0.02)
    assert ctrl.contacts[0].kind is ContactKind.WALL


def test_T3_exterior() -> None:
    _, _, facade = grid_truth()
    topo = _topo(grid_plan())
    got = dict(topo.exterior)
    assert set(got) == set(facade)
    for rid_, length in facade.items():
        assert got[rid_] == pytest.approx(length, rel=0.02), rid_
    assert [r for r, _ in topo.exterior] == sorted(got)


@pytest.mark.parametrize("seed", range(10))
def test_T4_noisy(seed: int) -> None:
    shared, doors, _ = grid_truth()
    topo = _topo(grid_plan(jitter_m=0.03, seed=seed))
    found = {(c.a, c.b) for c in topo.contacts}
    precision, recall = _precision_recall(found, set(shared))
    assert precision >= 0.9
    assert recall >= 0.9
    found_doors = {(c.a, c.b) for c in topo.contacts if c.kind is ContactKind.DOOR}
    p_d, r_d = _precision_recall(found_doors, doors)
    assert p_d >= 0.9
    assert r_d >= 0.9


def test_T5_no_scale() -> None:
    plan = grid_plan()
    data = plan.model_dump()
    data.update(scale_m_per_unit=None, scale_method="UNKNOWN")
    unscaled = type(plan).model_validate(data)
    assert extract_topology(unscaled, CFG) is None


@pytest.mark.parametrize("seed", range(5))
def test_T6_determinism(seed: int) -> None:
    plan = grid_plan(jitter_m=0.03, seed=7)
    ref = _topo(plan)
    rng = random.Random(seed)
    rooms = list(plan.rooms)
    walls = list(plan.walls)
    rng.shuffle(rooms)
    rng.shuffle(walls)
    shuffled = plan.model_copy(update={"rooms": tuple(rooms), "walls": tuple(walls)})
    assert shuffled.rooms != plan.rooms
    out = _topo(shuffled)
    assert out == ref
    assert out.model_dump_json() == ref.model_dump_json()
    assert [r[0] for r in out.rooms] == sorted(r[0] for r in out.rooms)
