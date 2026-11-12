"""Decomposition of a module footprint into rectangular pieces for the corridor grammar.

A rectangular footprint is one piece. An L-shaped footprint (6 vertices, one reflex vertex)
is cut through its reflex vertex into two rectangles: a *primary* (larger) piece and a
*secondary* piece. ``junction`` says how the corridor crosses the cut:

- ``"J1"``: the cut line is parallel to the primary's spine axis; the corridor turns the
  corner through a junction finger placed in the primary's block that faces the cut
  (``facing_block``).
- ``"J2"``: the cut line is perpendicular to the primary's spine axis; the two spines are
  collinear (both perpendicular to the cut).

Ticket G.1 (contracts 1.6.0): footprints with more than two pieces (T, U, H, comb, Z,
courtyard rings, ...) are decomposed into a *tree of pieces* (see :func:`decompose_footprint`).
``junctions`` lists one :class:`Junction` per tree edge (parent index < child index);
for one or two pieces it holds 0 or 1 junction equal to the legacy ``junction`` / ``cut`` /
``facing_block`` fields, which stay filled. Contacts between pieces that are not tree edges
are ``open_contacts`` (rooms may meet there, no corridor link is required).

Pure integer arithmetic (exact ``Fraction`` aspect ratios); no shapely.
"""

from __future__ import annotations

from fractions import Fraction
from itertools import product
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt

from ale.contracts.geometry import ModulePoint, ModulePolygon, ModuleRect

__all__ = ["MAX_PIECES", "FootprintPieces", "Junction", "Piece", "decompose_footprint"]

_CONFIG = ConfigDict(extra="forbid", frozen=True)

SpineAxis = Literal["X", "Y"]

MAX_PIECES = 12
"""Largest number of pieces a footprint may be decomposed into."""

UNSUPPORTED_MESSAGE = f"footprint cannot be decomposed into at most {MAX_PIECES} rectangles"


class Piece(BaseModel):
    """Axis-aligned rectangle of the module footprint with the axis of its spine corridor."""

    model_config = _CONFIG

    rect: ModuleRect
    spine_axis: SpineAxis


class Junction(BaseModel):
    """A tree edge between two pieces (Ticket G.1).

    ``kind``: ``"J1"`` (cut parallel to the parent's spine axis: a junction finger in the
    parent's block ``facing_block`` leads to the child) or ``"J2"`` (cut perpendicular to the
    parent's spine: collinear spines). ``cut``: endpoints of the shared segment, lower/left
    first.
    """

    model_config = _CONFIG

    parent: StrictInt
    child: StrictInt
    kind: Literal["J1", "J2"]
    cut: tuple[ModulePoint, ModulePoint]
    facing_block: Literal["A", "B"] | None


class FootprintPieces(BaseModel):
    """Result of :func:`decompose_footprint`.

    ``pieces``: root (primary) first, then in tree pre-order (a parent precedes its
    children). ``junction`` / ``cut`` / ``facing_block``: the legacy fields of the
    one-junction case (rectangle: ``NONE``; one or two pieces: the single junction; more
    than two pieces: ``NONE`` / ``None``, use ``junctions``). ``cut``: endpoints of the
    shared cut segment (lower/left endpoint first). ``facing_block``: J1 only, the block of
    the primary (``"A"`` lower/left, ``"B"`` upper/right) that faces the cut. ``junctions``:
    one per tree edge; ``open_contacts``: ``(i, j)`` piece pairs (``i < j``) that touch
    without being a tree edge.
    """

    model_config = _CONFIG

    pieces: tuple[Piece, ...]
    junction: Literal["NONE", "J1", "J2"]
    cut: tuple[ModulePoint, ModulePoint] | None
    facing_block: Literal["A", "B"] | None
    junctions: tuple[Junction, ...] = ()
    open_contacts: tuple[tuple[StrictInt, StrictInt], ...] = ()

    def children(self, parent: int) -> tuple[Junction, ...]:
        """Junctions whose parent is ``parent``, in child order."""
        return tuple(j for j in self.junctions if j.parent == parent)

    def parent_junction(self, child: int) -> Junction | None:
        """The junction leading to ``child`` (``None`` for the root)."""
        return next((j for j in self.junctions if j.child == child), None)


