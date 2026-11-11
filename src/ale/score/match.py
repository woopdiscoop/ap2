"""Drawn rooms of a sheet and their one-to-one matching with programme lines (R.10).

* :func:`extract_sheet`: every plan of a reader result -> rooms with an area in m² (the
  written ``area_text_m2`` when present, else polygon area x scale²), the plan they are on
  (rooms of one reader plan are split into plans by spatial proximity, since a PDF page
  gives one ``PlanGeometry``), whether they touch the plan's outer boundary and the stair
  cores of each plan.
* :func:`match_lines`: minimum-cost assignment (Hungarian), cost ``|area - target| / target``,
  halved when the room's label matches the programme name; pairs more than 25 % apart are
  not matched.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field

import shapely
from shapely.ops import unary_union

from ale.contracts.geometry import to_shapely
from ale.contracts.models import LabelledPolygon, PlanGeometry, Program
from ale.contracts.taxonomy import canon
from ale.join import resolve_scale

__all__ = [
    "MAX_GAP",
    "NAME_FACTOR",
    "STAIR_TYPE",
    "DrawnRoom",
    "Line",
    "Match",
    "PlanInfo",
    "Sheet",
    "assign",
    "extract_sheet",
    "lines_from_program",
    "match_lines",
]

MAX_GAP = 0.25  # relative gap above which a pair is not matched
NAME_FACTOR = 0.5  # cost factor when the drawn label matches the programme name
STAIR_TYPE = "stair"
PLAN_SPLIT_M = 1.5  # rooms closer than this belong to the same plan
_BIG = 1.0e9


@dataclass(frozen=True)
class DrawnRoom:
    """One room read from the drawing."""

    plan: int
    room_id: str
    area_m2: float
    source: str  # "texte" (written area) or "géométrie"
    label: str | None
    type: str | None
    on_facade: bool


@dataclass(frozen=True)
class PlanInfo:
    """One plan of the sheet."""

    index: int
    rooms: int
    stair_cores: int


@dataclass
class Sheet:
    """Everything read from the drawing."""

    rooms: list[DrawnRoom] = field(default_factory=list)
    plans: list[PlanInfo] = field(default_factory=list)
    stairs: list[DrawnRoom] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # rooms without any area
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Line:
    """One programme instance (a line with quantity n gives n instances)."""

    key: str
    name: str
    type: str
    target_m2: float
    needs_facade: bool


@dataclass(frozen=True)
class Match:
    """A programme instance assigned to a drawn room."""

    line: int
    room: int
    gap: float  # (drawn - target) / target


@dataclass(frozen=True)
class _Group:
    miny: float
    minx: float
    members: list[tuple[LabelledPolygon, shapely.Polygon]]
    buf: float
    scale: float | None


# --------------------------------------------------------------------------- programme


def lines_from_program(program: Program) -> list[Line]:
    """Programme instances (quantity expanded, ``.k`` suffix when quantity > 1)."""
    out: list[Line] = []
    for spec in program.rooms:
        if spec.type == STAIR_TYPE:
            continue  # vertical circulation is scored apart (U-14)
        for k in range(spec.quantity):
            key = spec.id if spec.quantity == 1 else f"{spec.id}.{k + 1}"
            out.append(Line(key, spec.name, spec.type, spec.target_area_m2, spec.needs_facade))
    return out


# --------------------------------------------------------------------------- Hungarian


def assign(cost: Sequence[Sequence[float]]) -> list[tuple[int, int]]:
    """Minimum-cost one-to-one assignment of a rectangular matrix: ``(row, col)`` pairs."""
    n, m = len(cost), len(cost[0]) if cost else 0
    if n == 0 or m == 0:
        return []
    transposed = n > m
    c = [list(col) for col in zip(*cost, strict=True)] if transposed else [list(r) for r in cost]
    rows, cols = len(c), len(c[0])  # rows <= cols
    u = [0.0] * (rows + 1)
    v = [0.0] * (cols + 1)
    p = [0] * (cols + 1)
    way = [0] * (cols + 1)
    for i in range(1, rows + 1):
        p[0] = i
        j0 = 0
        minv = [math.inf] * (cols + 1)
        used = [False] * (cols + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], math.inf, 0
            for j in range(1, cols + 1):
                if used[j]:
                    continue
                cur = c[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j], way[j] = cur, j0
                if minv[j] < delta:
                    delta, j1 = minv[j], j
            for j in range(cols + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    pairs = [(p[j] - 1, j - 1) for j in range(1, cols + 1) if p[j] != 0]
    if transposed:
        pairs = [(b, a) for a, b in pairs]
    return sorted(pairs)


def _names_match(room: DrawnRoom, line: Line) -> bool:
    if room.type is not None and room.type == line.type:
        return True
    if room.label:
        a, b = canon(room.label), canon(line.name)
        return bool(a) and bool(b) and (a in b or b in a)
    return False


def match_lines(lines: Sequence[Line], rooms: Sequence[DrawnRoom]) -> list[Match]:
    """One-to-one matching of programme instances with drawn rooms (see module docstring)."""
    cost: list[list[float]] = []
    for ln in lines:
        row: list[float] = []
        for rm in rooms:
            gap = abs(rm.area_m2 - ln.target_m2) / ln.target_m2
            if gap > MAX_GAP:
                row.append(_BIG)
            else:
                row.append(gap * (NAME_FACTOR if _names_match(rm, ln) else 1.0))
        cost.append(row)
    pairs = [(i, j) for i, j in assign(cost) if cost[i][j] < _BIG]
    return [
        Match(i, j, (rooms[j].area_m2 - lines[i].target_m2) / lines[i].target_m2) for i, j in pairs
    ]


# --------------------------------------------------------------------------- drawing


def _clusters(polys: Sequence[shapely.Polygon], gap: float) -> list[list[int]]:
    parent = list(range(len(polys)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            if polys[i].distance(polys[j]) <= gap:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(polys)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _outer_boundary(polys: Sequence[shapely.Polygon], buf: float) -> shapely.Geometry:
    merged = unary_union([p.buffer(buf) for p in polys])
    geoms = list(getattr(merged, "geoms", [merged]))
    return unary_union([shapely.Polygon(g.exterior).exterior for g in geoms])


def _split_plan(plan: PlanGeometry, sheet: Sheet) -> list[_Group]:
    resolved = plan if plan.scale_m_per_unit is not None else resolve_scale(plan)
    scale = resolved.scale_m_per_unit
    sheet.warnings.extend(resolved.warnings)
    if scale is None:
        sheet.warnings.append(
            f"plan p{plan.page}/{plan.plan_index} : échelle inconnue, "
            "seules les surfaces écrites sont lisibles"
        )
    items: list[tuple[LabelledPolygon, shapely.Polygon]] = []
    for r in resolved.rooms:
        g = to_shapely(r.polygon)
        if isinstance(g, shapely.Polygon) and not g.is_empty:
            items.append((r, g))
    if not items:
        return []
    unit_m = 1.0 / scale if scale else None
    minx, miny, maxx, maxy = unary_union([p for _, p in items]).bounds
    diag = math.dist((minx, miny), (maxx, maxy))
    split = PLAN_SPLIT_M * unit_m if unit_m else 0.03 * diag
    thick = [w.thickness for w in resolved.walls if w.thickness]
    buf = statistics.median(thick) if thick else (0.3 * unit_m if unit_m else 0.01 * diag)
    out: list[_Group] = []
    for idx in _clusters([p for _, p in items], split):
        members = [items[i] for i in idx]
        out.append(
            _Group(
                min(p.bounds[1] for _, p in members),
                min(p.bounds[0] for _, p in members),
                members,
                buf,
                scale,
            )
        )
    return out


def extract_sheet(plans: Sequence[PlanGeometry]) -> Sheet:
    """Rooms, plans and stair cores of the plans a reader returned (see module docstring)."""
    sheet = Sheet()
    groups: list[_Group] = []
    for plan in plans:
        groups.extend(_split_plan(plan, sheet))
    ys = [g.miny for g in groups]
    band = (max(ys) - min(ys)) / 10.0 if ys else 0.0
    band = band or 1.0
    groups.sort(key=lambda g: (round(g.miny / band), g.minx))  # reading order, top row first
    for index, g in enumerate(groups):
        outer = _outer_boundary([p for _, p in g.members], g.buf)
        stair_polys: list[shapely.Polygon] = []
        for room, poly in g.members:
            if room.area_text_m2 is not None:
                area, source = float(room.area_text_m2), "texte"
            elif g.scale is not None:
                area, source = float(poly.area) * g.scale * g.scale, "géométrie"
            else:
                sheet.skipped.append(f"plan {index + 1} · {room.id}")
                continue
            drawn = DrawnRoom(
                plan=index,
                room_id=room.id,
                area_m2=area,
                source=source,
                label=room.raw_label,
                type=room.type,
                on_facade=bool(poly.distance(outer) <= g.buf * 1.05),
            )
            if room.type == STAIR_TYPE:
                sheet.stairs.append(drawn)
                stair_polys.append(poly)
            else:
                sheet.rooms.append(drawn)
        cores = len(_clusters(stair_polys, 3.0 * g.buf)) if stair_polys else 0
        sheet.plans.append(PlanInfo(index, len(g.members), cores))
    return sheet
