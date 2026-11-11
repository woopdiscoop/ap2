"""Tests N03-N05 (Ticket G.1): exact plans in orthogonal footprints of several pieces."""

from __future__ import annotations

import sys
from functools import cache
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from g1_shapes import COMB, H, T, U, Z, p25, p25_ring  # noqa: E402
from geometry_helpers import band, load_test_rulebook, prepared_poly, rb, room  # noqa: E402

from ale.config import AleConfig  # noqa: E402
from ale.contracts.corridor_plan import CorridorPlan, FingerBay, PiecePlan  # noqa: E402
from ale.contracts.footprint import decompose_footprint  # noqa: E402
from ale.contracts.geometry import ModuleRect  # noqa: E402
from ale.geometry import realize  # noqa: E402
from ale.geometry.blocks import Consts  # noqa: E402
from ale.geometry.checks import check_layout, share_length  # noqa: E402
from ale.program.models import PreparedInput  # noqa: E402
from ale.topology import SeedResult, seed_plan  # noqa: E402

RULEBOOK = load_test_rulebook()
CFG = AleConfig()
K = Consts.from_config(CFG)
SEED_ATTEMPTS = 40


@cache
def seeded(name: str) -> tuple[PreparedInput, SeedResult]:
    shapes: dict[str, Any] = {"U": U, "T": T, "comb": COMB, "H": H}
    prep = p25_ring() if name == "ring" else p25(shapes[name])
    return prep, seed_plan(prep, RULEBOOK, CFG, seed=3, max_attempts=SEED_ATTEMPTS)


@pytest.mark.parametrize("name", ["U", "T", "comb", "ring", "H"])
def test_N03_realise(name: str) -> None:
    prep, res = seeded(name)
    assert res.realization.failures == ()
    layout = res.realization.layout
    assert layout is not None
    assert check_layout(layout, prep, CFG) == ()
    fp = decompose_footprint(prep.footprint.polygon)
    assert len(res.plan.pieces) == len(fp.pieces) >= 2
    # every piece got rooms, and the tiling covers the footprint exactly
    assert sum(r.rect.area_cells() for r in (*layout.rooms, *layout.circulation)) == (
        prep.footprint.polygon.area_cells()
    )
    assert res.plan.check_against([iid for iid, _ in prep.instances], fp) == ()


def _rect_of(piece_rect: ModuleRect, r: ModuleRect) -> bool:
    return piece_rect.intersection_cells(r) == r.area_cells()


@pytest.mark.parametrize("name", ["U", "comb", "ring", "H"])
def test_N04_circulation(name: str) -> None:
    prep, res = seeded(name)
    layout = res.realization.layout
    assert layout is not None
    circ = [c.rect for c in layout.circulation]
    # one connected set (independent flood fill, door-width contact is not required)
    seen = {0}
    todo = [0]
    while todo:
        i = todo.pop()
        for j, other in enumerate(circ):
            if j not in seen and share_length(circ[i], other) >= 1:
                seen.add(j)
                todo.append(j)
    assert len(seen) == len(circ)
    # it reaches every piece, and every room touches it with contact >= c
    fp = decompose_footprint(prep.footprint.polygon)
    for piece in fp.pieces:
        assert any(_rect_of(piece.rect, c) for c in circ)
    for room_ in layout.rooms:
        assert max(share_length(room_.rect, c) for c in circ) >= K.c, room_.instance_id


def _spine_extent(rects: list[ModuleRect], piece_rect: ModuleRect, axis: str) -> list[ModuleRect]:
    """Circulation rectangles of a piece that are ``s`` wide across its spine axis and run its
    whole length along it (spine strips)."""
    out = []
    for c in rects:
        if not _rect_of(piece_rect, c):
            continue
        if axis == "X" and c.h == K.s and c.w == piece_rect.w:
            out.append(c)
        if axis == "Y" and c.w == K.s and c.h == piece_rect.h:
            out.append(c)
    return out


def test_N05_multi_junction() -> None:
    prep, res = seeded("comb")
    fp = decompose_footprint(prep.footprint.polygon)
    assert [j.kind for j in fp.junctions] == ["J1", "J1", "J1"]
    assert {j.parent for j in fp.junctions} == {0}
    fingers = [
        bay
        for band_ in res.plan.pieces[0].bands
        for block in (band_.block_a, band_.block_b)
        for bay in block.bays
        if isinstance(bay, FingerBay) and bay.junction
    ]
    assert sorted(f.junction_to or 0 for f in fingers) == [1, 2, 3]
    layout = res.realization.layout
    assert layout is not None
    circ = [c.rect for c in layout.circulation]
    root = fp.pieces[0].rect
    for j in fp.junctions:
        child = fp.pieces[j.child]
        spines = _spine_extent(circ, child.rect, child.spine_axis)
        assert len(spines) == 1
        spine = spines[0]
        # a finger of the root, as wide as the spine, in line with it and touching the cut
        y = j.cut[0][1]
        aligned = [
            c
            for c in circ
            if _rect_of(root, c)
            and c.w == spine.w
            and c.x == spine.x
            and y in (c.y, c.y2())
            and c.h > spine.w
        ]
        assert aligned, f"no junction finger aligned with the spine of piece {j.child}"