def _long_axis(r: ModuleRect) -> SpineAxis:
    """``"X"`` if the rectangle is at least as wide as it is high, else ``"Y"``."""
    return "X" if r.w >= r.h else "Y"


def _aspect(r: ModuleRect) -> Fraction:
    """Exact aspect ratio long/short (≥ 1)."""
    return Fraction(max(r.w, r.h), min(r.w, r.h))


def _rect(x0: int, y0: int, x1: int, y1: int) -> ModuleRect:
    return ModuleRect(x=x0, y=y0, w=x1 - x0, h=y1 - y0)


def _reflex_vertex(pts: tuple[ModulePoint, ...]) -> ModulePoint:
    """The unique reflex vertex (right turn) of a counter-clockwise L polygon."""
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i - 1]
        bx, by = pts[i]
        cx, cy = pts[(i + 1) % n]  # int-mod
        if (bx - ax) * (cy - by) - (by - ay) * (cx - bx) < 0:
            return pts[i]
    raise ValueError("L-shaped footprint without a reflex vertex")  # pragma: no cover


def _decompose_l(pts: tuple[ModulePoint, ...]) -> FootprintPieces:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    rx, ry = _reflex_vertex(pts)
    corners = {(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)}
    (mx, my) = (corners - set(pts)).pop()  # the bounding-box corner cut away by the notch
    # x / y range left over beside the notch.
    nx0, nx1 = (xmin, rx) if mx == xmax else (rx, xmax)
    ny0, ny1 = (ymin, ry) if my == ymax else (ry, ymax)

    # Horizontal cut y = ry: the band on the notch side loses the notch's x range.
    if my == ymax:
        h_pair = (_rect(xmin, ymin, xmax, ry), _rect(nx0, ry, nx1, ymax))
    else:
        h_pair = (_rect(nx0, ymin, nx1, ry), _rect(xmin, ry, xmax, ymax))
    # Vertical cut x = rx: the band on the notch side loses the notch's y range.
    if mx == xmax:
        v_pair = (_rect(xmin, ymin, rx, ymax), _rect(rx, ny0, xmax, ny1))
    else:
        v_pair = (_rect(xmin, ny0, rx, ny1), _rect(rx, ymin, xmax, ymax))

    h_cost = max(_aspect(r) for r in h_pair)
    v_cost = max(_aspect(r) for r in v_pair)
    horizontal = h_cost <= v_cost  # tie → horizontal
    a, b = h_pair if horizontal else v_pair

    primary, secondary = sorted((a, b), key=lambda r: (-r.area_cells(), r.y, r.x))
    secondary_axis: SpineAxis = "Y" if horizontal else "X"  # perpendicular to the cut line
    # A square primary takes the axis perpendicular to the cut (orientation-independent).
    primary_axis = secondary_axis if primary.w == primary.h else _long_axis(primary)

    cut: tuple[ModulePoint, ModulePoint]
    if horizontal:
        cut = ((max(a.x, b.x), ry), (min(a.x2(), b.x2()), ry))
    else:
        cut = ((rx, max(a.y, b.y)), (rx, min(a.y2(), b.y2())))

    parallel = (primary_axis == "X") == horizontal
    facing: Literal["A", "B"] | None = None
    if parallel:
        on_far_edge = ry == primary.y2() if horizontal else rx == primary.x2()
        facing = "B" if on_far_edge else "A"
    kind: Literal["J1", "J2"] = "J1" if parallel else "J2"
    return FootprintPieces(
        pieces=(
            Piece(rect=primary, spine_axis=primary_axis),
            Piece(rect=secondary, spine_axis=secondary_axis),
        ),
        junction=kind,
        cut=cut,
        facing_block=facing,
        junctions=(Junction(parent=0, child=1, kind=kind, cut=cut, facing_block=facing),),
    )


# --------------------------------------------------------------------------- N pieces (G.1)


def _sign(v: int) -> int:
    return (v > 0) - (v < 0)


