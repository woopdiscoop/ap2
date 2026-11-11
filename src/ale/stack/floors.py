"""Per-floor cell diagrams inside the vertical skeleton (Ticket M.1, RD section 6)."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from shapely import LineString, Point

from ale.config import AleConfig
from ale.contracts.geometry import Polygon
from ale.contracts.models import CoreSpec, GridSpec, Program, SiteSpec
from ale.stack.building import Building
from ale.stack.rules import WET_TYPES, StackInputError
from ale.stack.skeleton import CELL_M, CellRect, Skeleton
from ale.topology.cellgrow import CORE_CELL, FREE, OUTSIDE, CellDiagram, grow

__all__ = [
    "SHORT_TOL",
    "FloorResult",
    "build_floors",
    "floor_programs",
    "stackability",
    "write_programme_xlsx",
]

SHORT_TOL = 0.95
_FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))
Cell = tuple[int, int]


@dataclass(frozen=True)
class FloorResult:
    """One floor: its site (outline + core + wet stack), programmes and cell diagram."""

    level: int
    offset: Cell
    site: SiteSpec
    program_all: Program | None
    program_cells: Program | None
    diagram: CellDiagram | None = None
    repaired: tuple[str, ...] = ()
    facade_missing: tuple[str, ...] = ()
    off_circulation: tuple[str, ...] = ()
    short: tuple[str, ...] = ()
    fragmented: tuple[str, ...] = ()
    skeleton_cells: frozenset[Cell] = frozenset()
    room_cells: Mapping[str, frozenset[Cell]] | None = None
    room_types: Mapping[str, str] | None = None
    error: str = ""

    def layer(self) -> dict[Cell, str]:
        """Global cell -> room type for every room cell (wet rooms included)."""
        out: dict[Cell, str] = {}
        for room, cs in (self.room_cells or {}).items():
            for c in cs:
                out[c] = (self.room_types or {})[room]
        return out


# ----------------------------------------------------------------------- programmes
def floor_programs(
    program: Program, level_of: Mapping[str, int], level: int
) -> tuple[Program | None, Program | None]:
    """``(all rooms, non-wet rooms)`` of ``level`` as programmes. Quantities are the number of
    instances on the floor, ``floor`` is set to the level, references to rooms absent from the
    floor are dropped."""
    counts: dict[str, int] = {}
    for iid, spec in program.instances():
        if level_of[iid] == level:
            counts[spec.id] = counts.get(spec.id, 0) + 1
    return _subset(program, counts, level), _subset(
        program, {k: v for k, v in counts.items() if _type(program, k) not in WET_TYPES}, level
    )


def _type(program: Program, spec_id: str) -> str:
    return next(r.type for r in program.rooms if r.id == spec_id)


def _subset(program: Program, counts: dict[str, int], level: int) -> Program | None:
    if not counts:
        return None
    rooms = []
    for r in program.rooms:
        if r.id not in counts:
            continue
        rooms.append(
            r.model_copy(
                update={
                    "quantity": counts[r.id],
                    "floor": level,
                    "adjacent_to": tuple(a for a in r.adjacent_to if a in counts),
                    "avoid": tuple(a for a in r.avoid if a in counts),
                    "anchor": None if (r.anchor == "entrance" and level > 0) else r.anchor,
                }
            )
        )
    return Program(rooms=tuple(rooms))


def write_programme_xlsx(program: Program, path: Path) -> Path:
    """Write ``program`` in the template columns; the bytes are deterministic."""
    import openpyxl  # type: ignore[import-untyped,unused-ignore]

    from ale.program.excel import HEADERS, SHEET_NAME
    from ale.program.template import program_rows

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    ws.append(list(HEADERS))
    for row in program_rows(program):
        ws.append(row)
    import datetime as dt

    fixed = dt.datetime(2026, 1, 1, 0, 0, 0)
    wb.properties.created = fixed
    wb.properties.modified = fixed
    wb.properties.creator = "ALE"
    raw = io.BytesIO()
    wb.save(raw)
    out = io.BytesIO()
    with zipfile.ZipFile(raw) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in sorted(zin.infolist(), key=lambda i: i.filename):
            zi = zipfile.ZipInfo(info.filename, date_time=_FIXED_ZIP_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o600 << 16
            zout.writestr(zi, zin.read(info.filename))
    path.write_bytes(out.getvalue())
    return path


# ---------------------------------------------------------------------------- sites
def _ring(outline_coords: Sequence[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    return tuple((round(x, 6), round(y, 6)) for x, y in outline_coords[:-1])


def _access_edge(ring: Sequence[tuple[float, float]], ref: tuple[float, float]) -> int:
    n = len(ring)
    edges = [LineString([ring[i], ring[(i + 1) % n]]) for i in range(n)]
    p = Point(ref)
    return min(range(n), key=lambda i: (round(edges[i].distance(p), 9), i))


def _core_spec(
    cid: str, kind: str, r: CellRect, off: Cell, origin: tuple[float, float]
) -> CoreSpec:
    x = origin[0] + (r[0] - off[0]) * CELL_M
    y = origin[1] + (r[1] - off[1]) * CELL_M
    return CoreSpec(
        id=cid,
        rect=(
            round(x, 6),
            round(y, 6),
            round((r[2] - r[0]) * CELL_M, 6),
            round((r[3] - r[1]) * CELL_M, 6),
        ),
        kind=kind,  # type: ignore[arg-type]
    )


def _floor_site(b: Building, sk: Skeleton, level: int) -> tuple[SiteSpec, Cell]:
    outline = b.outline(level)
    ring = _ring([(c[0], c[1]) for c in outline.exterior.coords])
    x0, y0 = outline.bounds[0], outline.bounds[1]
    off = (round((x0 - sk.grid.ox) / CELL_M), round((y0 - sk.grid.oy) / CELL_M))
    main = next((e for e in b.entrances if e.main), b.entrances[0] if b.entrances else None)
    if level == 0:
        access = b.access_edge
    elif main is not None:
        access = _access_edge(ring, main.point)
    else:
        g = b.floors[0].footprint.exterior
        a, c = g[b.access_edge], g[(b.access_edge + 1) % len(g)]
        access = _access_edge(ring, ((a[0] + c[0]) / 2, (a[1] + c[1]) / 2))
    cores = [_core_spec(b.core.id, b.core.kind, sk.core, off, (x0, y0))]
    if sk.wet is not None:
        cores.append(_core_spec("WET", "shaft", sk.wet, off, (x0, y0)))
    try:
        site = SiteSpec(
            footprint=Polygon(exterior=ring),
            north_angle_deg=b.north_angle_deg,
            access_edge=access,
            entrances=b.entrances if level == 0 else (),
            cores=tuple(cores),
            mode="footprint",
        )
    except ValueError as exc:
        raise StackInputError(f"Niveau {level} : site invalide ({exc}).") from None
    return site, off


# ------------------------------------------------------------------------- diagrams
def _components(cells: set[Cell]) -> list[set[Cell]]:
    comps: list[set[Cell]] = []
    left = set(cells)
    while left:
        seed = min(left)
        comp = {seed}
        stack = [seed]
        while stack:
            x, y = stack.pop()
            for dx, dy in _DIRS:
                q = (x + dx, y + dy)
                if q in left and q not in comp:
                    comp.add(q)
                    stack.append(q)
        comps.append(comp)
        left -= comp
    return comps


def _repair(d0: CellDiagram) -> tuple[CellDiagram, tuple[str, ...]]:
    """Keep each room's largest connected piece; strays become circulation (as in G.2)."""
    owner = [list(row) for row in d0.owner]
    cells = dict(d0.cells)
    repaired = []
    for room in d0.rooms:
        comps = _components(set(d0.cells[room]))
        if len(comps) > 1:
            keep = max(comps, key=lambda c: (len(c), min(c)))
            for x, y in set(d0.cells[room]) - keep:
                owner[y][x] = FREE
            repaired.append(room)
            cells[room] = tuple(sorted(keep))
    return replace(d0, owner=tuple(tuple(r) for r in owner), cells=cells), tuple(repaired)


