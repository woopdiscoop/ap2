"""Ticket Q.3 §3.4: ``ale.optimize.fastreal`` equals ``ale.geometry.realize`` on the paths
the annealing fixtures do not reach.

The linked-band path (J2 single-band pieces, J1 junctions) and the early failures, on the
inverse-construction plans of the geometry tests (realisable by construction), with random
``needs_facade`` flags so exterior blocks use the Q.3 narrow widths.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ale.config import AleConfig
from ale.contracts.models import Rulebook
from ale.geometry import realize
from ale.optimize.fastreal import RealizeCache
from ale.program.models import PreparedInput
from ale.topology import SeedResult

_GEOMETRY_TESTS = Path(__file__).resolve().parent.parent / "geometry"
if str(_GEOMETRY_TESTS) not in sys.path:
    sys.path.insert(0, str(_GEOMETRY_TESTS))

from band_gen import band_l_cases  # noqa: E402
from geometry_helpers import (  # noqa: E402
    load_test_rulebook,
    one_piece,
    prepared_poly,
    prepared_rect,
    rb,
    room,
)
from grammar_gen import l_cases  # noqa: E402

Seeded = dict[str, tuple[PreparedInput, SeedResult]]
fastreal_mod = importlib.import_module("ale.optimize.fastreal")
_RULEBOOK = load_test_rulebook()
_CFG = AleConfig()


@st.composite
def _linked(draw: st.DrawFn) -> tuple[Any, list[bool], int]:
    case = draw(
        st.one_of(
            l_cases("J1"),
            l_cases("J2"),
            band_l_cases("j2_single"),
            band_l_cases("j1_primary"),
            band_l_cases("j2_secondary"),
        )
    )
    n = len(case.rooms)
    flags = draw(st.lists(st.booleans(), min_size=n, max_size=n))
    return case, flags, draw(st.integers(0, 3))


def _crowded(plan: Any, shift: int) -> Any:
    """``plan`` with every bay of its first band in block A (rotated by ``shift``)."""
    piece = plan.pieces[0]
    band = piece.bands[0]
    bays = (*band.block_a.bays, *band.block_b.bays)
    moved = band.model_copy(
        update={
            "block_a": band.block_a.model_copy(update={"bays": bays[shift:] + bays[:shift]}),
            "block_b": band.block_b.model_copy(update={"bays": ()}),
        }
    )
    pieces = (piece.model_copy(update={"bands": (moved, *piece.bands[1:])}), *plan.pieces[1:])
    return plan.model_copy(update={"pieces": pieces})


@settings(
    max_examples=60,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
@given(_linked())
def test_cached_realize_matches_on_l_shapes(drawn: tuple[Any, list[bool], int]) -> None:
    case, flags, shift = drawn
    pairs = zip(case.rooms, flags, strict=True)
    rooms = [r.model_copy(update={"needs_facade": f}) for r, f in pairs]
    prep = prepared_poly(case.points, rooms, _RULEBOOK)
    cache = RealizeCache(prep, _CFG)
    for plan in (case.plan, _crowded(case.plan, shift)):
        for _ in range(2):  # cold, then warm cache
            ref = realize(prep, plan, _RULEBOOK, _CFG, seed=2)
            assert cache.realize(plan, _RULEBOOK, seed=2) == ref


def test_cached_realize_early_failures() -> None:
    rooms = [room("a", 12.0), room("b", 12.0)]
    plan = one_piece([rb("a")], [rb("b")])
    # G.1: a U decomposes now; a staircase of 14 steps (14 pieces) is still unsupported.
    u_shape = [(0, 0), (140, 0)]
    for k in range(14):
        u_shape += [(140 - 10 * k, 10 * (k + 1)), (130 - 10 * k, 10 * (k + 1))]
    codes = set()
    for prep in (prepared_poly(u_shape, rooms), prepared_rect(300, 8, rooms)):
        got = RealizeCache(prep, _CFG).realize(plan, _RULEBOOK)
        assert got == realize(prep, plan, _RULEBOOK, _CFG)
        codes.add(got.failures[0].code)
    assert codes == {"FOOTPRINT_UNSUPPORTED", "PIECE_TOO_SMALL"}


def test_cached_realize_memo_bounds(
    seeded: Seeded, rulebook: Rulebook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With tiny memos (cleared on every insert) the result is unchanged."""
    monkeypatch.setattr(fastreal_mod, "_MAX_ENTRIES", 1)
    prep, start = seeded["P60"]
    cache = RealizeCache(prep, _CFG)
    for _ in range(2):
        ref = realize(prep, start.plan, rulebook, _CFG, seed=1)
        assert cache.realize(start.plan, rulebook, seed=1) == ref
