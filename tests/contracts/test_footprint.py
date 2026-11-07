"""Tests F01-F05 (Ticket A.1): footprint decomposition into corridor-grammar pieces."""

from __future__ import annotations

import pytest
import shapely
from pydantic import ValidationError

from ale.contracts.footprint import FootprintPieces, Piece, decompose_footprint
from ale.contracts.geometry import ModulePolygon, ModuleRect, to_shapely

Pts = tuple[tuple[int, int], ...]

SITE_L: Pts = ((0, 0), (480, 0), (480, 180), (300, 180), (300, 300), (0, 300))
J1_L: Pts = ((0, 0), (600, 0), (600, 120), (200, 120), (200, 300), (0, 300))


def decompose(pts: Pts) -> FootprintPieces:
    return decompose_footprint(ModulePolygon(exterior=pts))


def _check_tiling(pts: Pts, out: FootprintPieces) -> None:
    poly = ModulePolygon(exterior=pts)
    rects = [p.rect for p in out.pieces]
    assert sum(r.area_cells() for r in rects) == poly.area_cells()
    if len(rects) == 2:
        assert rects[0].intersection_cells(rects[1]) == 0
    union = shapely.union_all([to_shapely(r) for r in rects])
    assert union.area == poly.area_cells()
    assert union.symmetric_difference(to_shapely(poly)).area == 0


# --------------------------------------------------------------------------- F01


def test_F01_rect() -> None:
    pts: Pts = ((0, 0), (240, 0), (240, 180), (0, 180))
    out = decompose(pts)
    assert out == FootprintPieces(
        pieces=(Piece(rect=ModuleRect(0, 0, 240, 180), spine_axis="X"),),
        junction="NONE",
        cut=None,
        facing_block=None,
    )
    tall = decompose(((10, 20), (110, 20), (110, 320), (10, 320)))
    assert tall.pieces == (Piece(rect=ModuleRect(10, 20, 100, 300), spine_axis="Y"),)
    square = decompose(((0, 0), (200, 0), (200, 200), (0, 200)))
    assert square.pieces[0].spine_axis == "X"
    assert square.junction == "NONE" and square.cut is None and square.facing_block is None
    # Vertex order does not matter as long as the polygon is valid (counter-clockwise).
    rotated = decompose(((240, 180), (0, 180), (0, 0), (240, 0)))
    assert rotated == out


# --------------------------------------------------------------------------- F02 / F03


def test_F02_site_L_J2() -> None:
    out = decompose(SITE_L)
    assert out.pieces == (
        Piece(rect=ModuleRect(0, 0, 300, 300), spine_axis="X"),
        Piece(rect=ModuleRect(300, 0, 180, 180), spine_axis="X"),
    )
    assert out.junction == "J2"
    assert out.cut == ((300, 0), (300, 180))
    assert out.facing_block is None
    _check_tiling(SITE_L, out)


def test_F03_J1() -> None:
    out = decompose(J1_L)
    assert out.pieces == (
        Piece(rect=ModuleRect(0, 0, 200, 300), spine_axis="Y"),
        Piece(rect=ModuleRect(200, 0, 400, 120), spine_axis="X"),
    )
    assert out.junction == "J1"
    assert out.cut == ((200, 0), (200, 120))
    assert out.facing_block == "B"
    _check_tiling(J1_L, out)


def test_F03_J1_variants() -> None:
    # Mirrored J1 (arm on the left): the cut is on the primary's left edge → block A.
    mirrored: Pts = ((0, 0), (600, 0), (600, 300), (400, 300), (400, 120), (0, 120))
    out = decompose(mirrored)
    assert out.pieces == (
        Piece(rect=ModuleRect(400, 0, 200, 300), spine_axis="Y"),
        Piece(rect=ModuleRect(0, 0, 400, 120), spine_axis="X"),
    )
    assert (out.junction, out.cut, out.facing_block) == ("J1", ((400, 0), (400, 120)), "A")
    # Horizontal-cut J1 with a primary along X: cut on the primary's top edge → block B.
    flat: Pts = ((0, 0), (300, 0), (300, 200), (120, 200), (120, 600), (0, 600))
    out = decompose(flat)
    assert out.pieces == (
        Piece(rect=ModuleRect(0, 0, 300, 200), spine_axis="X"),
        Piece(rect=ModuleRect(0, 200, 120, 400), spine_axis="Y"),
    )
    assert (out.junction, out.cut, out.facing_block) == ("J1", ((0, 200), (120, 200)), "B")
    # Same shape upside down: cut on the primary's bottom edge → block A.
    down: Pts = ((0, 0), (120, 0), (120, 400), (300, 400), (300, 600), (0, 600))
    out = decompose(down)
    assert out.pieces == (
        Piece(rect=ModuleRect(0, 400, 300, 200), spine_axis="X"),
        Piece(rect=ModuleRect(0, 0, 120, 400), spine_axis="Y"),
    )
    assert (out.junction, out.cut, out.facing_block) == ("J1", ((0, 400), (120, 400)), "A")
    for pts in (mirrored, flat, down):
        _check_tiling(pts, decompose(pts))


