"""Whole-programme cell-growth diagram (Ticket R.9, RD §3): the architect's method.

The programme is laid down as cells on the footprint, anchors first, then every room grows
to its exact cell count. The grown diagram decides which rooms get façade, who neighbours
whom and the order along each band (see :mod:`ale.topology.fromdiagram`); it is also an
output for the architect (:mod:`ale.export.diagram`).

Resolution: one diagram cell is ``step x step`` modules, ``step = max(1, round(600 /
module_mm))`` (about 0.6 m, the prototype's grid; one module at a 600 mm grid). Cores are
rounded to cells, entrances snap to the nearest ribbon cell. Everything is deterministic
for ``(inputs, seed, jitter)``: ties are broken by cell index and the only noise is a hash
of ``(cell, room, seed)``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from ale.contracts.config import AleConfig
from ale.contracts.models import RoomSpec, Rulebook
from ale.program.models import PreparedInput
from ale.topology.cellprior import Prior
from ale.topology.graph import REQUIRED, build_graph, edges_of_kind

__all__ = ["CellDiagram", "DiagramChecks", "grow"]

OUTSIDE = -2
CORE_CELL = -3
FREE = -1
DEFAULT_DEPTH_LIMIT_M = 7.2
_STEP_TARGET_MM = 600
_W_NEIGHBOUR = -3.0
_W_CENTROID = 0.5
_W_FACADE = 0.25
_FACADE_PENALTY = 10.0
_W_ENTRANCE = 0.6
_W_PARTNER = 0.08
_FRONTAGE_FACTOR = 1.6
_QUOTA_FACTOR = 4
_MAX_RESEEDS = 3
_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass(frozen=True)
class DiagramChecks:
    """The prototype's checks. Every field lists the offending rooms (empty = satisfied)."""

    area: dict[str, int] = field(default_factory=dict)
    """Room → missing cells, for the rooms that did not reach their count."""
    facade: tuple[str, ...] = ()
    """``needs_facade`` rooms without a cell on the façade."""
    corner: tuple[str, ...] = ()
    """``anchor="corner"`` rooms not owning a corner cell."""
    entrance: tuple[str, ...] = ()
    """``anchor="entrance"`` rooms not touching the main entrance."""
    adjacency: tuple[tuple[str, str], ...] = ()
    """REQUIRED pairs that do not share a cell side."""
    core: tuple[str, ...] = ()
    """``service_core`` rooms not next to a core."""

    @property
    def ok(self) -> bool:
        return not (
            self.area or self.facade or self.corner or self.entrance or self.adjacency or self.core
        )


@dataclass(frozen=True)
class CellDiagram:
    """The grown diagram. Cell ``(cx, cy)`` covers modules ``[cx·step, (cx+1)·step) x …``
    (polygon module coordinates). ``owner[cy][cx]`` is a room index into :attr:`rooms`,
    or :data:`FREE` (circulation reserve), :data:`CORE_CELL` or :data:`OUTSIDE`."""

    step: int
    module_m: float
    width: int
    height: int
    owner: tuple[tuple[int, ...], ...]
    rooms: tuple[str, ...]
    types: dict[str, str]
    targets: dict[str, int]
    cells: dict[str, tuple[tuple[int, int], ...]]
    cores: tuple[tuple[int, int], ...]
    entrance: tuple[int, int] | None
    checks: DiagramChecks

    @property
    def reserve(self) -> int:
        """Number of unclaimed footprint cells (circulation reserve)."""
        return sum(v == FREE for row in self.owner for v in row)

    def centroid_m(self, room: str) -> tuple[float, float]:
        """Centroid of ``room`` in footprint metres (module coordinates x module size)."""
        cs = self.cells[room]
        if not cs:
            return (0.0, 0.0)
        k = self.step * self.module_m
        return (
            (sum(c[0] for c in cs) / len(cs) + 0.5) * k,
            (sum(c[1] for c in cs) / len(cs) + 0.5) * k,
        )


# ---------------------------------------------------------------------------- footprint
def _inside(poly: list[tuple[int, int]], px: float, py: float) -> bool:
    """Even-odd test of a point against a rectilinear polygon (vertical edges only)."""
    n = len(poly)
    crossings = 0
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if a[0] == b[0] and px < a[0] and min(a[1], b[1]) < py < max(a[1], b[1]):
            crossings += 1
    return crossings % 2 == 1


