"""Prior of a cell diagram: the cells that carried each room type on another floor (Ticket M.3).

``grow(..., prior=...)`` lets a floor repeat the layout of the floor below: a room of type ``t``
(i) takes, on the ribbon, the positions that carried ``t`` below, (ii) starts, when it is not a
façade room, on the free prior cell of ``t`` nearest to their centroid, (iii) first takes the
prior cells of ``t`` connected to its seed, and (iv) grows towards them: the growth score gets
a bonus on cells that carried ``t`` and a penalty on cells that carried another type of the
floor. An empty prior changes nothing (every method is then a no-op).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableSequence, Sequence
from typing import Protocol

__all__ = ["W_PRIOR", "W_PRIOR_OTHER", "Prior"]

W_PRIOR = 4.0
"""Growth-score bonus on a cell that carried the room's type below."""
W_PRIOR_OTHER = 3.0
"""Growth-score penalty on a cell that carried another type present on the floor."""
FREE = -1
OUTSIDE = -2


class GridLike(Protocol):
    """The part of ``cellgrow._Grid`` the prior reads."""

    width: int
    height: int
    owner: list[int]

    def idx(self, cx: int, cy: int) -> int: ...

    def xy(self, i: int) -> tuple[int, int]: ...

    def nbrs(self, i: int) -> tuple[int, int, int, int]: ...


class Prior:
    """Prior cells (flat grid indices -> type label) and the ribbon positions per label."""

    def __init__(self, cells: dict[int, str], ribbon: dict[str, list[int]]) -> None:
        self.cells = cells
        self.ribbon = ribbon

    @classmethod
    def build(
        cls,
        prior: Mapping[tuple[int, int], str] | None,
        g: GridLike,
        ribbon_cells: Sequence[int],
    ) -> Prior:
        cells: dict[int, str] = {}
        for (px, py), label in (prior or {}).items():
            if 0 <= px < g.width and 0 <= py < g.height and g.owner[g.idx(px, py)] != OUTSIDE:
                cells[g.idx(px, py)] = label
        ribbon: dict[str, list[int]] = {}
        for pos, c in enumerate(ribbon_cells):
            if c in cells:
                ribbon.setdefault(cells[c], []).append(pos)
        return cls(cells, ribbon)

    def ribbon_span(self, label: str, used: Sequence[bool], length: int) -> list[int]:
        """Free ribbon positions that carried ``label`` below, in order (``[]``: no prior)."""
        return [p for p in self.ribbon.get(label, []) if not used[p]][:length]

    def seed(
        self,
        g: GridLike,
        label: str,
        dist_to: Callable[[int, tuple[float, float]], tuple[float, int]],
    ) -> int | None:
        """Free prior cell of ``label`` nearest to the centroid of the free ones."""
        free = [c for c, v in self.cells.items() if v == label and g.owner[c] == FREE]
        if not free:
            return None
        xs = [g.xy(c)[0] for c in free]
        ys = [g.xy(c)[1] for c in free]
        mid = (sum(xs) / len(xs) + 0.5, sum(ys) / len(ys) + 0.5)
        return min(free, key=lambda c: dist_to(c, mid))

    def prefill(
        self,
        g: GridLike,
        labels: Mapping[str, str],
        mine: Mapping[str, MutableSequence[int]],
        n_of: Mapping[str, int],
        claim: Callable[[str, int], None],
    ) -> None:
        """Each room takes the prior cells of its type connected to its first cell, nearest
        first, up to its cell count."""
        if not self.cells:
            return
        for iid, label in labels.items():
            if not mine[iid]:
                continue
            sx, sy = g.xy(mine[iid][0])
            while len(mine[iid]) < n_of[iid]:
                around = {j for c in mine[iid] for j in g.nbrs(c)}
                cand = [j for j in around if g.owner[j] == FREE and self.cells.get(j) == label]
                if not cand:
                    break
                claim(
                    iid, min(cand, key=lambda j: (abs(g.xy(j)[0] - sx) + abs(g.xy(j)[1] - sy), j))
                )

    def bonus(self, label: str, present: set[str]) -> dict[int, float]:
        """Growth-score term per cell for a room of type ``label``."""
        out: dict[int, float] = {}
        for c, v in self.cells.items():
            if v == label:
                out[c] = -W_PRIOR
            elif v in present:
                out[c] = W_PRIOR_OTHER
        return out
