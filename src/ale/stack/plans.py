"""Exact per-floor plans around the vertical skeleton (Ticket M.2, RD section 4).

After the stacking of M.1, every floor is laid out by the exact-plan engine (``ale generate``:
seed, anneal) on ``floor_NN/site.yaml`` whose core and wet stack are *solids*, with the floor's
non-wet programme; the core and the floor's wet rooms (M.1's tiling) are then put into
``Layout.fixed``. Files per floor in ``floor_NN/plan/``: ``layout.json``, ``layout.dxf``,
``preview.svg``, ``report.md`` (the engine's export), ``site.yaml`` and ``programme.xlsx`` (the
inputs given to the engine). ``plans.md`` (French) summarises every floor and carries the
**vertical check** (core and wet stack on identical rectangles on every floor: hard).

A floor whose generation fails (programme too big, no layout, engine error) is reported in
``plans.md``; the other floors still run. Exit code of ``ale stack --plans``: see
:func:`plans_misses` (a failed floor, a layout that does not pass ``check_layout`` or a failed
vertical check are hard misses; residual hard violations of the engine are reported per floor
but are a sketch tolerance, as in M.1).

Solids must not touch the outline (contracts 1.7.0), so a plan needs a wet stack that keeps
one cell (0.60 m) from the outline: :func:`build_skeleton_strict` places it so, and
:func:`run_plans` re-runs the stacking with it when the given result does not satisfy this.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ale.config import AleConfig
from ale.contracts.models import (
    GridSpec,
    Layout,
    PlacedRoom,
    RoomSpec,
    Rulebook,
    SiteSpec,
    Violation,
)
from ale.contracts.serialization import dump_yaml
from ale.stack.building import Building
from ale.stack.floors import FloorResult, _core_spec, write_programme_xlsx
from ale.stack.grid import Rhythm
from ale.stack.skeleton import (
    AREA_CELL_M2,
    CellRect,
    Grid,
    Skeleton,
    WetFloor,
    _place,
    _tile,
    _type_rank,
    _valid_cells,
    cells_of,
    core_cell_rect,
    distribute_wet,
    rect_cells,
)

if TYPE_CHECKING:
    from ale.bayplan import BayResult
    from ale.geometry.bay import BayHint
    from ale.optimize.anneal import AnnealResult
    from ale.program.models import PreparedInput
    from ale.stack.report import StackResult

__all__ = [
    "FloorPlan",
    "PlansResult",
    "build_skeleton_strict",
    "plans_misses",
    "render_plans_markdown",
    "run_plans",
    "write_plans",
]

PLANS_NAME = "plans.md"
GAP_PREFIX = "reserve_technique_g"
SEED_SHARE = 0.6
SEED_TRIES_MIN = 3
SEED_TRIES_MAX = 6
TRY_ATTEMPTS = 12
DEFAULT_BUDGET_S = 20.0
MARGINS_CELLS = (6, 4, 2, 1)
"""Cells (0.60 m) kept between the wet stack and the outline of the top floor, tried in order:
a thinner gap leaves a piece too shallow for the corridor grammar, so the widest that still
places the stack wins."""
#: ``(x, y, w, h)`` in metres, rounded to the millimetre.
MetreRect = tuple[float, float, float, float]


@dataclass(frozen=True)
class PlanRoom:
    """A room of a plan in building coordinates (metres); ``kind`` is ``room``, ``fixed`` or
    ``circulation``; ``type`` is the room type (``None`` for the core, shaft, circulation)."""

    iid: str
    spec_id: str | None
    type: str | None
    rect: MetreRect
    kind: str


# ------------------------------------------------------------------ strict skeleton
def build_skeleton_strict(
    building: Building,
    wet: Sequence[tuple[str, RoomSpec]],
    floor_areas: Sequence[float],
) -> Skeleton:
    """:func:`ale.stack.skeleton.build_skeleton` with the wet stack kept one cell away from the
    outline of the top floor, so that core + stack form a solid strictly inside every outline
    (contracts 1.7.0). Same sizing, tiling and miss reporting."""
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
    b = ground.bounds
    bounds: CellRect = (
        grid.cell_x(b[0]) - 1,
        grid.cell_y(b[1]) - 1,
        grid.cell_x(b[2]) + 2,
        grid.cell_y(b[3]) + 2,
    )
    base = _valid_cells(building.outline(n - 1), grid, bounds)
    found = None
    for margin in MARGINS_CELLS:
        reach = range(-margin, margin + 1)
        inner = {
            c for c in base if all((c[0] + dx, c[1] + dy) in base for dx in reach for dy in reach)
        }
        found = _place(needs, core, inner - set(rect_cells(core)))
        if found is not None:
            break
    if found is None:
        miss = (
            "Colonne humide : aucun emplacement adjacent au noyau, inscrit dans le contour du "
            "dernier niveau à 0,60 m au moins de celui-ci, pour la demande humide "
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


# ----------------------------------------------------------------------- results
@dataclass(frozen=True)
class FloorPlan:
    """The plan of one floor (or why there is none)."""

    level: int
    status: str  # "ok" | "failed" | "empty"
    message: str = ""
    layout: Layout | None = None
    out_dir: Path | None = None
    problems: tuple[str, ...] = ()
    hard: tuple[Violation, ...] = ()
    facade_missing: tuple[str, ...] = ()
    target_m2: float = 0.0
    placed_m2: float = 0.0
    circulation_m2: float = 0.0
    elapsed_s: float = 0.0
    core: MetreRect | None = None
    stack: MetreRect | None = None
    solids: tuple[MetreRect, ...] = ()
    fixed: tuple[tuple[str, MetreRect], ...] = ()
    rooms_abs: tuple[PlanRoom, ...] = ()
    outline: tuple[tuple[float, float], ...] = ()
    origin: tuple[float, float] = (0.0, 0.0)
    snapped: tuple[int, int, int] = (0, 0, 0)
    """Façade walls found, already on a bay line, moved onto one (:mod:`ale.stack.snap`)."""
    lattice: tuple[int, int, int] = (0, 0, 0)
    """M.3b: ``(1 if the annealing ran on the lattice else 0, realisations of
    :func:`ale.geometry.realize` on it, fallbacks to a lattice-free run)``."""
    planner: str = "engine"
    """M.4: ``"bay"`` when the floor was planned bay-first, else ``"engine"``."""
    why: str = ""
    """M.4: French reason why a floor was left to the engine under planner ``bay``."""
    bay: BayResult | None = None
    """M.4: the bay planner's figures (section, unplaced, « à ajuster », reserve, notes)."""

    @property
    def passes(self) -> bool:
        """A layout was produced and passes ``check_layout``."""
        return self.status == "ok" and not self.problems


