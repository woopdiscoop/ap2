"""Ticket R.8 eval (R801-R803, R806): depth / width / façade length learned from plans."""

from __future__ import annotations

from pathlib import Path

import pytest
from r8_helpers import Pair, corpus, facade_plan
from rulebook_helpers import TODAY, config, seed_rulebook, split, uniform_stats

from ale.contracts.models import Quantiles, Rulebook, TypeStats
from ale.contracts.serialization import canonical_json, dump_yaml, load_yaml
from ale.rulebook import build_rulebook, load_seed
from ale.rulebook.stats import PlanInput, facade_stats

REPO = Path(__file__).resolve().parents[2]


def _build(pairs, seed=None, cfg=None):  # type: ignore[no-untyped-def]
    topos, geoms = split(pairs)
    return build_rulebook(topos, geoms, seed, cfg or config(), today=TODAY, min_support=1)


def _plan_input(pair: Pair) -> PlanInput:
    topo, geom = pair
    return PlanInput(topology=topo, metric=geom.to_metric(), weight=1.0)


def test_R801_learned_quantiles_equal_constructed() -> None:
    depths = [4.8, 5.1, 5.4, 5.7, 6.0]
    pairs = corpus("office", [(3.0, d) for d in depths])
    pairs += corpus("meeting_room", [(6.0, 6.6)] * 5, start=10)
    res = _build(pairs)
    office = res.rulebook.types["office"]
    assert office.n_facade_samples == 5
    assert office.depth_m is not None and office.facade_width_m is not None
    # Hazen positions .1 .3 .5 .7 .9 -> p10 = 4.8, p50 = 5.4, p90 = 6.0
    assert office.depth_m.p10 == pytest.approx(4.8, abs=0.1)
    assert office.depth_m.p50 == pytest.approx(5.4, abs=0.1)
    assert office.depth_m.p90 == pytest.approx(6.0, abs=0.1)
    assert office.facade_width_m.p50 == pytest.approx(3.0, abs=0.1)
    assert office.facade_width_m.p90 == pytest.approx(3.0, abs=0.1)
    meeting = res.rulebook.types["meeting_room"]
    assert meeting.depth_m is not None and meeting.facade_width_m is not None
    assert meeting.depth_m.p50 == pytest.approx(6.6, abs=0.1)
    assert meeting.facade_width_m.p50 == pytest.approx(6.0, abs=0.1)
    # façade length per m2 = width / (width * depth) for a single south edge
    assert office.facade_m_per_m2 == pytest.approx(1.0 / 5.4, rel=0.05)


def test_R801_rooms_without_facade_count_as_zero() -> None:
    # 5 offices with a façade (3 x 5 m) + 5 enclosed offices (3 x 4 m, no façade)
    pairs = corpus("office", [(3.0, 5.0)] * 5, interior="office")
    stats = facade_stats([_plan_input(p) for p in pairs])["office"]
    assert stats.n == 5  # the enclosed offices add no depth / width sample
    assert stats.facade_len == pytest.approx(5 * 3.0)
    assert stats.area == pytest.approx(5 * 15.0 + 5 * 12.0)
    assert stats.m_per_m2 == pytest.approx(15.0 / 135.0)


def test_R802_insufficient_sample() -> None:
    res = _build(corpus("office", [(3.0, 5.4)] * 4))
    office = res.rulebook.types["office"]
    assert office.depth_m is None and office.facade_width_m is None
    assert office.facade_m_per_m2 is None and office.n_facade_samples == 0
    assert "échantillon insuffisant" in res.report_md
    # nothing of the new fields leaks into the serialised form
    assert b"depth_m" not in canonical_json(res.rulebook)
    assert "depth_m" not in dump_yaml(res.rulebook)


def test_R802_seed_values_kept_when_insufficient() -> None:
    prior = uniform_stats().model_copy(
        update={
            "depth_m": Quantiles(p10=4.0, p50=5.0, p90=6.0, n=9),
            "facade_width_m": Quantiles(p10=2.4, p50=3.0, p90=3.6, n=9),
            "facade_m_per_m2": 0.2,
            "n_facade_samples": 9,
        }
    )
    seed = seed_rulebook(types={"office": prior})
    res = _build(corpus("office", [(3.0, 5.4)] * 4), seed=seed)
    assert res.rulebook.types["office"].depth_m == prior.depth_m


def test_R802_blend_with_seed_depths() -> None:
    prior = uniform_stats().model_copy(
        update={"depth_m": Quantiles(p10=4.0, p50=5.0, p90=6.0, n=9)}
    )
    seed = seed_rulebook(types={"office": prior})
    res = _build(corpus("office", [(3.0, 7.0)] * 6), seed=seed)
    depth = res.rulebook.types["office"].depth_m
    assert depth is not None and 5.0 < depth.p50 < 7.0
    assert "mélangé" in res.report_md


def test_R803_old_rulebooks_load_unchanged() -> None:
    for rel in (
        "specs/tickets/0.3_seed-rulebook/seed_rulebook.yaml",
        "examples/rulebook_test.yaml",
        "tests/program/data/rulebook_test.yaml",
    ):
        rb = load_seed(REPO / rel)
        assert all(t.depth_m is None and t.n_facade_samples == 0 for t in rb.types.values())
        again = load_yaml(Rulebook, dump_yaml(rb))
        assert again.content_sha256() == rb.content_sha256()
        assert b"facade_width_m" not in canonical_json(rb)
    ts = TypeStats.model_validate(uniform_stats().model_dump(mode="json"))
    assert ts.depth_m is None


def test_R806_rulebook_report_table() -> None:
    res = _build(corpus("office", [(3.0, 5.4)] * 5))
    assert "## Profondeur et largeur de façade" in res.report_md
    assert "| office | 5.4 / 5.4 | 3 / 3 |" in res.report_md


def test_R801_helper_sanity() -> None:
    topo, geom = facade_plan(1, "office", 3.0, 5.4)
    assert len(geom.rooms) == 4 and topo.exterior == ()
