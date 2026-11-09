"""Ticket Q.2 eval G801-G802: realisation of the inner connector (contracts 1.3.0).

Note on G801: the literal footprint 120 x 116 has two bands of depth 58, i.e. block depth
46, where a 12 m² room cannot be exactly 30 wide (30 x 46 ≠ 1200); the band descent settles
at block depths 48 / 44, so the connector lies at x = 28, not 30 (same counting slip as the
3.3b N01 spec issue: ``2 x (12 + 40) = 104``). The literal ``x = 30`` is kept as a strict
xfail; every other G801 condition is asserted on the literal footprint, and the full G801
(``u_c = 30``) on the corrected footprint 120 x 104.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import pytest
from geometry_helpers import (
    AnyBay,
    band,
    fb,
    load_test_rulebook,
    prepared_poly,
    prepared_rect,
    rb,
    rect_tuple,
    room,
)
from grammar_gen import MIN_SIDE, S, _block, _depths, _Ids, _rooms
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from ale.config import AleConfig
from ale.contracts.corridor_plan import (
    BandPlan,
    BlockPlan,
    ConnectorBay,
    CorridorPlan,
    FingerBay,
    PiecePlan,
)
from ale.contracts.geometry import ModuleRect
from ale.contracts.models import RoomSpec
from ale.geometry import Realization, check_layout, realize
from ale.geometry.blocks import BlockOut, Consts, Solver
from ale.geometry.checks import share_length
from ale.program import PreparedInput

SETTINGS: dict[str, Any] = {
    "max_examples": 150,
    "derandomize": True,
    "deadline": None,
    "suppress_health_check": [HealthCheck.too_slow, HealthCheck.filter_too_much],
}
CONFIG = AleConfig()
RULEBOOK = load_test_rulebook()
M = ConnectorBay()

Bay = AnyBay | ConnectorBay


def _inner(bands: list[BandPlan]) -> CorridorPlan:
    return CorridorPlan(pieces=(PiecePlan(bands=tuple(bands), connector="inner"),))


def _band(a: list[Bay], b: list[Bay]) -> BandPlan:
    return BandPlan(block_a=BlockPlan(bays=tuple(a)), block_b=BlockPlan(bays=tuple(b)))


def _g801(width: int, height: int) -> tuple[Realization, PreparedInput]:
    prepared = prepared_rect(width, height, [room(r, 12.0) for r in ("r1", "r2", "r3")])
    plan = _inner([_band([M], [rb("r1"), M, rb("r2")]), _band([M], [rb("r3"), M])])
    return realize(prepared, plan, RULEBOOK, CONFIG), prepared


def _g801_common(real: Realization, prepared: PreparedInput, length: int, depth: int) -> int:
    """G801 conditions other than the value of ``u_c``; returns ``u_c``."""
    layout = real.layout
    assert layout is not None, real.failures
    assert check_layout(layout, prepared, CONFIG) == ()
    circ = [rect_tuple(c) for c in layout.circulation]
    u_c, y, w, h = circ[0]  # circ-001 = the connector
    assert (y, w, h) == (0, S, depth)
    rooms = {p.instance_id: rect_tuple(p) for p in layout.rooms}
    # Band 0 block B: r1 before the connector, r2 right after it; band 1: r3 before it.
    assert rooms["r1"][0] == 0
    assert rooms["r2"][0] == u_c + S
    assert rooms["r3"][0] == 0
    assert u_c == max(rooms["r1"][2], rooms["r3"][2])
    # Band 1's second segment (block B after the marker) is an end strip up to L.
    (d_a0, d_b0), (d_a1, d_b1) = real.depths
    b1_y = d_a0 + S + d_b0 + d_a1 + S
    assert (u_c + S, b1_y, length - u_c - S, d_b1) in circ
    # Spines run the full length, crossing the connector (two segments per band).
    spines = [c for c in circ if c[3] == S and c[2] != S]
    assert sum(c[2] for c in spines) == 2 * (length - S)
    # Exact tiling.
    total = sum(p.rect.area_cells() for p in (*layout.rooms, *layout.circulation))
    assert total == length * depth
    return u_c


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Spec issue: 120 x 116 gives two bands of depth 58 (block depth 46); 30 x 46 is not "
        "12 m², and the band descent settles at 48 / 44, so u_c = 28 (module note)."
    ),
)
def test_G801_inner_exact() -> None:
    real, prepared = _g801(120, 116)
    assert _g801_common(real, prepared, 120, 116) == 30


def test_G801_inner_exact_literal_rest() -> None:
    real, prepared = _g801(120, 116)
    assert _g801_common(real, prepared, 120, 116) == 28
    assert real.depths == ((0, 48), (0, 44))


def test_G801_inner_exact_corrected() -> None:
    """G801 on 120 x 104 (block depth 40, where a 12 m² room is exactly 30 x 40)."""
    real, prepared = _g801(120, 104)
    assert _g801_common(real, prepared, 120, 104) == 30
    assert real.layout is not None
    rooms = {p.instance_id: rect_tuple(p) for p in real.layout.rooms}
    assert rooms == {"r1": (0, 12, 30, 40), "r2": (42, 12, 30, 40), "r3": (0, 64, 30, 40)}
    circ = [rect_tuple(c) for c in real.layout.circulation]
    # Numbering: connector, band 0 spine segments, band 0 block B end strip, band 1 spine
    # segments, band 1 block B end strip.
    assert circ == [
        (30, 0, 12, 104),
        (0, 0, 30, 12),
        (42, 0, 78, 12),
        (72, 12, 48, 40),
        (0, 52, 30, 12),
        (42, 52, 78, 12),
        (42, 64, 78, 40),
    ]


# ------------------------------------------------------------------------------ G802
@dataclass
class InnerCase:
    points: list[tuple[int, int]]
    rooms: list[RoomSpec]
    plan: CorridorPlan
    cells: dict[str, int] = field(default_factory=dict)
    axis: str = "X"


def _equal(total: int, n: int) -> list[int]:
    depths = [total // n] * n
    depths[-1] += total - n * (total // n)
    return depths


@st.composite
def inner_cases(draw: st.DrawFn) -> InnerCase:
    """A valid inner-connector layout first (2-4 bands, markers anywhere), program after."""
    n = draw(st.integers(2, 4))
    depth = draw(st.integers(n * 3 * MIN_SIDE, min(200 * n, 400)))
    length = draw(st.integers(max(80, depth), max(400, depth)))
    u_c = draw(st.integers(0, length - S - MIN_SIDE))
    ids = _Ids()
    bands: list[BandPlan] = []
    for d in _equal(depth, n):
        assume(d >= 3 * MIN_SIDE)
        want_a, want_b, d_a = _depths(draw, d)
        d_b = d - S - d_a
        blocks: list[list[Bay]] = []
        for want, dd in ((want_a, d_a), (want_b, d_b)):
            if not want or dd < MIN_SIDE:
                blocks.append([M])
                continue
            pre = _block(draw, u_c, dd, ids)[0] if u_c >= MIN_SIDE else []
            post = _block(draw, length - u_c - S, dd, ids)[0]
            assume(pre or post)
            blocks.append([*pre, M, *post])
        bands.append(_band(blocks[0], blocks[1]))
    assume(ids.cells)
    points = [(0, 0), (length, 0), (length, depth), (0, depth)]
    axis = "X"
    if length != depth and draw(st.booleans()):
        points = [(0, 0), (depth, 0), (depth, length), (0, length)]
        axis = "Y"
    return InnerCase(points, _rooms(ids), _inner(bands), ids.cells, axis)


def _connected(rects: list[ModuleRect]) -> bool:
    seen = {0}
    todo = [0]
    while todo:
        i = todo.pop()
        for j, r in enumerate(rects):
            if j not in seen and share_length(rects[i], r) >= 1:
                seen.add(j)
                todo.append(j)
    return len(seen) == len(rects)


@settings(**SETTINGS)
@given(inner_cases())
def test_G802_inner_inverse(case: InnerCase) -> None:
    prepared = prepared_poly(case.points, case.rooms, RULEBOOK)
    real = realize(prepared, case.plan, RULEBOOK, CONFIG)
    assert real.failures == (), real.failures
    layout = real.layout
    assert layout is not None
    assert check_layout(layout, prepared, CONFIG) == ()
    placed = {p.instance_id: p.rect.area_cells() for p in layout.rooms}
    assert placed == case.cells  # zero overshoot
    circ = [c.rect for c in layout.circulation]
    assert _connected(circ)
    length, depth = (case.points[1][0], case.points[2][1])
    if case.axis == "Y":
        length, depth = depth, length
    conn = circ[0]  # the connector spans the piece depth
    u_c = conn.x if case.axis == "X" else conn.y
    assert conn == _abs(case.axis, u_c, 0, S, depth)
    # Every band spine runs the full length in two segments that touch the connector.
    v0 = 0
    for d_a, d_b in real.depths:
        for a, b in ((0, u_c), (u_c + S, length)):
            if b > a:
                seg = _abs(case.axis, a, v0 + d_a, b - a, S)
                assert seg in circ
                assert share_length(seg, conn) == S
        v0 += d_a + S + d_b
    assert v0 == depth


def _abs(axis: str, u: int, v: int, du: int, dv: int) -> ModuleRect:
    return ModuleRect(u, v, du, dv) if axis == "X" else ModuleRect(v, u, dv, du)


# ------------------------------------------------------------------------------ units
def test_inner_filler_and_marker_only_block() -> None:
    """A block whose bays end before u_c gets a filler strip touching the spine; a block
    holding only the marker is filler + end strip."""
    prepared = prepared_rect(160, 104, [room("big", 20.0), room("small", 12.0)])
    plan = _inner([_band([M], [rb("big"), M]), _band([M], [rb("small"), M])])
    real = realize(prepared, plan, RULEBOOK, CONFIG)
    layout = real.layout
    assert layout is not None, real.failures
    assert check_layout(layout, prepared, CONFIG) == ()
    rooms = {p.instance_id: rect_tuple(p) for p in layout.rooms}
    u_c = rooms["big"][2]
    assert rect_tuple(layout.circulation[0])[0] == u_c
    small = rooms["small"]
    assert small[2] < u_c
    circ = [rect_tuple(c) for c in layout.circulation]
    assert (small[2], small[1], u_c - small[2], small[3]) in circ  # filler strip


def test_inner_overflow_from_other_block() -> None:
    """A block that fits alone overflows once another block pushes the connector."""
    prepared = prepared_rect(100, 104, [room(f"r{i}", 12.0) for i in range(4)])
    # Band 0 block B: two rooms before the marker (u_c = 60); band 1 block B: one room
    # after the marker, plus one before: 30 + 12 + 30 = 72 alone, 60 + 12 + 30 = 102 > 100.
    plan = _inner([_band([M], [rb("r0"), rb("r1"), M]), _band([M], [rb("r2"), M, rb("r3")])])
    real = realize(prepared, plan, RULEBOOK, CONFIG)
    assert real.layout is None
    over = [f for f in real.failures if f.code == "PLAN_OVERFLOW"]
    assert over, real.failures
    assert any("band 1 block B" in f.detail for f in over)


def test_inner_block_own_overflow_reported_in_full() -> None:
    """Block-level and piece-level overflow amounts add up to the true overflow."""
    prepared = prepared_rect(90, 104, [room(f"r{i}", 12.0) for i in range(5)])
    plan = _inner(
        [_band([M], [rb("r0"), rb("r1"), M]), _band([M], [rb("r2"), M, rb("r3"), rb("r4")])]
    )
    real = realize(prepared, plan, RULEBOOK, CONFIG)
    assert real.layout is None
    amounts = [
        int(f.detail.split("over by ")[1].split()[0])
        for f in real.failures
        if f.code == "PLAN_OVERFLOW" and "band 1 block B" in f.detail
    ]
    # Its own layout (r2, marker, r3, r4) overflows; the connector pushed by band 0 adds
    # a second failure for the rest (u_c - its own width before the marker).
    assert len(amounts) == 2
    assert all(a > 0 for a in amounts)


def test_inner_finger_bays_and_axis_y() -> None:
    """Finger bays on both sides of the marker, spine axis Y."""
    rooms = [room(f"s{i}", 6.0) for i in range(4)] + [room("o1", 12.0), room("o2", 12.0)]
    prepared = prepared_poly([(0, 0), (104, 0), (104, 200), (0, 200)], rooms)
    plan = _inner(
        [
            _band([M], [fb(["s0"], ["s1"]), M, rb("o1")]),
            _band([rb("o2"), M], [M, fb(["s2"], ["s3"])]),
        ]
    )
    real = realize(prepared, plan, RULEBOOK, CONFIG)
    assert real.layout is not None, real.failures
    assert check_layout(real.layout, prepared, CONFIG) == ()
    conn = real.layout.circulation[0].rect
    assert (conn.w, conn.h) == (104, S)


def test_block_marker_items() -> None:
    """``Solver.block`` with a marker and :meth:`BlockOut.placed`."""
    k = Consts.from_config(CONFIG)
    prepared = prepared_rect(200, 104, [room("a", 12.0), room("b", 12.0)])
    reqs = {iid: k.req(spec) for iid, spec in prepared.instances}
    solver = Solver(k, reqs)
    out = solver.block((rb("a"), M, rb("b")), 40, 200, "x")
    assert (out.marker, out.post, out.split) == (30, 30, 1)
    items = out.placed(50, 200, S)
    kinds = sorted((it.kind, it.u, it.du) for it in items)
    assert kinds == [
        ("end_strip", 92, 108),
        ("filler", 30, 20),
        ("room", 0, 30),
        ("room", 62, 30),
    ]
    assert out.placed(None, 200, S) is out.items
    empty = solver.block((M,), 40, 200, "x")
    assert empty.marker == 0
    assert sorted((it.kind, it.u, it.du) for it in empty.placed(30, 200, S)) == [
        ("end_strip", 42, 158),
        ("filler", 0, 30),
    ]
    assert solver.block((M,), 0, 200, "x").placed(30, 200, S) == []
    assert BlockOut(depth=40).placed(10, 200, S) == []
    assert math.isfinite(float(out.dev()))


def test_inner_junction_after_marker_j1() -> None:
    """J1 primary with an inner connector: the junction finger after the marker is
    re-aligned with the final connector position (realise never raises)."""
    points = [(0, 0), (300, 0), (300, 160), (200, 160), (200, 300), (0, 300)]
    from ale.contracts.footprint import decompose_footprint
    from ale.contracts.geometry import ModulePolygon

    fp = decompose_footprint(ModulePolygon(exterior=tuple(points)))
    rooms = [room(f"r{i}", 12.0) for i in range(8)] + [room("big1", 60.0), room("big2", 30.0)]
    prepared = prepared_poly(points, rooms)
    if fp.junction != "J1" or fp.facing_block != "B":  # pragma: no cover - chosen footprint
        pytest.skip("not a J1 footprint facing B")
    bands = [
        _band([rb("r3"), rb("r4"), M], [M, rb("r5"), rb("r6")]),
        _band([rb("r7"), M], [rb("r0"), M, rb("r1"), FingerBay(junction=True), rb("r2")]),
    ]
    sec = PiecePlan(bands=(band([rb("big1")], [rb("big2")]),))
    plan = CorridorPlan(pieces=(PiecePlan(bands=tuple(bands), connector="inner"), sec))
    problems = plan.check_against([iid for iid, _ in prepared.instances], fp)
    assert problems == ()
    real = realize(prepared, plan, RULEBOOK, CONFIG)
    assert real.layout is not None, real.failures
    assert check_layout(real.layout, prepared, CONFIG) == ()
    # The secondary spine meets a finger of the primary (the junction finger).
    circ = [c.rect for c in real.layout.circulation]
    secondary = fp.pieces[1]
    spines = [c for c in circ if c.y >= secondary.rect.y and c.x >= secondary.rect.x]
    assert any(share_length(c, f) >= S for c in spines for f in circ if f.x < secondary.rect.x)
