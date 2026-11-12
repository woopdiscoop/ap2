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

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ale.config import AleConfig
from ale.contracts.models import GridSpec, Layout, PlacedRoom, RoomSpec, SiteSpec, Violation
from ale.contracts.serialization import dump_yaml
from ale.stack.building import Building
from ale.stack.floors import FloorResult, _core_spec, write_programme_xlsx
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
DEFAULT_BUDGET_S = 20.0
MARGINS_CELLS = (6, 4, 2, 1)
"""Cells (0.60 m) kept between the wet stack and the outline of the top floor, tried in order:
a thinner gap leaves a piece too shallow for the corridor grammar, so the widest that still
places the stack wins."""
#: ``(x, y, w, h)`` in metres, rounded to the millimetre.
MetreRect = tuple[float, float, float, float]


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

    @property
    def passes(self) -> bool:
        """A layout was produced and passes ``check_layout``."""
        return self.status == "ok" and not self.problems


@dataclass(frozen=True)
class PlansResult:
    """All floor plans, the vertical check and the hard misses."""

    floors: tuple[FloorPlan, ...]
    vertical: tuple[str, ...]  # one line per check
    vertical_ok: bool
    notes: tuple[str, ...] = ()
    misses: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        """No hard miss."""
        return not self.misses


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
) -> FloorPlan:
    """Prepare, seed, anneal, add the fixed rooms, check and export one floor."""
    from ale.export import export_run
    from ale.geometry.checks import check_layout
    from ale.geometry.evaluate import FACADE_CODES
    from ale.optimize.anneal import anneal
    from ale.program import load_rulebook, prepare_input
    from ale.program.models import InputError
    from ale.topology import seed_plan

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
    total = config.optimizer.time_budget_s
    seeded = None
    why = ""
    spent = 0.0
    attempt = 0
    # The seeder is chancy on rings around a solid: retry other seeds while the seeding share
    # (60 %) of the budget lasts, then anneal with what is left.
    while seeded is None or seeded.realization.layout is None:
        left = SEED_SHARE * total - spent
        if attempt > 0 and left < 0.5:
            break
        slot = min(left, max(2.0, 0.2 * total))
        seeded = seed_plan(
            prepared, rb, config, seed=seed + 1000 * attempt, time_budget_s=max(slot, 0.5)
        )
        spent += seeded.elapsed_s
        attempt += 1
        if seeded.realization.layout is None:
            why = "; ".join(f"{x.code}: {x.detail}" for x in seeded.realization.failures)
    assert seeded is not None
    if seeded.realization.layout is None:
        return FloorPlan(
            f.level, "failed", f"aucune réalisation exacte après {attempt} essai(s) ({why})"
        )
    anneal_config = config.model_copy(
        update={
            "optimizer": config.optimizer.model_copy(
                update={"time_budget_s": max(1.0, total - spent)}
            )
        }
    )
    res = anneal(prepared, rb, anneal_config, seeded.plan, seed=seed)
    base = res.layout
    fixed = _fixed_rooms(f, sk, building, config.grid.module_mm)
    layout = Layout.model_validate({**base.model_dump(), "fixed": [p.model_dump() for p in fixed]})
    problems = check_layout(layout, prepared, config)
    for stale in ("layout.json", "layout.dxf", "preview.svg", "report.md"):
        (plan_dir / stale).unlink(missing_ok=True)
    export_run(
        layout,
        prepared,
        plan_dir,
        rulebook_version=prepared.rulebook_version,
        run_id=f"plan-{f.level:02d}",
        config=config,
    )
    origin = prepared.footprint.origin_m
    rects = {p.instance_id: (p.rect.x, p.rect.y, p.rect.w, p.rect.h) for p in layout.fixed}
    core_id = building.core.id
    stack_rects = [r for i, r in rects.items() if i != core_id and not i.startswith(GAP_PREFIX)]
    fixed_m = tuple((i, _metres(layout, origin, r)) for i, r in sorted(rects.items()))
    target = sum(s.target_area_m2 for _, s in prepared.instances)
    placed = sum(p.area_m2(layout.grid) for p in layout.rooms)
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
    )


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
) -> tuple[PlansResult, StackResult]:
    """Lay out every floor of ``result`` (a :class:`ale.stack.report.StackResult`) and write
    ``floor_NN/plan/`` and ``plans.md`` under ``out``.

    Returns the plans and the stacking result actually used: when the given one has a wet
    stack that touches an outline, the stacking is re-run with :func:`build_skeleton_strict`
    (and the note says so). One variant per floor, seed ``seed + level``.
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
    plans: list[FloorPlan] = []
    for f in result.floors:
        plan_dir = out / f"floor_{f.level:02d}" / "plan"
        try:
            plans.append(
                _generate_floor(
                    f, result.skeleton, result.building, rulebook, plan_dir, config, seed + f.level
                )
            )
        except Exception as exc:  # one bad floor must not stop the others
            plans.append(
                FloorPlan(f.level, "failed", f"{type(exc).__name__} : {exc}", out_dir=plan_dir)
            )
    lines, ok = _vertical(plans, sum(1 for p in plans if p.status != "empty"))
    res = PlansResult(
        floors=tuple(plans),
        vertical=lines,
        vertical_ok=ok,
        notes=tuple(notes),
        misses=plans_misses(plans, ok),
    )
    write_plans(res, out)
    return res, result


# --------------------------------------------------------------------------- report
def _fmt_rect(r: MetreRect | None) -> str:
    return "—" if r is None else f"({r[0]:.2f} ; {r[1]:.2f}), {r[2]:.2f} x {r[3]:.2f} m"


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
            f"{p.elapsed_s:.1f} |"
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
