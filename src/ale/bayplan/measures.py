"""Figures of a bay floor for ``plans.md`` and the tests (Ticket M.4, RD section 4.7)."""

from __future__ import annotations

import heapq
from collections.abc import Mapping

from ale.contracts.models import Layout, PlacedRoom
from ale.geometry.checks import share_length, solid_contact

__all__ = ["circulation_graph", "dead_end_and_reach", "group_stretches"]


def group_stretches(
    layout: Layout,
    groups: Mapping[str, str],
    transposed: bool,
    core: tuple[int, int],
    bay: int,
) -> dict[str, int]:
    """Stretches of each group along the bar: its placed rooms projected on the bar axis with
    the core segment ``core = (u0, u1)`` collapsed to zero length; gaps of at most two bays
    are merged."""
    c0, c1 = core
    cut = c1 - c0

    def squash(u: int) -> int:
        return u if u <= c0 else (c0 if u < c1 else u - cut)

    spans: dict[str, list[tuple[int, int]]] = {}
    for p in layout.rooms:
        g = groups.get(p.instance_id)
        if g is None:
            continue
        a, b = (p.rect.y, p.rect.y2()) if transposed else (p.rect.x, p.rect.x2())
        spans.setdefault(g, []).append((squash(a), squash(b)))
    out: dict[str, int] = {}
    for g, lst in spans.items():
        n = 0
        end = None
        for a, b in sorted(lst):
            if end is None or a - end > 2 * bay:
                n += 1
            end = b if end is None else max(end, b)
        out[g] = n
    return out


def circulation_graph(
    layout: Layout,
) -> tuple[list[PlacedRoom], dict[int, list[tuple[int, float]]]]:
    """Circulation rectangles and their adjacency (rectangles sharing a side of at least one
    module); the weight is the walk from centre to centre through the middle of the shared
    side, in metres."""
    circ = list(layout.circulation)
    unit = layout.grid.module_mm / 1000
    adj: dict[int, list[tuple[int, float]]] = {i: [] for i in range(len(circ))}
    for i, a in enumerate(circ):
        for j in range(i + 1, len(circ)):
            b = circ[j]
            if share_length(a.rect, b.rect) < 1:
                continue
            ca = (a.rect.x + a.rect.w / 2, a.rect.y + a.rect.h / 2)
            cb = (b.rect.x + b.rect.w / 2, b.rect.y + b.rect.h / 2)
            if a.rect.x2() == b.rect.x or b.rect.x2() == a.rect.x:
                mx: float = a.rect.x2() if a.rect.x2() == b.rect.x else a.rect.x
                lo = max(a.rect.y, b.rect.y)
                hi = min(a.rect.y2(), b.rect.y2())
                my: float = min(max(ca[1], lo), hi)
            else:
                my = float(a.rect.y2() if a.rect.y2() == b.rect.y else a.rect.y)
                lo = max(a.rect.x, b.rect.x)
                hi = min(a.rect.x2(), b.rect.x2())
                mx = float(min(max(ca[0], lo), hi))
            w = (abs(ca[0] - mx) + abs(ca[1] - my) + abs(cb[0] - mx) + abs(cb[1] - my)) * unit
            adj[i].append((j, w))
            adj[j].append((i, w))
    return circ, adj


def dead_end_and_reach(layout: Layout, min_door: int) -> tuple[float, float]:
    """``(longest dead end, longest walk from a room to the core)`` in metres. A dead end is a
    circulation rectangle with a single neighbour (its long side); the walk goes through the
    circulation from the rectangles along the solid to the rectangle each room opens on."""
    circ, adj = circulation_graph(layout)
    unit = layout.grid.module_mm / 1000
    dead = 0.0
    for i, a in enumerate(circ):
        if len(adj[i]) <= 1:
            dead = max(dead, max(a.rect.w, a.rect.h) * unit)
    dist = [float("inf")] * len(circ)
    heap: list[tuple[float, int]] = []
    for i, a in enumerate(circ):
        if any(solid_contact(a.rect, ring) >= 1 for ring in layout.footprint.solids):
            dist[i] = 0.0
            heap.append((0.0, i))
    heapq.heapify(heap)
    while heap:
        d, i = heapq.heappop(heap)
        if d > dist[i]:
            continue
        for j, w in adj[i]:
            if d + w < dist[j]:
                dist[j] = d + w
                heapq.heappush(heap, (d + w, j))
    reach = 0.0
    for p in layout.rooms:
        if p.spec_id is None:
            continue
        best = min(
            (dist[i] for i, c in enumerate(circ) if share_length(p.rect, c.rect) >= min_door),
            default=float("inf"),
        )
        if best < float("inf"):
            reach = max(reach, best)
    return dead, reach
