"""Frozen-output helper of eval N01 (Ticket G.1): rectangles and L shapes decompose as before.

Uses only what exists since contracts 1.0.0 / A.1, so it also runs against the base commit of
G.1 (``bf798b6``), where the pinned digest was computed.
"""

from __future__ import annotations

import hashlib
import json

from ale.contracts.footprint import decompose_footprint
from ale.contracts.geometry import ModulePolygon

Pts = tuple[tuple[int, int], ...]

L_SHAPES: tuple[Pts, ...] = (
    ((0, 0), (480, 0), (480, 180), (300, 180), (300, 300), (0, 300)),  # J2 (site_L)
    ((0, 0), (600, 0), (600, 120), (200, 120), (200, 300), (0, 300)),  # J1
)


def _transforms(pts: Pts) -> list[Pts]:
    """The 8 axis symmetries of ``pts`` as counter-clockwise rings starting at the lowest-left
    vertex."""
    out: list[Pts] = []
    for flip in (False, True):
        for rot in range(4):
            cur = [(-x, y) if flip else (x, y) for x, y in pts]
            for _ in range(rot):
                cur = [(-y, x) for x, y in cur]
            if flip:
                cur.reverse()  # reflection reverses the orientation
            lo = min(range(len(cur)), key=lambda i: (cur[i][1], cur[i][0]))
            cur = cur[lo:] + cur[:lo]
            out.append(tuple(cur))
    return out


def shapes() -> list[Pts]:
    """Rectangles (wide, tall, square) and the L shapes in all 8 orientations."""
    rects: list[Pts] = [
        ((0, 0), (240, 0), (240, 180), (0, 180)),
        ((10, 20), (110, 20), (110, 320), (10, 320)),
        ((0, 0), (200, 0), (200, 200), (0, 200)),
    ]
    ls = [pts for base in L_SHAPES for pts in _transforms(base)]
    ls += _transforms(((0, 0), (300, 0), (300, 150), (150, 150), (150, 300), (0, 300)))  # square
    ls += _transforms(((0, 0), (400, 0), (400, 100), (100, 100), (100, 400), (0, 400)))
    return [*rects, *ls]


def decomposition_digest() -> str:
    """SHA-256 of the pieces / junction / cut / facing block of every shape."""
    rows = []
    for pts in shapes():
        d = decompose_footprint(ModulePolygon(exterior=pts))
        rows.append(
            [
                [[p.rect.x, p.rect.y, p.rect.w, p.rect.h, p.spine_axis] for p in d.pieces],
                d.junction,
                d.cut,
                d.facing_block,
            ]
        )
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