@dataclass(frozen=True)
class FloorRhythm:
    """Bay and column figures of one plan (Ticket M.3)."""

    level: int
    partitions: int
    on_bay: int
    columns: int
    small: int


@dataclass(frozen=True)
class PlansResult:
    """All floor plans, the vertical check and the hard misses."""

    floors: tuple[FloorPlan, ...]
    vertical: tuple[str, ...]  # one line per check
    vertical_ok: bool
    notes: tuple[str, ...] = ()
    misses: tuple[str, ...] = field(default=())
    rhythm: Rhythm | None = None
    rhythms: tuple[FloorRhythm, ...] = ()
    stacking: tuple[float, ...] = ()
    """Plan-level stackability of floors 1.. against the floor below (exact plans)."""
    planner: str = "engine"
    section_note: str = ""
    """M.4: French reason for the facade-row depth of the building (planner ``bay``)."""
    bound: tuple[float, ...] = ()
    """M.4: type-area bound of floors 1.. (planner ``bay``)."""
    entrances: tuple[tuple[float, float], ...] = ()
    """M.4: entrance points of the building (planner ``bay``)."""
    anchored: tuple[str, ...] = ()
    """M.4: ids of the programme rooms anchored at the entrance (planner ``bay``)."""
    longside: tuple[tuple[int, int, int, int], ...] = ()
    """M.4: ``(level, partitions, on half-bay lines, on bay lines)`` of the bay floors."""

    @property
    def ok(self) -> bool:
        """No hard miss."""
        return not self.misses


# ------------------------------------------------------------------- bay context
@dataclass(frozen=True)
class BayContext:
    """What the bay planner (Ticket M.4) needs from the building: the facade-row depth
    (modules), the corridor width, the sketch configuration and the room groups."""

    df: int
    corridor_m: float
    sketch: AleConfig
    group_of: Callable[[str, RoomSpec], str]


# --------------------------------------------------------------------- one floor
def _rect_of(cells: Sequence[tuple[int, int]]) -> CellRect:
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def _placed(
    iid: str, spec_id: str | None, r: CellRect, off: tuple[int, int], k: int, target: float | None
) -> PlacedRoom:
    from ale.contracts.geometry import ModuleRect

    return PlacedRoom(
        instance_id=iid,
        spec_id=spec_id,
        rect=ModuleRect(
            x=(r[0] - off[0]) * k, y=(r[1] - off[1]) * k, w=(r[2] - r[0]) * k, h=(r[3] - r[1]) * k
        ),
        target_area_m2=target,
    )


def _fixed_rooms(
    f: FloorResult, sk: Skeleton, building: Building, module_mm: int
) -> tuple[PlacedRoom, ...]:
    """Core, wet rooms, shaft strip and technical reserve of a floor, in the floor's modules."""
    if 600 % module_mm:
        raise ValueError(f"trame de {module_mm} mm : la grille de 0,60 m n'est pas un multiple")
    k = 600 // module_mm
    off = f.offset
    rooms = [_placed(building.core.id, None, sk.core, off, k, None)]
    wf = sk.floors[f.level]
    for wr in wf.rooms:
        rooms.append(_placed(wr.iid, wr.spec_id, _rect_of(sorted(wr.cells)), off, k, wr.target_m2))
    if sk.wet is not None:
        if sk.shaft:
            rooms.append(_placed("gaine_humide", None, _rect_of(sorted(sk.shaft)), off, k, None))
        if wf.reserve:
            rooms.append(
                _placed("reserve_technique", None, _rect_of(sorted(wf.reserve)), off, k, None)
            )
    if sk.wet is not None:
        for n, g in enumerate(_gap_rects(sk), start=1):
            rooms.append(_placed(f"{GAP_PREFIX}{n}", None, g, off, k, None))
    return tuple(sorted(rooms, key=lambda p: p.instance_id))


def _metres(layout: Layout, origin: tuple[float, float], r: tuple[int, int, int, int]) -> MetreRect:
    m = layout.grid.module_mm / 1000
    return (
        round(origin[0] + r[0] * m, 3),
        round(origin[1] + r[1] * m, 3),
        round(r[2] * m, 3),
        round(r[3] * m, 3),
    )


