"""Orientation helpers: compass bearings (degrees) and outward edge normals (modules)."""

from __future__ import annotations

import math

from ale.contracts.enums import Bearing
from ale.contracts.geometry import ModulePolygon

__all__ = ["bearing_bin", "compass_bearing_deg", "edge_outward_normals"]


def _wrap_deg(a: float) -> float:
    """Reduce an angle in degrees to ``[0, 360)`` without float modulo."""
    b = a - 360.0 * math.floor(a / 360.0)
    if b >= 360.0 or b < 0.0:  # float rounding at the boundaries
        b = 0.0
    return b + 0.0  # normalise -0.0


def compass_bearing_deg(dx: float, dy: float, north_angle_deg: float) -> float:
    """Bearing in degrees ``[0, 360)``, clockwise from true north, of direction ``(dx, dy)``.

    ``(dx, dy)`` is given in drawing coordinates (+y up, any length unit);
    ``north_angle_deg`` is the clockwise angle in degrees from drawing +y to true north.
    """
    drawing_bearing = math.degrees(math.atan2(dx, dy))  # clockwise from drawing +y
    return _wrap_deg(drawing_bearing - north_angle_deg)


def bearing_bin(bearing_deg: float) -> Bearing:
    """Bin a bearing in degrees: N = [315, 45), E = [45, 135), S = [135, 225), W = [225, 315)."""
    b = _wrap_deg(bearing_deg)
    if b >= 315.0 or b < 45.0:
        return Bearing.N
    if b < 135.0:
        return Bearing.E
    if b < 225.0:
        return Bearing.S
    return Bearing.W


def _sign(v: int) -> int:
    return (v > 0) - (v < 0)


def edge_outward_normals(poly: ModulePolygon) -> tuple[tuple[int, int], ...]:
    """Outward unit normals (axis vectors, unitless), one per edge of a CCW polygon.

    Outward = edge direction rotated by -90°: ``(dx, dy) → (dy, -dx)``.
    """
    out: list[tuple[int, int]] = []
    for a, b in poly.edges():
        dx, dy = _sign(b[0] - a[0]), _sign(b[1] - a[1])
        out.append((dy, -dx))
    return tuple(out)
