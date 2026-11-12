"""The vertical skeleton: one core and one wet stack on identical cells (Ticket M.1, RD section 5).

Everything is expressed on the *global* 0.60 m cell grid anchored at the minimum corner of the
ground-floor outline: cell ``(gx, gy)`` covers ``[ox + gx*0.6, ox + (gx+1)*0.6) x ...``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely import Polygon as ShPolygon

from ale.contracts.models import RoomSpec
from ale.stack.building import Building

__all__ = [
    "AREA_CELL_M2",
    "CELL_M",
    "CellRect",
    "Grid",
    "Skeleton",
    "WetFloor",
    "WetRoom",
    "build_skeleton",
    "cells_of",
    "core_cell_rect",
    "distribute_wet",
    "rect_cells",
]

CELL_M = 0.6
AREA_CELL_M2 = CELL_M * CELL_M
_WET_ORDER = ("sanitary", "cleaning_room", "technical_room")
_MIN_CONTACT = 3
_DEPTHS = range(5, 13)
_MARGIN_M = 0.1

#: ``(x0, y0, x1, y1)`` in global cells, upper bounds exclusive.
CellRect = tuple[int, int, int, int]


@dataclass(frozen=True)
class Grid:
    """Origin of the global cell grid (metres)."""

    ox: float
    oy: float

    def cell_x(self, x: float) -> int:
        return round((x - self.ox) / CELL_M)

    def cell_y(self, y: float) -> int:
        return round((y - self.oy) / CELL_M)

    def centre(self, gx: int, gy: int) -> tuple[float, float]:
        return (self.ox + (gx + 0.5) * CELL_M, self.oy + (gy + 0.5) * CELL_M)

    def metres(self, r: CellRect) -> tuple[float, float, float, float]:
        """``(x, y, w, h)`` in metres of a cell rectangle."""
        return (
            self.ox + r[0] * CELL_M,
            self.oy + r[1] * CELL_M,
            (r[2] - r[0]) * CELL_M,
            (r[3] - r[1]) * CELL_M,
        )


@dataclass(frozen=True)
class WetRoom:
    """A wet room tiled in the stack."""

    iid: str
    spec_id: str
    type: str
    target_m2: float
    cells: frozenset[tuple[int, int]]

    @property
    def area_m2(self) -> float:
        return len(self.cells) * AREA_CELL_M2


@dataclass(frozen=True)
class WetFloor:
    """The wet stack on one floor: the rooms, the technical reserve and the shaft strip."""

    level: int
    rooms: tuple[WetRoom, ...]
    reserve: frozenset[tuple[int, int]]
    unplaced: tuple[str, ...] = ()


@dataclass(frozen=True)
class Skeleton:
    """Core and wet stack in global cells, plus the wet rooms of every floor."""

    grid: Grid
    core: CellRect
    wet: CellRect | None
    shaft: frozenset[tuple[int, int]]
    axis: str
    depth: int
    floors: tuple[WetFloor, ...]
    misses: tuple[str, ...] = ()
    level_of: dict[str, int] = field(default_factory=dict)
    """Level of every wet instance (placed or not)."""

    @property
    def core_cells(self) -> frozenset[tuple[int, int]]:
        return rect_cells(self.core)

    @property
    def wet_cells(self) -> frozenset[tuple[int, int]]:
        return rect_cells(self.wet) if self.wet is not None else frozenset()

    @property
    def wet_area_m2(self) -> float:
        return len(self.wet_cells) * AREA_CELL_M2

    @property
    def core_area_m2(self) -> float:
        return len(self.core_cells) * AREA_CELL_M2

    def wet_adjacent(self) -> bool:
        """The wet stack shares a side stretch with the core."""
        core = self.core_cells
        return any(
            (x + dx, y + dy) in core
            for x, y in self.wet_cells
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
        )

    def wet_instances(self) -> list[WetRoom]:
        return [r for f in self.floors for r in f.rooms]


def rect_cells(r: CellRect) -> frozenset[tuple[int, int]]:
    return frozenset((x, y) for x in range(r[0], r[2]) for y in range(r[1], r[3]))


def core_cell_rect(b: Building, grid: Grid) -> CellRect:
    """The building core on the global grid (at least one cell each way)."""
    x, y, w, h = b.core.rect
    x0, y0 = grid.cell_x(x), grid.cell_y(y)
    return (x0, y0, max(x0 + 1, grid.cell_x(x + w)), max(y0 + 1, grid.cell_y(y + h)))


def cells_of(target_m2: float) -> int:
    """Cells needed to reach ``target_m2`` (never below the target)."""
    return max(1, math.ceil(target_m2 / AREA_CELL_M2 - 1e-9))


# -------------------------------------------------------------------- distribution
def _largest_remainder(total: int, weights: Sequence[float]) -> list[int]:
    w = sum(weights)
    if total <= 0 or w <= 0:
        return [0] * len(weights)
    quotas = [total * x / w for x in weights]
    base = [int(q) for q in quotas]
    left = total - sum(base)
    order = sorted(range(len(weights)), key=lambda k: (-(quotas[k] - base[k]), k))
    for k in order[:left]:
        base[k] += 1
    return base


def distribute_wet(
    instances: Sequence[tuple[str, RoomSpec]], floor_areas: Sequence[float]
) -> dict[str, int]:
    """Floor of each wet instance: in proportion to each floor's assigned area, by type; every
    occupied floor gets a sanitary room when there are enough. Rooms with ``floor > 0`` in the
    programme keep their level."""
    n = len(floor_areas)
    occupied = [k for k, a in enumerate(floor_areas) if a > 0] or [0]
    out: dict[str, int] = {}
    by_type: dict[str, list[str]] = {}
    for iid, spec in sorted(instances, key=lambda t: (_type_rank(t[1].type), t[0])):
        if spec.floor > 0:
            out[iid] = min(spec.floor, n - 1)
        else:
            by_type.setdefault(spec.type, []).append(iid)
    for spec_type, ids in by_type.items():
        counts = [0] * n
        left = len(ids)
        if spec_type == "sanitary" and left >= len(occupied):
            for k in occupied:
                counts[k] = 1
            left -= len(occupied)
        extra = _largest_remainder(left, [floor_areas[k] for k in occupied])
        for k, c in zip(occupied, extra, strict=True):
            counts[k] += c
        it = iter(ids)
        for k in range(n):
            for _ in range(counts[k]):
                out[next(it)] = k
    return out


def _type_rank(t: str) -> int:
    return _WET_ORDER.index(t) if t in _WET_ORDER else len(_WET_ORDER)


# ---------------------------------------------------------------------------- stack
def _valid_cells(top: ShPolygon, grid: Grid, bounds: CellRect) -> set[tuple[int, int]]:
    inner = top.buffer(-_MARGIN_M)
    xs = np.arange(bounds[0], bounds[2])
    ys = np.arange(bounds[1], bounds[3])
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    px = grid.ox + (gx + 0.5) * CELL_M
    py = grid.oy + (gy + 0.5) * CELL_M
    inside = shapely.contains_xy(inner, px, py)
    return {(int(x), int(y)) for x, y in zip(gx[inside], gy[inside], strict=True)}


def _candidates(core: CellRect, sx: int, sy: int) -> list[tuple[int, CellRect]]:
    """Rectangles ``sx x sy`` sharing a side stretch with ``core``: ``(order, rect)``."""
    cw, ch = core[2] - core[0], core[3] - core[1]
    out: list[tuple[int, CellRect]] = []
    c_y = min(_MIN_CONTACT, ch, sy)
    for y0 in range(core[1] - sy + c_y, core[3] - c_y + 1):
        out.append((0, (core[2], y0, core[2] + sx, y0 + sy)))
        out.append((1, (core[0] - sx, y0, core[0], y0 + sy)))
    c_x = min(_MIN_CONTACT, cw, sx)
    for x0 in range(core[0] - sx + c_x, core[2] - c_x + 1):
        out.append((2, (x0, core[3], x0 + sx, core[3] + sy)))
        out.append((3, (x0, core[1] - sy, x0 + sx, core[1])))
    return out


def _demand(needs: list[list[int]], d: int) -> int:
    return max((sum(math.ceil(n / d) for n in floor) for floor in needs), default=0)


def _place(
    needs: list[list[int]], core: CellRect, valid: set[tuple[int, int]]
) -> tuple[CellRect, str, int] | None:
    best: tuple[tuple[int, int, bool, int, int], CellRect, str, int] | None = None
    for d in _DEPTHS:
        length = 1 + _demand(needs, d)
        for axis in ("x", "y"):
            sx, sy = (length, d) if axis == "x" else (d, length)
            if sx * sy > len(valid):
                continue
            for order, rect in _candidates(core, sx, sy):
                if not all(c in valid for c in rect_cells(rect)):
                    continue
                key = (
                    sx * sy + 2 * abs(sx - sy),
                    d,
                    axis == "y",
                    order,
                    rect[1] * 10_000 + rect[0],
                )
                if best is None or key < best[0]:
                    best = (key, rect, axis, d)
    return None if best is None else (best[1], best[2], best[3])


def _tile(
    level: int,
    rooms: list[tuple[str, RoomSpec]],
    rect: CellRect,
    axis: str,
    depth: int,
) -> WetFloor:
    length = (rect[2] - rect[0]) if axis == "x" else (rect[3] - rect[1])

    def cell(s: int, t: int) -> tuple[int, int]:
        return (rect[0] + s, rect[1] + t) if axis == "x" else (rect[0] + t, rect[1] + s)

    placed: list[WetRoom] = []
    unplaced: list[str] = []
    s = 1  # strip 0 is the shaft strip
    for iid, spec in rooms:
        width = math.ceil(cells_of(spec.target_area_m2) / depth)
        if s + width > length:
            unplaced.append(iid)
            continue
        cs = frozenset(cell(s + i, t) for i in range(width) for t in range(depth))
        placed.append(WetRoom(iid, spec.id, spec.type, spec.target_area_m2, cs))
        s += width
    reserve = frozenset(cell(i, t) for i in range(s, length) for t in range(depth))
    return WetFloor(level, tuple(placed), reserve, tuple(unplaced))


def build_skeleton(
    building: Building,
    wet: Sequence[tuple[str, RoomSpec]],
    floor_areas: Sequence[float],
) -> Skeleton:
    """Core cells, wet stack rectangle and per-floor wet tilings.

    ``floor_areas`` are the non-wet areas assigned to each floor (the weights of the wet
    distribution). The stack is the smallest rectangle on the 0.60 m grid, adjacent to the core,
    inside the top floor's outline, sized to the largest per-floor wet demand plus one shaft
    strip. When no placement exists the stack is absent and the miss is reported."""
    ground = building.outline(0)
    grid = Grid(ground.bounds[0], ground.bounds[1])
    core = core_cell_rect(building, grid)
    n = building.n_floors
    level_of = distribute_wet(wet, floor_areas) if wet else {}
    per_floor: list[list[tuple[str, RoomSpec]]] = [[] for _ in range(n)]
    for iid, spec in sorted(wet, key=lambda t: (_type_rank(t[1].type), t[0])):
        per_floor[level_of[iid]].append((iid, spec))
    if not wet:
        empty = tuple(WetFloor(k, (), frozenset()) for k in range(n))
        return Skeleton(grid, core, None, frozenset(), "x", 0, empty)
    needs = [[cells_of(s.target_area_m2) for _, s in fl] for fl in per_floor]
    top = building.outline(n - 1)
    b = ground.bounds
    bounds: CellRect = (
        grid.cell_x(b[0]) - 1,
        grid.cell_y(b[1]) - 1,
        grid.cell_x(b[2]) + 2,
        grid.cell_y(b[3]) + 2,
    )
    valid = _valid_cells(top, grid, bounds) - set(rect_cells(core))
    found = _place(needs, core, valid)
    if found is None:
        miss = (
            "Colonne humide : aucun emplacement adjacent au noyau et inscrit dans le contour du "
            "dernier niveau pour la demande humide "
            f"({max(sum(f) for f in needs) * AREA_CELL_M2:.1f} m² sur le niveau le plus chargé)."
        )
        floors = tuple(
            WetFloor(k, (), frozenset(), tuple(i for i, _ in per_floor[k])) for k in range(n)
        )
        return Skeleton(grid, core, None, frozenset(), "x", 0, floors, (miss,), level_of)
    rect, axis, depth = found
    floors_t = tuple(_tile(k, per_floor[k], rect, axis, depth) for k in range(n))
    shaft = frozenset(
        (rect[0], t + rect[1]) if axis == "x" else (t + rect[0], rect[1]) for t in range(depth)
    )
    misses = tuple(
        f"Colonne humide, niveau {f.level} : pièce {i} sans place dans la colonne."
        for f in floors_t
        for i in f.unplaced
    )
    return Skeleton(grid, core, rect, shaft, axis, depth, floors_t, misses, level_of)