def test_N05_u_chain_and_h_j2() -> None:
    """A U (two J1 in a chain) and an H (J1 then a J2 with collinear spines) realise."""
    for name in ("U", "H"):
        prep, res = seeded(name)
        fp = decompose_footprint(prep.footprint.polygon)
        layout = res.realization.layout
        assert layout is not None
        kinds = [j.kind for j in fp.junctions]
        assert kinds == (["J1", "J1"] if name == "U" else ["J1", "J2"])
        for j in fp.junctions:
            if j.kind != "J2":
                continue
            a, b = fp.pieces[j.parent], fp.pieces[j.child]
            circ = [c.rect for c in layout.circulation]
            sa = _spine_extent(circ, a.rect, a.spine_axis)
            sb = _spine_extent(circ, b.rect, b.spine_axis)
            assert sa and sb
            # collinear: the same absolute band across the shared cut
            assert any(x.y == y.y and x.h == y.h for x in sa for y in sb)


# ------------------------------------------------------------------- failure paths (hand plans)
def _tree_plan(root: PiecePlan, *others: PiecePlan) -> CorridorPlan:
    return CorridorPlan(pieces=(root, *others))


def _one(a: list[Any], b: list[Any]) -> PiecePlan:
    return PiecePlan(bands=(band(a, b),))


def test_junction_outside_cut_is_reported_and_child_still_realised() -> None:
    """A finger that is not inside its cut is a JUNCTION_MISALIGNED failure (the child is
    nevertheless realised at the nearest depth, so its own problems are reported too)."""
    prep = prepared_poly(
        list(COMB), [room("a", 12.0), room("b", 12.0), room("c", 12.0), room("d", 12.0)]
    )
    fp = decompose_footprint(prep.footprint.polygon)
    assert len(fp.pieces) == 4
    plan = _tree_plan(
        _one(
            [rb("a")],
            [
                FingerBay(junction=True, junction_to=1),
                rb("b"),
                FingerBay(junction=True, junction_to=2),
                FingerBay(junction=True, junction_to=3),
            ],
        ),
        _one([rb("c")], []),
        _one([], [rb("d")]),
        _one([], []),
    )
    real = realize(prep, plan, RULEBOOK, CFG)
    assert real.layout is None
    assert "JUNCTION_MISALIGNED" in {f.code for f in real.failures}
    assert len(real.depths) == 4  # every piece reported, none hidden by the misalignment


def test_tree_plan_rejections_reach_realize() -> None:
    prep = prepared_poly(list(Z), [room("a", 12.0)])
    # Z is a two-piece J1 footprint; a tree plan with a missing finger is PLAN_INVALID.
    plan = _tree_plan(_one([rb("a")], []), _one([], []))
    real = realize(prep, plan, RULEBOOK, CFG)
    assert [f.code for f in real.failures] == ["PLAN_INVALID"]


def test_two_band_root_with_fingers_and_inner_connector() -> None:
    """A comb whose base is deep enough for two bands: the plan realises; with an ``inner``
    connector the fingers are re-aligned with the final connector position."""
    from ale.topology.seed import _Search, with_inner

    pts = (
        (0, 0), (300, 0), (300, 260), (230, 260), (230, 200), (185, 200),
        (185, 260), (115, 260), (115, 200), (70, 200), (70, 260), (0, 260),
    )  # fmt: skip
    prep = p25(pts)
    res = seed_plan(prep, RULEBOOK, CFG, seed=3, max_attempts=SEED_ATTEMPTS)
    layout = res.realization.layout
    assert layout is not None and check_layout(layout, prep, CFG) == ()
    assert [len(p.bands) for p in res.plan.pieces] == [2, 1, 1, 1]
    search = _Search(prep, RULEBOOK, CFG, decompose_footprint(prep.footprint.polygon), 3)
    inner = with_inner(res.plan, [0], search.ctx)
    real = realize(prep, inner, RULEBOOK, CFG)
    assert len(real.depths) == 5  # 2 bands + 3 fingers' pieces, none hidden
    assert "JUNCTION_MISALIGNED" not in {f.code for f in real.failures}


def test_greedy_plan_is_for_one_or_two_pieces() -> None:
    from ale.geometry.greedy import greedy_plan

    with pytest.raises(ValueError, match="one or two pieces"):
        greedy_plan(p25(U), RULEBOOK, CFG)
