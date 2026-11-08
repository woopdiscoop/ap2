"""Seeded force layout of the adjacency graph (RD 3.2 section 5.1).

Positions are in footprint metres (module coordinates x module size), deterministic for a
seed: ``networkx.spring_layout`` on the graph without its AVOID edges, scaled to the
footprint bounding box; then 50 rounds of pairwise push for AVOID pairs closer than the
median pairwise distance; ``needs_facade`` rooms projected onto the nearest exterior edge
(distance weighted by the orientation preference of the edge's outward normal); ``CORE``
pinned to the rulebook core target.
"""

from __future__ import annotations

import math
import statistics

import networkx as nx  # type: ignore[import-untyped]  # no stubs in the dev extra

from ale.contracts.models import RoomSpec, Rulebook
from ale.contracts.orientation import bearing_bin, compass_bearing_deg, edge_outward_normals
from ale.guards import bounded
from ale.program.models import PreparedInput
from ale.topology.graph import AVOID, CORE

__all__ = ["AVOID_PUSH_ROUNDS", "Positions", "core_target_m", "embed"]

Positions = dict[str, tuple[float, float]]

AVOID_PUSH_ROUNDS = 50
_LOOP_BUDGET_S = 5.0
_ORIENTATION_PULL = 0.5  # distance factor 1 - 0.5·w for orientation weight w ∈ [-1, 1]


def _bbox(prepared: PreparedInput) -> tuple[float, float, float, float]:
    m = prepared.grid.module_mm / 1000
    xs = [p[0] * m for p in prepared.footprint.polygon.exterior]
    ys = [p[1] * m for p in prepared.footprint.polygon.exterior]
    return min(xs), min(ys), max(xs), max(ys)


def core_target_m(prepared: PreparedInput, rulebook: Rulebook) -> tuple[float, float]:
    """Core target in footprint metres: ``site.core_hint`` if set, else the bounding-box
    centre shifted by the rulebook ``core_offset`` (same rule as ``ale.geometry.evaluate``)."""
    x0, y0, x1, y1 = _bbox(prepared)
    hint = prepared.site.core_hint
    if hint is not None:
        ox, oy = prepared.footprint.origin_m
        return (min(max(hint[0] - ox, x0), x1), min(max(hint[1] - oy, y0), y1))
    w, h = x1 - x0, y1 - y0
    off = rulebook.core_offset
    return (x0 + w / 2 + off.dx_norm * w, y0 + h / 2 + off.dy_norm * h)


def _orientation(
    spec: RoomSpec, rulebook: Rulebook, normal: tuple[int, int], north: float
) -> float:
    b = bearing_bin(compass_bearing_deg(normal[0], normal[1], north))
    if spec.orientation_override is not None:
        return float(spec.orientation_override.get(b, 0.0))
    stats = rulebook.types.get(spec.type)
    return 0.0 if stats is None else float(stats.orientation[b])


def _project(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> tuple[float, tuple[float, float]]:
    """``(distance, foot)`` of ``p`` on segment ``ab``."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    norm = dx * dx + dy * dy
    t = 0.0 if norm == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / norm))
    fx, fy = ax + t * dx, ay + t * dy
    return math.hypot(p[0] - fx, p[1] - fy), (fx, fy)


def _push_avoid(pos: Positions, pairs: list[tuple[str, str]], box: tuple[float, ...]) -> None:
    if not pairs or len(pos) < 2:
        return
    names = sorted(pos)
    dists = [math.dist(pos[a], pos[b]) for i, a in enumerate(names) for b in names[i + 1 :]]
    median = statistics.median(dists)
    x0, y0, x1, y1 = box
    with bounded(
        max_iter=AVOID_PUSH_ROUNDS + 1,
        time_budget_s=_LOOP_BUDGET_S,
        label="avoid-push",
        on_exhaust="stop",
    ) as budget:
        for _ in range(AVOID_PUSH_ROUNDS):
            if not budget.tick():  # pragma: no cover - 50 cheap rounds
                break
            moved = False
            for a, b in pairs:
                (ax, ay), (bx, by) = pos[a], pos[b]
                d = math.hypot(bx - ax, by - ay)
                if d >= median:
                    continue
                moved = True
                if d == 0:
                    ux, uy = 1.0, 0.0
                else:
                    ux, uy = (bx - ax) / d, (by - ay) / d
                step = (median - d) / 2
                pos[a] = (min(max(ax - ux * step, x0), x1), min(max(ay - uy * step, y0), y1))
                pos[b] = (min(max(bx + ux * step, x0), x1), min(max(by + uy * step, y0), y1))
            if not moved:
                break


def embed(graph: nx.Graph, prepared: PreparedInput, rulebook: Rulebook, *, seed: int) -> Positions:
    """Seeded positions (footprint metres) of every node of ``graph``."""
    box = _bbox(prepared)
    x0, y0, x1, y1 = box
    layout_graph = nx.Graph()
    layout_graph.add_nodes_from(graph.nodes)
    layout_graph.add_edges_from(
        (a, b, {"weight": float(w)})
        for a, b, d in graph.edges(data=True)
        if d["kind"] != AVOID
        for w in (d["weight"],)
    )
    tx, ty = core_target_m(prepared, rulebook)

    def norm(v: float, a: float, b: float) -> float:
        return 0.0 if b == a else 2 * (v - a) / (b - a) - 1

    fixed = [CORE] if CORE in layout_graph else None
    start = {CORE: (norm(tx, x0, x1), norm(ty, y0, y1))} if fixed else None
    raw = nx.spring_layout(
        layout_graph, pos=start, fixed=fixed, weight="weight", seed=seed % (2**32)
    )
    xs = [float(p[0]) for p in raw.values()]
    ys = [float(p[1]) for p in raw.values()]
    lo_x, hi_x, lo_y, hi_y = min(xs), max(xs), min(ys), max(ys)

    def scale(v: float, lo: float, hi: float, a: float, b: float) -> float:
        return (a + b) / 2 if hi == lo else a + (v - lo) / (hi - lo) * (b - a)

    pos: Positions = {
        str(n): (scale(float(p[0]), lo_x, hi_x, x0, x1), scale(float(p[1]), lo_y, hi_y, y0, y1))
        for n, p in raw.items()
    }
    avoid = sorted(
        (a, b) if a <= b else (b, a) for a, b, k in graph.edges(data="kind") if k == AVOID
    )
    _push_avoid(pos, avoid, box)

    specs = dict(prepared.instances)
    m = prepared.grid.module_mm / 1000
    poly = prepared.footprint.polygon
    edges = [((a[0] * m, a[1] * m), (b[0] * m, b[1] * m)) for a, b in poly.edges()]
    normals = edge_outward_normals(poly)
    north = prepared.site.north_angle_deg
    for name in list(pos):
        spec = specs.get(name)
        if spec is None or not spec.needs_facade:
            continue
        best: tuple[float, tuple[float, float]] | None = None
        for (a, b), normal in zip(edges, normals, strict=True):
            dist, foot = _project(pos[name], a, b)
            score = dist * (1 - _ORIENTATION_PULL * _orientation(spec, rulebook, normal, north))
            if best is None or score < best[0]:
                best = (score, foot)
        if best is not None:
            pos[name] = best[1]
    if CORE in pos:
        pos[CORE] = (tx, ty)
    return pos
