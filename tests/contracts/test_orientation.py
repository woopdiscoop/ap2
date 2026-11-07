"""Tests O01-O04: compass bearings, bins and outward normals."""

from __future__ import annotations

import pytest

from ale.contracts.enums import Bearing
from ale.contracts.geometry import ModulePolygon
from ale.contracts.orientation import bearing_bin, compass_bearing_deg, edge_outward_normals


@pytest.mark.parametrize(
    ("dx", "dy", "expected"), [(0, 1, 0.0), (1, 0, 90.0), (0, -1, 180.0), (-1, 0, 270.0)]
)
def test_O01_bearings_north_up(dx: float, dy: float, expected: float) -> None:
    b = compass_bearing_deg(dx, dy, 0.0)
    assert b == pytest.approx(expected, abs=1e-9)
    assert 0.0 <= b < 360.0


def test_O02_bearings_rotated() -> None:
    assert compass_bearing_deg(1, 0, 90) == pytest.approx(0.0, abs=1e-9)
    assert compass_bearing_deg(0, 1, 90) == pytest.approx(270.0, abs=1e-9)
    assert compass_bearing_deg(0, 1, 30) == pytest.approx(330.0, abs=1e-9)
    assert 0.0 <= compass_bearing_deg(0, 1, 1e-14) < 360.0  # wrap guard near 360


@pytest.mark.parametrize(
    ("deg", "expected"),
    [
        (0, Bearing.N),
        (44.999, Bearing.N),
        (45, Bearing.E),
        (134.9, Bearing.E),
        (135, Bearing.S),
        (225, Bearing.W),
        (314.9, Bearing.W),
        (315, Bearing.N),
        (359.99, Bearing.N),
        (360, Bearing.N),
        (-90, Bearing.W),
    ],
)
def test_O03_bins(deg: float, expected: Bearing) -> None:
    assert bearing_bin(deg) is expected


def test_O04_normals() -> None:
    poly = ModulePolygon(exterior=((0, 0), (4, 0), (4, 3), (0, 3)))
    assert edge_outward_normals(poly) == ((0, -1), (1, 0), (0, 1), (-1, 0))
