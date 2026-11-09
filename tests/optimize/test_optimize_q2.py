"""Ticket Q.2 eval G803-G805: moves G8-G10 and the façade results of the annealer.

Ticket Q.3: G804 / G805 run on the deterministic quality runs of ``conftest.quality_runs``
(iteration and attempt budgets instead of 15 s); G804 is strict and G805 has no coverage
xfail. ``test_G804_facade_drops`` asserts the drop against the baseline measured before Q.2
(15 ``NO_FACADE`` at the start and the end of the same run).
"""

from __future__ import annotations

import random
from collections import Counter

import pytest
from optimize_helpers import QualityRun

from ale.contracts.corridor_plan import ConnectorBay, CorridorPlan
from ale.contracts.footprint import decompose_footprint
from ale.contracts.geometry import ModulePolygon
from ale.contracts.models import Rulebook
from ale.geometry import realize
from ale.optimize import MoveContext
from ale.optimize.anneal import focus_on
from ale.optimize.moves import (
    g7_split_merge,
    g8_move_marker,
    g9_facade_pull,
    g10_switch_connector,
)
from ale.program.models import PreparedInput
from ale.topology import SeedResult

Seeded = dict[str, tuple[PreparedInput, SeedResult]]
ANNEAL_SEED = 6  # as 3.4 O03
#: ``NO_FACADE`` of the P60 seed-3 start and of its 15 s annealing before Ticket Q.2.
P60_NO_FACADE_BEFORE = 15


def _valid(new: CorridorPlan, ctx: MoveContext) -> None:
    again = CorridorPlan.model_validate(new.model_dump())
    assert again == new
    assert new.check_against(ctx.instance_ids, ctx.footprint) == ()


def _markers(plan: CorridorPlan) -> int:
    return sum(
        isinstance(bay, ConnectorBay)
        for piece in plan.pieces
        for band in piece.bands
        for block in (band.block_a, band.block_b)
        for bay in block.bays
    )


def _two_band(prep: PreparedInput, plan: CorridorPlan, ctx: MoveContext) -> CorridorPlan:
    """A multi-band variant of ``plan`` (G7 splits until one applies)."""
    rng = random.Random(5)
    for _ in range(200):
        new = g7_split_merge(plan, ctx, rng)
        if new is not None and len(new.pieces[0].bands) >= 2:
            return new
    raise AssertionError("no split applied")  # pragma: no cover


# ------------------------------------------------------------------------------ G803
def test_G803_moves(seeded: Seeded) -> None:
    moves = {"G8": g8_move_marker, "G9": g9_facade_pull, "G10": g10_switch_connector}
    applied: Counter[str] = Counter()
    inner_seen = 0
    for name in ("P25", "P60"):
        prep, res = seeded[name]
        ctx = MoveContext.from_prepared(prep)
        layout = res.realization.layout
        assert layout is not None
        ctx = focus_on(ctx, layout, 24)
        plan = res.plan if name == "P60" else _two_band(prep, res.plan, ctx)
        zones0 = len(plan.zone_violations(ctx.zone_of))
        rng = random.Random(2026)
        for _ in range(1000):
            key = rng.choice(sorted(moves))
            new = moves[key](plan, ctx, rng)
            if new is None:
                continue
            _valid(new, ctx)
            assert len(new.zone_violations(ctx.zone_of)) <= zones0
            for piece in new.pieces:
                n_blocks = 2 * len(piece.bands)
                got = sum(
                    isinstance(bay, ConnectorBay)
                    for band in piece.bands
                    for block in (band.block_a, band.block_b)
                    for bay in block.bays
                )
                assert got == (n_blocks if piece.connector == "inner" else 0)
            inner_seen += any(p.connector == "inner" for p in new.pieces)
            applied[key] += 1
            plan = new
    assert set(applied) == set(moves), applied
    assert inner_seen


def test_G803_g10_round_trip(seeded: Seeded) -> None:
    prep, res = seeded["P25"]
    ctx = MoveContext.from_prepared(prep)
    start = _two_band(prep, res.plan, ctx)
    start = start.model_copy(
        update={"pieces": (start.pieces[0].model_copy(update={"connector": "start"}),)}
    )
    rng = random.Random(1)
    inner = None
    for _ in range(100):
        inner = g10_switch_connector(start, ctx, rng)
        if inner is not None and inner.pieces[0].connector == "inner":
            break
    assert inner is not None and inner.pieces[0].connector == "inner"
    assert _markers(inner) == 2 * len(inner.pieces[0].bands)
    back = None
    for _ in range(100):
        back = g10_switch_connector(inner, ctx, rng)
        if back is not None and back.pieces[0].connector == "start":
            break
    assert back == start


