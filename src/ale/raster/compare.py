"""Cross-check of the classical and the VLM room geometry (Ticket R.7).

Rooms are matched one-to-one by IoU (Hungarian algorithm on ``1 - IoU``); a pair counts
as matched when its IoU reaches :data:`MATCH_IOU`. :func:`compare` returns the
:class:`Agreement` metrics and :meth:`Agreement.choice` applies the decision rules:

* ``"classical"``: the classical reader found >= 2 rooms and the mean IoU of the matched
  rooms is >= :data:`CONFIRM_IOU` (the VLM only confirms);
* ``"vlm"``: the classical reader found < 2 rooms, or the VLM found >= 1.5x more rooms
  with a matched mean IoU >= :data:`UNDERSEG_IOU`;
* ``"disagreement"``: otherwise (classical kept, flag ``GEOMETRY_DISAGREEMENT``).

A VLM answer without any room never replaces the classical result (``"classical"``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

import shapely

__all__ = [
    "CONFIRM_IOU",
    "MATCH_IOU",
    "MORE_ROOMS_FACTOR",
    "UNDERSEG_IOU",
    "Agreement",
    "Choice",
    "compare",
    "iou",
]

#: IoU a pair needs to count as matched.
MATCH_IOU: Final = 0.5
#: Mean IoU above which the classical rooms are confirmed.
CONFIRM_IOU: Final = 0.8
#: Mean IoU of the matched rooms needed to prefer a finer VLM segmentation.
UNDERSEG_IOU: Final = 0.6
#: The VLM must find this many times more rooms to be preferred over >= 2 classical rooms.
MORE_ROOMS_FACTOR: Final = 1.5

Choice = Literal["classical", "vlm", "disagreement"]


def iou(a: shapely.Polygon, b: shapely.Polygon) -> float:
    """Intersection over union of two polygons (0 for empty or invalid input)."""
    try:
        inter = a.intersection(b).area
        union = a.area + b.area - inter
    except Exception:
        return 0.0
    return float(inter / union) if union > 0.0 else 0.0


@dataclass(frozen=True)
class Agreement:
    """Agreement of the classical and VLM rooms of one plan."""

    n_classical: int
    n_vlm: int
    #: Matched pairs ``(classical index, vlm index, iou)``.
    pairs: tuple[tuple[int, int, float], ...]

    @property
    def matched(self) -> int:
        return len(self.pairs)

    @property
    def mean_iou(self) -> float:
        """Mean IoU of the matched pairs (0.0 when none matched)."""
        return sum(p[2] for p in self.pairs) / len(self.pairs) if self.pairs else 0.0

    @property
    def unmatched_classical(self) -> int:
        return self.n_classical - self.matched

    @property
    def unmatched_vlm(self) -> int:
        return self.n_vlm - self.matched

    def choice(self) -> Choice:
        """The decision rule of the module docstring."""
        if self.n_vlm == 0:
            return "classical"
        if self.n_classical >= 2 and self.mean_iou >= CONFIRM_IOU:
            return "classical"
        if self.n_classical < 2:
            return "vlm"
        if self.n_vlm >= MORE_ROOMS_FACTOR * self.n_classical and self.mean_iou >= UNDERSEG_IOU:
            return "vlm"
        return "disagreement"


def _hungarian(cost: list[list[float]]) -> list[int]:
    """Row -> column of a minimum-cost assignment of a matrix with rows <= columns."""
    n, m = len(cost), len(cost[0])
    inf = float("inf")
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j], way[j] = cur, j0
                if minv[j] < delta:
                    delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    assignment = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            assignment[p[j] - 1] = j - 1
    return assignment


def compare(
    classical_rooms: Sequence[shapely.Polygon], vlm_rooms: Sequence[shapely.Polygon]
) -> Agreement:
    """Match the rooms one-to-one by IoU and report the agreement."""
    nc, nv = len(classical_rooms), len(vlm_rooms)
    if nc == 0 or nv == 0:
        return Agreement(nc, nv, ())
    table = [[iou(c, v) for v in vlm_rooms] for c in classical_rooms]
    pairs: list[tuple[int, int, float]] = []
    if nc <= nv:
        for i, j in enumerate(_hungarian([[1.0 - x for x in row] for row in table])):
            pairs.append((i, j, table[i][j]))
    else:
        transposed = [[1.0 - table[i][j] for i in range(nc)] for j in range(nv)]
        for j, i in enumerate(_hungarian(transposed)):
            pairs.append((i, j, table[i][j]))
    matched = tuple(sorted(p for p in pairs if p[2] >= MATCH_IOU))
    return Agreement(nc, nv, matched)