class _Grid:
    """Padded flat cell grid (one border of ``OUTSIDE`` cells)."""

    def __init__(self, prepared: PreparedInput, rulebook: Rulebook, config: AleConfig) -> None:
        mm = prepared.grid.module_mm
        self.module_m = mm / 1000
        self.step = max(1, round(_STEP_TARGET_MM / mm))
        poly = [(int(x), int(y)) for x, y in prepared.footprint.polygon.exterior]
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        self.width = max(1, math.ceil(max(xs) / self.step))
        self.height = max(1, math.ceil(max(ys) / self.step))
        self.wp = self.width + 2
        self.size = self.wp * (self.height + 2)
        self.owner = [OUTSIDE] * self.size
        s = self.step
        for cy in range(self.height):
            for cx in range(self.width):
                if _inside(poly, (cx + 0.5) * s, (cy + 0.5) * s):
                    self.owner[self.idx(cx, cy)] = FREE
        self.n_inside = sum(v == FREE for v in self.owner)
        self.poly = poly
        self._cores(prepared)

    def idx(self, cx: int, cy: int) -> int:
        return (cy + 1) * self.wp + cx + 1

    def xy(self, i: int) -> tuple[int, int]:
        return i % self.wp - 1, i // self.wp - 1

    def nbrs(self, i: int) -> tuple[int, int, int, int]:
        w = self.wp
        return i + 1, i - 1, i + w, i - w

    def to_cell(self, prepared: PreparedInput, pt: tuple[float, float]) -> tuple[float, float]:
        """Site metres → cell coordinates (floats)."""
        ox, oy = prepared.footprint.origin_m
        k = self.step * self.module_m
        return (pt[0] - ox) / k, (pt[1] - oy) / k

    def _cores(self, prepared: PreparedInput) -> None:
        self.core_cells: list[int] = []
        for core in prepared.site.cores:
            x, y, w, h = core.rect
            (ax, ay) = self.to_cell(prepared, (x, y))
            (bx, by) = self.to_cell(prepared, (x + w, y + h))
            x0, x1 = round(ax), max(round(ax) + 1, round(bx))
            y0, y1 = round(ay), max(round(ay) + 1, round(by))
            for cy in range(y0, y1):
                for cx in range(x0, x1):
                    if 0 <= cx < self.width and 0 <= cy < self.height:
                        i = self.idx(cx, cy)
                        if self.owner[i] == FREE:
                            self.owner[i] = CORE_CELL
                            self.core_cells.append(i)


# ---------------------------------------------------------------------------- ribbon
@dataclass
class _Ribbon:
    cells: list[int]  # footprint cells along the exterior edge, in walk order (no cores)
    inward: list[tuple[int, int]]
    corners: list[int]  # ribbon positions of convex corner cells


def _boundary(g: _Grid) -> list[tuple[int, tuple[int, int]]]:
    """Exterior unit edges walked counter-clockwise: ``(cell, inward direction)``."""
    edges: dict[tuple[int, int], tuple[tuple[int, int], int, tuple[int, int]]] = {}
    for cy in range(g.height):
        for cx in range(g.width):
            i = g.idx(cx, cy)
            if g.owner[i] == OUTSIDE:
                continue
            if g.owner[i - g.wp] == OUTSIDE:
                edges[(cx, cy)] = ((cx + 1, cy), i, (0, 1))
            if g.owner[i + 1] == OUTSIDE:
                edges[(cx + 1, cy)] = ((cx + 1, cy + 1), i, (-1, 0))
            if g.owner[i + g.wp] == OUTSIDE:
                edges[(cx + 1, cy + 1)] = ((cx, cy + 1), i, (0, -1))
            if g.owner[i - 1] == OUTSIDE:
                edges[(cx, cy + 1)] = ((cx, cy), i, (1, 0))
    if not edges:
        return []
    start = min(edges)
    out: list[tuple[int, tuple[int, int]]] = []
    seen: set[tuple[int, int]] = set()
    v = start
    while v in edges and v not in seen:
        seen.add(v)
        nxt, cell, inward = edges[v]
        out.append((cell, inward))
        v = nxt
    return out


