"""Snap façade partitions of an exact plan onto the bay lines (Ticket M.3, RD section 2).

The exact-plan engine sizes rooms from their areas, so façade partitions fall anywhere on the
0.60 m grid. After the seeding and the annealing, :func:`snap_layout` moves each *interior
wall* that reaches the exterior onto the nearest bay line of the building's rhythm when the
rooms on both sides stay valid: area inside the rule of the programme (-3 % / +max(3 %, 1.2 m²)),
aspect inside the limit, minimum width, and no new hard violation (``evaluate``), no
``check_layout`` problem. A wall is the set of room edges lying on one line and flanked by
rooms on both sides over the whole run (a room whose edge only partly touches the wall, a
corridor or the outline stops the wall from moving). Deterministic: walls are tried by
increasing distance, then position.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import shapely

from ale.config import AleConfig
from ale.contracts.geometry import ModuleRect
from ale.contracts.models import Layout, PlacedRoom, RoomSpec, Rulebook
from ale.geometry.blocks import Consts, aspect_ok
from ale.geometry.checks import check_layout
from ale.geometry.evaluate import evaluate, hard_codes_of
from ale.program.models import PreparedInput
from ale.stack.grid import Rhythm

__all__ = ["SnapStats", "snap_layout"]

WHY: list[str] = []
MAX_SHIFT_M = 1.2
"""A wall is never moved farther than this."""


@dataclass(frozen=True)
class SnapStats:
    walls: int = 0
    """Façade walls found."""
    already: int = 0
    """Already on a bay line (within the tolerance)."""
    moved: int = 0
    tried: int = 0


@dataclass
class _Wall:
    axis: str  # "x": vertical wall at x = pos; "y": horizontal wall at y = pos
    pos: int
    lo: int
    hi: int
    left: list[int]  # indices of rooms ending on the wall
    right: list[int]  # indices of rooms starting on the wall


def _walls(rooms: list[ModuleRect], axis: str) -> list[_Wall]:
    """Interior walls (all of them) of ``rooms`` along ``axis``."""
    out: list[_Wall] = []
    ends: dict[int, list[int]] = {}
    starts: dict[int, list[int]] = {}
    for i, r in enumerate(rooms):
        a0, a1 = (r.x, r.x2()) if axis == "x" else (r.y, r.y2())
        ends.setdefault(a1, []).append(i)
        starts.setdefault(a0, []).append(i)

    def span(i: int) -> tuple[int, int]:
        r = rooms[i]
        return (r.y, r.y2()) if axis == "x" else (r.x, r.x2())

    for pos in sorted(set(ends) & set(starts)):
        cover_l = {u for i in ends[pos] for u in range(*span(i))}
        cover_r = {u for i in starts[pos] for u in range(*span(i))}
        both = sorted(cover_l & cover_r)
        runs: list[tuple[int, int]] = []
        for u in both:
            if runs and runs[-1][1] == u:
                runs[-1] = (runs[-1][0], u + 1)
            else:
                runs.append((u, u + 1))
        for lo, hi in runs:
            left = [i for i in ends[pos] if span(i)[0] < hi and span(i)[1] > lo]
            right = [i for i in starts[pos] if span(i)[0] < hi and span(i)[1] > lo]
            whole = all(lo <= span(i)[0] and span(i)[1] <= hi for i in left + right)
            if left and right and whole:
                out.append(_Wall(axis, pos, lo, hi, left, right))
    return out


def _reaches_exterior(w: _Wall, ext: shapely.LineString) -> bool:
    """The wall touches the exterior ring at one of its ends."""
    if w.axis == "x":
        ends = [shapely.Point(w.pos, w.lo), shapely.Point(w.pos, w.hi)]
    else:
        ends = [shapely.Point(w.lo, w.pos), shapely.Point(w.hi, w.pos)]
    return any(ext.distance(p) < 1e-9 for p in ends)


def snap_layout(
    layout: Layout,
    prepared: PreparedInput,
    rulebook: Rulebook,
    config: AleConfig,
    rhythm: Rhythm,
    tol_m: float = 0.30,
) -> tuple[Layout, SnapStats]:
    """``layout`` with its façade partitions moved onto the bay lines of ``rhythm`` where the
    rooms stay valid, and the counts."""
    m = layout.grid.module_mm / 1000
    ox, oy = prepared.footprint.origin_m
    k = Consts.from_config(config)
    specs = dict(prepared.instances)
    ext = shapely.LineString(
        [(p[0], p[1]) for p in layout.footprint.exterior] + [layout.footprint.exterior[0]]
    )
    base_hard = len(_hard(layout))
    cur = layout
    stats = SnapStats()
    seen: set[tuple[str, int, int, int]] = set()
    while True:
        rects = [r.rect for r in cur.rooms]
        walls = [w for axis in ("x", "y") for w in _walls(rects, axis) if _reaches_exterior(w, ext)]
        todo = []
        found = 0
        already = 0
        for w in walls:
            origin = ox if w.axis == "x" else oy
            dist = (
                rhythm.off_bay_x(origin + w.pos * m)
                if w.axis == "x"
                else rhythm.off_bay_y(origin + w.pos * m)
            )
            found += 1
            if dist <= tol_m + 1e-9:
                already += 1
                continue
            if dist > MAX_SHIFT_M + 1e-9:
                continue
            key = (w.axis, w.pos, w.lo, w.hi)
            if key in seen:
                continue
            todo.append((dist, w.axis, w.pos, w.lo, w, origin))
        if not stats.walls:
            stats = SnapStats(found, already, 0, 0)
        todo.sort(key=lambda t: t[:4])
        progressed = False
        for _, _, _, _, w, origin in todo:
            seen.add((w.axis, w.pos, w.lo, w.hi))
            line = _nearest_line(rhythm, w.axis, origin + w.pos * m)
            if line is None:
                continue
            delta = round((line - origin) / m) - w.pos
            stats = SnapStats(stats.walls, stats.already, stats.moved, stats.tried + 1)
            cand = _shift(cur, w, delta, specs, k)
            if cand is None:
                continue
            metrics = evaluate(cand, prepared, rulebook, config)
            cand = cand.model_copy(update={"metrics": metrics})
            if len(_hard(cand)) > base_hard or check_layout(cand, prepared, config):
                continue
            base_hard = len(_hard(cand))
            cur = cand
            stats = SnapStats(stats.walls, stats.already, stats.moved + 1, stats.tried)
            progressed = True
            break  # walls changed: look again
        if not progressed:
            break
    return cur, stats


def _hard(layout: Layout) -> list[str]:
    from ale.optimize.anneal import HARD_CODES

    hard = hard_codes_of(layout.metrics, HARD_CODES)
    return [v.code for v in layout.metrics.violations if v.code in hard]


def _nearest_line(r: Rhythm, axis: str, at_m: float) -> float | None:
    lines = (
        r.bay_lines_x(at_m - MAX_SHIFT_M - 0.01, at_m + MAX_SHIFT_M + 0.01)
        if axis == "x"
        else r.bay_lines_y(at_m - MAX_SHIFT_M - 0.01, at_m + MAX_SHIFT_M + 0.01)
    )
    if not lines:
        return None
    return min(lines, key=lambda x: (abs(x - at_m), x))


def _shift(
    layout: Layout, w: _Wall, delta: int, specs: Mapping[str, RoomSpec], k: Consts
) -> Layout | None:
    """``layout`` with wall ``w`` moved by ``delta`` modules, ``None`` when a room would
    become invalid (width, aspect, area rule)."""
    rooms = list(layout.rooms)
    for i in w.left + w.right:
        p = rooms[i]
        r = p.rect
        if i in w.left:
            nr = (
                ModuleRect(x=r.x, y=r.y, w=r.w + delta, h=r.h)
                if w.axis == "x"
                else ModuleRect(x=r.x, y=r.y, w=r.w, h=r.h + delta)
            )
        else:
            nr = (
                ModuleRect(x=r.x + delta, y=r.y, w=r.w - delta, h=r.h)
                if w.axis == "x"
                else ModuleRect(x=r.x, y=r.y + delta, w=r.w, h=r.h - delta)
            )
        if nr.w < 1 or nr.h < 1:
            WHY.append("size")
            return None
        spec = specs.get(p.instance_id)
        if spec is not None:
            req = k.req(spec)
            cells = nr.area_cells()
            was = r.area_cells()
            # keep inside the rule, or at least not further out than before
            if not req.lo <= cells <= req.hi and not (
                (cells >= was and cells <= req.hi) or (cells <= was and cells >= req.lo)
            ):
                WHY.append(f"area {p.instance_id} {was}->{cells} [{req.lo},{req.hi}]")
                return None
            if min(nr.w, nr.h) < req.wmin and min(nr.w, nr.h) < min(r.w, r.h):
                WHY.append("wmin")
                return None
        if not aspect_ok(nr.w, nr.h, k.amax) and aspect_ok(r.w, r.h, k.amax):
            WHY.append("aspect")
            return None
        rooms[i] = PlacedRoom(
            instance_id=p.instance_id, spec_id=p.spec_id, rect=nr, target_area_m2=p.target_area_m2
        )
    return layout.model_copy(update={"rooms": tuple(rooms)})