def _ctx(zones: dict[str, str], facade: dict[str, bool], areas: dict[str, float]) -> MoveContext:
    poly = ModulePolygon.model_validate({"exterior": [[0, 0], [400, 0], [400, 300], [0, 300]]})
    return MoveContext(
        instance_ids=tuple(zones),
        zone_of=zones,  # type: ignore[arg-type]
        area_of=areas,
        footprint=decompose_footprint(poly),
        facade=facade,
    )


def _plan(bands: list[tuple[list[object], list[object]]], connector: str) -> CorridorPlan:
    return CorridorPlan.model_validate(
        {
            "pieces": [
                {
                    "bands": [{"block_a": {"bays": a}, "block_b": {"bays": b}} for a, b in bands],
                    "connector": connector,
                }
            ]
        }
    )


def room(r: str) -> dict[str, str]:
    return {"kind": "room", "room": r}


MARK = {"kind": "connector"}


def test_g8_moves_marker_by_one_bay() -> None:
    ids = ["a", "b", "c", "d"]
    ctx = _ctx(
        dict.fromkeys(ids, "ADMINISTRATIVE"), dict.fromkeys(ids, False), dict.fromkeys(ids, 10.0)
    )
    plan = _plan(
        [([room("a"), MARK, room("b")], [MARK]), ([MARK], [room("c"), room("d"), MARK])], "inner"
    )
    rng = random.Random(3)
    seen = set()
    for _ in range(100):
        new = g8_move_marker(plan, ctx, rng)
        if new is None:
            continue
        _valid(new, ctx)
        assert _markers(new) == 4
        seen.add(new)
    # a|M|b → M a b or a b M; c d M → c M d (the empty blocks cannot move).
    assert len(seen) == 3
    no_inner = _plan([([room("a"), room("b")], []), ([], [room("c"), room("d")])], "start")
    assert g8_move_marker(no_inner, ctx, rng) is None


def test_g9_facade_pull() -> None:
    zones = {"f1": "ADMINISTRATIVE", "n1": "ADMINISTRATIVE", "n2": "SERVICES", "x": "SERVICES"}
    facade = {"f1": True, "n1": False, "n2": False, "x": False}
    areas = dict.fromkeys(zones, 10.0)
    ctx = _ctx(zones, facade, areas)
    # Band 0 block A and band 1 block B are exterior; f1 sits in band 0 block B (inner).
    plan = _plan([([room("n1"), room("n2")], [room("f1")]), ([room("x")], [])], "start")
    rng = random.Random(4)
    news = {g9_facade_pull(plan, ctx, rng) for _ in range(50)} - {None}
    assert news
    for new in news:
        assert new is not None
        _valid(new, ctx)
        # Same zone preferred: f1 swaps with n1 (ADMINISTRATIVE), never with n2.
        assert new.locate("f1").block == "A" and new.locate("f1").band == 0
        assert new.locate("n1").block == "B"
    # Known lacking rooms come from the context; partners include on-facade rooms.
    known = ctx.with_no_facade(["f1"]).with_on_facade(["x"])
    assert known.no_facade == ("f1",) and known.on_facade == ("x",)
    assert known.with_no_facade(["f1"]) is known and known.with_on_facade(["x"]) is known
    assert g9_facade_pull(plan, known, rng) is not None
    # Nothing to pull: every façade room is already in an exterior block.
    done = _plan([([room("f1"), room("n2")], [room("n1")]), ([room("x")], [])], "start")
    assert g9_facade_pull(done, ctx, rng) is None
    # No partner: the exterior blocks hold only façade rooms.
    only = {"f1": True, "f2": True, "n1": False}
    ctx2 = _ctx(dict.fromkeys(only, "ADMINISTRATIVE"), only, dict.fromkeys(only, 10.0))
    lone = _plan([([room("f2")], [room("f1")]), ([room("n1")], [])], "start")
    assert g9_facade_pull(lone, ctx2.with_no_facade(["f1"]), rng) is None