def _metrics(d: CellDiagram, needs: Mapping[str, bool]) -> tuple[tuple[str, ...], ...]:
    nofac, off = [], []
    for room in d.rooms:
        cs = d.cells[room]
        if not cs:
            continue
        on_facade = touch = False
        for x, y in cs:
            for dx, dy in _DIRS:
                nx, ny = x + dx, y + dy
                if not (0 <= ny < d.height and 0 <= nx < d.width) or d.owner[ny][nx] == OUTSIDE:
                    on_facade = True
                elif d.owner[ny][nx] in (FREE, CORE_CELL):
                    touch = True
        if needs[room] and not on_facade:
            nofac.append(room)
        if not touch:
            off.append(room)
    short = tuple(sorted(r for r in d.rooms if len(d.cells[r]) < SHORT_TOL * d.targets[r]))
    frag = tuple(r for r in d.rooms if d.cells[r] and len(_components(set(d.cells[r]))) > 1)
    return tuple(nofac), tuple(off), short, frag


def _diagram(prog: Program, site: SiteSpec, seed: int) -> tuple[CellDiagram, dict[str, bool]]:
    from ale.parti.evaluate import neutral_rulebook
    from ale.program.feasibility import check_feasibility
    from ale.program.models import PreparedInput
    from ale.program.site import to_module_footprint

    config = AleConfig()
    grid = GridSpec(module_mm=config.grid.module_mm)
    fp = to_module_footprint(site, grid)
    rb = neutral_rulebook(prog)
    feas = check_feasibility(prog, fp, rb, config)
    prep = PreparedInput(
        program=prog,
        instances=prog.instances(),
        site=site,
        footprint=fp,
        grid=grid,
        rulebook_version=rb.version,
        feasibility=feas,
        warnings=(),
    )
    needs = {iid: spec.needs_facade for iid, spec in prep.instances}
    return grow(prep, rb, config, seed=seed), needs


