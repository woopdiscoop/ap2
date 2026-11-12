"""Column grid and bay module of a building (Ticket M.3, RD sections 2-3).

One decision drives the structure of every floor: a **column grid** (spans ``sx`` x ``sy``, both
multiples of 0.60 m, 5.40-9.00 m by default) and a **bay module** ``b`` (a multiple of 0.60 m
that divides both spans, 2.40-4.80 m by default). The grid is anchored on the core (its west and
south sides lie on grid lines), so it is the same on every floor, and columns stand on its
intersections wherever they fall inside a floor outline and outside the core / wet stack.

Everything is expressed on the global 0.60 m cell grid of :mod:`ale.stack.skeleton` (integer
cells); a column sits on a cell corner ``(gx, gy)`` and touches the four cells around it.

Choice (:func:`choose_rhythm`), minimised over the candidates, ties to the larger span:

``score = columns in small rooms + 0.25 x façade partitions off a bay line + 2 x façade rooms lost``

measured on the cell diagrams of all floors: a column is *in a small room* when its four cells
belong to one room of less than 30 m² (a column on a wall or in a corridor is harmless); a
façade partition is a change of owner along the exterior; a façade room is *lost* when its
façade contact is shorter than one bay.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import shapely
from shapely import Polygon as ShPolygon

from ale.geometry.bay import BayHint
from ale.stack.rules import RhythmInputError, StackRules
from ale.stack.skeleton import AREA_CELL_M2, CELL_M, CellRect, Skeleton
from ale.topology.cellgrow import OUTSIDE, CellDiagram

__all__ = [
    "BAY_RANGE_M",
    "SMALL_ROOM_M2",
    "SPAN_RANGE_M",
    "TOL_M",
    "ColumnStats",
    "Rhythm",
    "RhythmScore",
    "choose_rhythm",
    "columns_of",
    "diagram_column_stats",
    "diagram_facade_stats",
    "partition_off_bay",
    "plan_columns",
    "plan_facade_partitions",
    "plan_longside_partitions",
    "plan_stackability",
    "validate_overrides",
]

SPAN_RANGE_M = (5.4, 9.0)
BAY_RANGE_M = (2.4, 4.8)
SMALL_ROOM_M2 = 30.0
TOL_M = 0.30
"""A partition is *on* a bay line when it lies within this distance of it."""
W_OFF_BAY = 0.25
W_LOST = 2.0
_EPS = 1e-6
Cell = tuple[int, int]

if TYPE_CHECKING:
    from ale.stack.plans import FloorPlan as PlanLike


def _cells(metres: float) -> int | None:
    """``metres`` as a whole number of 0.60 m cells, ``None`` when it is not one."""
    n = round(metres / CELL_M)
    return n if abs(n * CELL_M - metres) < _EPS and n > 0 else None


@dataclass(frozen=True)
class RhythmScore:
    """The components of the choice score (cell diagrams of all floors)."""

    small_columns: int = 0
    columns: int = 0
    off_bay: int = 0
    partitions: int = 0
    lost: int = 0

    @property
    def total(self) -> float:
        return self.small_columns + W_OFF_BAY * self.off_bay + W_LOST * self.lost


@dataclass(frozen=True)
class Rhythm:
    """Column grid + bay module, in global cells. Grid lines are the cells ``g`` with
    ``(g - phase) % span == 0``; bay lines those with ``(g - phase) % bay == 0``."""

    span_x: int
    span_y: int
    bay: int
    phase_x: int
    phase_y: int
    ox: float
    oy: float
    score: RhythmScore = field(default_factory=RhythmScore)
    overridden: tuple[str, ...] = ()
    candidates: int = 0
    typical: int = 0

    @property
    def span_x_m(self) -> float:
        return round(self.span_x * CELL_M, 6)

    @property
    def span_y_m(self) -> float:
        return round(self.span_y * CELL_M, 6)

    @property
    def bay_m(self) -> float:
        return round(self.bay * CELL_M, 6)

    def x_m(self, gx: int) -> float:
        return self.ox + gx * CELL_M

    def y_m(self, gy: int) -> float:
        return self.oy + gy * CELL_M

    def bay_lines_x(self, lo: float, hi: float) -> list[float]:
        """Bay lines (metres) with ``lo <= x <= hi``."""
        return _lines(self.ox, self.phase_x, self.bay, lo, hi)

    def bay_lines_y(self, lo: float, hi: float) -> list[float]:
        return _lines(self.oy, self.phase_y, self.bay, lo, hi)

    def grid_lines_x(self, lo: float, hi: float) -> list[float]:
        return _lines(self.ox, self.phase_x, self.span_x, lo, hi)

    def grid_lines_y(self, lo: float, hi: float) -> list[float]:
        return _lines(self.oy, self.phase_y, self.span_y, lo, hi)

    def off_bay_x(self, x: float) -> float:
        """Distance (m) from ``x`` to the nearest vertical bay line."""
        return _off(x - self.ox, self.phase_x, self.bay)

    def off_bay_y(self, y: float) -> float:
        return _off(y - self.oy, self.phase_y, self.bay)

    def hint(self) -> BayHint:
        """The lattice for the realiser (M.3b): bay lines and column lines in millimetres."""

        def mm(metres: float) -> int:
            return round(metres * 1000)

        return BayHint(
            bay_x_mm=mm(self.bay * CELL_M),
            bay_y_mm=mm(self.bay * CELL_M),
            line_x_mm=mm(self.ox + self.phase_x * CELL_M),
            line_y_mm=mm(self.oy + self.phase_y * CELL_M),
            col_x_mm=mm(self.span_x * CELL_M),
            col_y_mm=mm(self.span_y * CELL_M),
            colline_x_mm=mm(self.ox + self.phase_x * CELL_M),
            colline_y_mm=mm(self.oy + self.phase_y * CELL_M),
        )

    def core_on_grid(self, core: CellRect) -> bool:
        """The west and south sides of the core lie on grid lines."""
        return (core[0] - self.phase_x) % self.span_x == 0 and (
            core[1] - self.phase_y
        ) % self.span_y == 0


def _lines(origin: float, phase: int, step: int, lo: float, hi: float) -> list[float]:
    g0 = math.floor((lo - origin) / CELL_M) - step
    g = g0 + ((phase - g0) % step)
    out = []
    while origin + g * CELL_M <= hi + _EPS:
        x = origin + g * CELL_M
        if x >= lo - _EPS:
            out.append(round(x, 6))
        g += step
    return out


def _off(rel_m: float, phase: int, step: int) -> float:
    rem = (rel_m / CELL_M - phase) % step
    return min(rem, step - rem) * CELL_M


# ---------------------------------------------------------------------------- columns
def columns_of(
    rhythm: Rhythm, outline: ShPolygon, solids: Iterable[CellRect] = ()
) -> list[tuple[float, float]]:
    """Grid intersections (metres) inside or on ``outline`` and not strictly inside a solid
    (core, wet stack: ``solids`` are global cell rectangles)."""
    b = outline.bounds
    xs = rhythm.grid_lines_x(b[0], b[2])
    ys = rhythm.grid_lines_y(b[1], b[3])
    out: list[tuple[float, float]] = []
    boxes = list(solids)
    prepared = outline.buffer(1e-6)
    for x in xs:
        for y in ys:
            if not prepared.covers(shapely.Point(x, y)):
                continue
            gx = round((x - rhythm.ox) / CELL_M)
            gy = round((y - rhythm.oy) / CELL_M)
            if any(r[0] < gx < r[2] and r[1] < gy < r[3] for r in boxes):
                continue
            out.append((x, y))
    return out


@dataclass(frozen=True)
class ColumnStats:
    columns: int
    small: int


def diagram_column_stats(
    rhythm: Rhythm, outline: ShPolygon, skeleton: Skeleton, diagram: CellDiagram | None, off: Cell
) -> ColumnStats:
    """Columns of a floor and how many stand inside a room of less than 30 m² (cell diagram)."""
    solids = [skeleton.core] + ([skeleton.wet] if skeleton.wet is not None else [])
    cols = columns_of(rhythm, outline, solids)
    if diagram is None:
        return ColumnStats(len(cols), 0)
    small = 0
    for x, y in cols:
        gx = round((x - rhythm.ox) / CELL_M)
        gy = round((y - rhythm.oy) / CELL_M)
        owners = {
            _owner(diagram, gx + dx - off[0], gy + dy - off[1])
            for dx, dy in ((-1, -1), (0, -1), (-1, 0), (0, 0))
        }
        if len(owners) == 1:
            (o,) = owners
            if o >= 0 and len(diagram.cells[diagram.rooms[o]]) * AREA_CELL_M2 < SMALL_ROOM_M2:
                small += 1
    return ColumnStats(len(cols), small)


def _owner(d: CellDiagram, cx: int, cy: int) -> int:
    if 0 <= cx < d.width and 0 <= cy < d.height:
        return d.owner[cy][cx]
    return OUTSIDE


# ------------------------------------------------------------------------ partitions
def partition_off_bay(positions: Sequence[float], dist: Sequence[float]) -> tuple[int, int]:
    """``(count, off)``: how many partitions and how many farther than :data:`TOL_M` from a
    bay line (``dist`` are the distances)."""
    return len(positions), sum(1 for d in dist if d > TOL_M + _EPS)


def diagram_facade_stats(
    rhythm: Rhythm, diagram: CellDiagram | None, off: Cell, bay_cells: int | None = None
) -> tuple[int, int, int]:
    """``(façade partitions, partitions off a bay line, façade rooms lost)`` of a floor diagram.

    A partition is a change of owner between two consecutive cells of the exterior row / column
    (a room-to-room or room-to-circulation boundary); a façade room is lost when its façade
    contact is shorter than one bay."""
    if diagram is None:
        return 0, 0, 0
    bay = rhythm.bay if bay_cells is None else bay_cells
    n = off_n = 0
    contact: dict[int, int] = {}
    for cy in range(diagram.height):
        for cx in range(diagram.width):
            o = diagram.owner[cy][cx]
            if o == OUTSIDE:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if _owner(diagram, cx + dx, cy + dy) != OUTSIDE:
                    continue
                if o >= 0:
                    contact[o] = contact.get(o, 0) + 1
                # next cell along the edge (to the right / up) with the same exterior side
                ax, ay = (cx, cy + 1) if dx else (cx + 1, cy)
                if _owner(diagram, ax + dx, ay + dy) != OUTSIDE:
                    continue
                o2 = _owner(diagram, ax, ay)
                if o2 in (OUTSIDE, o):
                    continue
                n += 1
                # the partition is the line between the two cells
                if dx:  # vertical exterior side, boundary at y = cy + 1
                    pos = off[1] + cy + 1
                    far = _off(pos * CELL_M, rhythm.phase_y, bay)
                else:
                    pos = off[0] + cx + 1
                    far = _off(pos * CELL_M, rhythm.phase_x, bay)
                if far > TOL_M + _EPS:
                    off_n += 1
    lost = sum(
        1
        for name, o in ((r, i) for i, r in enumerate(diagram.rooms))
        if diagram.cells[name] and contact.get(o, 0) and contact[o] < bay
    )
    return n, off_n, lost


# --------------------------------------------------------------------------- choice
def validate_overrides(rules: StackRules, n_floors: int) -> None:
    """French :class:`RhythmInputError` for an unusable ``bay_m``, ``grid_m`` or
    ``typical_floor`` (never a crash)."""
    errors: list[str] = []
    bay = _cells(rules.bay_m) if rules.bay_m is not None else None
    if rules.bay_m is not None and bay is None:
        errors.append(f"« bay_m » = {rules.bay_m} : multiple de 0,60 m attendu (par exemple 3,6).")
    spans: list[int | None] = []
    if rules.grid_m is not None:
        for name, v in zip(("sx", "sy"), rules.grid_m, strict=True):
            c = _cells(v)
            spans.append(c)
            if c is None:
                errors.append(f"« grid_m » {name} = {v} : multiple de 0,60 m attendu.")
        if all(s is not None for s in spans) and bay is not None:
            for name, s in zip(("sx", "sy"), spans, strict=True):
                if s is not None and s % bay:
                    errors.append(
                        f"« bay_m » = {rules.bay_m} ne divise pas la portée {name} = "
                        f"{s * CELL_M:.1f} m de « grid_m »."
                    )
    if rules.typical_floor is not None and rules.typical_floor >= n_floors:
        errors.append(
            f"« typical_floor » = {rules.typical_floor} : le bâtiment n'a que {n_floors} niveaux "
            f"(0 à {n_floors - 1})."
        )
    if errors:
        raise RhythmInputError(*errors)


def _candidate_spans(rules: StackRules, bay: int | None) -> list[tuple[int, int]]:
    if rules.grid_m is not None:
        sx, sy = (_cells(v) or 0 for v in rules.grid_m)
        return [(sx, sy)]
    lo, hi = round(SPAN_RANGE_M[0] / CELL_M), round(SPAN_RANGE_M[1] / CELL_M)
    spans = [s for s in range(lo, hi + 1) if bay is None or s % bay == 0]
    if not spans and bay is not None:  # a bay override with no span in range: widen
        spans = [s for s in range(round(3.0 / CELL_M), round(12.0 / CELL_M) + 1) if s % bay == 0]
    return [(sx, sy) for sx in spans for sy in spans]


def choose_rhythm(
    skeleton: Skeleton,
    outlines: Sequence[ShPolygon],
    diagrams: Sequence[tuple[CellDiagram | None, Cell]],
    rules: StackRules,
    *,
    typical: int = 0,
) -> Rhythm:
    """The grid and bay of the building (see the module docstring for the score).

    ``outlines[k]`` is the outline of floor ``k`` (metres), ``diagrams[k]`` its cell diagram
    and cell offset. ``rules.grid_m`` / ``rules.bay_m`` override the choice."""
    n_floors = len(outlines)
    validate_overrides(rules, n_floors)
    core = skeleton.core
    ox, oy = skeleton.grid.ox, skeleton.grid.oy
    bay_o = _cells(rules.bay_m) if rules.bay_m is not None else None
    bays = (
        [bay_o]
        if bay_o is not None
        else list(range(round(BAY_RANGE_M[0] / CELL_M), round(BAY_RANGE_M[1] / CELL_M) + 1))
    )
    best: tuple[tuple[float, int, int], Rhythm] | None = None
    seen = 0
    for sx, sy in _candidate_spans(rules, bay_o):
        for bay in bays:
            if sx % bay or sy % bay:
                continue
            seen += 1
            r = Rhythm(sx, sy, bay, core[0] % sx, core[1] % sy, ox, oy)
            sc = _score(r, skeleton, outlines, diagrams)
            r = Rhythm(
                sx,
                sy,
                bay,
                r.phase_x,
                r.phase_y,
                ox,
                oy,
                sc,
                tuple(
                    k
                    for k, v in (
                        ("bay_m", rules.bay_m),
                        ("grid_m", rules.grid_m),
                        ("typical_floor", rules.typical_floor),
                    )
                    if v is not None
                ),
                typical=typical,
            )
            key = (sc.total, -(sx + sy), -bay)
            if best is None or key < best[0]:
                best = (key, r)
    if best is None:
        raise RhythmInputError(
            "Trame : aucune portée (5,40 à 9,00 m) n'est divisible par le module de travée "
            f"« bay_m » = {rules.bay_m}."
        )
    r = best[1]
    return Rhythm(
        r.span_x, r.span_y, r.bay, r.phase_x, r.phase_y, ox, oy, r.score, r.overridden, seen,
        typical,
    )  # fmt: skip


def _score(
    r: Rhythm,
    skeleton: Skeleton,
    outlines: Sequence[ShPolygon],
    diagrams: Sequence[tuple[CellDiagram | None, Cell]],
) -> RhythmScore:
    cols = small = parts = off = lost = 0
    for outline, (d, offset) in zip(outlines, diagrams, strict=True):
        cs = diagram_column_stats(r, outline, skeleton, d, offset)
        cols += cs.columns
        small += cs.small
        p, o, lo = diagram_facade_stats(r, d, offset)
        parts += p
        off += o
        lost += lo
    return RhythmScore(small, cols, off, parts, lost)


# ------------------------------------------------------------------------ exact plans
def plan_stackability(plans: Sequence[PlanLike]) -> tuple[float, ...]:
    """For each floor ``k >= 1`` that has a plan and a plan below it: share of its room area
    (typed rooms, wet rooms included) whose type is the type directly below (exact)."""
    out: list[float] = []
    for upper, lower in zip(plans[1:], plans[:-1], strict=True):
        if upper.status != "ok" or lower.status != "ok":
            continue
        below: dict[str, list[ShPolygon]] = {}
        for r in lower.rooms_abs:
            if r.type and r.kind != "circulation":
                below.setdefault(r.type, []).append(_box(r.rect))
        union = {t: shapely.unary_union(v) for t, v in below.items()}
        total = same = 0.0
        for r in upper.rooms_abs:
            if not r.type or r.kind == "circulation":
                continue
            b = _box(r.rect)
            total += b.area
            if r.type in union:
                same += b.intersection(union[r.type]).area
        out.append(same / total if total else 0.0)
    return tuple(out)


def _box(r: tuple[float, float, float, float]) -> ShPolygon:
    return shapely.box(r[0], r[1], r[0] + r[2], r[1] + r[3])


def plan_facade_partitions(rhythm: Rhythm, plan: PlanLike, tol_m: float = TOL_M) -> tuple[int, int]:
    """``(partitions, on a bay line)`` of one plan: the ends of the rooms' sides that lie on an
    exterior edge of the outline and strictly inside it (each partition counted once)."""
    ring = list(plan.outline)
    if len(ring) < 3:
        return 0, 0
    edges = [(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring))]
    seen: set[tuple[str, float]] = set()
    n = ok = 0
    for r in plan.rooms_abs:
        if r.kind != "room":
            continue
        x0, y0, w, h = r.rect
        x1, y1 = x0 + w, y0 + h
        for a, c in edges:
            if abs(a[1] - c[1]) < _EPS:  # horizontal exterior edge
                if not (abs(a[1] - y0) < 1e-3 or abs(a[1] - y1) < 1e-3):
                    continue
                lo, hi = sorted((a[0], c[0]))
                if x1 <= lo + 1e-3 or x0 >= hi - 1e-3:
                    continue
                for x in (x0, x1):
                    if lo + 1e-3 < x < hi - 1e-3 and ("x", round(x, 3)) not in seen:
                        seen.add(("x", round(x, 3)))
                        n += 1
                        ok += rhythm.off_bay_x(x) <= tol_m + _EPS
            else:  # vertical exterior edge
                if not (abs(a[0] - x0) < 1e-3 or abs(a[0] - x1) < 1e-3):
                    continue
                lo, hi = sorted((a[1], c[1]))
                if y1 <= lo + 1e-3 or y0 >= hi - 1e-3:
                    continue
                for y in (y0, y1):
                    if lo + 1e-3 < y < hi - 1e-3 and ("y", round(y, 3)) not in seen:
                        seen.add(("y", round(y, 3)))
                        n += 1
                        ok += rhythm.off_bay_y(y) <= tol_m + _EPS
    return n, ok


def plan_longside_partitions(
    rhythm: Rhythm, plan: PlanLike, tol_m: float = 1e-3
) -> tuple[int, int, int]:
    """``(partitions, on a half-bay line, on a whole bay line)`` of one plan (Ticket M.4, U-20):
    the ends of the rooms' sides (reserve rooms included) that lie on a *long* side of the
    outline (an edge at least half as long as the longest one) and strictly inside it. Half-bay
    lines are the absolute bay lines and their midpoints; the distance is exact (``tol_m``
    only absorbs the millimetre rounding of the coordinates)."""
    ring = list(plan.outline)
    if len(ring) < 3:
        return 0, 0, 0
    edges = [(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring))]
    longest = max(abs(a[0] - c[0]) + abs(a[1] - c[1]) for a, c in edges)
    seen: set[tuple[str, float]] = set()
    n = half = whole = 0
    half_m = rhythm.bay_m / 2
    for r in plan.rooms_abs:
        if r.kind != "room":
            continue
        x0, y0, w, h = r.rect
        x1, y1 = x0 + w, y0 + h
        for a, c in edges:
            length = abs(a[0] - c[0]) + abs(a[1] - c[1])
            if length < longest / 2 - tol_m:
                continue
            horizontal = abs(a[1] - c[1]) < _EPS
            if horizontal:
                if not (abs(a[1] - y0) < tol_m or abs(a[1] - y1) < tol_m):
                    continue
                lo, hi = sorted((a[0], c[0]))
                span, ends, axis = (x0, x1), (lo, hi), "x"
                off: Callable[[float], float] = rhythm.off_bay_x
            else:
                if not (abs(a[0] - x0) < tol_m or abs(a[0] - x1) < tol_m):
                    continue
                lo, hi = sorted((a[1], c[1]))
                span, ends, axis = (y0, y1), (lo, hi), "y"
                off = rhythm.off_bay_y
            if span[1] <= ends[0] + tol_m or span[0] >= ends[1] - tol_m:
                continue
            for t in span:
                if ends[0] + tol_m < t < ends[1] - tol_m and (axis, round(t, 3)) not in seen:
                    seen.add((axis, round(t, 3)))
                    n += 1
                    on_whole = off(t) <= tol_m
                    whole += on_whole
                    half += on_whole or off(t - half_m) <= tol_m
    return n, half, whole


def plan_columns(
    rhythm: Rhythm, plan: PlanLike, skeleton: Skeleton
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """``(columns, columns inside a room of less than 30 m²)`` of one plan; a column is inside
    a room when it is farther than 0.15 m from every side (otherwise it is on a wall)."""
    outline = ShPolygon(list(plan.outline)) if len(plan.outline) >= 3 else None
    if outline is None:
        return [], []
    solids = [skeleton.core] + ([skeleton.wet] if skeleton.wet is not None else [])
    cols = columns_of(rhythm, outline, solids)
    small: list[tuple[float, float]] = []
    for x, y in cols:
        for r in plan.rooms_abs:
            if r.kind != "room":
                continue
            rx, ry, w, h = r.rect
            m = 0.15
            if rx + m < x < rx + w - m and ry + m < y < ry + h - m and w * h < SMALL_ROOM_M2:
                small.append((x, y))
                break
    return cols, small