def test_F03_tie_breaks() -> None:
    # Both cuts give max aspect 2 → horizontal cut wins.
    tie: Pts = ((0, 0), (200, 0), (200, 100), (100, 100), (100, 200), (0, 200))
    out = decompose(tie)
    assert out.cut == ((0, 100), (100, 100))
    assert out.pieces[1].spine_axis == "Y"  # perpendicular to a horizontal cut line
    assert out.pieces[0].rect == ModuleRect(0, 0, 200, 100)
    assert out.pieces[1].rect == ModuleRect(0, 100, 100, 100)
    _check_tiling(tie, out)
    # Equal areas (30 000 cells each) → the piece with the smaller (y, x) origin is primary.
    eq: Pts = ((0, 0), (400, 0), (400, 100), (100, 100), (100, 300), (0, 300))
    out = decompose(eq)
    assert [p.rect for p in out.pieces] == [
        ModuleRect(0, 0, 100, 300),
        ModuleRect(100, 0, 300, 100),
    ]


# --------------------------------------------------------------------------- F04


def _mirror_x(pts: Pts) -> Pts:
    return tuple(reversed([(480 - x, y) for x, y in pts]))


def _mirror_y(pts: Pts) -> Pts:
    return tuple(reversed([(x, 300 - y) for x, y in pts]))


def _rot180(pts: Pts) -> Pts:
    return tuple((480 - x, 300 - y) for x, y in pts)


ORIENTATIONS = {
    "identity": SITE_L,
    "mirror_x": _mirror_x(SITE_L),
    "mirror_y": _mirror_y(SITE_L),
    "rot180": _rot180(SITE_L),
}


@pytest.mark.parametrize("name", list(ORIENTATIONS))
def test_F04_rotations(name: str) -> None:
    pts = ORIENTATIONS[name]
    out = decompose(pts)
    assert len(out.pieces) == 2
    assert [p.rect.area_cells() for p in out.pieces] == [90_000, 32_400]
    assert out.junction == "J2"
    assert out.facing_block is None
    assert [p.spine_axis for p in out.pieces] == ["X", "X"]
    assert out.cut is not None and out.cut[0][0] == out.cut[1][0]  # vertical cut
    assert out.cut[0][1] < out.cut[1][1]  # lower endpoint first
    _check_tiling(pts, out)


@pytest.mark.parametrize("quarter", [1, 3])
def test_F04_quarter_turns(quarter: int) -> None:
    # A quarter turn makes the cut horizontal; the square primary keeps its tie axis "X",
    # so the cut is parallel to the primary's spine: J1 under the RD rule.
    pts = SITE_L
    for _ in range(quarter):
        pts = tuple((-y, x) for x, y in pts)
    out = decompose(pts)
    assert [p.rect.area_cells() for p in out.pieces] == [90_000, 32_400]
    assert out.cut is not None and out.cut[0][1] == out.cut[1][1]  # horizontal cut
    assert out.cut[0][0] < out.cut[1][0]  # left endpoint first
    assert out.junction == "J1"
    assert out.pieces[1].spine_axis == "Y"
    _check_tiling(pts, out)


# --------------------------------------------------------------------------- F05


def test_F05_unsupported() -> None:
    u_shape: Pts = (
        (0, 0),
        (300, 0),
        (300, 300),
        (200, 300),
        (200, 100),
        (100, 100),
        (100, 300),
        (0, 300),
    )
    with pytest.raises(ValueError, match="v1 supports rectangular and L-shaped footprints only"):
        decompose(u_shape)


def test_F05_models_strict() -> None:
    with pytest.raises(ValidationError):
        Piece(rect=ModuleRect(0, 0, 1, 1), spine_axis="Z")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        FootprintPieces(
            pieces=(),
            junction="J1",
            cut=((0.0, 0), (0, 1)),  # type: ignore[arg-type]
            facing_block="A",
        )
