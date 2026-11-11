"""Metrics and ranking of the candidate forms (Ticket G.3, RD section 5)."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from ale.form.grow import CIRC_ID, COURT, FormResult
from ale.form.outline import Outline
from ale.topology.cellgrow import FREE, OUTSIDE

__all__ = ["FormMetrics", "compute_metrics", "rank_key"]


@dataclass(frozen=True)
class FormMetrics:
    coverage: float  # built cells / buildable cells
    footprint_m2: float
    facade_m: float  # length of the outline facing outside (party walls excluded)
    compactness: float  # perimeter / (4 sqrt(area))
    vertices: int
    courtyard: str  # "none" | "open" | "enclosed"
    courtyard_cells: int
    facade_rooms: int  # rooms that need a facade
    facade_rooms_ok: int  # ... and touch the outside
    rooms: int
    rooms_on_circulation: int
    short: int  # rooms short of their area
    circ_extra: int

    @property
    def facade_share(self) -> float:
        return self.facade_rooms_ok / self.facade_rooms if self.facade_rooms else 1.0

    @property
    def circulation_share(self) -> float:
        return self.rooms_on_circulation / self.rooms if self.rooms else 1.0

    @property
    def facade_missing(self) -> int:
        return self.facade_rooms - self.facade_rooms_ok

    @property
    def off_circulation(self) -> int:
        return self.rooms - self.rooms_on_circulation


def rank_key(m: FormMetrics) -> tuple[int, int, int, int, float]:
    """(rooms short of area, facade rooms without facade, rooms off circulation, vertices,
    compactness): lower is better."""
    return (m.short, m.facade_missing, m.off_circulation, m.vertices, round(m.compactness, 9))


def _is_outside(v: int) -> bool:
    return v in (FREE, OUTSIDE, COURT)


def courtyard_state(res: FormResult, outline: Outline) -> str:
    """``open`` (U form) when the courtyard reaches the street through unbuilt cells of the
    simplified outline, ``enclosed`` (a hole of the outline) otherwise."""
    if not res.court_cells:
        return "none"
    cells = outline.cells
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    x0, x1, y0, y1 = min(xs) - 1, max(xs) + 1, min(ys) - 1, max(ys) + 1
    start = (x0, y0)
    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if x0 <= n[0] <= x1 and y0 <= n[1] <= y1 and n not in cells and n not in seen:
                seen.add(n)
                queue.append(n)
    return "open" if any(res.xy(i) in seen for i in res.court_cells) else "enclosed"


def compute_metrics(res: FormResult, outline: Outline) -> FormMetrics:
    """Metrics of one candidate (facade, compactness and footprint on the simplified outline)."""
    area = outline.area()
    n_build = sum(res.buildable)
    built = res.built_cells()
    cells = outline.cells
    facade = 0
    for cx, cy in cells:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (cx + dx, cy + dy)
            if n not in cells and _is_outside(res.owner[res.idx(*n)]):
                facade += 1
    counts = res.counts()
    circ = len(res.rooms) - 1
    wp = res.wp
    rooms = [r for r in res.rooms if r != CIRC_ID]
    short = sum(counts[r] < res.need[r] for r in rooms)
    fac_total = fac_ok = on_circ = 0
    for k, name in enumerate(res.rooms[:-1]):
        mine = res.cells_of(k)
        touches_out = any(
            _is_outside(res.owner[m]) for i in mine for m in (i + 1, i - 1, i + wp, i - wp)
        )
        if res.needs_facade[name]:
            fac_total += 1
            fac_ok += touches_out
        on_circ += any(res.owner[m] == circ for i in mine for m in (i + 1, i - 1, i + wp, i - wp))
    return FormMetrics(
        coverage=len(built) / n_build if n_build else 0.0,
        footprint_m2=area,
        facade_m=facade * res.cell_m,
        compactness=outline.perimeter() / (4 * math.sqrt(area)) if area > 0 else 0.0,
        vertices=outline.vertices_after,
        courtyard=courtyard_state(res, outline),
        courtyard_cells=len(res.court_cells),
        facade_rooms=fac_total,
        facade_rooms_ok=fac_ok,
        rooms=len(rooms),
        rooms_on_circulation=on_circ,
        short=short,
        circ_extra=res.circ_extra,
    )
