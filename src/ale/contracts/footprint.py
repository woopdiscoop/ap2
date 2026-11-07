"""Decomposition of a module footprint into rectangular pieces for the corridor grammar.

A rectangular footprint is one piece. An L-shaped footprint (6 vertices, one reflex vertex)
is cut through its reflex vertex into two rectangles: a *primary* (larger) piece and a
*secondary* piece. ``junction`` says how the corridor crosses the cut:

- ``"J1"``: the cut line is parallel to the primary's spine axis; the corridor turns the
  corner through a junction finger placed in the primary's block that faces the cut
  (``facing_block``).
- ``"J2"``: the cut line is perpendicular to the primary's spine axis; the two spines are
  collinear (both perpendicular to the cut).

Pure integer arithmetic (exact ``Fraction`` aspect ratios); no shapely.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ale.contracts.geometry import ModulePoint, ModulePolygon, ModuleRect

__all__ = ["FootprintPieces", "Piece", "decompose_footprint"]

_CONFIG = ConfigDict(extra="forbid", frozen=True)

SpineAxis = Literal["X", "Y"]

UNSUPPORTED_MESSAGE = "v1 supports rectangular and L-shaped footprints only"


class Piece(BaseModel):
    """Axis-aligned rectangle of the module footprint with the axis of its spine corridor."""

    model_config = _CONFIG

    rect: ModuleRect
    spine_axis: SpineAxis


class FootprintPieces(BaseModel):
    """Result of :func:`decompose_footprint`.

    ``pieces``: primary first (one piece for a rectangle, two for an L). ``cut``: endpoints of
    the shared cut segment (lower/left endpoint first), ``None`` for a rectangle.
    ``facing_block``: J1 only, the block of the primary (``"A"`` lower/left, ``"B"``
    upper/right) that faces the cut.
    """

    model_config = _CONFIG

    pieces: tuple[Piece, ...]
    junction: Literal["NONE", "J1", "J2"]
    cut: tuple[ModulePoint, ModulePoint] | None
    facing_block: Literal["A", "B"] | None


def _long_axis(r: ModuleRect) -> SpineAxis:
    """``"X"`` if the rectangle is at least as wide as it is high, else ``"Y"``."""
    return "X" if r.w >= r.h else "Y"


def _aspect(r: ModuleRect) -> Fraction:
    """Exact aspect ratio long/short (≥ 1)."""
    return Fraction(max(r.w, r.h), min(r.w, r.h))


def _rect(x0: int, y0: int, x1: int, y1: int) -> ModuleRect:
    return ModuleRect(x=x0, y=y0, w=x1 - x0, h=y1 - y0)


def _reflex_vertex(pts: tuple[ModulePoint, ...]) -> ModulePoint:
    """The unique reflex vertex (right turn) of a counter-clockwise L polygon."""
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i - 1]
        bx, by = pts[i]
        cx, cy = pts[(i + 1) % n]  # int-mod
        if (bx - ax) * (cy - by) - (by - ay) * (cx - bx) < 0:
            return pts[i]
    raise ValueError("L-shaped footprint without a reflex vertex")  # pragma: no cover


def _decompose_l(pts: tuple[ModulePoint, ...]) -> FootprintPieces:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    rx, ry = _reflex_vertex(pts)
    corners = {(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)}
    (mx, my) = (corners - set(pts)).pop()  # the bounding-box corner cut away by the notch
    # x / y range left over beside the notch.
    nx0, nx1 = (xmin, rx) if mx == xmax else (rx, xmax)
    ny0, ny1 = (ymin, ry) if my == ymax else (ry, ymax)

    # Horizontal cut y = ry: the band on the notch side loses the notch's x range.
    if my == ymax:
        h_pair = (_rect(xmin, ymin, xmax, ry), _rect(nx0, ry, nx1, ymax))
    else:
        h_pair = (_rect(nx0, ymin, nx1, ry), _rect(xmin, ry, xmax, ymax))
    # Vertical cut x = rx: the band on the notch side loses the notch's y range.
    if mx == xmax:
        v_pair = (_rect(xmin, ymin, rx, ymax), _rect(rx, ny0, xmax, ny1))
    else:
        v_pair = (_rect(xmin, ny0, rx, ny1), _rect(rx, ymin, xmax, ymax))

    h_cost = max(_aspect(r) for r in h_pair)
    v_cost = max(_aspect(r) for r in v_pair)
    horizontal = h_cost <= v_cost  # tie → horizontal
    a, b = h_pair if horizontal else v_pair

    primary, secondary = sorted((a, b), key=lambda r: (-r.area_cells(), r.y, r.x))
    secondary_axis: SpineAxis = "Y" if horizontal else "X"  # perpendicular to the cut line
    # A square primary takes the axis perpendicular to the cut (orientation-independent).
    primary_axis = secondary_axis if primary.w == primary.h else _long_axis(primary)

    cut: tuple[ModulePoint, ModulePoint]
    if horizontal:
        cut = ((max(a.x, b.x), ry), (min(a.x2(), b.x2()), ry))
    else:
        cut = ((rx, max(a.y, b.y)), (rx, min(a.y2(), b.y2())))

    parallel = (primary_axis == "X") == horizontal
    facing: Literal["A", "B"] | None = None
    if parallel:
        on_far_edge = ry == primary.y2() if horizontal else rx == primary.x2()
        facing = "B" if on_far_edge else "A"
    return FootprintPieces(
        pieces=(
            Piece(rect=primary, spine_axis=primary_axis),
            Piece(rect=secondary, spine_axis=secondary_axis),
        ),
        junction="J1" if parallel else "J2",
        cut=cut,
        facing_block=facing,
    )


def decompose_footprint(fp: ModulePolygon) -> FootprintPieces:
    """Decompose a rectangular or L-shaped module footprint into 1 or 2 pieces.

    Rectangle: one piece, spine along the long axis (tie → ``"X"``). L: cut through the
    reflex vertex, horizontally or vertically, minimising the larger of the two pieces'
    aspect ratios (tie → horizontal); primary = larger area (tie → smaller ``(y, x)``
    origin) with its spine on its long axis (square → perpendicular to the cut line);
    secondary spine perpendicular to the cut line. Raises ``ValueError`` for any other vertex count.
    """
    pts = fp.exterior
    if len(pts) == 4:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        rect = _rect(min(xs), min(ys), max(xs), max(ys))
        return FootprintPieces(
            pieces=(Piece(rect=rect, spine_axis=_long_axis(rect)),),
            junction="NONE",
            cut=None,
            facing_block=None,
        )
    if len(pts) == 6:
        return _decompose_l(pts)
    raise ValueError(UNSUPPORTED_MESSAGE)
