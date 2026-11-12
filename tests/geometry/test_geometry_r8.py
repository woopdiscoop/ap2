"""Ticket R.8 eval R802 (realiser side), R804, R805: per-type soft depth limit.

A rulebook type with a learned ``depth_m`` replaces ``facade.max_depth_m`` by
``floor(depth_m.p90 / module)`` for its ``needs_facade`` rooms (soft rule only); other types
and rulebooks without learned depths keep today's behaviour. R805 (byte identity of the whole
pipeline: P08 / P25 / P60 digests) is the M206 test of ``test_geometry_m2.py``; the realiser
level is checked here too.
"""

from __future__ import annotations

from collections import Counter

import pytest
from geometry_helpers import (
    load_test_rulebook,
    one_piece,
    prepared_from,
    rb,
    rect_pts,
    room,
    site_modules,
)

from ale.config import AleConfig
from ale.contracts.models import Program, Quantiles, Rulebook
from ale.contracts.serialization import canonical_json
from ale.geometry import check_layout, evaluate, realize
from ale.geometry.blocks import Consts
from ale.geometry.evaluate import facade_depth
from ale.optimize.fastreal import RealizeCache

BASE = load_test_rulebook()


def config(max_depth_m: float | None = 7.2, hard: bool = False) -> AleConfig:
    return AleConfig.model_validate(
        {
            "grid": {"module_mm": 600},
            "area": {"tol_down_pct": 0, "tol_up_pct": 10, "tol_up_abs_m2": 0},
            "facade": {"max_depth_m": max_depth_m, "max_depth_hard": hard},
        }
    )


def with_depth(rulebook: Rulebook, rtype: str, p90: float) -> Rulebook:
    stats = rulebook.types[rtype].model_copy(
        update={
            "depth_m": Quantiles(p10=p90 - 1.4, p50=p90 - 0.6, p90=p90, n=9),
            "n_facade_samples": 9,
        }
    )
    return rulebook.model_copy(update={"types": {**rulebook.types, rtype: stats}})


def codes(layout) -> Counter[str]:  # type: ignore[no-untyped-def]
    return Counter(v.code for v in layout.metrics.violations)


def _case(rulebook: Rulebook, cfg: AleConfig, height: int = 22):  # type: ignore[no-untyped-def]
    """Two facing blocks 10 modules (6.0 m) deep: an office (``a``) and a meeting room (``b``),
    both ``needs_facade``."""
    rooms = [
        room("a", 20 * 10 * 0.36, needs_facade=True),
        room("b", 20 * 10 * 0.36, needs_facade=True, rtype="meeting_room"),
    ]
    prep = prepared_from(
        Program(rooms=tuple(rooms)), site_modules(rect_pts(40, height), module_m=0.6), rulebook, cfg
    )
    return prep, realize(prep, one_piece([rb("a")], [rb("b")]), rulebook, cfg)


def test_R804_learned_p90_flags_deeper_rooms_of_that_type() -> None:
    cfg = config()
    learned = with_depth(BASE, "office", 5.4)
    assert Consts.from_config(cfg, learned).type_dmax == (("office", 9),)
    assert Consts.from_config(cfg).type_dmax == ()
    # config limit 7.2 m (12 modules): both 6.0 m-deep rooms are fine.
    _, base = _case(BASE, cfg)
    assert base.layout is not None
    assert codes(base.layout)["FACADE_DEPTH"] == 0
    # office p90 = 5.4 m (9 modules): the 10-module office is deeper -> soft FACADE_DEPTH;
    # the meeting room (no learned depth) keeps the configured limit.
    prep, real = _case(learned, cfg)
    assert real.layout is not None, real.failures
    layout = real.layout
    depth = [v for v in layout.metrics.violations if v.code == "FACADE_DEPTH"]
    assert [v.instance_ids for v in depth] == [("a",)]
    assert "depth 10 > 9 modules" in depth[0].detail
    rects = {p.instance_id: p.rect for p in layout.rooms}
    assert rects == {p.instance_id: p.rect for p in base.layout.rooms}  # same plate, same depth
    got = facade_depth(rects["a"], layout.footprint)
    assert got is not None and got[0] == 10
    # soft: a cost term, not a hard violation
    assert layout.metrics.cost_breakdown["facade_depth"] == pytest.approx(0.5 * (10 - 9) / 9)
    assert check_layout(layout, prep, cfg) == ()
    # evaluate() agrees with the realiser
    again = evaluate(layout, prep, learned, cfg)
    assert [v.code for v in again.violations].count("FACADE_DEPTH") == 1


