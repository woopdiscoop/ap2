"""Bay / column-line hint for the realiser (Ticket M.3b).

A :class:`BayHint` describes the structural lattice of a building in absolute millimetres: the
bay lines (the bay module of M.3) and the column lines, per axis. When a hint is active
(:func:`use_bay_hint`) :func:`ale.geometry.realize` chooses, inside each room's width window
(area rule, aspect, minimum width), the widths of a block's room bays and the block depths so
that the partitions along an exterior side fall on bay lines and the column lines do not cross
small rooms. **Without a hint nothing changes** (same code path, byte-identical output).

:class:`BlockLattice` is the hint seen from one block: periods and residues in modules along the
block's spine (``u``) plus the number of column lines across its depth.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import shapely

if TYPE_CHECKING:
    from ale.contracts.models import Layout

__all__ = [
    "LATTICE_COST",
    "BayHint",
    "BayStats",
    "BlockLattice",
    "LatticeFigures",
    "axis_lattice",
    "current_bay_hint",
    "lattice_figures",
    "lines_in",
    "use_bay_hint",
]

SMALL_ROOM_MM2 = 30_000_000
"""A room of less than 30 m² is *small* (M.3 M305)."""
WALL_MM = 150
"""A column within this distance of a room side stands on a wall (M.3 M305)."""
TOL_MM = 300
"""A partition within this distance of a bay line is on it (M.3 M304)."""
LATTICE_COST = "lattice"
"""Name of the cost term added to ``cost_breakdown`` while a hint is active: façade partitions
off a bay line plus columns inside small rooms, per room."""


@dataclass
class BayStats:
    """Counters filled by the realiser while a hint is active."""

    realisations: int = 0
    """:func:`ale.geometry.realize` calls that succeeded with the hint."""
    fallbacks: int = 0
    """:func:`ale.geometry.realize` calls that failed with the hint and were redone without it."""


@dataclass(frozen=True)
class BayHint:
    """Lattice in absolute millimetres, per axis. ``line_*_mm`` is the position of one bay line
    (the others are ``line + n * bay``); likewise ``colline_*_mm`` for the column lines."""

    bay_x_mm: int
    bay_y_mm: int
    line_x_mm: int
    line_y_mm: int
    col_x_mm: int
    col_y_mm: int
    colline_x_mm: int
    colline_y_mm: int
    tol_mm: int = TOL_MM
    small_mm2: int = SMALL_ROOM_MM2
    weight: float = 1.0
    """Weight of the :data:`LATTICE_COST` term in ``total_cost``."""
    stats: BayStats = field(default_factory=BayStats, compare=False, hash=False, repr=False)


@dataclass(frozen=True)
class BlockLattice:
    """A hint seen from one block, in modules. Bay lines lie at ``u`` with
    ``(u - bay_res) % bay == 0`` (``bay == 0``: no bay objective), column lines likewise with
    ``col`` / ``col_res``; ``tol``: distance counted as on a line; ``edge``: a column line at
    least this far from both sides of a room is inside it; ``cross_t``: distance ``t`` from the
    spine of each column line across the block's depth (empty: not known); ``small_mm2``: rooms
    below this area count."""

    bay: int
    bay_res: int
    col: int
    col_res: int
    tol: int
    edge: int
    cross_t: tuple[int, ...]
    small_mm2: int


def axis_lattice(line_mm: int, period_mm: int, start_mm: int, module_mm: int) -> tuple[int, int]:
    """``(period, residue)`` in modules of the lines ``line_mm + n * period_mm`` seen from
    ``start_mm`` (``u = 0``); ``(0, 0)`` when the lattice is not a whole number of modules."""
    if period_mm <= 0 or period_mm % module_mm:
        return 0, 0
    off = (line_mm - start_mm) % period_mm
    if off % module_mm:
        return 0, 0
    return period_mm // module_mm, off // module_mm


def lines_in(line_mm: int, period_mm: int, lo_mm: int, hi_mm: int) -> list[int]:
    """The ``line_mm + n * period_mm`` in ``[lo_mm, hi_mm]``, ascending."""
    if period_mm <= 0 or hi_mm < lo_mm:
        return []
    first = -((line_mm - lo_mm) // period_mm)  # ceil((lo - line) / period)
    last = (hi_mm - line_mm) // period_mm
    return [line_mm + n * period_mm for n in range(first, last + 1)]


_HINT: ContextVar[BayHint | None] = ContextVar("ale_bay_hint", default=None)


def current_bay_hint() -> BayHint | None:
    """The hint active in this context, or ``None``."""
    return _HINT.get()


@contextmanager
def use_bay_hint(hint: BayHint | None) -> Iterator[None]:
    """Run the enclosed :func:`ale.geometry.realize` calls with ``hint`` (``None``: without)."""
    token = _HINT.set(hint)
    try:
        yield
    finally:
        _HINT.reset(token)


@dataclass(frozen=True)
class LatticeFigures:
    """Façade partitions (and how many are off a bay line) and columns (and how many stand inside
    a room of less than ``small_mm2``) of a layout, as :func:`ale.stack.grid.plan_facade_partitions`
    and :func:`ale.stack.grid.plan_columns` measure them."""

    partitions: int
    off: int
    columns: int
    small: int


def lattice_figures(layout: Layout, origin_mm: tuple[int, int], hint: BayHint) -> LatticeFigures:
    """Figures of ``layout`` (footprint origin ``origin_mm``) against ``hint``."""
    mod = layout.grid.module_mm
    ring = list(layout.footprint.exterior)
    edges = [(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring))]
    seen: set[tuple[int, int]] = set()
    parts = off = 0
    for room in layout.rooms:
        r = room.rect
        x0, y0, x1, y1 = r.x, r.y, r.x + r.w, r.y + r.h
        for a, c in edges:
            if a[1] == c[1]:  # horizontal exterior edge
                if a[1] not in (y0, y1):
                    continue
                lo, hi = sorted((a[0], c[0]))
                if x1 <= lo or x0 >= hi:
                    continue
                for x in (x0, x1):
                    if lo < x < hi and (0, x) not in seen:
                        seen.add((0, x))
                        parts += 1
                        dx = _off(origin_mm[0] + x * mod, hint.line_x_mm, hint.bay_x_mm)
                        off += dx > hint.tol_mm
            else:
                if a[0] not in (x0, x1):
                    continue
                lo, hi = sorted((a[1], c[1]))
                if y1 <= lo or y0 >= hi:
                    continue
                for y in (y0, y1):
                    if lo < y < hi and (1, y) not in seen:
                        seen.add((1, y))
                        parts += 1
                        dy = _off(origin_mm[1] + y * mod, hint.line_y_mm, hint.bay_y_mm)
                        off += dy > hint.tol_mm
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    outline = shapely.Polygon(ring).buffer(1e-6)
    cols = small = 0
    solids = [
        (min(q[0] for q in s), min(q[1] for q in s), max(q[0] for q in s), max(q[1] for q in s))
        for s in layout.footprint.solids
    ]
    cell = mod * mod
    for cx_mm in lines_in(
        hint.colline_x_mm,
        hint.col_x_mm,
        origin_mm[0] + min(xs) * mod,
        origin_mm[0] + max(xs) * mod,
    ):
        for cy_mm in lines_in(
            hint.colline_y_mm,
            hint.col_y_mm,
            origin_mm[1] + min(ys) * mod,
            origin_mm[1] + max(ys) * mod,
        ):
            fx, fy = (cx_mm - origin_mm[0]) / mod, (cy_mm - origin_mm[1]) / mod
            if not outline.covers(shapely.Point(fx, fy)):
                continue
            if any(b[0] < fx < b[2] and b[1] < fy < b[3] for b in solids):
                continue
            cols += 1
            for room in layout.rooms:
                r = room.rect
                if r.w * r.h * cell >= hint.small_mm2:
                    continue
                rx0, ry0 = origin_mm[0] + r.x * mod, origin_mm[1] + r.y * mod
                if (
                    rx0 + WALL_MM < cx_mm < rx0 + r.w * mod - WALL_MM
                    and ry0 + WALL_MM < cy_mm < ry0 + r.h * mod - WALL_MM
                ):
                    small += 1
                    break
    return LatticeFigures(parts, off, cols, small)


def _off(pos_mm: int, line_mm: int, period_mm: int) -> int:
    """Distance (mm) from ``pos_mm`` to the nearest ``line_mm + n * period_mm``."""
    if period_mm <= 0:
        return 0
    r = (pos_mm - line_mm) % period_mm
    return min(r, period_mm - r)