def _reflex_vertices(ring: tuple[ModulePoint, ...]) -> list[tuple[int, int, int, int]]:
    """Reflex vertices of a ring as ``(x, y, dx, dy)``: the vertex and the direction in which
    the extension of its horizontal edge (``dx``) / vertical edge (``dy``) enters the region.

    ``ring`` is counter-clockwise (exterior) or clockwise (hole); the region lies to the left
    of every edge, so a right turn is reflex in both cases.
    """
    n = len(ring)
    out: list[tuple[int, int, int, int]] = []
    for i in range(n):
        ax, ay = ring[i - 1]
        bx, by = ring[i]
        cx, cy = ring[(i + 1) % n]  # int-mod
        if (bx - ax) * (cy - by) - (by - ay) * (cx - bx) >= 0:
            continue
        in_dx, in_dy = _sign(bx - ax), _sign(by - ay)
        out_dx, out_dy = _sign(cx - bx), _sign(cy - by)
        # The extension continues the incoming edge past the vertex, or the outgoing edge
        # backwards past it.
        hdx = in_dx if in_dy == 0 else -out_dx
        vdy = in_dy if in_dx == 0 else -out_dy
        out.append((bx, by, hdx, vdy))
    return out


class _Grid:
    """Compressed grid of a rectilinear region (exterior minus holes)."""

    def __init__(self, fp: ModulePolygon) -> None:
        rings = (fp.exterior, *fp.holes)
        self.xs = sorted({p[0] for r in rings for p in r})
        self.ys = sorted({p[1] for r in rings for p in r})
        self.nx, self.ny = len(self.xs) - 1, len(self.ys) - 1
        self.inside = [
            [
                self._in_ring(fp.exterior, i, j)
                and not any(self._in_ring(h, i, j) for h in fp.holes)
                for j in range(self.ny)
            ]
            for i in range(self.nx)
        ]

    def _in_ring(self, ring: tuple[ModulePoint, ...], i: int, j: int) -> bool:
        """Whether the centre of cell ``(i, j)`` lies inside ``ring`` (doubled coordinates)."""
        cx = self.xs[i] + self.xs[i + 1]
        cy = self.ys[j] + self.ys[j + 1]
        crossings = 0
        n = len(ring)
        for k in range(n):
            (x0, y0), (x1, y1) = ring[k], ring[(k + 1) % n]  # int-mod
            if x0 == x1 and 2 * min(y0, y1) < cy < 2 * max(y0, y1) and 2 * x0 > cx:
                crossings += 1
        return crossings % 2 == 1  # int-mod

    def ok(self, i: int, j: int) -> bool:
        return 0 <= i < self.nx and 0 <= j < self.ny and self.inside[i][j]


Edges = set[tuple[int, int]]


def _cuts(
    grid: _Grid, reflex: list[tuple[int, int, int, int]], choice: tuple[bool, ...]
) -> tuple[Edges, Edges]:
    """Blocked unit edges for one orientation choice (``True`` = horizontal extension).

    Returns ``(hcut, vcut)``: ``(i, j)`` in ``hcut`` blocks the edge between cells
    ``(i, j - 1)`` and ``(i, j)``; in ``vcut`` between ``(i - 1, j)`` and ``(i, j)``.
    A cut stops at the boundary or at the first earlier cut it meets.
    """
    hcut: Edges = set()
    vcut: Edges = set()
    for (x, y, dx, dy), horizontal in zip(reflex, choice, strict=True):
        a, b = grid.xs.index(x), grid.ys.index(y)
        if horizontal:
            i = a if dx > 0 else a - 1
            while grid.ok(i, b - 1) and grid.ok(i, b):
                hcut.add((i, b))
                nxt = i + 1 if dx > 0 else i
                if (nxt, b - 1) in vcut or (nxt, b) in vcut:
                    break
                i += dx
        else:
            j = b if dy > 0 else b - 1
            while grid.ok(a - 1, j) and grid.ok(a, j):
                vcut.add((a, j))
                nxt = j + 1 if dy > 0 else j
                if (a - 1, nxt) in hcut or (a, nxt) in hcut:
                    break
                j += dy
    return hcut, vcut