def test_R804_other_type_limit_only_applies_to_its_type() -> None:
    cfg = config()
    learned = with_depth(BASE, "meeting_room", 5.4)
    _, real = _case(learned, cfg)
    assert real.layout is not None
    flagged = [v.instance_ids for v in real.layout.metrics.violations if v.code == "FACADE_DEPTH"]
    assert flagged == [("b",)]


def test_R804_learned_limit_above_config_relaxes_nothing_for_other_types() -> None:
    cfg = config(max_depth_m=5.4)  # configured 9 modules: both rooms flagged
    _, real = _case(BASE, cfg)
    assert real.layout is not None
    assert sorted(
        v.instance_ids[0] for v in real.layout.metrics.violations if v.code == "FACADE_DEPTH"
    ) == ["a", "b"]
    # a learned office p90 of 7.2 m replaces the configured 5.4 m for the office only
    _, real2 = _case(with_depth(BASE, "office", 7.2), cfg)
    assert real2.layout is not None
    flagged = [v.instance_ids for v in real2.layout.metrics.violations if v.code == "FACADE_DEPTH"]
    assert flagged == [("b",)]


def test_R804_hard_limit_keeps_the_configured_value() -> None:
    cfg = config(hard=True)
    learned = with_depth(BASE, "office", 5.4)
    assert Consts.from_config(cfg, learned).type_dmax == ()
    _, a = _case(BASE, cfg)
    _, b = _case(learned, cfg)
    assert a.layout is not None and b.layout is not None
    assert canonical_json(a.layout) == canonical_json(b.layout)


def test_R804_rule_off_in_config_but_learned_depth_applies() -> None:
    cfg = config(max_depth_m=None)
    _, off = _case(BASE, cfg)
    assert off.layout is not None and codes(off.layout)["FACADE_DEPTH"] == 0
    _, real = _case(with_depth(BASE, "office", 5.4), cfg)
    assert real.layout is not None
    assert [v.instance_ids for v in real.layout.metrics.violations if v.code == "FACADE_DEPTH"] == [
        ("a",)
    ]


def test_R802_type_without_learned_depth_uses_config() -> None:
    cfg = config()
    # a rulebook whose office has fields None (e.g. fewer than 5 samples) behaves as before
    rulebook = BASE.model_copy(
        update={
            "types": {
                **BASE.types,
                "office": BASE.types["office"].model_copy(update={"n_facade_samples": 3}),
            }
        }
    )
    assert Consts.from_config(cfg, rulebook).type_dmax == ()
    _, a = _case(BASE, cfg)
    _, b = _case(rulebook, cfg)
    assert a.layout is not None and b.layout is not None
    assert canonical_json(a.layout) == canonical_json(b.layout)


def test_R805_no_learned_depth_is_byte_identical() -> None:
    for cfg in (config(), config(hard=True), config(max_depth_m=None), AleConfig()):
        for height in (22, 24, 26):
            _, real = _case(BASE, cfg, height)
            twin = BASE.model_copy(update={"version": BASE.version})
            _, same = _case(twin, cfg, height)
            assert (real.layout is None) == (same.layout is None)
            if real.layout is not None and same.layout is not None:
                assert canonical_json(real.layout) == canonical_json(same.layout)
    # the serialised rulebook carries none of the R.8 keys
    text = canonical_json(BASE).decode()
    assert "depth_m" not in text and "facade_width_m" not in text and "n_facade" not in text


def test_R804_fast_cache_matches_realize_and_guards_rulebook() -> None:
    cfg = config()
    learned = with_depth(BASE, "office", 5.4)
    prep, real = _case(learned, cfg)
    cache = RealizeCache(prep, cfg, learned)
    fast = cache.realize(one_piece([rb("a")], [rb("b")]), learned)
    assert real.layout is not None and fast.layout is not None
    assert canonical_json(real.layout) == canonical_json(fast.layout)
    with pytest.raises(ValueError, match="learned depth"):
        cache.realize(one_piece([rb("a")], [rb("b")]), BASE)