def build_floors(
    building: Building,
    skeleton: Skeleton,
    program: Program,
    level_of: Mapping[str, int],
    *,
    seed: int = 0,
) -> tuple[FloorResult, ...]:
    """One :class:`FloorResult` per floor (``level_of`` maps every instance id to a level)."""
    out = []
    expected = skeleton.core_cells | skeleton.wet_cells
    for k in range(building.n_floors):
        site, off = _floor_site(building, skeleton, k)
        p_all, p_cells = floor_programs(program, level_of, k)
        wet = skeleton.floors[k]
        wet_cells = {r.iid: r.cells for r in wet.rooms}
        wet_types = {r.iid: r.type for r in wet.rooms}
        if p_cells is None:
            out.append(
                FloorResult(
                    k,
                    off,
                    site,
                    p_all,
                    None,
                    room_cells=wet_cells,
                    room_types=wet_types,
                    skeleton_cells=expected,
                )
            )
            continue
        try:
            d0, needs = _diagram(p_cells, site, seed)
        except Exception as exc:  # report and go on: one bad floor must not stop the others
            out.append(
                FloorResult(
                    k,
                    off,
                    site,
                    p_all,
                    p_cells,
                    room_cells=wet_cells,
                    room_types=wet_types,
                    error=f"Niveau {k} : diagramme impossible ({type(exc).__name__} : {exc}).",
                )
            )
            continue
        d, repaired = _repair(d0)
        nofac, off_circ, short, frag = _metrics(d, needs)
        cells = {r: frozenset((x + off[0], y + off[1]) for x, y in d.cells[r]) for r in d.rooms}
        types = dict(d.types)
        sk_cells = frozenset((x + off[0], y + off[1]) for x, y in d.cores)
        cells.update(wet_cells)
        types.update(wet_types)
        out.append(
            FloorResult(
                k,
                off,
                site,
                p_all,
                p_cells,
                d,
                repaired,
                nofac,
                off_circ,
                short,
                frag,
                sk_cells,
                cells,
                types,
            )
        )
    return tuple(out)


def stackability(layers: Sequence[Mapping[Cell, str]]) -> float:
    """Share of room cells whose cell directly above or below is a room cell of the same type
    (``layers[k]`` maps global cells to room types on floor ``k``)."""
    total = stacked = 0
    for k, layer in enumerate(layers):
        for c, t in layer.items():
            total += 1
            above = layers[k + 1].get(c) if k + 1 < len(layers) else None
            below = layers[k - 1].get(c) if k > 0 else None
            if t in (above, below):
                stacked += 1
    return stacked / total if total else 0.0


def skeleton_identical(floors: Sequence[FloorResult], skeleton: Skeleton) -> bool:
    """Core and wet-stack cells of every floor diagram equal the skeleton's (hard check)."""
    expected = skeleton.core_cells | skeleton.wet_cells
    return all(f.diagram is None or f.skeleton_cells == expected for f in floors)


__all__ += ["skeleton_identical"]