def _faces(grid: _Grid, hcut: Edges, vcut: Edges) -> list[list[tuple[int, int]]]:
    """Connected components of inside cells not separated by a cut."""
    seen: set[tuple[int, int]] = set()
    faces: list[list[tuple[int, int]]] = []
    for i in range(grid.nx):
        for j in range(grid.ny):
            if not grid.inside[i][j] or (i, j) in seen:
                continue
            comp: list[tuple[int, int]] = []
            stack = [(i, j)]
            seen.add((i, j))
            while stack:
                ci, cj = stack.pop()
                comp.append((ci, cj))
                for ni, nj, blocked in (
                    (ci + 1, cj, (ci + 1, cj) in vcut),
                    (ci - 1, cj, (ci, cj) in vcut),
                    (ci, cj + 1, (ci, cj + 1) in hcut),
                    (ci, cj - 1, (ci, cj) in hcut),
                ):
                    if not blocked and grid.ok(ni, nj) and (ni, nj) not in seen:
                        seen.add((ni, nj))
                        stack.append((ni, nj))
            faces.append(comp)
    return faces


def _as_rects(grid: _Grid, faces: list[list[tuple[int, int]]]) -> list[ModuleRect] | None:
    """Faces as rectangles, or ``None`` when one is not a rectangle."""
    out: list[ModuleRect] = []
    for comp in faces:
        i0, i1 = min(c[0] for c in comp), max(c[0] for c in comp)
        j0, j1 = min(c[1] for c in comp), max(c[1] for c in comp)
        if len(comp) != (i1 - i0 + 1) * (j1 - j0 + 1):
            return None
        out.append(_rect(grid.xs[i0], grid.ys[j0], grid.xs[i1 + 1], grid.ys[j1 + 1]))
    return out


def _union(a: ModuleRect, b: ModuleRect) -> ModuleRect | None:
    """The union of ``a`` and ``b`` if it is a rectangle (they share a full side), else ``None``."""
    if a.y == b.y and a.h == b.h and (a.x2() == b.x or b.x2() == a.x):
        return _rect(min(a.x, b.x), a.y, max(a.x2(), b.x2()), a.y2())
    if a.x == b.x and a.w == b.w and (a.y2() == b.y or b.y2() == a.y):
        return _rect(a.x, min(a.y, b.y), a.x2(), max(a.y2(), b.y2()))
    return None


def _order(r: ModuleRect) -> tuple[int, int, int, int]:
    return (r.y, r.x, r.w, r.h)


def _merge(rects: list[ModuleRect]) -> list[ModuleRect]:
    """Merge neighbouring pieces whose union is a rectangle (lowest pair first)."""
    rects = sorted(rects, key=_order)
    while True:
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                u = _union(rects[i], rects[j])
                if u is not None:
                    keep = [r for k, r in enumerate(rects) if k not in (i, j)]
                    rects = sorted([*keep, u], key=_order)
                    break
            else:
                continue
            break
        else:
            return rects


def _contact(a: ModuleRect, b: ModuleRect) -> tuple[ModulePoint, ModulePoint] | None:
    """Shared boundary segment of two disjoint rectangles (lower/left first), or ``None``."""
    if a.x2() == b.x or b.x2() == a.x:
        x = a.x2() if a.x2() == b.x else a.x
        lo, hi = max(a.y, b.y), min(a.y2(), b.y2())
        return ((x, lo), (x, hi)) if hi > lo else None
    if a.y2() == b.y or b.y2() == a.y:
        y = a.y2() if a.y2() == b.y else a.y
        lo, hi = max(a.x, b.x), min(a.x2(), b.x2())
        return ((lo, y), (hi, y)) if hi > lo else None
    return None


