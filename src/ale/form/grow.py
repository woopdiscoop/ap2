"""Cell growth of one building mass on the plot (Ticket G.3, RD section 3).

The plot is gridded in 0.60 m cells. Setbacks and everything beyond a street edge are
*outside*; beyond a party edge is *party* (a wall: neither building nor outside). The building
grows as ONE mass: the hall at the main entrance, then circulation (a compact zone attracted
to the cores), then each next room seeded on the edge of the mass once the previous one
reached 60 % of its count (or is stuck). Rule: no claim may cut the outside off from the
street (local simple-point test, then a flood fill from the neighbours when the local test is
ambiguous). Deterministic for ``(inputs, seed)``: ties by cell index, the only noise is a hash.
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field

from ale.contracts.models import Program, RoomSpec, SiteSpec
from ale.topology.cellgrow import CORE_CELL, FREE, OUTSIDE

__all__ = [
    "CELL_M",
    "CIRC_ID",
    "COURT",
    "PARTY",
    "FormResult",
    "grow_form",
    "outside_cells_connected",
]

CELL_M = 0.6
CIRC_SHARE = 0.16
COURT_CELLS = 19
SEED_AT = 0.60
CIRC_ID = "CIRC"
PARTY = -4
COURT = -5
_MAX_RESTARTS = 10
_EPS = 1e-9
#: 8-neighbourhood in cyclic order (E, NE, N, NW, W, SW, S, SE); even entries are 4-neighbours.
_RING = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
_STORAGE = frozenset({"storage", "archive"})
_SERVICE_ZONE = "SERVICES"


@dataclass
class FormResult:
    """One grown form. ``owner[(cy + 1) * wp + cx + 1]`` is a room index (>= 0, the last
    index is the circulation), ``FREE`` (unbuilt, buildable), ``OUTSIDE``, ``CORE_CELL``,
    ``PARTY`` or ``COURT``; the grid has one border of non-plot cells."""

    seed: int
    cell_m: float
    origin: tuple[float, float]
    width: int  # cells in x (without border)
    height: int
    owner: list[int]
    in_plot: list[bool]
    buildable: list[bool]
    rooms: list[str]  # instance ids; rooms[-1] == CIRC_ID
    types: dict[str, str]
    needs_facade: dict[str, bool]
    need: dict[str, int]  # target cell count (circulation: the target without extra cells)
    hall: str
    entrance: tuple[float, float]
    entrance_cell: tuple[int, int]
    cores: list[tuple[str, list[int]]]
    court_cells: list[int] = field(default_factory=list)
    circ_extra: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def wp(self) -> int:
        return self.width + 2

    def idx(self, cx: int, cy: int) -> int:
        return (cy + 1) * self.wp + cx + 1

    def xy(self, i: int) -> tuple[int, int]:
        return i % self.wp - 1, i // self.wp - 1

    def cells_of(self, room: int) -> list[int]:
        return [i for i, v in enumerate(self.owner) if v == room]

    def built_cells(self) -> list[int]:
        return [i for i, v in enumerate(self.owner) if v >= 0 or v == CORE_CELL]

    def counts(self) -> dict[str, int]:
        n = [0] * len(self.rooms)
        for v in self.owner:
            if v >= 0:
                n[v] += 1
        return dict(zip(self.rooms, n, strict=True))


def _is_outside(v: int) -> bool:
    return v in (FREE, OUTSIDE, COURT)


def _noise(cell: int, room: int, seed: int) -> float:
    return ((cell * 2654435761 + room * 40503 + seed * 97) % 1000) / 1000.0


def _box_dist(
    box: tuple[float, float, float, float], seg: tuple[float, float, float, float]
) -> float:
    """Distance between two axis-aligned boxes (a segment is a degenerate box)."""
    dx = max(seg[0] - box[2], box[0] - seg[2], 0.0)
    dy = max(seg[1] - box[3], box[1] - seg[3], 0.0)
    return math.hypot(dx, dy)


def _crossings(ring: list[tuple[float, float]], px: float, py: float) -> int:
    n, c = len(ring), 0
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        if a[0] == b[0] and px < a[0] and min(a[1], b[1]) < py < max(a[1], b[1]):
            c += 1
    return c


def _inside_polygon(
    ext: list[tuple[float, float]], holes: list[list[tuple[float, float]]], px: float, py: float
) -> bool:
    return _crossings(ext, px, py) % 2 == 1 and all(_crossings(h, px, py) % 2 == 0 for h in holes)


def _runs_with_neighbour(bits: list[bool]) -> int:
    """Cyclic runs of ``True`` in the 8-ring that contain a 4-neighbour (even entry)."""
    start = bits.index(False)
    runs = 0
    in_run = has_even = False
    for step in range(1, 9):
        k = (start + step) % 8
        if bits[k]:
            in_run = True
            has_even = has_even or k % 2 == 0
        elif in_run:
            runs += has_even
            in_run = has_even = False
    return runs + (1 if in_run and has_even else 0)


class _Grower:
    def __init__(self, program: Program, site: SiteSpec, seed: int, court: int | None) -> None:
        self.seed = seed
        self._site(site)
        self._rooms(program, seed)
        self._cores(site)
        self.court_cells: list[int] = []
        self.court_size = court
        self.entrance_pt = self._entrance(site)
        if court:
            self._court(court)
        self.cells: list[list[int]] = [[] for _ in self.names]
        self.frontier: list[set[int]] = [set() for _ in self.names]
        self.edge: set[int] = set()
        self.count = [0] * len(self.names)
        self.done: set[int] = set()
        self.borrowed = [0] * len(self.names)
        self.restarts = [0] * len(self.names)
        self.touched_cores: set[int] = set()
        self.circ_extra = 0
        for i, v in enumerate(self.owner):
            if v == CORE_CELL:
                self._edge_add(i)

    # ------------------------------------------------------------------ set-up
    def _site(self, site: SiteSpec) -> None:
        ext = [(float(x), float(y)) for x, y in site.footprint.exterior]
        holes = [[(float(x), float(y)) for x, y in h] for h in site.footprint.holes]
        self.origin = (min(p[0] for p in ext), min(p[1] for p in ext))
        ox, oy = self.origin
        self.width = max(1, math.ceil((max(p[0] for p in ext) - ox) / CELL_M - _EPS))
        self.height = max(1, math.ceil((max(p[1] for p in ext) - oy) / CELL_M - _EPS))
        self.wp = self.width + 2
        self.size = self.wp * (self.height + 2)
        n = len(ext)
        setbacks = site.setbacks if site.setbacks is not None else (0.0,) * n
        segs = []
        for k in range(n):
            a, b = ext[k], ext[(k + 1) % n]
            segs.append((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])))
        party = set(site.party_edges)
        self.owner = [OUTSIDE] * self.size
        self.in_plot = [False] * self.size
        self.buildable = [False] * self.size
        self.root = [False] * self.size
        e = 1e-6
        for cy in range(-1, self.height + 1):
            for cx in range(-1, self.width + 1):
                i = self.idx(cx, cy)
                x0, y0 = ox + cx * CELL_M, oy + cy * CELL_M
                box = (x0, y0, x0 + CELL_M, y0 + CELL_M)
                inside = all(
                    _inside_polygon(ext, holes, x, y)
                    for x, y in (
                        (box[0] + e, box[1] + e),
                        (box[2] - e, box[1] + e),
                        (box[0] + e, box[3] - e),
                        (box[2] - e, box[3] - e),
                    )
                )
                self.in_plot[i] = inside
                if inside:
                    if all(_box_dist(box, segs[k]) >= setbacks[k] - _EPS for k in range(n)):
                        self.owner[i] = FREE
                        self.buildable[i] = True
                elif any(_box_dist(box, segs[k]) <= _EPS for k in party):
                    self.owner[i] = PARTY
                else:
                    self.root[i] = True

    def idx(self, cx: int, cy: int) -> int:
        return (cy + 1) * self.wp + cx + 1

    def xy(self, i: int) -> tuple[int, int]:
        return i % self.wp - 1, i // self.wp - 1

    def _rooms(self, program: Program, seed: int) -> None:
        inst = program.instances()
        cells = {iid: max(1, round(spec.target_area_m2 / (CELL_M * CELL_M))) for iid, spec in inst}
        specs: dict[str, RoomSpec] = dict(inst)
        base: dict[str, list[str]] = {}
        for iid, spec in inst:
            base.setdefault(spec.id, []).append(iid)
        hall = next((iid for iid, s in inst if s.anchor == "entrance"), None)
        if hall is None:
            public = [(k, iid) for k, (iid, s) in enumerate(inst) if s.macro_zone.value == "PUBLIC"]
            pool = public or [(k, iid) for k, (iid, _) in enumerate(inst)]
            hall = max(pool, key=lambda p: (cells[p[1]], -p[0]))[1]
        rest = [iid for iid, _ in inst if iid != hall]
        if seed > 1:
            random.Random(10_000 + seed).shuffle(rest)
        circ = max(1, round(CIRC_SHARE * sum(cells.values())))
        self.hall = hall
        self.names = [*(iid for iid, _ in inst), CIRC_ID]
        self.rid = {n: k for k, n in enumerate(self.names)}
        self.circ = len(self.names) - 1
        self.need = [cells[n] for n in self.names[:-1]] + [circ]
        self.types = {iid: s.type for iid, s in inst} | {CIRC_ID: "circulation"}
        self.facade = [specs[n].needs_facade for n in self.names[:-1]] + [False]
        zones = [specs[n].macro_zone.value == _SERVICE_ZONE for n in self.names[:-1]]
        self.service = [*zones, False]
        self.storage = [specs[n].type in _STORAGE for n in self.names[:-1]] + [False]
        self.partners: list[list[int]] = []
        self.avoid: list[set[int]] = []
        for n in self.names[:-1]:
            sp = specs[n]
            self.partners.append(
                [self.rid[p] for ref in sp.adjacent_to for p in base[ref] if p != n]
            )
            self.avoid.append({self.rid[p] for ref in sp.avoid for p in base[ref]})
        self.partners.append([])
        self.avoid.append(set())
        self.order = [self.rid[hall], self.circ, *(self.rid[n] for n in rest)]

    def _cores(self, site: SiteSpec) -> None:
        ox, oy = self.origin
        self.core_list: list[tuple[str, list[int]]] = []
        for core in site.cores:
            x, y, w, h = core.rect
            # cells covering the rectangle, so that the footprint covers the core
            x0, x1 = math.floor((x - ox) / CELL_M + 1e-6), math.ceil((x + w - ox) / CELL_M - 1e-6)
            y0, y1 = math.floor((y - oy) / CELL_M + 1e-6), math.ceil((y + h - oy) / CELL_M - 1e-6)
            cs: list[int] = []
            for cy in range(y0, y1):
                for cx in range(x0, x1):
                    if 0 <= cx < self.width and 0 <= cy < self.height:
                        i = self.idx(cx, cy)
                        if self.in_plot[i]:
                            self.owner[i] = CORE_CELL
                            cs.append(i)
            self.core_list.append((core.id, cs))

    def _entrance(self, site: SiteSpec) -> tuple[float, float]:
        main = next((e for e in site.entrances if e.main), None)
        if main is None and site.entrances:
            main = site.entrances[0]
        if main is not None:
            pt = (float(main.point[0]), float(main.point[1]))
        else:
            ext = site.footprint.exterior
            a, b = ext[site.access_edge], ext[(site.access_edge + 1) % len(ext)]
            pt = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        self.entrance_cell = (
            math.floor((pt[0] - self.origin[0]) / CELL_M),
            math.floor((pt[1] - self.origin[1]) / CELL_M),
        )
        return pt

    def _court(self, size: int) -> None:
        cells = [i for i, b in enumerate(self.buildable) if b]
        if not cells:
            return
        xs = [self.xy(i)[0] for i in cells]
        ys = [self.xy(i)[1] for i in cells]
        bw, bh = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        s = max(3, min(size, bw // 2, bh // 2))
        shift = (self.seed % 3 - 1) * max(1, min(bw, bh) // 12)
        cx0 = min(xs) + (bw - s) // 2 + shift
        cy0 = min(ys) + (bh - s) // 2 + shift
        cx0 = max(min(xs), min(cx0, max(xs) - s + 1))
        cy0 = max(min(ys), min(cy0, max(ys) - s + 1))
        hall_cell = self._hall_order()[0]
        for cy in range(cy0, cy0 + s):
            for cx in range(cx0, cx0 + s):
                i = self.idx(cx, cy)
                if self.owner[i] == FREE and i != hall_cell:
                    self.owner[i] = COURT
                    self.root[i] = True
                    self.court_cells.append(i)
        self.court_size = s

    def _hall_order(self) -> list[int]:
        ox, oy = self.origin
        pt = self.entrance_pt

        def dist(i: int) -> tuple[float, int]:
            cx, cy = self.xy(i)
            dx = ox + (cx + 0.5) * CELL_M - pt[0]
            dy = oy + (cy + 0.5) * CELL_M - pt[1]
            return round(dx * dx + dy * dy, 9), i

        return sorted((i for i, v in enumerate(self.owner) if v == FREE), key=dist)

    # ------------------------------------------------------------------ topology rule
    def _nbr4(self, i: int) -> tuple[int, int, int, int]:
        w = self.wp
        return i + 1, i - 1, i + w, i - w

    def _may_claim(self, i: int) -> bool:
        """True when building on ``i`` keeps every outside cell connected to a street."""
        owner, w = self.owner, self.wp
        bits = [_is_outside(owner[i + dx + dy * w]) for dx, dy in _RING]
        if not any(bits[0::2]) or all(bits):
            return True
        if _runs_with_neighbour(bits) <= 1:
            return True
        return self._anchored_after(i)

    def _anchored_after(self, i: int) -> bool:
        """Global check: every outside neighbour of ``i`` still reaches a street or the court."""
        owner = self.owner
        anchored: set[int] = set()
        for n in self._nbr4(i):
            if not _is_outside(owner[n]) or n in anchored:
                continue
            seen = {n}
            queue = deque([n])
            found = False
            while queue:
                c = queue.popleft()
                if self.root[c] or c in anchored:
                    found = True
                    break
                for m in self._nbr4(c):
                    if m != i and m not in seen and _is_outside(owner[m]):
                        seen.add(m)
                        queue.append(m)
            if not found:
                return False
            anchored |= seen
        return True

    # ------------------------------------------------------------------ scoring
    def _score(self, r: int, i: int) -> float:
        owner, w = self.owner, self.wp
        n4 = [owner[j] for j in self._nbr4(i)]
        own4 = sum(v == r for v in n4)
        own8 = sum(owner[i + dx + dy * w] == r for dx, dy in _RING[1::2])
        out4 = sum(_is_outside(v) for v in n4)
        cx, cy = self.xy(i)
        s = _noise(i, r, self.seed) * 0.15 + self._mass_term(i, n4)
        for v in set(n4):  # do not smother a neighbour that is still growing
            if v >= 0 and v != r and self.count[v] < self.need[v] and len(self.frontier[v]) <= 10:
                s -= 2.5
        if r == self.circ:
            s += 2.0 * own4 + 0.6 * own8 - 0.8 * out4
            tgt = self._core_target(cx, cy)
            return s - 1.2 * tgt if tgt is not None else s
        s += 1.2 * own4 + 0.3 * own8
        free4 = sum(v == FREE for v in n4)
        left = self.need[r] - self.count[r] - 1
        if left > 0:  # keep liberties: do not close the room's own last way out
            liberties = free4 + len(self.frontier[r]) - 1
            if liberties < min(left, 6):
                s -= 1.5 * (min(left, 6) - liberties)
        s += 0.9 * min(out4, 2) if self.facade[r] else -0.4 * out4
        if any(v == self.circ for v in n4):
            s += 0.2 if self._touches_circ(r) else 3.0
        for p in self.partners[r][:4]:
            c = self._centroid(p)
            if c is not None:
                s -= 0.04 * (abs(c[0] - cx) + abs(c[1] - cy))
        if self.service[r] and self.core_list:
            s -= 0.05 * min(self._core_dist(cx, cy, k) for k in range(len(self.core_list)))
        if self.storage[r]:
            s += sum(v == PARTY for v in n4)
        if self.avoid[r] and any(v in self.avoid[r] for v in n4):
            s -= 2.0
        return s

    def _mass_term(self, i: int, n4: list[int]) -> float:
        """Keep the mass compact and free of narrow notches (any owner counts as building)."""
        owner = self.owner
        built4 = sum(v >= 0 or v == CORE_CELL for v in n4)
        s = 0.5 * built4
        if (n4[0] >= 0 or n4[0] == CORE_CELL) and (n4[1] >= 0 or n4[1] == CORE_CELL):
            s += 1.6
        if (n4[2] >= 0 or n4[2] == CORE_CELL) and (n4[3] >= 0 or n4[3] == CORE_CELL):
            s += 1.6
        for d in (1, -1, self.wp, -self.wp):
            far = owner[i + 2 * d]
            if owner[i + d] == FREE and (far >= 0 or far == CORE_CELL):
                s -= 1.6
        return s

    def _core_dist(self, cx: int, cy: int, k: int) -> float:
        cells = self.core_list[k][1]
        if not cells:
            return 0.0
        x, y = self.xy(cells[0])
        return abs(x - cx) + abs(y - cy)

    def _core_target(self, cx: int, cy: int) -> float | None:
        todo = [k for k in range(len(self.core_list)) if k not in self.touched_cores]
        if not todo:
            return None
        return min(self._core_dist(cx, cy, k) for k in todo)

    def _centroid(self, r: int) -> tuple[float, float] | None:
        if not self.count[r]:
            return None
        pts = [self.xy(i) for i in self.cells[r]]
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)

    def _touches_circ(self, r: int) -> bool:
        return any(self.owner[n] == self.circ for i in self.cells[r] for n in self._nbr4(i))

    # ------------------------------------------------------------------ claims
    def _edge_add(self, i: int) -> None:
        for n in self._nbr4(i):
            if self.owner[n] == FREE:
                self.edge.add(n)

    def _claim(self, r: int, i: int) -> None:
        self.owner[i] = r
        self.cells[r].append(i)
        self.count[r] += 1
        self.edge.discard(i)
        for n in self._nbr4(i):
            if self.owner[n] == FREE:
                self.frontier[r].add(n)
                self.edge.add(n)
        if r == self.circ:
            nb = set(self._nbr4(i))
            for k, (_, cs) in enumerate(self.core_list):
                if k not in self.touched_cores and nb & set(cs):
                    self.touched_cores.add(k)

    def _grow_one(self, r: int) -> bool:
        cands = [i for i in self.frontier[r] if self.owner[i] == FREE]
        self.frontier[r] = set(cands)
        for i in sorted(cands, key=lambda c: (-self._score(r, c), c)):
            if self._may_claim(i):
                self._claim(r, i)
                return True
        return False

    def _seed_score(self, r: int, i: int) -> float:
        n4 = [self.owner[j] for j in self._nbr4(i)]
        s = self._score(r, i)
        if r != self.circ and any(v == self.circ for v in n4):
            s += 2.5
        if any(v in self.partners[r] for v in n4):
            s += 1.5
        s += 0.3 * sum(v >= 0 or v == CORE_CELL for v in n4)
        w = self.wp
        s += 0.3 * sum(self.owner[i + dx + dy * w] == FREE for dx, dy in _RING)
        return s + 0.6 * _noise(i, r + 7 + 131 * self.restarts[r], self.seed)

    def _space(self, start: int, limit: int) -> int:
        """Free cells reachable from ``start`` through free cells (capped at ``limit``)."""
        seen = {start}
        queue = deque([start])
        while queue and len(seen) < limit:
            c = queue.popleft()
            for m in self._nbr4(c):
                if m not in seen and self.owner[m] == FREE:
                    seen.add(m)
                    queue.append(m)
        return len(seen)

    def _seed(self, r: int, pool: list[int] | None = None) -> bool:
        """Seed ``r`` on one cell where the room can still grow to its count (best score
        first; the largest free space when none can)."""
        cands = [i for i in (sorted(self.edge) if pool is None else pool) if self.owner[i] == FREE]
        ranked = sorted(cands, key=lambda c: (-self._seed_score(r, c), c))
        need = self.need[r] - self.count[r]
        best, best_space = -1, -1
        for i in ranked[:30]:
            if not self._may_claim(i):
                continue
            space = self._space(i, need)
            if space >= need:
                best = i
                break
            if space > best_space:
                best, best_space = i, space
        if best < 0:
            for i in ranked[30:]:
                if self._may_claim(i):
                    best = i
                    break
        if best < 0:
            return False
        self._claim(r, best)
        return True

    def _seed_hall(self, r: int) -> bool:
        for i in self._hall_order()[:20]:
            if self._may_claim(i):
                self._claim(r, i)
                return True
        return False

    # ------------------------------------------------------------------ main loop
    def run(self) -> None:
        queue = deque(self.order)
        active: list[int] = []
        done = self.done
        last: int | None = None
        last_stuck = False
        first = self.order[0]
        while True:
            growable = [r for r in active if r not in done]
            trigger = (
                last is None
                or last_stuck
                or not growable
                or (
                    self.count[last] >= SEED_AT * self.need[last]
                    and (last != self.circ or len(self.touched_cores) == len(self.core_list))
                )
            )
            if queue and trigger:
                r = queue.popleft()
                if r == first:
                    ok = self._seed_hall(r)
                elif r == self.circ:
                    around = sorted({n for i in self.cells[first] for n in self._nbr4(i)})
                    ok = self._seed(r, around)
                else:
                    ok = self._seed(r)
                active.append(r)
                last, last_stuck = r, False
                if not ok:
                    done.add(r)
                    last_stuck = True
                continue
            if not growable:
                break
            r = min(growable, key=lambda q: (self.count[q] / self.need[q], q))
            if self._want_more(r):
                if self._grow_one(r):
                    continue
                if self.count[r] == 0 and self._seed(r):
                    continue
                if self._steal(r) or self._borrow(r) or self._restart(r):
                    continue
            done.add(r)
            if r == last:
                last_stuck = True
        for r in range(len(self.names) - 1):  # last resort: the circulation may shrink to 50 %
            while self.count[r] < self.need[r] and self._steal(r, 0.5):
                pass
        self.circ_extra = max(0, self.count[self.circ] - self.need[self.circ])

    def _steal(self, r: int, floor: float = 0.75) -> bool:
        """The circulation is the elastic zone: a stuck room takes ONE circulation cell next to
        its own region when the circulation stays in one piece, keeps touching its cores and
        keeps at least ``floor`` of its target."""
        c = self.circ
        if r == c or self.count[c] <= floor * self.need[c]:
            return False
        mine = set(self.cells[r])
        cand = sorted({n for i in mine for n in self._nbr4(i) if self.owner[n] == c})
        for n in cand:
            if any(self.owner[m] == CORE_CELL for m in self._nbr4(n)):
                continue
            rest = [i for i in self.cells[c] if i != n]
            if not self._piece(rest):
                continue
            self.cells[c] = rest
            self.count[c] -= 1
            self._refrontier(c)
            self.owner[n] = r
            self.cells[r].append(n)
            self.count[r] += 1
            for m in self._nbr4(n):
                if self.owner[m] == FREE:
                    self.frontier[r].add(m)
            return True
        return False

    def _borrow(self, r: int) -> bool:
        """A stuck room takes ONE cell next to its region from a neighbour that still has a free
        way out (the neighbour stays in one piece and regrows elsewhere)."""
        if self.borrowed[r] >= 150:
            return False
        mine = set(self.cells[r])
        for n in sorted({n for i in mine for n in self._nbr4(i)}):
            y = self.owner[n]
            if y < 0 or y == r or y in (self.circ, self.rid[self.hall]) or self.borrowed[y] >= 150:
                continue
            free_out = [m for m in self.frontier[y] if self.owner[m] == FREE]
            if not free_out:
                continue
            rest = [i for i in self.cells[y] if i != n]
            if not self._piece(rest):
                continue
            self.cells[y] = rest
            self.count[y] -= 1
            self._refrontier(y)
            self.owner[n] = r
            self.cells[r].append(n)
            self.count[r] += 1
            self.borrowed[r] += 1
            self.done.discard(y)
            for m in self._nbr4(n):
                if self.owner[m] == FREE:
                    self.frontier[r].add(m)
            return True
        return False

    def _refrontier(self, r: int) -> None:
        """Free cells touching the room's own cells (after it lost a cell)."""
        self.frontier[r] = {
            n for i in self.cells[r] for n in self._nbr4(i) if self.owner[n] == FREE
        }

    def _piece(self, cells: list[int]) -> bool:
        """The cells form one 4-connected region."""
        left = set(cells)
        if not left:
            return True
        start = cells[0]
        left.discard(start)
        stack = [start]
        while stack:
            for m in self._nbr4(stack.pop()):
                if m in left:
                    left.discard(m)
                    stack.append(m)
        return not left

    def _outside_ok(self) -> bool:
        """Every outside cell reaches a street or the courtyard."""
        owner = self.owner
        seen = {i for i, v in enumerate(owner) if self.root[i] and _is_outside(v)}
        queue = deque(seen)
        while queue:
            c = queue.popleft()
            for m in self._nbr4(c):
                if 0 <= m < len(owner) and m not in seen and _is_outside(owner[m]):
                    seen.add(m)
                    queue.append(m)
        return len(seen) == sum(_is_outside(v) for v in owner)

    def _restart(self, r: int) -> bool:
        """A stuck room is released and reseeded as ONE piece on the mass edge (never a
        second, disconnected seed). The release must keep the outside connected."""
        if r in (self.circ, self.rid[self.hall]) or self.restarts[r] >= _MAX_RESTARTS:
            return False
        released = list(self.cells[r])
        for i in released:
            self.owner[i] = FREE
        if not self._outside_ok():
            for i in released:
                self.owner[i] = r
            self.restarts[r] = _MAX_RESTARTS
            return False
        self.restarts[r] += 1
        self.cells[r], self.count[r], self.frontier[r] = [], 0, set()
        for i in released:
            for n in self._nbr4(i):
                v = self.owner[n]
                if v >= 0:
                    self.frontier[v].add(i)
                    if v != r and self._want_more(v):
                        self.done.discard(v)  # the released cell gives it a way out again
            if any(self.owner[n] >= 0 or self.owner[n] == CORE_CELL for n in self._nbr4(i)):
                self.edge.add(i)
        return self._seed(r)

    def _want_more(self, r: int) -> bool:
        if self.count[r] < self.need[r]:
            return True
        if r == self.circ and len(self.touched_cores) < len(self.core_list):
            return self.count[r] < 3 * self.need[r]
        return False

    def result(self) -> FormResult:
        res = FormResult(
            seed=self.seed,
            cell_m=CELL_M,
            origin=self.origin,
            width=self.width,
            height=self.height,
            owner=self.owner,
            in_plot=self.in_plot,
            buildable=self.buildable,
            rooms=self.names,
            types=self.types,
            needs_facade={n: self.facade[k] for k, n in enumerate(self.names)},
            need={n: self.need[k] for k, n in enumerate(self.names)},
            hall=self.hall,
            entrance=self.entrance_pt,
            entrance_cell=self.entrance_cell,
            cores=self.core_list,
            court_cells=self.court_cells,
            circ_extra=self.circ_extra,
        )
        if self.court_cells:
            res.notes.append(f"cour : {self.court_size} x {self.court_size} cellules")
        return res


def grow_form(
    program: Program,
    site: SiteSpec,
    *,
    seed: int = 1,
    courtyard: bool = False,
    court_cells: int = COURT_CELLS,
) -> FormResult:
    """Grow one form (RD section 3). ``seed`` 1 keeps the programme order, others shuffle."""
    g = _Grower(program, site, seed, court_cells if courtyard else None)
    g.run()
    return g.result()


def outside_cells_connected(res: FormResult) -> bool:
    """True iff every unbuilt, non-party cell reaches a street cell (or the courtyard)."""
    wp = res.wp
    outside = [_is_outside(v) for v in res.owner]
    roots = [
        i for i, v in enumerate(res.owner) if _is_outside(v) and (not res.in_plot[i] or v == COURT)
    ]
    seen = set(roots)
    queue = deque(roots)
    while queue:
        c = queue.popleft()
        for m in (c + 1, c - 1, c + wp, c - wp):
            if 0 <= m < len(outside) and outside[m] and m not in seen:
                seen.add(m)
                queue.append(m)
    return len(seen) == sum(outside)