def _ribbon(g: _Grid, access: tuple[float, float]) -> _Ribbon:
    walk = _boundary(g)
    n = len(walk)
    # convex corner cells: the cell owns two consecutive edges that turn left
    corner_cells: list[int] = []
    for k in range(n):
        c0, d0 = walk[k]
        c1, d1 = walk[(k + 1) % n]
        if c0 == c1 and d0 != d1 and c0 not in corner_cells:
            corner_cells.append(c0)

    # start at the corner nearest the access point (or the first boundary cell)
    def dist(i: int) -> tuple[float, int]:
        x, y = g.xy(i)
        return (math.hypot(x + 0.5 - access[0], y + 0.5 - access[1]), i)

    first = min(corner_cells, key=dist) if corner_cells else (walk[0][0] if walk else -1)
    cells: list[int] = []
    inward: list[tuple[int, int]] = []
    if walk:
        k0 = next(k for k in range(n) if walk[k][0] == first)
        order = [walk[(k0 + j) % n] for j in range(n)]
        for cell, d in order:
            if g.owner[cell] == CORE_CELL:
                continue
            if cells and cells[-1] == cell:
                continue
            cells.append(cell)
            inward.append(d)
        if len(cells) > 1 and cells[0] == cells[-1]:
            cells.pop()
            inward.pop()
    corners = [p for p, c in enumerate(cells) if c in corner_cells]
    return _Ribbon(cells, inward, corners)


# ---------------------------------------------------------------------------- growth
def _noise(cell: int, room: int, seed: int) -> float:
    return ((cell * 2654435761 + room * 40503 + seed * 97) % 1000) / 1000.0


def _cells_of(n_modules_cells: float, step: int) -> int:
    return max(1, round(n_modules_cells / (step * step)))


