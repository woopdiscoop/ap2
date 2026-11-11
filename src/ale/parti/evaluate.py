"""Joint evaluation of partis (Ticket G.2, RD section 5): every criterion at once, the cell
diagram of the typical floor, forcedness and the non-dominated ranking."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from itertools import pairwise, product

from shapely import LineString, Point, box
from shapely import Polygon as ShPolygon
from shapely.geometry.polygon import orient

from ale.config import AleConfig
from ale.contracts.geometry import Polygon
from ale.contracts.models import (
    Adjacency,
    CoreOffset,
    CoreSpec,
    Program,
    Rulebook,
    SiteSpec,
    TypeStats,
)
from ale.parti.genes import DEPTH_SINGLE_M, ROOM_DEPTH_M, Dropped, Parti
from ale.parti.massing import Massing, entrance_edge, largest_polygon, make_massing
from ale.topology.cellgrow import CORE_CELL, FREE, OUTSIDE, CellDiagram

__all__ = [
    "Entry",
    "Evaluation",
    "FormMatch",
    "Requirement",
    "SiteSetting",
    "dominates",
    "evaluate_massing",
    "facade_edges",
    "match_forms",
    "neutral_rulebook",
    "non_dominated",
    "rank",
    "run_partis",
    "typical_floor_program",
    "typical_floor_site",
]

EGRESS_REPORT_M = 40.0
FACADE_USABLE = {"single": 0.5, "double": 0.9}
GOOD_SHARE_MIN = 0.5
SHORT_TOL = 0.95
MIN_FRONTAGE_M = 3.0


@dataclass(frozen=True)
class SiteSetting:
    """Façade orientation setting. Bearings are compass degrees of the façade's outward
    normal; the default is AREP-MS (Marrakech): NNO / SSE good, OSO / ENE exposed."""

    good: tuple[float, float] = (337.5, 157.5)
    exposed: tuple[float, float] = (247.5, 67.5)


@dataclass(frozen=True)
class Requirement:
    name: str
    met: bool


@dataclass(frozen=True)
class Evaluation:
    gross_m2: float
    need_m2: float
    capacity_ratio: float
    facade_m: float
    facade_good_m: float
    good_share: float
    frontage_capacity_m: float
    frontage_demand_m: float
    compactness: float
    coverage: float
    court_short_m: float
    court_ok: bool
    core_distance_m: float
    requirements: tuple[Requirement, ...]
    # typical-floor cell diagram (None when not computed)
    cells_done: bool = False
    rooms_short: tuple[str, ...] = ()
    facade_missing: tuple[str, ...] = ()
    off_circulation: tuple[str, ...] = ()
    fragmented: tuple[str, ...] = ()
    strays: tuple[str, ...] = ()
    diagram: CellDiagram | None = field(default=None, compare=False, repr=False)

    @property
    def exceptions(self) -> int:
        return (
            len(self.rooms_short)
            + len(self.facade_missing)
            + len(self.off_circulation)
            + len(self.fragmented)
            + len(self.strays)
        )

    @property
    def share_met(self) -> float:
        return sum(r.met for r in self.requirements) / len(self.requirements)

    @property
    def forcedness(self) -> float:
        """Lower is better: unmet share (x10) plus local exceptions in the cell diagram."""
        return round((1.0 - self.share_met) * 10.0 + self.exceptions, 6)

    @property
    def hard_misses(self) -> int:
        return (
            int(self.capacity_ratio < 1 - 0.10 - 1e-9)
            + int(not self.court_ok)
            + len(self.facade_missing)
            + len(self.fragmented)
        )

    @property
    def key(self) -> tuple[float, float, float, float]:
        """Ranking vector, all minimised: hard misses, forcedness, 1 - good share, compactness."""
        return (
            float(self.hard_misses),
            self.forcedness,
            round(1.0 - self.good_share, 6),
            round(self.compactness, 6),
        )


@dataclass(frozen=True)
class Entry:
    parti: Parti
    massing: Massing
    evaluation: Evaluation
    non_dominated: bool = False


# ------------------------------------------------------------------------- façades
def _party_lines(site: SiteSpec) -> list[LineString]:
    ext = site.footprint.exterior
    n = len(ext)
    return [LineString([ext[i], ext[(i + 1) % n]]) for i in site.party_edges]


def facade_edges(
    outline: ShPolygon, site: SiteSpec
) -> list[tuple[tuple[float, float], tuple[float, float], float]]:
    """``(a, b, bearing)`` of every outline edge not on a party wall; ``bearing`` is the
    compass bearing (degrees) of the outward normal."""
    party = _party_lines(site)
    out = []
    for ring in (outline.exterior, *outline.interiors):
        pts = list(ring.coords)
        for a, b in pairwise(pts):
            mid = Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if any(line.distance(mid) < 1e-6 for line in party):
                continue
            nx, ny = b[1] - a[1], -(b[0] - a[0])  # outward for CCW exterior / CW holes
            ang = math.degrees(math.atan2(nx, ny))  # clockwise from +y
            out.append((a, b, (ang - site.north_angle_deg) % 360.0))
    return out


def _is_good(bearing: float, setting: SiteSetting) -> bool:
    def dev(x: float, ref: float) -> float:
        d = abs(x - ref) % 360.0
        return min(d, 360.0 - d)

    dg = min(dev(bearing, g) for g in setting.good)
    de = min(dev(bearing, e) for e in setting.exposed)
    return dg <= de + 1e-9


def _facade_stats(outline: ShPolygon, site: SiteSpec, setting: SiteSetting) -> tuple[float, float]:
    total = good = 0.0
    for a, b, bearing in facade_edges(outline, site):
        ln = math.hypot(b[0] - a[0], b[1] - a[1])
        total += ln
        if _is_good(bearing, setting):
            good += ln
    return total, good


# ------------------------------------------------------------------ typical floor
def neutral_rulebook(program: Program) -> Rulebook:
    """A rulebook with uniform statistics for the programme's types (cell growth only uses
    its adjacency priors)."""
    stats = TypeStats.model_validate(
        {
            "aspect": {"p10": 1.0, "p50": 1.4, "p90": 2.0},
            "area_m2": {"p10": 2, "p50": 12, "p90": 80},
            "orientation": {"N": 0.0, "E": 0.0, "S": 0.0, "W": 0.0},
        }
    )
    return Rulebook(
        version="parti-neutral",
        kind="seed",
        author="ale.parti",
        date="2026-11-11",
        types={t: stats for t in sorted({r.type for r in program.rooms})},
        adjacency=Adjacency(default_p=0.5, pairs=()),
        core_offset=CoreOffset(dx_norm=0.0, dy_norm=0.0),
    )


def typical_floor_program(program: Program, floors: int) -> Program:
    """The programme share of an upper floor: instances balanced over the floors by area,
    entrance-anchored rooms on the ground floor; references to absent rooms dropped."""
    insts = list(program.instances())
    bins: list[list[str]] = [[] for _ in range(floors)]
    load = [0.0] * floors
    by_id = dict(insts)
    rest = []
    for iid, spec in insts:
        if spec.anchor == "entrance":
            bins[0].append(iid)
            load[0] += spec.target_area_m2
        else:
            rest.append((iid, spec))
    for iid, spec in sorted(rest, key=lambda t: (-t[1].target_area_m2, t[0])):
        k = min(range(floors), key=lambda j: (load[j], j))
        bins[k].append(iid)
        load[k] += spec.target_area_m2
    typical = bins[1] if floors > 1 else bins[0]
    counts: dict[str, int] = {}
    for iid in typical:
        sid = iid.split("#")[0]
        counts[sid] = counts.get(sid, 0) + 1
    keep = set(counts)
    rooms = []
    for r in program.rooms:
        if r.id not in keep:
            continue
        rooms.append(
            r.model_copy(
                update={
                    "quantity": counts[r.id],
                    "adjacent_to": tuple(a for a in r.adjacent_to if a in keep),
                    "avoid": tuple(a for a in r.avoid if a in keep),
                    "anchor": None if r.anchor == "entrance" else r.anchor,
                }
            )
        )
    del by_id
    return Program(rooms=tuple(rooms))


def typical_floor_site(site: SiteSpec, m: Massing, *, for_diagram: bool = False) -> SiteSpec:
    """The typical floor as a footprint site (the plan phase input). With ``for_diagram`` the
    ring is cut by its one-cell slit so that the outline has no hole."""
    poly = m.typical
    if for_diagram and m.slit is not None:
        cut = poly.difference(box(*m.slit))
        poly = largest_polygon(cut)
        poly = orient(largest_polygon(ShPolygon(poly.exterior).simplify(0)), 1.0)
    ext = [(round(x, 6), round(y, 6)) for x, y in list(poly.exterior.coords)[:-1]]
    holes = tuple(
        tuple((round(x, 6), round(y, 6)) for x, y in list(r.coords)[:-1]) for r in poly.interiors
    )
    ents = [e for e in site.entrances if e.main] or list(site.entrances)
    ref = Point(ents[0].point) if ents else Point(site.footprint.exterior[site.access_edge])
    n = len(ext)
    edges = [LineString([ext[i], ext[(i + 1) % n]]) for i in range(n)]
    access = min(range(n), key=lambda i: (round(edges[i].distance(ref), 9), i))
    x0, y0, x1, y1 = m.core
    return SiteSpec(
        footprint=Polygon(exterior=tuple(ext), holes=holes),
        north_angle_deg=site.north_angle_deg,
        access_edge=access,
        cores=(CoreSpec(id="C1", rect=(x0, y0, x1 - x0, y1 - y0), kind="core"),),
        mode="footprint",
    )


def _cell_diagram(
    program: Program,
    site: SiteSpec,
    m: Massing,
    rulebook: Rulebook | None,
    config: AleConfig,
) -> tuple[
    CellDiagram, tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]
]:
    from ale.contracts.models import GridSpec
    from ale.program.feasibility import check_feasibility
    from ale.program.models import PreparedInput
    from ale.program.site import to_module_footprint
    from ale.topology.cellgrow import grow

    prog = typical_floor_program(program, m.parti.floors)
    fsite = typical_floor_site(site, m, for_diagram=True)
    grid = GridSpec(module_mm=config.grid.module_mm)
    fp = to_module_footprint(fsite, grid)
    rb = rulebook or neutral_rulebook(prog)
    feas = check_feasibility(prog, fp, rb, config)
    prep = PreparedInput(
        program=prog,
        instances=prog.instances(),
        site=fsite,
        footprint=fp,
        grid=grid,
        rulebook_version=rb.version,
        feasibility=feas,
        warnings=(),
    )
    d0 = grow(prep, rb, config, seed=0)
    d, strays = _clean(d0)
    needs = {iid: spec.needs_facade for iid, spec in prep.instances}
    nofac = []
    off = []
    for room in d.rooms:
        cs = d.cells[room]
        if not cs:
            continue
        on_facade = touch = False
        for x, y in cs:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
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
    return d, short, tuple(nofac), tuple(off), _fragmented(d), strays


def _clean(d0: CellDiagram) -> tuple[CellDiagram, tuple[str, ...]]:
    """R.9 can scatter a few cells of a room: keep each room's largest 4-connected component
    and release the strays to the circulation reserve. Returns the diagram and the rooms
    that had strays (each is a local exception: an odd room shape)."""
    owner = [list(row) for row in d0.owner]
    cells = {}
    strays = []
    for ri, room in enumerate(d0.rooms):
        cs = set(d0.cells[room])
        comps: list[set[tuple[int, int]]] = []
        left = set(cs)
        while left:
            seed = min(left)
            comp = {seed}
            stack = [seed]
            while stack:
                x, y = stack.pop()
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    q = (x + dx, y + dy)
                    if q in left and q not in comp:
                        comp.add(q)
                        stack.append(q)
            comps.append(comp)
            left -= comp
        if len(comps) > 1:
            keep = max(comps, key=lambda c: (len(c), next(iter(sorted(c)))))
            for x, y in cs - keep:
                owner[y][x] = FREE
            strays.append(room)
            cells[room] = tuple(sorted(keep))
        else:
            cells[room] = d0.cells[room]
        del ri
    d = replace(d0, owner=tuple(tuple(r) for r in owner), cells=cells)
    return d, tuple(strays)


def _fragmented(d: CellDiagram) -> tuple[str, ...]:
    out = []
    for room in d.rooms:
        cs = set(d.cells[room])
        if not cs:
            continue
        seen = {next(iter(cs))}
        stack = list(seen)
        while stack:
            x, y = stack.pop()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                q = (x + dx, y + dy)
                if q in cs and q not in seen:
                    seen.add(q)
                    stack.append(q)
        if len(seen) != len(cs):
            out.append(room)
    return tuple(out)


# ------------------------------------------------------------------------ evaluate
def evaluate_massing(
    m: Massing,
    program: Program,
    site: SiteSpec,
    *,
    setting: SiteSetting | None = None,
    cells: bool = True,
    rulebook: Rulebook | None = None,
    config: AleConfig | None = None,
) -> Evaluation:
    setting = setting or SiteSetting()
    p = m.parti
    typ = m.typical
    fac, good = _facade_stats(typ, site, setting)
    typ.exterior.length + sum(r.length for r in typ.interiors)
    net = sum(r.target_area_m2 * r.quantity for r in program.rooms)
    cap_ratio = m.gross_m2 * (1.0 - 0.16) / net
    demand = (
        sum(
            max(r.target_area_m2 / ROOM_DEPTH_M, MIN_FRONTAGE_M) * r.quantity
            for r in program.rooms
            if r.needs_facade
        )
        / p.floors
    )
    cap = fac * FACADE_USABLE[p.loading]
    compact = typ.exterior.length / (4.0 * math.sqrt(typ.area))
    plot_area = Polygon(exterior=site.footprint.exterior, holes=site.footprint.holes)
    del plot_area
    from shapely import Polygon as P2

    plot = P2(site.footprint.exterior, site.footprint.holes)
    coverage = typ.area / plot.area
    cx, cy = (m.core[0] + m.core[2]) / 2, (m.core[1] + m.core[3]) / 2
    core_dist = max(
        math.hypot(x - cx, y - cy)
        for ring in (typ.exterior, *typ.interiors)
        for x, y in ring.coords
    )
    court_ok = m.court is None or m.court_short_m + 1e-9 >= m.height_m / 2
    reqs = [
        Requirement("capacité", cap_ratio >= 0.9 - 1e-9),
        Requirement("prospect de la cour", court_ok),
        Requirement("façade utile pour les pièces à façade", cap + 1e-9 >= demand),
        Requirement("orientation des façades", (good / fac if fac else 1.0) >= GOOD_SHARE_MIN),
    ]
    ev = Evaluation(
        gross_m2=round(m.gross_m2, 3),
        need_m2=round(m.need_m2, 3),
        capacity_ratio=round(cap_ratio, 6),
        facade_m=round(fac, 3),
        facade_good_m=round(good, 3),
        good_share=round(good / fac, 6) if fac else 1.0,
        frontage_capacity_m=round(cap, 3),
        frontage_demand_m=round(demand, 3),
        compactness=round(compact, 6),
        coverage=round(coverage, 6),
        court_short_m=round(m.court_short_m, 3) if m.court is not None else 0.0,
        court_ok=court_ok,
        core_distance_m=round(core_dist, 3),
        requirements=tuple(reqs),
    )
    if not cells:
        return ev
    d, short, nofac, off, frag, strays = _cell_diagram(
        program, site, m, rulebook, config or AleConfig()
    )
    reqs += [
        Requirement("pièces à façade dotées d'une façade (diagramme)", not nofac),
        Requirement("pièces sur circulation (diagramme)", not off),
        Requirement("surfaces atteintes (diagramme)", not short),
    ]
    return replace(
        ev,
        requirements=tuple(reqs),
        cells_done=True,
        rooms_short=short,
        facade_missing=nofac,
        off_circulation=off,
        fragmented=frag,
        strays=strays,
        diagram=d,
    )


# --------------------------------------------------------------------------- ranking
def dominates(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return all(x <= y for x, y in zip(a, b, strict=True)) and any(
        x < y for x, y in zip(a, b, strict=True)
    )


def non_dominated(keys: list[tuple[float, ...]]) -> list[bool]:
    """``True`` for each key not dominated by any other (all components minimised)."""
    return [
        not any(dominates(o, k) for j, o in enumerate(keys) if j != i) for i, k in enumerate(keys)
    ]


def rank(entries: list[Entry]) -> list[Entry]:
    """Non-dominated set first, each group ordered by the key, ties by the parti key."""
    flags = non_dominated([e.evaluation.key for e in entries])
    marked = [
        Entry(e.parti, e.massing, e.evaluation, f) for e, f in zip(entries, flags, strict=True)
    ]
    return sorted(marked, key=lambda e: (not e.non_dominated, e.evaluation.key, e.parti.key()))


def _cheap_key(ev: Evaluation) -> tuple[float, ...]:
    short = max(0.0, ev.frontage_demand_m - ev.frontage_capacity_m)
    return (float(not ev.court_ok), round(short, 3), round(1.0 - ev.good_share, 6), ev.compactness)


def run_partis(
    program: Program,
    site: SiteSpec,
    *,
    floors: tuple[int, int] = (3, 5),
    count: int = 40,
    seeds: tuple[Parti, ...] = (),
    setting: SiteSetting | None = None,
    rulebook: Rulebook | None = None,
    config: AleConfig | None = None,
) -> tuple[list[Entry], list[Dropped]]:
    """Generate, size, pre-select (diverse over typologies), evaluate jointly and rank."""
    from ale.parti.genes import enumerate_genes
    from ale.parti.massing import buildable_zone

    zone = buildable_zone(site)
    side = entrance_edge(site)
    genes, dropped = enumerate_genes(side, floors)
    genes = [*seeds, *[g for g in genes if g not in seeds]]
    sized: list[tuple[Parti, Massing, Evaluation]] = []
    for g in genes:
        m = make_massing(g, site, program, zone)
        if isinstance(m, Dropped):
            dropped.append(m)
            continue
        sized.append((g, m, evaluate_massing(m, program, site, setting=setting, cells=False)))
    # a forecourt only translates the building: keep the variant with the forecourt
    uniq: dict[tuple[object, ...], tuple[Parti, Massing, Evaluation]] = {}
    for t in sized:
        g = t[0]
        sig = (
            g.typology,
            g.orientation_deg,
            g.wing_depth_m,
            g.floors,
            g.core_position,
            g.terrace,
            g.fingers,
            round(t[1].gross_m2, 3),
        )
        if sig not in uniq or (g.forecourt_m > 0 and uniq[sig][0].forecourt_m == 0) or g in seeds:
            uniq[sig] = t
    sized = list(uniq.values())
    order = sorted(sized, key=lambda t: (_cheap_key(t[2]), t[0].key()))
    chosen: list[tuple[Parti, Massing, Evaluation]] = [t for t in order if t[0] in seeds][:count]
    by_typ: dict[str, list[tuple[Parti, Massing, Evaluation]]] = {}
    for t in order:
        if t not in chosen:
            by_typ.setdefault(t[0].typology, []).append(t)
    while len(chosen) < count and any(by_typ.values()):
        for typ in sorted(by_typ):
            if by_typ[typ] and len(chosen) < count:
                chosen.append(by_typ[typ].pop(0))
    entries = [
        Entry(
            g,
            m,
            evaluate_massing(
                m, program, site, setting=setting, cells=True, rulebook=rulebook, config=config
            ),
        )
        for g, m, _ in chosen
    ]
    return rank(entries), dropped


_ = (DEPTH_SINGLE_M,)


# ---------------------------------------------------------------------- from G.3 forms
@dataclass(frozen=True)
class FormMatch:
    """A G.3 form mapped to the nearest typology (IoU of the outlines in the site frame)."""

    name: str
    typology: str
    iou: float
    parti: Parti


def match_forms(
    forms: dict[str, SiteSpec], program: Program, site: SiteSpec, floors: tuple[int, int]
) -> list[FormMatch]:
    """Map each form outline to the typology (and orientation / loading) whose sized massing
    has the best IoU with it; ``forms`` maps a name to the footprint site written by
    ``ale form``."""
    from ale.parti.genes import (
        CIRCULATIONS,
        COURT_TYPES,
        DEPTH_DOUBLE_M,
        TYPOLOGIES,
        validate_parti,
    )
    from ale.parti.massing import buildable_zone

    _ = CIRCULATIONS
    zone = buildable_zone(site)
    side = entrance_edge(site)
    circ = {"comb": "comb", "courtyard": "loop"}
    refs: list[tuple[Parti, Massing]] = []
    for typ in TYPOLOGIES:
        for ori, depth, nfl in product(
            (0, 90), (DEPTH_SINGLE_M, DEPTH_DOUBLE_M), range(floors[0], floors[1] + 1)
        ):
            g = Parti(
                typ,
                ori,
                depth,
                nfl,
                "centre",
                circ.get(typ, "spine"),
                side,
                typ in COURT_TYPES,
                0.0,
                None,
                3 if typ == "comb" else 0,
                False,
            )
            if validate_parti(g, floors) is not None:
                continue
            m = make_massing(g, site, program, zone)
            if not isinstance(m, Dropped):
                refs.append((g, m))
    out = []
    for name in sorted(forms):
        fs = forms[name].footprint
        poly = ShPolygon(fs.exterior, fs.holes)
        best: tuple[float, Parti] | None = None
        for g, m in refs:
            union = poly.union(m.typical).area
            iou = poly.intersection(m.typical).area / union if union else 0.0
            if best is None or iou > best[0] + 1e-12:
                best = (iou, g)
        if best is not None:
            out.append(FormMatch(name, best[1].typology, round(best[0], 4), best[1]))
    return out
