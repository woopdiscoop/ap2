"""Outline of a grown form (Ticket G.3, RD section 4).

The built cells become orthogonal polygon(s) in metres on the cell grid. Notches narrower
than 2 cells (an outside cell with building on both opposite sides) are removed first: filled
or cut, whichever changes less area (a tie fills), never cutting the outside connection and
never leaving the building in several pieces. Cells are ``(cx, cy)`` pairs.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

__all__ = ["Cell", "Outline", "OutlinePolygon", "outline_from_cells", "ring_area", "trace_rings"]

Cell = tuple[int, int]
Point = tuple[float, float]
_NB = ((1, 0), (-1, 0), (0, 1), (0, -1))
_MAX_ROUNDS = 2000


@dataclass(frozen=True)
class OutlinePolygon:
    """One polygon: counter-clockwise ``exterior`` and clockwise ``holes`` (open rings, m)."""

    exterior: tuple[Point, ...]
    holes: tuple[tuple[Point, ...], ...] = ()

    def area(self) -> float:
        return ring_area(self.exterior) + sum(ring_area(h) for h in self.holes)

    def perimeter(self) -> float:
        return sum(_perimeter(r) for r in (self.exterior, *self.holes))


@dataclass(frozen=True)
class Outline:
    polygons: tuple[OutlinePolygon, ...]
    cells: frozenset[Cell]  # the built cells after notch removal
    vertices_before: int
    vertices_after: int
    cells_filled: int
    cells_cut: int

    def area(self) -> float:
        return sum(p.area() for p in self.polygons)

    def perimeter(self) -> float:
        return sum(p.perimeter() for p in self.polygons)


def ring_area(ring: tuple[Point, ...]) -> float:
    """Signed shoelace area (positive counter-clockwise, negative clockwise)."""
    n = len(ring)
    return (
        sum(ring[i][0] * ring[(i + 1) % n][1] - ring[(i + 1) % n][0] * ring[i][1] for i in range(n))
        / 2
    )


def _perimeter(ring: tuple[Point, ...]) -> float:
    n = len(ring)
    return sum(
        abs(ring[i][0] - ring[(i + 1) % n][0]) + abs(ring[i][1] - ring[(i + 1) % n][1])
        for i in range(n)
    )


# ---------------------------------------------------------------------- tracing
def trace_rings(cells: frozenset[Cell] | set[Cell]) -> list[list[tuple[int, int]]]:
    """Closed boundary rings in cell-corner integers, interior on the left (outer rings
    counter-clockwise, holes clockwise), collinear vertices removed. Where two cells only
    touch at a corner the ring turns left, so the cells stay separate pieces."""
    out: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for x, y in cells:
        if (x, y - 1) not in cells:
            out.setdefault((x, y), []).append((x + 1, y))
        if (x + 1, y) not in cells:
            out.setdefault((x + 1, y), []).append((x + 1, y + 1))
        if (x, y + 1) not in cells:
            out.setdefault((x + 1, y + 1), []).append((x, y + 1))
        if (x - 1, y) not in cells:
            out.setdefault((x, y + 1), []).append((x, y))
    for v in out.values():
        v.sort()
    rings: list[list[tuple[int, int]]] = []
    for start in sorted(out):
        while out[start]:
            nxt = out[start].pop(0)
            ring = [start]
            prev_dir = (nxt[0] - start[0], nxt[1] - start[1])
            cur = nxt
            while cur != start:
                ring.append(cur)
                pick = _leftmost(cur, prev_dir, out[cur])
                out[cur].remove(pick)
                prev_dir = (pick[0] - cur[0], pick[1] - cur[1])
                cur = pick
            rings.append(_simplify(ring))
    return rings


def _leftmost(
    cur: tuple[int, int], prev_dir: tuple[int, int], options: list[tuple[int, int]]
) -> tuple[int, int]:
    def turn(o: tuple[int, int]) -> int:
        d = (o[0] - cur[0], o[1] - cur[1])
        cross = prev_dir[0] * d[1] - prev_dir[1] * d[0]
        dot = prev_dir[0] * d[0] + prev_dir[1] * d[1]
        if cross > 0:
            return 0  # left
        if dot > 0:
            return 1  # straight
        return 2  # right

    return min(options, key=lambda o: (turn(o), o))


def _simplify(ring: list[tuple[int, int]]) -> list[tuple[int, int]]:
    changed = True
    pts = list(ring)
    while changed and len(pts) > 3:
        changed = False
        n = len(pts)
        for i in range(n):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
            if (a[0] == b[0] == c[0]) or (a[1] == b[1] == c[1]):
                pts.pop(i)
                changed = True
                break
    return pts


# ---------------------------------------------------------------------- notches
def _outside_from_margin(
    cells: set[Cell], bbox: tuple[int, int, int, int], roots: frozenset[Cell] = frozenset()
) -> set[Cell]:
    """Unbuilt cells that reach the margin of ``bbox`` or a root (a courtyard counts as
    outside) through unbuilt cells."""
    x0, y0, x1, y1 = bbox
    start = (x0 - 1, y0 - 1)
    seen = {start} | {r for r in roots if r not in cells}
    queue = deque(seen)
    while queue:
        x, y = queue.popleft()
        for dx, dy in _NB:
            n = (x + dx, y + dy)
            if (
                n not in seen
                and x0 - 1 <= n[0] <= x1 + 1
                and y0 - 1 <= n[1] <= y1 + 1
                and n not in cells
            ):
                seen.add(n)
                queue.append(n)
    return seen


def _bbox(cells: set[Cell]) -> tuple[int, int, int, int]:
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    return min(xs), min(ys), max(xs), max(ys)


def _notch_cells(cells: set[Cell], outside: set[Cell]) -> set[Cell]:
    return {
        (x, y)
        for x, y in outside
        if ((x - 1, y) in cells and (x + 1, y) in cells)
        or ((x, y - 1) in cells and (x, y + 1) in cells)
    }


def _components(cs: set[Cell]) -> list[set[Cell]]:
    left, comps = set(cs), []
    for c in sorted(cs):
        if c not in left:
            continue
        comp, queue = {c}, deque([c])
        left.discard(c)
        while queue:
            x, y = queue.popleft()
            for dx, dy in _NB:
                n = (x + dx, y + dy)
                if n in left:
                    left.discard(n)
                    comp.add(n)
                    queue.append(n)
        comps.append(comp)
    return comps


def _connected(cells: set[Cell]) -> bool:
    if not cells:
        return True
    first = min(cells)
    seen, queue = {first}, deque([first])
    while queue:
        x, y = queue.popleft()
        for dx, dy in _NB:
            n = (x + dx, y + dy)
            if n in cells and n not in seen:
                seen.add(n)
                queue.append(n)
    return len(seen) == len(cells)


def _remove_notches(
    cells: set[Cell], protected: frozenset[Cell], roots: frozenset[Cell]
) -> tuple[set[Cell], int, int]:
    """Fill or cut every notch narrower than 2 cells. A cell filled is never cut later and
    a cell cut is never filled later, so the loop cannot oscillate."""
    filled: set[Cell] = set()
    cut: set[Cell] = set()
    bbox = _bbox(cells)
    for _ in range(_MAX_ROUNDS):
        outside = _outside_from_margin(cells, bbox, roots)
        changed = False
        for comp in _components(_notch_cells(cells, outside)):
            fill_ok = not comp & cut and _fill_keeps_outside(cells, comp, bbox, outside, roots)
            walls = [w for w in _cut_walls(cells, comp, protected) if not w & filled]
            best_wall = min(walls, key=lambda w: (len(w), sorted(w)), default=None)
            if best_wall is not None and (not fill_ok or len(best_wall) < len(comp)):
                trial = cells - best_wall
                if _connected(trial):
                    cells = trial
                    cut |= best_wall
                    changed = True
                    break  # the outside changed: measure again
            if fill_ok:
                cells = cells | comp
                filled |= comp
                changed = True
                break
        if not changed:
            break
    return cells, len(filled), len(cut)


def _fill_keeps_outside(
    cells: set[Cell],
    comp: set[Cell],
    bbox: tuple[int, int, int, int],
    outside: set[Cell],
    roots: frozenset[Cell],
) -> bool:
    after = _outside_from_margin(cells | comp, bbox, roots)
    return outside - comp <= after


def _cut_walls(cells: set[Cell], comp: set[Cell], protected: frozenset[Cell]) -> list[set[Cell]]:
    """Walls whose removal widens the notch: for cells sandwiched left/right, the cells to the
    left (or to the right); for cells sandwiched above/below, the cells above (or below). The
    closed end of a dead-end notch is not a wall."""
    horizontal = {c for c in comp if (c[0] - 1, c[1]) in cells and (c[0] + 1, c[1]) in cells}
    vertical = comp - horizontal
    walls: list[set[Cell]] = []
    for group, steps in ((horizontal, ((1, 0), (-1, 0))), (vertical, ((0, 1), (0, -1)))):
        for dx, dy in steps:
            wall = {(x + dx, y + dy) for x, y in group}
            if wall and not wall & protected:
                walls.append(wall)
    return walls


# ---------------------------------------------------------------------- public
def _polygons(
    rings: list[list[tuple[int, int]]], origin: Point, cell_m: float
) -> tuple[OutlinePolygon, ...]:
    def metres(ring: list[tuple[int, int]]) -> tuple[Point, ...]:
        return tuple(
            (round(origin[0] + x * cell_m, 6), round(origin[1] + y * cell_m, 6)) for x, y in ring
        )

    def signed(ring: list[tuple[int, int]]) -> int:
        n = len(ring)
        return sum(
            ring[i][0] * ring[(i + 1) % n][1] - ring[(i + 1) % n][0] * ring[i][1] for i in range(n)
        )

    exteriors = [r for r in rings if signed(r) > 0]
    holes = [r for r in rings if signed(r) < 0]
    exteriors.sort(key=lambda r: (-signed(r), r))
    out: list[OutlinePolygon] = []
    for ext in exteriors:
        mine = [h for h in holes if _ring_inside(h, ext)]
        out.append(OutlinePolygon(metres(ext), tuple(metres(h) for h in sorted(mine))))
    return tuple(out)


def _ring_inside(hole: list[tuple[int, int]], ext: list[tuple[int, int]]) -> bool:
    """Whether a hole lies in an exterior ring (even-odd test of an interior point)."""
    # Point just inside the hole's first edge midpoint, nudged off the grid lines.
    px = min(p[0] for p in hole) + 0.25
    py = min(p[1] for p in hole if p[0] == min(q[0] for q in hole)) + 0.25
    n, inside = len(ext), False
    for i in range(n):
        a, b = ext[i], ext[(i + 1) % n]
        if a[0] == b[0] and px < a[0] and min(a[1], b[1]) < py < max(a[1], b[1]):
            inside = not inside
    return inside


def outline_from_cells(
    built: set[Cell] | frozenset[Cell],
    origin: Point = (0.0, 0.0),
    cell_m: float = 0.6,
    protected: frozenset[Cell] = frozenset(),
    outside_roots: frozenset[Cell] = frozenset(),
) -> Outline:
    """Outline of ``built`` after removing notches narrower than 2 cells. ``protected`` cells
    (cores) are never cut; ``outside_roots`` (courtyard cells) count as connected outside."""
    if not built:
        return Outline((), frozenset(), 0, 0, 0, 0)
    raw = trace_rings(built)
    cells, filled, cut = _remove_notches(set(built), protected, outside_roots)
    rings = trace_rings(cells)
    return Outline(
        _polygons(rings, origin, cell_m),
        frozenset(cells),
        sum(len(r) for r in raw),
        sum(len(r) for r in rings),
        filled,
        cut,
    )