def _union_rect(rects: Sequence[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    y1 = max(r[1] + r[3] for r in rects)
    return (x0, y0, x1 - x0, y1 - y0)


def _hard_of(layout: Layout) -> tuple[Violation, ...]:
    from ale.geometry.evaluate import hard_codes_of
    from ale.optimize.anneal import HARD_CODES

    hard = hard_codes_of(layout.metrics, HARD_CODES)
    return tuple(v for v in layout.metrics.violations if v.code in hard)


def _bbox_cells(sk: Skeleton) -> CellRect:
    """Bounding rectangle (global cells) of the core and the wet stack: the solid of a plan."""
    rects = [sk.core] + ([sk.wet] if sk.wet is not None else [])
    return (
        min(r[0] for r in rects),
        min(r[1] for r in rects),
        max(r[2] for r in rects),
        max(r[3] for r in rects),
    )


def _gap_rects(sk: Skeleton) -> list[CellRect]:
    """Rectangles tiling the solid's cells that are neither core nor wet stack (row scan)."""
    box = _bbox_cells(sk)
    left = set(rect_cells(box)) - sk.core_cells - sk.wet_cells
    out: list[CellRect] = []
    while left:
        x0, y0 = min(left, key=lambda c: (c[1], c[0]))
        x1 = x0
        while (x1 + 1, y0) in left:
            x1 += 1
        y1 = y0
        while all((x, y1 + 1) in left for x in range(x0, x1 + 1)):
            y1 += 1
        r = (x0, y0, x1 + 1, y1 + 1)
        out.append(r)
        left -= set(rect_cells(r))
    return out


def _plan_site(f: FloorResult, sk: Skeleton, building: Building) -> SiteSpec:
    """The floor site given to the engine: one rectangular solid around core and wet stack
    (the corner left between them is a technical reserve, drawn as fixed rooms)."""
    ext = f.site.footprint.exterior
    origin = (min(p[0] for p in ext), min(p[1] for p in ext))
    core = _core_spec(f"{building.core.id[:20]}_HUM", "core", _bbox_cells(sk), f.offset, origin)
    return f.site.model_copy(update={"cores": (core,)})


def _generate_floor(
    f: FloorResult,
    sk: Skeleton,
    building: Building,
    rulebook: Path,
    plan_dir: Path,
    config: AleConfig,
    seed: int,
    rhythm: Rhythm | None = None,
    below: FloorPlan | None = None,
    bay: BayContext | None = None,
) -> FloorPlan:
    """Prepare, seed, anneal, snap to the bay lines, add the fixed rooms, check and export one
    floor. ``below`` is the neighbouring floor already planned (its room order is the prior of
    the seeding). With ``bay`` (Ticket M.4) an eligible floor is planned bay-first instead
    (no seed, no annealing); the rest of the function is shared."""
    from ale.export import export_run
    from ale.geometry.checks import check_layout
    from ale.geometry.evaluate import FACADE_CODES
    from ale.program import load_rulebook, prepare_input
    from ale.program.models import InputError

    if f.program_cells is None:
        return FloorPlan(f.level, "empty", "aucune pièce hors colonne humide à ce niveau")
    start = time.monotonic()
    plan_dir.mkdir(parents=True, exist_ok=True)
    prog_path = write_programme_xlsx(f.program_cells, plan_dir / "programme.xlsx")
    site_path = plan_dir / "site.yaml"
    site_path.write_text(dump_yaml(_plan_site(f, sk, building)), encoding="utf-8", newline="\n")
    try:
        prepared = prepare_input(prog_path, site_path, rulebook, config)
    except InputError as exc:
        errors = "; ".join(i.message for i in exc.issues if i.severity == "error")
        return FloorPlan(f.level, "failed", f"entrées refusées : {errors}")
    rb, _ = load_rulebook(rulebook)
    assert rb is not None  # prepare_input validated it
    bay_res: BayResult | None = None
    why = ""
    if bay is not None:
        from ale.bayplan import NotEligible, plan_bar

        if rhythm is None:
            why = "aucune trame de travée : le moteur dessine le niveau."
        else:
            try:
                bay_res = plan_bar(
                    prepared,
                    rb,
                    bay.sketch,
                    rhythm,
                    df=bay.df,
                    corridor_m=bay.corridor_m,
                    group_of=bay.group_of,
                )
            except NotEligible as exc:
                why = f"{exc.reason} : le moteur dessine le niveau."
    check_config = config
    if bay_res is not None:
        base = bay_res.layout
        check_config = bay.sketch if bay is not None else config
        snapped = (0, 0, 0)
        lattice = (0, 0, 0)
    else:
        prior = _prior_positions(prepared, rb, below, seed)
        hint = None if rhythm is None else rhythm.hint()
        res, attempt, why_seed = _seed_and_anneal(prepared, rb, config, prior, seed, hint)
        if res is None:
            return FloorPlan(
                f.level,
                "failed",
                f"aucune réalisation exacte après {attempt} essai(s) ({why_seed})",
                why=why,
            )
        base = res.layout
        snapped = (0, 0, 0)
        lattice = (0, 0, 0)
        if rhythm is not None:
            assert hint is not None
            lattice = (
                int(hint.stats.fallbacks == 0),
                hint.stats.realisations,
                hint.stats.fallbacks,
            )
            from ale.stack.snap import snap_layout

            base, st = snap_layout(base, prepared, rb, config, rhythm)
            snapped = (st.walls, st.already, st.moved)
    fixed = _fixed_rooms(f, sk, building, config.grid.module_mm)
    layout = Layout.model_validate({**base.model_dump(), "fixed": [p.model_dump() for p in fixed]})
    problems = check_layout(layout, prepared, check_config)
    for stale in ("layout.json", "layout.dxf", "preview.svg", "report.md"):
        (plan_dir / stale).unlink(missing_ok=True)
    export_run(
        layout,
        prepared,
        plan_dir,
        rulebook_version=prepared.rulebook_version,
        run_id=f"plan-{f.level:02d}",
        config=check_config,
        rulebook=rb,
    )
    origin = prepared.footprint.origin_m
    rects = {p.instance_id: (p.rect.x, p.rect.y, p.rect.w, p.rect.h) for p in layout.fixed}
    core_id = building.core.id
    stack_rects = [r for i, r in rects.items() if i != core_id and not i.startswith(GAP_PREFIX)]
    fixed_m = tuple((i, _metres(layout, origin, r)) for i, r in sorted(rects.items()))
    target = sum(s.target_area_m2 for _, s in prepared.instances)
    placed = sum(p.area_m2(layout.grid) for p in layout.rooms if p.spec_id is not None)
    types = {r.id: str(r.type) for r in f.program_all.rooms} if f.program_all else {}
    rooms_abs = tuple(
        PlanRoom(
            p.instance_id,
            p.spec_id,
            types.get(p.spec_id) if p.spec_id else None,
            _metres(layout, origin, (p.rect.x, p.rect.y, p.rect.w, p.rect.h)),
            kind,
        )
        for kind, group in (
            ("room", layout.rooms),
            ("circulation", layout.circulation),
            ("fixed", layout.fixed),
        )
        for p in group
    )
    ring = tuple(
        (
            round(origin[0] + x * layout.grid.module_mm / 1000, 3),
            round(origin[1] + y * layout.grid.module_mm / 1000, 3),
        )
        for x, y in layout.footprint.exterior
    )
    return FloorPlan(
        level=f.level,
        status="ok",
        layout=layout,
        out_dir=plan_dir,
        problems=problems,
        hard=_hard_of(layout),
        facade_missing=tuple(
            sorted(
                {
                    i
                    for v in layout.metrics.violations
                    if v.code in FACADE_CODES
                    for i in v.instance_ids
                }
            )
        ),
        target_m2=target,
        placed_m2=placed,
        circulation_m2=layout.metrics.circulation_area_m2,
        elapsed_s=time.monotonic() - start,
        core=_metres(layout, origin, rects[core_id]),
        stack=_metres(layout, origin, _union_rect(stack_rects)) if stack_rects else None,
        solids=tuple(
            _metres(layout, origin, (s[0], s[1], s[2], s[3]))
            for s in (_bbox(r) for r in layout.footprint.solids)
        ),
        fixed=fixed_m,
        rooms_abs=rooms_abs,
        outline=ring,
        origin=origin,
        snapped=snapped,
        lattice=lattice,
        planner="bay" if bay_res is not None else "engine",
        why=why,
        bay=bay_res,
    )


def _seed_and_anneal(
    prepared: PreparedInput,
    rb: Rulebook,
    config: AleConfig,
    prior: Mapping[str, tuple[float, float]] | None,
    seed: int,
    hint: BayHint | None,
) -> tuple[AnnealResult | None, int, str]:
    """Seed (several tries) then anneal one floor; ``(None, tries, why)`` when no seeding
    realises. With ``hint`` (M.3b) the annealing realises with widths and depths chosen for the
    bay lines and column lines of the building and its cost gains the lattice term; the seeding
    (a lattice-free arrangement of the rooms) is as before."""
    from ale.geometry.bay import use_bay_hint
    from ale.optimize.anneal import anneal
    from ale.topology import seed_plan

    total = config.optimizer.time_budget_s
    seeded = None
    why = ""
    spent = 0.0
    attempt = 0
    # The seeder is chancy on rings around a solid (about one seed in two succeeds): try
    # other seeds, each bounded by a number of attempts (not by time, so that the result
    # does not depend on the speed of the machine): at least SEED_TRIES_MIN tries, then
    # more while the seeding share of the budget lasts, at most SEED_TRIES_MAX.
    while seeded is None or seeded.realization.layout is None:
        if attempt >= SEED_TRIES_MAX or (attempt >= SEED_TRIES_MIN and spent >= SEED_SHARE * total):
            break
        seeded = seed_plan(
            prepared,
            rb,
            config,
            seed=seed + 1000 * attempt,
            time_budget_s=max(total, 1.0),
            max_attempts=TRY_ATTEMPTS,
            prior=prior if attempt % 2 == 0 else None,
        )
        spent += seeded.elapsed_s
        attempt += 1
        if seeded.realization.layout is None:
            why = "; ".join(f"{x.code}: {x.detail}" for x in seeded.realization.failures)
    assert seeded is not None
    if seeded.realization.layout is None:
        return None, attempt, why
    anneal_config = config.model_copy(
        update={
            "optimizer": config.optimizer.model_copy(
                update={"time_budget_s": max(1.0, total - spent)}
            )
        }
    )
    try:
        with use_bay_hint(hint):
            return anneal(prepared, rb, anneal_config, seeded.plan, seed=seed), attempt, why
    except ValueError:  # the start plan does not realise on the lattice: as without it
        if hint is None:
            raise
        hint.stats.fallbacks += 1
        return anneal(prepared, rb, anneal_config, seeded.plan, seed=seed), attempt, why


def _prior_positions(
    prepared: PreparedInput, rulebook: Rulebook, below: FloorPlan | None, seed: int
) -> Mapping[str, tuple[float, float]] | None:
    """Positions (footprint metres) of this floor's rooms taken from the rooms of the same spec
    (then the same type) on ``below``, so that the floor repeats the room order of its
    neighbour. Each room takes the unused room below that is nearest to its own position in
    the spring embedding (greedy by increasing distance): rooms move to where their type was,
    not all to the same corner, so the seeding stays feasible."""
    if below is None or not below.rooms_abs:
        return None
    from ale.topology.embed import embed
    from ale.topology.graph import build_graph

    ox, oy = prepared.footprint.origin_m
    specs = dict(prepared.instances)
    spring = embed(build_graph(prepared, rulebook), prepared, rulebook, seed=seed)
    old = [r for r in below.rooms_abs if r.kind == "room" and r.spec_id]
    centre = {r.iid: (r.rect[0] + r.rect[2] / 2 - ox, r.rect[1] + r.rect[3] / 2 - oy) for r in old}
    taken: set[str] = set()
    out: dict[str, tuple[float, float]] = {}
    for use_spec in (True, False):
        pairs = []
        for iid, spec in specs.items():
            if iid in out or iid not in spring:
                continue
            for r in old:
                same = r.spec_id == spec.id if use_spec else r.type == str(spec.type)
                if same and r.iid not in taken:
                    d = math.dist(spring[iid], centre[r.iid])
                    pairs.append((d, iid, r.iid))
        for _, iid, oid in sorted(pairs):
            if iid in out or oid in taken:
                continue
            out[iid] = centre[oid]
            taken.add(oid)
    return out or None


def _bbox(ring: Sequence[tuple[int, int]]) -> tuple[int, int, int, int]:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


# ------------------------------------------------------------------ vertical check
def _vertical(plans: Sequence[FloorPlan], expected: int) -> tuple[tuple[str, ...], bool]:
    """Core, wet stack and solids on identical rectangles on every floor (hard)."""
    done = [p for p in plans if p.status == "ok"]
    lines: list[str] = []
    ok = True

    def same(label: str, values: list[MetreRect | tuple[MetreRect, ...] | None]) -> None:
        nonlocal ok
        kinds = {v for v in values if v is not None}
        good = len(kinds) <= 1
        ok = ok and good
        lines.append(f"{label} : {'identique' if good else 'DIFFÉRENT'} sur {len(done)} niveau(x).")

    if done:
        same("Noyau", [p.core for p in done])
        same("Colonne humide", [p.stack for p in done])
        same("Volumes pleins (noyau + colonne)", [p.solids for p in done])
    if len(done) < expected:
        ok = False
        lines.append(
            f"Contrôle incomplet : {expected - len(done)} niveau(x) sans plan sur {expected}."
        )
    return tuple(lines), ok


def plans_misses(plans: Sequence[FloorPlan], vertical_ok: bool) -> tuple[str, ...]:
    """Hard misses: failed floors, ``check_layout`` problems, failed vertical check."""
    out: list[str] = []
    for p in plans:
        if p.status == "failed":
            out.append(f"Niveau {p.level} : plan impossible ({p.message}).")
        for msg in p.problems:
            out.append(f"Niveau {p.level} : invariant du plan violé ({msg}).")
        if p.bay is not None and p.bay.unplaced:
            out.append(
                f"Niveau {p.level} : pièce(s) non placée(s) par le plan en travées : "
                f"{', '.join(p.bay.unplaced)}."
            )
    if not vertical_ok:
        out.append("Contrôle vertical : noyau ou colonne humide différents selon les niveaux.")
    return tuple(out)


# ------------------------------------------------------------------------- driver
def _strict_ok(result: StackResult, config: AleConfig) -> bool:
    from ale.program.models import InputError
    from ale.program.site import to_module_footprint

    grid = GridSpec(module_mm=config.grid.module_mm)
    for f in result.floors:
        try:
            to_module_footprint(
                _plan_site(f, result.skeleton, result.building), grid, strict_cores=True
            )
        except InputError:
            return False
    return True


def run_plans(
    result: StackResult,
    rulebook: Path,
    out: Path,
    *,
    budget_s: float = DEFAULT_BUDGET_S,
    seed: int = 0,
    planner: str = "engine",
) -> tuple[PlansResult, StackResult]:
    """Lay out every floor of ``result`` (a :class:`ale.stack.report.StackResult`) and write
    ``floor_NN/plan/`` and ``plans.md`` under ``out``.

    Returns the plans and the stacking result actually used: when the given one has a wet
    stack that touches an outline, the stacking is re-run with :func:`build_skeleton_strict`
    (and the note says so). One variant per floor, seed ``seed + level``.

    ``planner`` (Ticket M.4): ``"engine"`` (default, as before) or ``"bay"``: an eligible bar
    floor is planned bay-first (:mod:`ale.bayplan`), the others by the engine with the reason in
    ``plans.md``.
    """
    from ale.stack.report import run_stack

    config = AleConfig()
    config = config.model_copy(
        update={"optimizer": config.optimizer.model_copy(update={"time_budget_s": budget_s})}
    )
    notes: list[str] = []
    if not _strict_ok(result, config):
        notes.append(
            "La colonne humide de l'empilement touchait un contour : empilement refait avec une "
            "colonne à 0,60 m au moins du contour (un volume plein ne touche pas le contour)."
        )
        result = run_stack(
            result.program, result.building, result.rules, seed=seed, strict_solids=True
        )
    bay_ctx, section_note = (None, "")
    if planner == "bay":
        bay_ctx, section_note = _bay_context(result, rulebook, config)
    done: dict[int, FloorPlan] = {}
    n = len(result.floors)
    t0 = min(max(result.typical, 0), n - 1)
    for k in [*range(t0, -1, -1), *range(t0 + 1, n)]:  # typical floor first, then outward
        f = result.floors[k]
        plan_dir = out / f"floor_{f.level:02d}" / "plan"
        nb = done.get(k + 1 if k < t0 else k - 1)
        try:
            done[k] = _generate_floor(
                f,
                result.skeleton,
                result.building,
                rulebook,
                plan_dir,
                config,
                seed + f.level,
                result.rhythm,
                nb if nb is not None and nb.status == "ok" else None,
                bay_ctx,
            )
        except Exception as exc:  # one bad floor must not stop the others
            done[k] = FloorPlan(
                f.level, "failed", f"{type(exc).__name__} : {exc}", out_dir=plan_dir
            )
    plans = [done[k] for k in range(n)]
    lines, ok = _vertical(plans, sum(1 for p in plans if p.status != "empty"))
    rhythms: tuple[FloorRhythm, ...] = ()
    stacking: tuple[float, ...] = ()
    if result.rhythm is not None:
        from ale.stack.grid import plan_columns, plan_facade_partitions, plan_stackability

        stacking = plan_stackability(plans)
        figures = []
        for p in plans:
            if p.status != "ok":
                continue
            n_part, on_bay = plan_facade_partitions(result.rhythm, p)
            cols, small = plan_columns(result.rhythm, p, result.skeleton)
            figures.append(FloorRhythm(p.level, n_part, on_bay, len(cols), len(small)))
            _write_grid_svg(result.rhythm, p, cols, small)
        rhythms = tuple(figures)
    longside: list[tuple[int, int, int, int]] = []
    bound: tuple[float, ...] = ()
    if planner == "bay":
        from ale.stack.grid import plan_longside_partitions

        if result.rhythm is not None:
            for p in plans:
                if p.status == "ok" and p.planner == "bay":
                    ls = plan_longside_partitions(result.rhythm, p)
                    longside.append((p.level, *ls))
        bound = _type_area_bound(plans)
    res = PlansResult(
        floors=tuple(plans),
        vertical=lines,
        vertical_ok=ok,
        notes=tuple(notes),
        misses=plans_misses(plans, ok),
        rhythm=result.rhythm,
        rhythms=rhythms,
        stacking=stacking,
        planner=planner,
        section_note=section_note,
        bound=bound,
        longside=tuple(longside),
        entrances=tuple((e.point[0], e.point[1]) for e in result.building.entrances)
        if planner == "bay"
        else (),
        anchored=tuple(
            sorted({sp.id for _, sp in result.program.instances() if sp.anchor == "entrance"})
        )
        if planner == "bay"
        else (),
    )
    write_plans(res, out)
    return res, result


def _bay_context(
    result: StackResult, rulebook: Path, config: AleConfig
) -> tuple[BayContext | None, str]:
    """The building-level data of the bay planner: facade-row depth, corridor, sketch
    configuration, groups. ``(None, reason)`` when there is no bay."""
    from ale.bayplan import choose_facade_depth
    from ale.geometry.blocks import Consts
    from ale.program import load_rulebook
    from ale.stack.assign import _explicit_group, default_group
    from ale.stack.rules import WET_TYPES

    rules = result.rules
    if result.rhythm is None:
        return None, "Aucune trame de travée : tous les niveaux vont au moteur."
    pct = 10.0 if rules.sketch_tolerance_pct is None else rules.sketch_tolerance_pct
    sketch = config.model_copy(
        update={"area": config.area.model_copy(update={"tol_down_pct": pct, "tol_up_pct": pct})}
    )
    rb, _ = load_rulebook(rulebook)
    k = Consts.from_config(sketch)
    specs = [s for _, s in result.program.instances() if str(s.type) not in WET_TYPES]
    bay = result.rhythm.bay * 600 // config.grid.module_mm
    df, total = choose_facade_depth(
        specs, k, bay, rulebook=rb, max_depth_m=config.facade.max_depth_m
    )
    ref = ""
    if rb is not None and "office" in rb.types and rb.types["office"].depth_m is not None:
        ref = f" (profondeur de référence {rb.types['office'].depth_m.p50:.1f} m)"
    note = (
        f"profondeur de rangée de façade d_f = {df * config.grid.module_mm / 1000:.1f} m : "
        f"maximise la surface cible des pièces de façade ayant une forme dans la fenêtre "
        f"({total:.0f} m²), à égalité la plus proche de la profondeur de référence{ref}"
    )
    corridor = 1.8 if rules.corridor_m is None else rules.corridor_m

    def group_of(iid: str, spec: RoomSpec) -> str:
        return _explicit_group(iid, spec.id, rules) or default_group(spec.id)

    return BayContext(df, corridor, sketch, group_of), note


def _type_area_bound(plans: Sequence[FloorPlan]) -> tuple[float, ...]:
    """Bound of the stackability of floors 1..: ``sum over types of min(area on k, area on
    k-1) / area on k`` over the same rooms as :func:`ale.stack.grid.plan_stackability` (typed
    rooms, wet rooms included; circulation and reserve excluded), so that it bounds it."""
    out: list[float] = []
    for upper, lower in zip(plans[1:], plans[:-1], strict=True):
        if upper.status != "ok" or lower.status != "ok":
            continue

        def area(p: FloorPlan) -> dict[str, float]:
            acc: dict[str, float] = {}
            for r in p.rooms_abs:
                if r.type and r.kind != "circulation":
                    acc[r.type] = acc.get(r.type, 0.0) + r.rect[2] * r.rect[3]
            return acc

        a, b = area(upper), area(lower)
        total = sum(a.values())
        out.append(sum(min(v, b.get(t, 0.0)) for t, v in a.items()) / total if total else 0.0)
    return tuple(out)


# --------------------------------------------------------------------------- report
def _fmt_rect(r: MetreRect | None) -> str:
    return "—" if r is None else f"({r[0]:.2f} ; {r[1]:.2f}), {r[2]:.2f} x {r[3]:.2f} m"


def _trame_lines(res: PlansResult) -> list[str]:
    """Section « Trame et empilement » of ``plans.md`` (exact plans)."""
    rh = res.rhythm
    if rh is None:
        return []
    cols = sum(f.columns for f in res.rhythms)
    small = sum(f.small for f in res.rhythms)
    parts = sum(f.partitions for f in res.rhythms)
    on_bay = sum(f.on_bay for f in res.rhythms)
    lines = [
        "",
        "## Trame et empilement",
        "",
        f"- Trame de poteaux : portées {rh.span_x_m:.2f} x {rh.span_y_m:.2f} m, identique à tous "
        f"les niveaux, noyau sur la trame ; module de travée {rh.bay_m:.2f} m.",
        (
            f"- Poteaux : {cols} (tous niveaux), dont {small} dans une pièce de moins de 30 m² "
            f"({small / cols:.1%})."
            if cols
            else "- Poteaux : aucun."
        ),
        f"- Cloisons de façade sur une ligne de travée (à 0,30 m près) : {on_bay} sur {parts}"
        + (f" ({on_bay / parts:.1%})." if parts else "."),
        (
            "- Réalisation sur la trame : largeurs des pièces et profondeurs des blocs choisies "
            "pour les lignes de travée et de poteaux (coût « lattice » de l'optimisation) "
            f"sur {sum(1 for p in res.floors if p.lattice[0])} niveau(x)."
        ),
        "",
        "| Niveau | Cloisons de façade | Sur la travée | Poteaux | Poteaux en pièce < 30 m² | "
        "Parois déplacées |",
        "|---|---|---|---|---|---|",
    ]
    by_level = {p.level: p for p in res.floors}
    for f in res.rhythms:
        sn = by_level[f.level].snapped
        share = f"{f.on_bay / f.partitions:.0%}" if f.partitions else "—"
        lines.append(
            f"| {f.level} | {f.partitions} | {f.on_bay} ({share}) | {f.columns} | {f.small} | "
            f"{sn[2]} sur {sn[0]} |"
        )
    lines += [
        "",
        "| Niveaux | Empilabilité des plans (surface de même type au niveau inférieur) |",
        "|---|---|",
    ]
    lines += [f"| {k} / {k + 1} | {v:.1%} |" for k, v in enumerate(res.stacking)]
    lines.append("")
    return lines


def _line(
    axis: str,
    at: float,
    lo: float,
    hi: float,
    dark: bool,
    px: Callable[[float], float],
    py: Callable[[float], float],
) -> str:
    stroke = "#c0392b" if dark else "#999999"
    dash = "" if dark else ' stroke-dasharray="2 3"'
    cls = "column-line" if dark else "bay-line"
    if axis == "x":
        a, b = (px(at), py(lo)), (px(at), py(hi))
    else:
        a, b = (px(lo), py(at)), (px(hi), py(at))
    return (
        f'<line class="{cls}" x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
        f'stroke="{stroke}" stroke-width="0.8"{dash}/>'
    )


def _write_grid_svg(
    rh: Rhythm,
    p: FloorPlan,
    cols: list[tuple[float, float]],
    small: list[tuple[float, float]],
) -> None:
    """``grille.svg`` next to the plan: rooms, bay lines (grey), column lines (red), columns."""
    if p.out_dir is None or len(p.outline) < 3:
        return
    xs = [q[0] for q in p.outline]
    ys = [q[1] for q in p.outline]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    k = 10.0
    h = (y1 - y0) * k

    def px(x: float) -> float:
        return 10 + (x - x0) * k

    def py(y: float) -> float:
        return 10 + h - (y - y0) * k

    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{(x1 - x0) * k + 20:.0f}" '
        f'height="{h + 20:.0f}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<g id="rooms" fill="#f4f1ea" stroke="#555555" stroke-width="0.6">',
    ]
    for r in p.rooms_abs:
        if r.kind == "circulation":
            continue
        x, y, w, hh = r.rect
        out.append(
            f'<rect x="{px(x):.1f}" y="{py(y + hh):.1f}" width="{w * k:.1f}" '
            f'height="{hh * k:.1f}"/>'
        )
    out.append("</g>")
    out.append('<g id="grid" fill="none">')
    colx = set(rh.grid_lines_x(x0, x1))
    coly = set(rh.grid_lines_y(y0, y1))
    for x in rh.bay_lines_x(x0, x1):
        out.append(_line("x", x, y0, y1, x in colx, px, py))
    for y in rh.bay_lines_y(y0, y1):
        out.append(_line("y", y, x0, x1, y in coly, px, py))
    out.append("</g>")
    bad = set(small)
    for x, y in cols:
        flag = (x, y) in bad
        out.append(
            f'<circle class="column{" in-room" if flag else ""}" cx="{px(x):.1f}" '
            f'cy="{py(y):.1f}" r="3" fill="{"#c0392b" if flag else "#333333"}"/>'
        )
    out.append("</svg>")
    (p.out_dir / "grille.svg").write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


def _on_side(x: float, y: float, r: MetreRect, tol: float = 1e-3) -> bool:
    """The point lies on the boundary of the rectangle ``r`` (x, y, w, h)."""
    inside_x = r[0] - tol <= x <= r[0] + r[2] + tol
    inside_y = r[1] - tol <= y <= r[1] + r[3] + tol
    on_x = abs(x - r[0]) <= tol or abs(x - r[0] - r[2]) <= tol
    on_y = abs(y - r[1]) <= tol or abs(y - r[1] - r[3]) <= tol
    return inside_x and inside_y and (on_x or on_y)


def _bay_lines(res: PlansResult) -> list[str]:
    """Section « Plans en travées » of ``plans.md`` (planner ``bay`` only, Ticket M.4)."""
    from ale.bayplan.measures import dead_end_and_reach, group_stretches

    lines = ["", "## Plans en travées (M.4)", "", f"- Section : {res.section_note}."]
    longside = {x[0]: x for x in res.longside}
    for p in res.floors:
        if p.status != "ok":
            continue
        if p.bay is None or p.layout is None:
            lines += ["", f"### Niveau {p.level}", "", "- Planificateur : moteur de plans exacts."]
            if p.why:
                lines.append(f"- Raison : {p.why}")
            continue
        b, lay = p.bay, p.layout
        unit = lay.grid.module_mm / 1000
        sec = b.section
        plate = lay.footprint.area_cells() * unit * unit
        circ_area = sum(c.area_m2(lay.grid) for c in lay.circulation)
        by_kind: dict[str, float] = {}
        for c in lay.circulation:
            kind = b.kinds[c.instance_id]
            by_kind[kind] = by_kind.get(kind, 0.0) + c.area_m2(lay.grid)
        palier, reliquat = by_kind.get("palier", 0.0), by_kind.get("reliquat", 0.0)
        reserve = [r for r in lay.rooms if r.spec_id is None]
        res_m2 = sum(r.area_m2(lay.grid) for r in reserve)
        placed = [r for r in lay.rooms if r.spec_id is not None]
        dead, reach = dead_end_and_reach(lay, round(1.2 / unit))
        bay_mod = round(sec["bay"] / unit)
        st = group_stretches(
            lay,
            b.groups,
            bool(sec["transposed"]),
            (round(sec["core0"] / unit), round(sec["core1"] / unit)),
            bay_mod,
        )
        multi = ", ".join(f"{g} ({n})" for g, n in sorted(st.items()) if n > 1) or "aucun"
        depth = sec["plate_depth"]
        lines += [
            "",
            f"### Niveau {p.level}",
            "",
            "- Planificateur : plan en travées (rangées de façade, couloirs, bande centrale).",
            f"- Section ({depth:.1f} m de profondeur) : façade {sec['df']:.1f} m, couloir "
            f"{sec['c']:.1f} m, bande centrale {sec['band']:.1f} m, couloir {sec['c']:.1f} m, "
            f"façade {sec['df']:.1f} m ; d_f = {sec['df']:.1f} m (voir ci-dessus) ; travée "
            f"{sec['bay']:.1f} m ; segment du noyau de {sec['core0']:.1f} à {sec['core1']:.1f} m.",
            f"- Travées de façade : {b.facade_bays_used:.1f} occupées sur "
            f"{b.facade_bays_available:.1f} disponibles ; bande disponible "
            f"{b.band_m_available:.1f} m.",
            f"- Pièces : {len(placed)} placées, {len(b.unplaced)} non placée(s)"
            + (f" ({', '.join(b.unplaced)})." if b.unplaced else "."),
        ]
        if b.adjust:
            lines += ["- À ajuster (aucune forme admissible) :"]
            lines += [
                f"  - {i} : cible {t:.1f} m², placée {a:.1f} m² ({(a - t) / t:+.0%})"
                for i, t, a in b.adjust
            ]
        else:
            lines.append("- À ajuster : aucune pièce.")
        lines += [
            f"- Réserve : {len(reserve)} pièce(s), {res_m2:.1f} m² "
            f"({res_m2 / plate:.1%} du plateau).",
            f"- Circulation : {circ_area:.1f} m² ({circ_area / plate:.1%} du plateau), dont palier "
            f"{palier:.1f} m² et reliquat {reliquat:.1f} m² (affichés à part).",
        ]
        if sec["narrowed"]:
            lines.append("- Couloir rétréci le long du noyau.")
        lines += [
            f"- Pièces d'un même groupe en plusieurs tronçons : {multi}.",
            f"- Plus long cul-de-sac de couloir : {dead:.1f} m"
            + (" (> 10 m)" if dead > 10 else "")
            + f" ; plus longue distance d'une pièce au noyau : {reach:.1f} m"
            + (" (> 40 m)" if reach > 40 else (" (> 10 m)" if reach > 10 else ""))
            + ".",
        ]
        lines += [f"- Remarque : {n}." for n in b.notes]
        if p.level == 0:
            circ_abs = [r.rect for r in p.rooms_abs if r.kind == "circulation"]
            for ex, ey in res.entrances:
                on = any(_on_side(ex, ey, r) for r in circ_abs)
                lines.append(
                    f"- Entrée ({ex:.1f} ; {ey:.1f}) : sur un côté de la circulation : "
                    + ("oui." if on else "non (entrée sur un pignon ou hors travée).")
                )
            for r in p.rooms_abs:
                if r.kind == "room" and r.spec_id in res.anchored:
                    for ex, ey in res.entrances[:1]:
                        d = math.hypot(
                            max(r.rect[0] - ex, 0.0, ex - r.rect[0] - r.rect[2]),
                            max(r.rect[1] - ey, 0.0, ey - r.rect[1] - r.rect[3]),
                        )
                        lines.append(f"- Pièce d'entrée {r.iid} : à {d:.1f} m de l'entrée.")
        if p.level in longside:
            _, n, half, whole = longside[p.level]
            lines.append(
                f"- Cloisons de façade longue : {half} sur {n} sur une ligne de demi-travée, "
                f"{whole} sur une ligne de travée entière."
            )
    if res.bound:
        lines += [
            "",
            "Borne d'empilement par type (surface de même type au niveau inférieur) :",
            "",
        ]
        lines += [
            f"- Niveaux {k} / {k + 1} : plans {s:.1%}, borne {bd:.1%}"
            for k, (s, bd) in enumerate(zip(res.stacking, res.bound, strict=False))
        ]
    lines.append("")
    return lines


def render_plans_markdown(res: PlansResult) -> str:
    """``plans.md`` (French)."""
    lines = [
        "# Plans exacts par niveau",
        "",
        "Chaque niveau est dessiné par le moteur de plans exacts autour du noyau et de la colonne "
        "humide (volumes pleins, non cloisonnés) ; le noyau et les locaux humides de M.1 sont "
        "posés dans `Layout.fixed`.",
        "",
    ]
    lines += [f"- Remarque : {n}" for n in res.notes]
    lines += [
        "",
        "## Niveaux",
        "",
        "| Niveau | Statut | Violations dures | Façade manquante | Surface cible (m²) | "
        "Surface placée (m²) | Circulation (m²) | Durée (s) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in res.floors:
        if p.status != "ok":
            label = "vide" if p.status == "empty" else "ÉCHEC"
            lines.append(f"| {p.level} | {label} : {p.message} | | | | | | |")
            continue
        lines.append(
            f"| {p.level} | plan produit | {len(p.hard)} | {len(p.facade_missing)} | "
            f"{p.target_m2:.1f} | {p.placed_m2:.1f} | {p.circulation_m2:.1f} | "
            f"{'—' if p.planner == 'bay' else format(p.elapsed_s, '.1f')} |"
        )
    detail = [p for p in res.floors if p.status == "ok" and (p.hard or p.problems)]
    if detail:
        lines += ["", "## Violations dures par niveau", ""]
        for p in detail:
            for v in p.hard:
                lines.append(
                    f"- Niveau {p.level} : {v.code} {', '.join(v.instance_ids)} — {v.detail}"
                )
            for msg in p.problems:
                lines.append(f"- Niveau {p.level} : invariant `check_layout` : {msg}")
    lines += [
        "",
        "## Contrôle vertical (dur)",
        "",
        "| Niveau | Noyau | Colonne humide |",
        "|---|---|---|",
    ]
    lines += [
        f"| {p.level} | {_fmt_rect(p.core)} | {_fmt_rect(p.stack)} |"
        for p in res.floors
        if p.status == "ok"
    ]
    lines += ["", *(f"- {v}" for v in res.vertical)]
    lines += _trame_lines(res)
    if res.planner == "bay":
        lines += _bay_lines(res)
    lines += ["", "## Locaux fixes par niveau", ""]
    for p in res.floors:
        if p.status != "ok":
            continue
        lines.append(
            f"- Niveau {p.level} : " + ", ".join(f"{i} {_fmt_rect(r)}" for i, r in p.fixed)
        )
    lines += ["", "## Manques durs", ""]
    lines += [f"- {m}" for m in res.misses] or ["Aucun."]
    lines.append("")
    return "\n".join(lines)


def write_plans(res: PlansResult, out: Path) -> Path:
    """Write ``plans.md`` into ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    path = out / PLANS_NAME
    path.write_text(render_plans_markdown(res), encoding="utf-8", newline="\n")
    return path