def _decompose_tree(fp: ModulePolygon, solid_aware: bool = False) -> FootprintPieces:
    """Cut at the reflex vertices into rectangles and build the piece tree (G.1).

    Every reflex vertex is resolved by extending one of its two edges through the region
    (to the boundary or to an earlier cut); all ``2^r`` orientation choices are tried. The
    winner minimises, in order: the number of pieces (after merging neighbours whose union
    is a rectangle), the number of J2 junctions (wings hang off the spine they grow from),
    the largest piece aspect ratio (long / short; the wing-likeness measure used for L
    shapes), and the sorted ``(y, x, w, h)`` tuples of the pieces.
    """
    grid = _Grid(fp)
    reflex = [v for ring in (fp.exterior, *fp.holes) for v in _reflex_vertices(ring)]
    reflex.sort(key=lambda v: (v[1], v[0]))
    if len(reflex) > MAX_PIECES:
        raise ValueError(UNSUPPORTED_MESSAGE)
    cands: list[tuple[tuple[object, ...], FootprintPieces]] = []
    for choice in product((True, False), repeat=len(reflex)):
        hcut, vcut = _cuts(grid, reflex, choice)
        rects0 = _as_rects(grid, _faces(grid, hcut, vcut))
        if rects0 is None:  # pragma: no cover - every reflex vertex is resolved
            continue
        rects = _merge(rects0)
        if len(rects) > MAX_PIECES:
            continue
        for flip in (False, True) if solid_aware else (False,):
            got = _tree(rects, flip, solid_aware)
            n_j2 = sum(j.kind == "J2" for j in got.junctions)
            asp = max(_aspect(r) for r in rects)
            order = tuple(sorted(_order(r) for r in rects))
            key = (
                (len(rects), not _spans_short_side(got.pieces[0].rect, fp), -got.pieces[0].rect.area_cells(), not flip, -n_j2, asp, order)
                if solid_aware
                else (len(rects), n_j2, asp, order)
            )
            cands.append((key, got))
    if not cands:
        raise ValueError(UNSUPPORTED_MESSAGE)
    cands.sort(key=lambda t: t[0])
    return cands[0][1]


def _spans_short_side(r: ModuleRect, fp: ModulePolygon) -> bool:
    """Whether ``r`` crosses the whole bounding box of ``fp`` in the box's short direction
    (a *wing* of a bar: the cross-section piece, as opposed to a strip along the bar)."""
    xs = [p[0] for p in fp.exterior]
    ys = [p[1] for p in fp.exterior]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    return r.h == h if w >= h else r.w == w


def _level(parent: dict[int, int], i: int) -> int:
    """Depth of piece ``i`` in the parent map (the root has depth 0)."""
    d = 0
    while i in parent:
        i = parent[i]
        d += 1
    return d