def test_g10_and_g7_with_inner() -> None:
    ids = ["a", "b", "c", "d", "e", "f"]
    ctx = _ctx(
        dict.fromkeys(ids, "ADMINISTRATIVE"), dict.fromkeys(ids, False), dict.fromkeys(ids, 10.0)
    )
    one = _plan([([room(r) for r in ids], [])], "none")
    assert g10_switch_connector(one, ctx, random.Random(0)) is None
    inner = _plan(
        [
            ([room("a"), MARK, room("b")], [room("c"), MARK]),
            ([MARK, room("d")], [room("e"), room("f"), MARK]),
        ],
        "inner",
    )
    rng = random.Random(9)
    kinds = set()
    for _ in range(200):
        new = g7_split_merge(inner, ctx, rng)
        if new is None:
            continue
        _valid(new, ctx)
        piece = new.pieces[0]
        expected = 2 * len(piece.bands) if piece.connector == "inner" else 0
        assert _markers(new) == expected
        kinds.add(len(piece.bands))
    assert kinds >= {1, 3}
    switched = {g10_switch_connector(inner, ctx, rng) for _ in range(40)} - {None}
    assert {p.pieces[0].connector for p in switched if p is not None} == {"start", "end"}
    assert all(_markers(p) == 0 for p in switched if p is not None)


def test_g10_respects_j2_cut_side(seeded: Seeded) -> None:
    """P60 (J2, multi-band primary): the primary's connector stays on the cut side."""
    prep, res = seeded["P60"]
    ctx = MoveContext.from_prepared(prep)
    rng = random.Random(11)
    for _ in range(100):
        new = g10_switch_connector(res.plan, ctx, rng)
        if new is not None:
            assert new.pieces[0].connector == res.plan.pieces[0].connector


def test_focus_on(seeded: Seeded) -> None:
    prep, res = seeded["P60"]
    layout = res.realization.layout
    assert layout is not None
    ctx = focus_on(MoveContext.from_prepared(prep), layout, 24)
    lacking = {v.instance_ids[0] for v in layout.metrics.violations if v.code == "NO_FACADE"}
    assert set(ctx.no_facade) == lacking
    assert all(not ctx.facade[r] for r in ctx.on_facade)


# ------------------------------------------------------------------------------ G804-G805
# Ticket Q.3: the quality runs use iteration / attempt budgets (``conftest.quality_runs``),
# so G804 is strict and G805 no longer depends on coverage tracing.
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_G804_facade_P60(quality_runs: dict[str, QualityRun]) -> None:
    assert quality_runs["P60"].after.get("NO_FACADE", 0) <= 6


@pytest.mark.slow
@pytest.mark.timeout(900)
def test_G804_facade_drops(quality_runs: dict[str, QualityRun]) -> None:
    run = quality_runs["P60"]
    assert run.before.get("NO_FACADE", 0) < P60_NO_FACADE_BEFORE
    assert run.after.get("NO_FACADE", 0) < P60_NO_FACADE_BEFORE


@pytest.mark.slow
@pytest.mark.timeout(900)
def test_G805_no_regression(quality_runs: dict[str, QualityRun]) -> None:
    assert quality_runs["P8"].result.final_hard == 0
    assert quality_runs["P25"].result.final_hard <= 6


@pytest.mark.timeout(120)
def test_cached_realize_matches_geometry_inner(seeded: Seeded, rulebook: Rulebook) -> None:
    """The annealer's memoised realisation equals ``realize`` on inner-connector plans."""
    from ale.config import AleConfig
    from ale.optimize import propose
    from ale.optimize.fastreal import RealizeCache

    prep, res = seeded["P25"]
    cfg = AleConfig()
    ctx = MoveContext.from_prepared(prep)
    plan = _two_band(prep, res.plan, ctx)
    rng = random.Random(23)
    for _ in range(50):
        got = g10_switch_connector(plan, ctx, rng)
        if got is not None and got.pieces[0].connector == "inner":
            plan = got
            break
    assert plan.pieces[0].connector == "inner"
    cache = RealizeCache(prep, cfg)
    checked = 0
    for _ in range(600):
        if checked >= 40:
            break
        _, cand = propose(plan, ctx, rng)
        if cand is None or cand.pieces[0].connector != "inner":
            continue
        assert cache.realize(cand, rulebook, seed=4) == realize(prep, cand, rulebook, cfg, seed=4)
        checked += 1
        plan = cand
    assert checked == 40
