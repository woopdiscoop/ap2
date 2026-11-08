"""Several plans in one model space: cluster walls by connectivity (native units).

Two walls are connected when their centrelines are within the gap tolerance
``max(5 m, 0.03 x drawing diagonal)``. Clusters are ordered top-left first:
by (min y descending, min x ascending).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import shapely

from ale.contracts.models import Wall
from ale.guards import bounded

__all__ = ["GAP_DIAGONAL_SHARE", "GAP_MIN_M", "cluster_walls", "gap_tolerance"]

GAP_MIN_M = 5.0
GAP_DIAGONAL_SHARE = 0.03
_TIME_BUDGET_S = 30.0

Box = tuple[float, float, float, float]


def gap_tolerance(diagonal: float, m_per_unit: float) -> float:
    """Gap tolerance in native units."""
    return max(GAP_MIN_M / m_per_unit, GAP_DIAGONAL_SHARE * diagonal)


def _find(parent: list[int], i: int) -> int:
    root = i
    with bounded(len(parent) + 1, _TIME_BUDGET_S, label="cad.cluster.find") as b:
        while parent[root] != root and b.tick():
            root = parent[root]
    while parent[i] != root:  # path compression: at most the path just walked
        parent[i], i = root, parent[i]
    return root


def cluster_walls(walls: Sequence[Wall], tol: float) -> list[list[int]]:
    """Wall-index clusters, ordered top-left first; indices ascending within a cluster."""
    n = len(walls)
    if n == 0:
        return []
    lines = [shapely.LineString(w.centerline.coords) for w in walls]
    tree = shapely.STRtree(lines)
    qi, qj = tree.query(lines, predicate="dwithin", distance=tol)
    parent = list(range(n))
    for i, j in zip(qi.tolist(), qj.tolist(), strict=True):
        if i < j:
            ri, rj = _find(parent, i), _find(parent, j)
            if ri != rj:
                parent[max(ri, rj)] = min(ri, rj)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(_find(parent, i), []).append(i)
    bounds = shapely.bounds(np.array(lines, dtype=object))

    def key(members: list[int]) -> tuple[float, float]:
        b = bounds[members]
        return (-float(b[:, 1].min()), float(b[:, 0].min()))

    return sorted(groups.values(), key=key)


def bbox_of(walls: Sequence[Wall]) -> Box:
    """Bounding box (x0, y0, x1, y1) of wall centrelines."""
    xs = [p[0] for w in walls for p in w.centerline.coords]
    ys = [p[1] for w in walls for p in w.centerline.coords]
    return (min(xs), min(ys), max(xs), max(ys))


def diagonal_of(box: Box) -> float:
    """Diagonal length of a box."""
    return math.hypot(box[2] - box[0], box[3] - box[1])