def _tree(rects: list[ModuleRect], flip_root: bool = False, deep_parents: bool = False) -> FootprintPieces:
    """Spanning tree of the contact graph rooted at the largest piece (BFS), pre-order."""
    n = len(rects)
    contact: dict[tuple[int, int], tuple[ModulePoint, ModulePoint]] = {}
    for i in range(n):
        for j in range(i + 1, n):
            seg = _contact(rects[i], rects[j])
            if seg is not None:
                contact[(i, j)] = seg
    root = min(range(n), key=lambda i: (-rects[i].area_cells(), rects[i].y, rects[i].x))
    by_pos = sorted(range(n), key=lambda i: (rects[i].y, rects[i].x))
    parent: dict[int, int] = {}
    queue = [root]
    seen = {root}
    while queue:
        cur = queue.pop(0)
        for nb in by_pos:
            if nb not in seen and (min(cur, nb), max(cur, nb)) in contact:
                seen.add(nb)
                parent[nb] = cur
                queue.append(nb)
    if deep_parents:
        # A J2 child must follow its parent's spine band: hang each piece on the deepest of
        # the pieces of the previous tree level it touches (a thin strip pins the band to
        # the outline), lowest-leftmost on ties.
        level = {root: 0}
        for c in sorted(parent, key=lambda i: _level(parent, i)):
            level[c] = level[parent[c]] + 1
        for c in parent:
            near = [
                q
                for q in by_pos
                if level.get(q) == level[c] - 1 and (min(c, q), max(c, q)) in contact
            ]
            parent[c] = max(near, key=lambda q: min(rects[q].w, rects[q].h))
    kids: dict[int, list[int]] = {i: [] for i in range(n)}
    for c, p in parent.items():
        kids[p].append(c)
    for lst in kids.values():
        lst.sort(key=lambda i: (rects[i].y, rects[i].x))
    pre: list[int] = []
    stack = [root]
    while stack:
        cur = stack.pop()
        pre.append(cur)
        stack.extend(reversed(kids[cur]))
    index = {old: new for new, old in enumerate(pre)}
    root_axis = _long_axis(rects[root])
    if flip_root:
        root_axis = "Y" if root_axis == "X" else "X"
    axis: dict[int, SpineAxis] = {root: root_axis}
    junctions: list[Junction] = []
    for old in pre[1:]:
        p = parent[old]
        cut = contact[(min(p, old), max(p, old))]
        horizontal = cut[0][1] == cut[1][1]
        axis[old] = "Y" if horizontal else "X"  # perpendicular to the cut
        parallel = (axis[p] == "X") == horizontal
        facing: Literal["A", "B"] | None = None
        if parallel:
            on_far = cut[0][1] == rects[p].y2() if horizontal else cut[0][0] == rects[p].x2()
            facing = "B" if on_far else "A"
        junctions.append(
            Junction(
                parent=index[p],
                child=index[old],
                kind="J1" if parallel else "J2",
                cut=cut,
                facing_block=facing,
            )
        )
    tree_edges = {(min(j.parent, j.child), max(j.parent, j.child)) for j in junctions}
    opened = sorted(
        e
        for e in {(min(index[a], index[b]), max(index[a], index[b])) for a, b in contact}
        if e not in tree_edges
    )
    only = junctions[0] if len(junctions) == 1 else None
    return FootprintPieces(
        pieces=tuple(Piece(rect=rects[old], spine_axis=axis[old]) for old in pre),
        junction=only.kind if only else "NONE",
        cut=only.cut if only else None,
        facing_block=only.facing_block if only else None,
        junctions=tuple(sorted(junctions, key=lambda j: (j.parent, j.child))),
        open_contacts=tuple(opened),
    )


def decompose_footprint(fp: ModulePolygon) -> FootprintPieces:
    """Decompose a module footprint into a tree of rectangular pieces.

    Rectangle: one piece, spine along the long axis (tie → ``"X"``). L: cut through the
    reflex vertex, horizontally or vertically, minimising the larger of the two pieces'
    aspect ratios (tie → horizontal); primary = larger area (tie → smaller ``(y, x)``
    origin) with its spine on its long axis (square → perpendicular to the cut line);
    secondary spine perpendicular to the cut line. Any other rectilinear footprint (more
    vertices, or with courtyard holes, Ticket G.1): cut at the reflex vertices into
    rectangles (fewest pieces, then fewest J2 junctions, then smallest largest aspect, then
    the sorted piece tuples),
    build the contact graph, take the BFS spanning tree from the largest piece (ties:
    lowest-leftmost; neighbours in ``(y, x)`` order) with pieces numbered in pre-order; each
    tree edge is a :class:`Junction` classified as for an L (cut parallel to the parent's
    spine: J1, perpendicular: J2) and a child's spine is perpendicular to its cut. Contacts
    outside the tree are ``open_contacts``. Raises ``ValueError`` when more than
    :data:`MAX_PIECES` pieces are needed. Ticket M.2 (contracts 1.7.0): ``solids`` are treated
    as holes (a ring of pieces around a central core is the expected figure).
    """
    solid_aware = bool(fp.solids)
    if fp.solids:
        fp = ModulePolygon(exterior=fp.exterior, holes=(*fp.holes, *fp.solids))
    pts = fp.exterior
    if len(pts) == 4 and not fp.holes:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        rect = _rect(min(xs), min(ys), max(xs), max(ys))
        return FootprintPieces(
            pieces=(Piece(rect=rect, spine_axis=_long_axis(rect)),),
            junction="NONE",
            cut=None,
            facing_block=None,
        )
    if len(pts) == 6 and not fp.holes:
        return _decompose_l(pts)
    return _decompose_tree(fp, solid_aware)