def grow(
    prepared: PreparedInput,
    rulebook: Rulebook,
    config: AleConfig,
    *,
    seed: int = 0,
    jitter: float = 0.0,
    prior: Mapping[tuple[int, int], str] | None = None,
) -> CellDiagram:
    """The cell diagram of ``prepared`` (RD §3). ``jitter`` > 0 adds a small seeded noise to
    the growth score (used by the seeder's later attempts); 0 is the plain algorithm.

    ``prior`` (Ticket M.3) maps diagram cells ``(cx, cy)`` to a label (the room type of
    another floor): rooms of that type start on and grow towards the cells that carry their
    label, so that a floor repeats the layout below it. ``None`` (or empty) leaves the output
    byte-identical to the plain algorithm."""
    g = _Grid(prepared, rulebook, config)
    insts = prepared.instances
    ids = [iid for iid, _ in insts]
    spec_of: dict[str, RoomSpec] = dict(insts)
    ridx = {iid: r for r, iid in enumerate(ids)}
    graph = build_graph(prepared, rulebook)
    n_of: dict[str, int] = {}
    from ale.geometry.blocks import Consts

    k_consts = Consts.from_config(config)
    for iid, spec in insts:
        n_of[iid] = _cells_of(float(k_consts.req(spec).target), g.step)
    n_max = max(n_of.values(), default=1)
    cell_m = g.step * g.module_m
    limit_m = config.facade.max_depth_m
    limit_cells = max(1, int((limit_m if limit_m else DEFAULT_DEPTH_LIMIT_M) / cell_m + 1e-9))

    # entrances (main first), default: midpoint of the access edge
    a, b = prepared.footprint.polygon.edges()[prepared.footprint.access_edge]
    s_mod = g.step
    access = ((a[0] + b[0]) / 2 / s_mod, (a[1] + b[1]) / 2 / s_mod)
    main_pt: tuple[float, float] = access
    if prepared.site.entrances:
        ent = next((e for e in prepared.site.entrances if e.main), prepared.site.entrances[0])
        main_pt = g.to_cell(prepared, (ent.point[0], ent.point[1]))
    rib = _ribbon(g, access)

    def dist_to(i: int, pt: tuple[float, float]) -> tuple[float, int]:
        x, y = g.xy(i)
        return (math.hypot(x + 0.5 - pt[0], y + 0.5 - pt[1]), i)

    pool = rib.cells or [i for i in range(g.size) if g.owner[i] == FREE]
    ent_cell = min(pool, key=lambda i: dist_to(i, main_pt)) if pool else -1
    ent_pos = rib.cells.index(ent_cell) if ent_cell in rib.cells else 0

    # façade distance (cells; 0 on the façade line)
    fd = [10**6] * g.size
    queue: list[int] = []
    for i in range(g.size):
        if g.owner[i] != OUTSIDE and any(g.owner[j] == OUTSIDE for j in g.nbrs(i)):
            fd[i] = 0
            queue.append(i)
    for i in queue:
        for j in g.nbrs(i):
            if g.owner[j] != OUTSIDE and fd[j] > fd[i] + 1:
                fd[j] = fd[i] + 1
                queue.append(j)

    owner = g.owner
    mine: dict[str, list[int]] = {iid: [] for iid in ids}

    def depth_of(iid: str) -> int:
        return max(1, min(limit_cells, round(math.sqrt(_FRONTAGE_FACTOR * n_of[iid]))))

    def claim(iid: str, i: int) -> None:
        owner[i] = ridx[iid]
        mine[iid].append(i)

    def snap(i: int) -> int:
        """Nearest free cell to ``i`` (ties by index); -1 when the footprint is full."""
        if owner[i] == FREE:
            return i
        x, y = g.xy(i)
        best = min(
            (j for j in range(g.size) if owner[j] == FREE),
            key=lambda j: (abs(g.xy(j)[0] - x) + abs(g.xy(j)[1] - y), j),
            default=-1,
        )
        return best

    partners: dict[str, list[str]] = {iid: [] for iid in ids}
    for u, v in edges_of_kind(graph, REQUIRED):
        partners[u].append(v)
        partners[v].append(u)
    anchors_corner = [iid for iid in ids if spec_of[iid].anchor == "corner"]
    anchors_ent = [iid for iid in ids if spec_of[iid].anchor == "entrance"]
    zone_rank: dict[str, int] = {}
    for iid in ids:
        zone_rank.setdefault(str(spec_of[iid].macro_zone), len(zone_rank))
    on_ribbon = [iid for iid in ids if spec_of[iid].needs_facade or spec_of[iid].anchor is not None]
    on_ribbon.sort(key=lambda t: (zone_rank[str(spec_of[t].macro_zone)], ridx[t]))
    share = {t: -(-n_of[t] // depth_of(t)) for t in on_ribbon}
    npos = len(rib.cells)
    used = [False] * npos
    seed_cell: dict[str, int] = {}
    unplaced: list[str] = []

    def take_span(start: int, length: int, forward: bool = True) -> list[int]:
        pos = [(start + j) % npos if forward else (start - j) % npos for j in range(length)]
        return pos if all(not used[p] for p in pos) and length <= npos else []

    placed_pos: dict[str, list[int]] = {}

    def put(iid: str, positions: list[int]) -> None:
        placed_pos[iid] = positions
        for p in positions:
            used[p] = True
        seed_cell[iid] = rib.cells[sorted(positions)[len(positions) // 2]] if positions else -1

    pr = Prior.build(prior, g, rib.cells)

    if npos:
        # budget the shares to the usable perimeter
        total = sum(share.values())
        if total > npos:
            scale = npos / total
            for t in share:
                share[t] = max(1, math.floor(share[t] * scale))
        # corner rooms: first at the start corner, the others at the next corners
        corner_pos = list(rib.corners) or [0]
        for r, iid in enumerate(anchors_corner):
            c = corner_pos[min(r, len(corner_pos) - 1)] if r else 0
            span = take_span(c, share.get(iid, 1))
            if not span:
                span = take_span(c, share.get(iid, 1), forward=False)
            if span:
                put(iid, span)
                # the corner room's seed is the corner cell itself
                seed_cell[iid] = rib.cells[c]
            else:
                unplaced.append(iid)
        # entrance rooms: share centred on the main entrance (or the nearest free span)
        for iid in anchors_ent:
            if iid in seed_cell:
                continue
            ln = share.get(iid, 1)
            placed = False
            for off in range(npos):
                for sgn in (1, -1) if off else (1,):
                    span = take_span(ent_pos - ln // 2 + sgn * off, ln)
                    if span:
                        put(iid, span)
                        placed = True
                        break
                if placed:
                    break
            if not placed:
                unplaced.append(iid)
        # remaining façade rooms along the free ribbon (macro-zone, then programme order); a
        # room whose REQUIRED partner is already on the ribbon takes the free span next to it
        scan = 0
        for iid in on_ribbon:
            if iid in seed_cell or iid in unplaced:
                continue
            free = [p for p in range(npos) if not used[p]]
            ln = min(share[iid], len(free))
            if ln <= 0:
                unplaced.append(iid)
                continue
            span = []
            near = next((placed_pos[q] for q in partners[iid] if q in placed_pos), None)
            span = pr.ribbon_span(str(spec_of[iid].type), used, ln)
            if not span and near is not None:
                for k in range(npos):
                    span = take_span(max(near) + 1 + k, ln) or take_span(min(near) - ln - k, ln)
                    if span:
                        break
            if not span:
                ahead = [p for p in free if p >= scan] + [p for p in free if p < scan]
                span = ahead[:ln]
                scan = span[-1] + 1
            put(iid, span)
    else:
        unplaced = list(on_ribbon)

    placed_cells: dict[str, int] = {}
    # first claims: the seeds on the façade line
    for iid in on_ribbon:
        c = seed_cell.get(iid, -1)
        if c < 0:
            continue
        c = snap(c)
        if c >= 0:
            claim(iid, c)
            placed_cells[iid] = c

    # non-façade rooms: next to the first REQUIRED partner, next to a core, else centre
    core_set = set(g.core_cells)
    centre = (g.width / 2, g.height / 2)
    centre_cell = min(
        (i for i in range(g.size) if owner[i] != OUTSIDE),
        key=lambda i: dist_to(i, centre),
        default=0,
    )
    rest = [iid for iid in ids if iid not in placed_cells]

    def inward_dir(c: int) -> tuple[int, int]:
        if c in rib.cells:
            return rib.inward[rib.cells.index(c)]
        x, y = g.xy(c)
        dx, dy = centre[0] - x, centre[1] - y
        return (1 if dx >= 0 else -1, 0) if abs(dx) >= abs(dy) else (0, 1 if dy >= 0 else -1)

    def place_prior(iid: str) -> bool:
        """Ticket M.3: seed on the free prior cell of the room's type."""
        c = pr.seed(g, str(spec_of[iid].type), dist_to)
        if c is not None:
            claim(iid, c)
            placed_cells[iid] = c
        return c is not None

    def place_rest(iid: str) -> bool:
        return place_prior(iid) or place_plain(iid)

    def place_plain(iid: str) -> bool:
        if graph.nodes[iid]["service_core"] and core_set:
            nxt = sorted(
                {j for c in core_set for j in g.nbrs(c) if owner[j] == FREE},
                key=lambda j: (dist_to(j, g.xy(sorted(core_set)[0])[0:2])[0], j),
            )
            if nxt:
                claim(iid, nxt[0])
                return True
        for p in partners[iid]:
            if p in placed_cells:
                pc = placed_cells[p]
                dx, dy = inward_dir(pc)
                off = depth_of(p) // 2 + 1
                x, y = g.xy(pc)
                tgt = g.idx(
                    min(max(x + dx * off, 0), g.width - 1), min(max(y + dy * off, 0), g.height - 1)
                )
                c = snap(tgt)
                if c >= 0:
                    claim(iid, c)
                    placed_cells[iid] = c
                    return True
        return False

    pending = list(rest)
    while pending:
        progress = False
        nxt_pending: list[str] = []
        for iid in pending:
            if place_rest(iid):
                placed_cells.setdefault(iid, mine[iid][0])
                progress = True
            else:
                nxt_pending.append(iid)
        pending = nxt_pending
        if not progress:
            break
    for iid in pending:  # others at the free cell nearest the footprint centre
        c = snap(centre_cell)
        if c >= 0:
            claim(iid, c)
            placed_cells[iid] = c

    # Ticket M.3: a room first takes the prior cells of its type connected to its seed
    pr.prefill(g, {iid: str(spec_of[iid].type) for iid in ids}, mine, n_of, claim)

    # ------------------------------------------------------------------ growth
    sums = {iid: [0.0, 0.0] for iid in ids}
    for iid in ids:
        for c in mine[iid]:
            x, y = g.xy(c)
            sums[iid][0] += x
            sums[iid][1] += y
    frontier: dict[str, set[int]] = {iid: set() for iid in ids}
    for iid in ids:
        for c in mine[iid]:
            frontier[iid].update(j for j in g.nbrs(c) if owner[j] == FREE)
    is_fac = {iid: spec_of[iid].needs_facade for iid in ids}
    ent_room = set(anchors_ent)
    ex, ey = g.xy(ent_cell) if ent_cell >= 0 else (0, 0)
    quota = {iid: max(1, round(_QUOTA_FACTOR * n_of[iid] / n_max)) for iid in ids}

    reseeds = {iid: 0 for iid in ids}
    present = {str(spec_of[iid].type) for iid in ids}
    prior_bonus = {iid: pr.bonus(str(spec_of[iid].type), present) for iid in ids}

    def refresh(iid: str) -> None:
        sums[iid] = [sum(g.xy(c)[0] for c in mine[iid]), sum(g.xy(c)[1] for c in mine[iid])]
        frontier[iid] = {j for c in mine[iid] for j in g.nbrs(c) if owner[j] == FREE}

    def unstick(iid: str) -> bool:
        """A room whose frontier is empty (enclosed by other rooms). A room with less than
        half of its cells is moved to the free spot with the roomiest surroundings (at most
        three times); otherwise it jumps to the free cell nearest its centroid and goes on
        from there. ``False`` when no free cell is left."""
        free = [i for i in range(g.size) if owner[i] == FREE]
        if not free:
            return False
        cnt = len(mine[iid])
        cx0, cy0 = sums[iid][0] / cnt, sums[iid][1] / cnt
        if cnt < max(2, n_of[iid] / 2) and reseeds[iid] < _MAX_RESEEDS:
            reseeds[iid] += 1
            for c in mine[iid]:
                owner[c] = FREE
            mine[iid].clear()

            def room_around(i: int) -> tuple[int, float, int]:
                x, y = g.xy(i)
                n_free = sum(
                    owner[g.idx(x + dx, y + dy)] == FREE
                    for dx in range(-3, 4)
                    for dy in range(-3, 4)
                    if 0 <= x + dx < g.width and 0 <= y + dy < g.height
                )
                return (-n_free, math.hypot(x - cx0, y - cy0), i)

            claim(iid, min(free, key=room_around))
        else:
            claim(iid, min(free, key=lambda i: dist_to(i, (cx0 + 0.5, cy0 + 0.5))))
        refresh(iid)
        return True

    while True:
        moved = False
        for iid in ids:
            if len(mine[iid]) >= n_of[iid] or not mine[iid]:
                continue
            if not any(owner[c] == FREE for c in frontier[iid]):
                if not unstick(iid):
                    continue
                moved = True
            r = ridx[iid]
            cnt = len(mine[iid])
            cx0, cy0 = sums[iid][0] / cnt, sums[iid][1] / cnt
            pcs: list[tuple[float, float]] = []
            for p in partners[iid]:
                if mine[p]:
                    pcs.append(
                        (
                            sum(g.xy(c)[0] for c in mine[p]) / len(mine[p]),
                            sum(g.xy(c)[1] for c in mine[p]) / len(mine[p]),
                        )
                    )
            static: dict[int, float] = {}

            def base(
                c: int,
                iid: str = iid,
                r: int = r,
                cx0: float = cx0,
                cy0: float = cy0,
                pcs: list[tuple[float, float]] = pcs,
                bonus: dict[int, float] = prior_bonus[iid],
            ) -> float:
                x, y = g.xy(c)
                s = _W_CENTROID * math.hypot(x - cx0, y - cy0)
                if is_fac[iid]:
                    s += _W_FACADE * fd[c]
                    if fd[c] + 1 > limit_cells:
                        s += _FACADE_PENALTY
                s += bonus.get(c, 0.0)
                if iid in ent_room:
                    s += _W_ENTRANCE * (abs(x - ex) + abs(y - ey))
                for px, py in pcs:
                    s += _W_PARTNER * math.hypot(x - px, y - py)
                if jitter:
                    s += jitter * _noise(c, r, seed)
                return s

            for _ in range(quota[iid]):
                if len(mine[iid]) >= n_of[iid]:
                    break
                best_c = -1
                best_s = math.inf
                for c in frontier[iid]:
                    if owner[c] != FREE:
                        continue
                    if c not in static:
                        static[c] = base(c)
                    own = sum(owner[j] == r for j in g.nbrs(c))
                    sc = _W_NEIGHBOUR * own + static[c]
                    if sc < best_s or (sc == best_s and c < best_c):
                        best_s, best_c = sc, c
                if best_c < 0:
                    break
                claim(iid, best_c)
                x, y = g.xy(best_c)
                sums[iid][0] += x
                sums[iid][1] += y
                frontier[iid].discard(best_c)
                frontier[iid].update(j for j in g.nbrs(best_c) if owner[j] == FREE)
                moved = True
        if not moved:
            break
        if all(len(mine[i]) >= n_of[i] or not mine[i] for i in ids):
            break

    return _finish(g, ids, spec_of, graph, mine, n_of, ent_cell, rib, core_set, partners)


def _finish(
    g: _Grid,
    ids: list[str],
    spec_of: dict[str, RoomSpec],
    graph: object,
    mine: dict[str, list[int]],
    n_of: dict[str, int],
    ent_cell: int,
    rib: _Ribbon,
    core_set: set[int],
    partners: dict[str, list[str]],
) -> CellDiagram:
    ridx = {iid: r for r, iid in enumerate(ids)}
    owner_rows = tuple(
        tuple(g.owner[g.idx(cx, cy)] for cx in range(g.width)) for cy in range(g.height)
    )
    cells = {iid: tuple(sorted(g.xy(c) for c in mine[iid])) for iid in ids}
    area = {iid: n_of[iid] - len(mine[iid]) for iid in ids if len(mine[iid]) < n_of[iid]}
    on_edge = {
        i
        for i in range(g.size)
        if g.owner[i] >= 0 and any(g.owner[j] == OUTSIDE for j in g.nbrs(i))
    }
    facade = tuple(
        iid for iid in ids if spec_of[iid].needs_facade and not any(c in on_edge for c in mine[iid])
    )
    corner_cells = {rib.cells[p] for p in rib.corners}
    corner = tuple(
        iid
        for iid in ids
        if spec_of[iid].anchor == "corner" and not any(c in corner_cells for c in mine[iid])
    )
    entrance: tuple[str, ...] = ()
    if ent_cell >= 0:
        near = {ent_cell, *g.nbrs(ent_cell)}
        entrance = tuple(
            iid
            for iid in ids
            if spec_of[iid].anchor == "entrance" and not any(c in near for c in mine[iid])
        )
    adjacency: list[tuple[str, str]] = []
    for u in ids:
        for v in partners[u]:
            if u < v:
                touch = any(g.owner[j] == ridx[v] for c in mine[u] for j in g.nbrs(c))
                if not touch:
                    adjacency.append((u, v))
    core_rooms = tuple(
        iid
        for iid in ids
        if graph.nodes[iid]["service_core"]  # type: ignore[attr-defined]
        and core_set
        and not any(j in core_set for c in mine[iid] for j in g.nbrs(c))
    )
    entrance_xy = g.xy(ent_cell) if ent_cell >= 0 else None
    return CellDiagram(
        step=g.step,
        module_m=g.module_m,
        width=g.width,
        height=g.height,
        owner=owner_rows,
        rooms=tuple(ids),
        types={iid: spec_of[iid].type for iid in ids},
        targets=dict(n_of),
        cells=cells,
        cores=tuple(sorted(g.xy(c) for c in core_set)),
        entrance=entrance_xy,
        checks=DiagramChecks(
            area=area,
            facade=facade,
            corner=corner,
            entrance=entrance,
            adjacency=tuple(sorted(adjacency)),
            core=core_rooms,
        ),
    )
