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

__all__ = [
    "BayHint",
    "BayStats",
    "BlockLattice",
    "axis_lattice",
    "current_bay_hint",
    "use_bay_hint",
]

SMALL_ROOM_MM2 = 30_000_000
"""A room of less than 30 m² is *small* (M.3 M305)."""
WALL_MM = 150
"""A column within this distance of a room side stands on a wall (M.3 M305)."""
TOL_MM = 300
"""A partition within this distance of a bay line is on it (M.3 M304)."""


@dataclass
class BayStats:
    """Counters filled by the realiser while a hint is active."""

    realisations: int = 0
    lattice_blocks: int = 0
    """Blocks laid out with the lattice objective."""
    plain_blocks: int = 0
    """Blocks laid out as without a hint (marker, infeasible window, no room bay)."""
    fallbacks: int = 0
    """Realisations that failed with the hint and were redone without it."""


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
    stats: BayStats = field(default_factory=BayStats, compare=False, hash=False, repr=False)


@dataclass(frozen=True)
class BlockLattice:
    """A hint seen from one block, in modules. Bay lines lie at ``u`` with
    ``(u - bay_res) % bay == 0`` (``bay == 0``: no bay objective), column lines likewise with
    ``col`` / ``col_res``; ``tol``: distance counted as on a line; ``edge``: a column line at
    least this far from both sides of a room is inside it; ``n_cross``: column lines across the
    block's depth that are at least ``edge`` from both of its sides; ``small_mm2``: rooms
    below this area count."""

    bay: int
    bay_res: int
    col: int
    col_res: int
    tol: int
    edge: int
    n_cross: int
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


def count_lines(line_mm: int, period_mm: int, lo_mm: int, hi_mm: int) -> int:
    """Number of ``line_mm + n * period_mm`` in ``[lo_mm, hi_mm]``."""
    if period_mm <= 0 or hi_mm < lo_mm:
        return 0
    first = -((line_mm - lo_mm) // period_mm)  # ceil((lo - line) / period)
    last = (hi_mm - line_mm) // period_mm
    return max(0, last - first + 1)


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
