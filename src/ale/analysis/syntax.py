"""Space-syntax measures of a layout (Ticket R.3): justified graph, depth, integration,
control and walking distance from the entrance.

Graph (RD R.3 §2): one node per room, one ``CIRC`` node per connected circulation component
(``CIRC`` when there is one, ``CIRC#1``, ``CIRC#2``… otherwise) and ``ENTRANCE``. A room is
linked to a circulation component when it shares at least ``c`` modules (a door fits) with
one of its rectangles; two rooms are linked only when a REQUIRED adjacency exists between
their specs and they share at least ``c`` modules. ``ENTRANCE`` is linked to every
circulation component touching the site's access edge, else to the component of the nearest
circulation rectangle (``entrance_inferred``).

Walking distances are exact (``Fraction``): inside a circulation rectangle one walks to its
centreline (the axis parallel to its longer side; horizontal for a square), along it, then
off it to the target; one passes from a rectangle to the next through the midpoint of their
common boundary. The entrance point is the midpoint of the longest contact between a
circulation rectangle and the access edge (first rectangle on ties) or, when inferred, the
point of the nearest circulation rectangle closest to the middle of the access edge.
Everything is deterministic (sorted ids) and pure.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations

import networkx as nx  # type: ignore[import-untyped]  # no stubs in the dev extra

from ale.contracts.config import AleConfig
from ale.contracts.enums import MacroZone
from ale.contracts.geometry import ModuleRect
from ale.contracts.models import Layout, PlacedRoom, RoomSpec
from ale.geometry.blocks import Consts
from ale.geometry.checks import share_length
from ale.program.models import PreparedInput

__all__ = [
    "CIRC",
    "ENTRANCE",
    "NodeMeasures",
    "RoomSyntax",
    "SyntaxAnalysis",
    "SyntaxGraph",
    "analyse",
    "build_graph",
    "measures",
]

ENTRANCE = "ENTRANCE"
CIRC = "CIRC"

Pt = tuple[Fraction, Fraction]
_Key = tuple[str, str, int]
_HALF = Fraction(1, 2)
_ENTRY: _Key = ("E", "", 0)


# --------------------------------------------------------------------------- results


@dataclass(frozen=True)
class NodeMeasures:
    """Measures of one graph node (``None`` = undefined: unreachable or too small a graph)."""

    depth: int | None
    mean_depth: Fraction | None
    relative_asymmetry: Fraction | None
    integration: Fraction | None
    control: Fraction


@dataclass(frozen=True)
class RoomSyntax:
    """Measures of one room; ``walk_m`` in metres (``None`` without a circulation door)."""

    instance_id: str
    zone: MacroZone | None
    depth: int | None
    mean_depth: Fraction | None
    relative_asymmetry: Fraction | None
    integration: Fraction | None
    control: Fraction
    walk_m: Fraction | None


@dataclass(frozen=True)
class SyntaxGraph:
    """The justified graph and what is needed to measure walks.

    ``circ_nodes[i]`` is the graph node of ``layout.circulation[i]``; ``entrance_point`` is
    in modules, on circulation rectangle ``entrance_rect`` (both ``None`` without circulation).
    """

    graph: nx.Graph
    room_ids: tuple[str, ...]
    circ_nodes: tuple[str, ...]
    entrance_point: Pt | None
    entrance_rect: int | None
    entrance_inferred: bool


@dataclass(frozen=True)
class SyntaxAnalysis:
    """Space-syntax reading of a layout (rooms in instance-id order)."""

    rooms: tuple[RoomSyntax, ...]
    nodes: Mapping[str, NodeMeasures]
    entrance_inferred: bool
    mean_depth: Fraction | None
    max_walk_m: Fraction | None
    zone_mean_depth: Mapping[MacroZone, Fraction]


# --------------------------------------------------------------------------- geometry


def _shared_mid(a: ModuleRect, b: ModuleRect) -> Pt:
    """Midpoint of the common boundary of two rectangles sharing a positive length."""
    if a.x2() == b.x or b.x2() == a.x:
        x = Fraction(a.x2() if a.x2() == b.x else a.x)
        return (x, Fraction(max(a.y, b.y) + min(a.y2(), b.y2()), 2))
    y = Fraction(a.y2() if a.y2() == b.y else a.y)
    return (Fraction(max(a.x, b.x) + min(a.x2(), b.x2()), 2), y)


def _edge_contact(r: ModuleRect, a: tuple[int, int], b: tuple[int, int]) -> tuple[int, Pt] | None:
    """``(length, midpoint)`` of the part of footprint edge ``a-b`` lying on a side of ``r``."""
    if a[1] == b[1]:
        if a[1] not in (r.y, r.y2()):
            return None
        lo, hi = max(r.x, min(a[0], b[0])), min(r.x2(), max(a[0], b[0]))
        return (hi - lo, (Fraction(lo + hi, 2), Fraction(a[1]))) if hi > lo else None
    if a[0] not in (r.x, r.x2()):
        return None
    lo, hi = max(r.y, min(a[1], b[1])), min(r.y2(), max(a[1], b[1]))
    return (hi - lo, (Fraction(a[0]), Fraction(lo + hi, 2))) if hi > lo else None


def _clamp(r: ModuleRect, p: Pt) -> Pt:
    return (
        min(max(p[0], Fraction(r.x)), Fraction(r.x2())),
        min(max(p[1], Fraction(r.y)), Fraction(r.y2())),
    )


def _manhattan(p: Pt, q: Pt) -> Fraction:
    return abs(p[0] - q[0]) + abs(p[1] - q[1])


def _centreline_dist(r: ModuleRect, p: Pt, q: Pt) -> Fraction:
    """Walk from ``p`` to ``q`` (both on ``r``) via the centreline of ``r``."""
    if p == q:
        return Fraction(0)
    if r.w >= r.h:
        cy = r.y + r.h * _HALF
        return abs(p[1] - cy) + abs(p[0] - q[0]) + abs(q[1] - cy)
    cx = r.x + r.w * _HALF
    return abs(p[0] - cx) + abs(p[1] - q[1]) + abs(q[0] - cx)


# --------------------------------------------------------------------------- graph


def _circ_components(circ: tuple[PlacedRoom, ...]) -> tuple[str, ...]:
    g = nx.Graph()
    g.add_nodes_from(range(len(circ)))
    for i, j in combinations(range(len(circ)), 2):
        if share_length(circ[i].rect, circ[j].rect) >= 1:
            g.add_edge(i, j)
    comps = sorted((sorted(c) for c in nx.connected_components(g)), key=lambda c: c[0])
    names = [CIRC] if len(comps) == 1 else [f"{CIRC}#{k + 1}" for k in range(len(comps))]
    out = [""] * len(circ)
    for name, comp in zip(names, comps, strict=True):
        for i in comp:
            out[i] = name
    return tuple(out)


def _required(a: RoomSpec | None, b: RoomSpec | None) -> bool:
    if a is None or b is None:
        return False
    return b.id in a.adjacent_to or a.id in b.adjacent_to


def build_graph(layout: Layout, prepared: PreparedInput, config: AleConfig) -> SyntaxGraph:
    """The justified graph of ``layout`` (RD R.3 §2)."""
    c = Consts.from_config(config).c
    specs = dict(prepared.instances)
    rooms = sorted(layout.rooms, key=lambda p: p.instance_id)
    circ = layout.circulation
    circ_nodes = _circ_components(circ)

    g = nx.Graph()
    g.add_node(ENTRANCE)
    g.add_nodes_from(sorted(set(circ_nodes)))
    g.add_nodes_from(p.instance_id for p in rooms)
    for p in rooms:
        for q, node in zip(circ, circ_nodes, strict=True):
            if share_length(p.rect, q.rect) >= c:
                g.add_edge(p.instance_id, node)
    for p, q in combinations(rooms, 2):
        if share_length(p.rect, q.rect) >= c and _required(
            specs.get(p.instance_id), specs.get(q.instance_id)
        ):
            g.add_edge(p.instance_id, q.instance_id)

    a, b = prepared.footprint.polygon.edges()[prepared.footprint.access_edge]
    point: Pt | None = None
    rect_index: int | None = None
    best = 0
    for i, q in enumerate(circ):
        contact = _edge_contact(q.rect, a, b)
        if contact is None:
            continue
        g.add_edge(ENTRANCE, circ_nodes[i])
        if contact[0] > best:
            best, point, rect_index = contact[0], contact[1], i
    inferred = rect_index is None
    if inferred and circ:
        mid: Pt = (Fraction(a[0] + b[0], 2), Fraction(a[1] + b[1], 2))
        rect_index = min(
            range(len(circ)), key=lambda i: (_manhattan(mid, _clamp(circ[i].rect, mid)), i)
        )
        point = _clamp(circ[rect_index].rect, mid)
        g.add_edge(ENTRANCE, circ_nodes[rect_index])
    return SyntaxGraph(
        graph=g,
        room_ids=tuple(p.instance_id for p in rooms),
        circ_nodes=circ_nodes,
        entrance_point=point,
        entrance_rect=rect_index,
        entrance_inferred=inferred,
    )


# --------------------------------------------------------------------------- measures


def measures(graph: nx.Graph, root: str = ENTRANCE) -> dict[str, NodeMeasures]:
    """Depth from ``root``, mean depth MD, RA = 2(MD - 1)/(k - 2), integration = 1/RA and
    Hillier-Hanson control of every node.

    MD and ``k`` are taken over the node's connected component; MD needs ``k >= 2``, RA
    ``k >= 3``; integration is ``None`` when RA is 0 or undefined.
    """
    depths: dict[str, int] = (
        dict(nx.single_source_shortest_path_length(graph, root)) if root in graph else {}
    )
    out: dict[str, NodeMeasures] = {}
    for node in sorted(graph.nodes):
        dist: dict[str, int] = dict(nx.single_source_shortest_path_length(graph, node))
        k = len(dist)
        md = Fraction(sum(dist.values()), k - 1) if k >= 2 else None
        ra = 2 * (md - 1) / (k - 2) if md is not None and k >= 3 else None
        control = Fraction(0)
        for n in sorted(graph.neighbors(node)):
            control += Fraction(1, int(graph.degree(n)))
        out[node] = NodeMeasures(
            depth=depths.get(node),
            mean_depth=md,
            relative_asymmetry=ra,
            integration=1 / ra if ra else None,
            control=control,
        )
    return out


def _walks(layout: Layout, sg: SyntaxGraph, c: int) -> dict[str, Fraction]:
    """Shortest walk (modules) from the entrance point to each room's corridor contact."""
    if sg.entrance_point is None or sg.entrance_rect is None:
        return {}
    circ = layout.circulation
    points: list[dict[_Key, Pt]] = [{} for _ in circ]
    points[sg.entrance_rect][_ENTRY] = sg.entrance_point
    for i, j in combinations(range(len(circ)), 2):
        if share_length(circ[i].rect, circ[j].rect) >= 1:
            mid = _shared_mid(circ[i].rect, circ[j].rect)
            points[i][("P", str(i), j)] = mid
            points[j][("P", str(i), j)] = mid
    contacts: dict[str, list[_Key]] = {}
    for p in layout.rooms:
        for i, q in enumerate(circ):
            if share_length(p.rect, q.rect) >= c:
                key: _Key = ("K", p.instance_id, i)
                points[i][key] = _shared_mid(p.rect, q.rect)
                contacts.setdefault(p.instance_id, []).append(key)
    w = nx.Graph()
    for i, q in enumerate(circ):
        w.add_nodes_from(points[i])
        for (ka, pa), (kb, pb) in combinations(points[i].items(), 2):
            d = _centreline_dist(q.rect, pa, pb)
            if not w.has_edge(ka, kb) or d < w[ka][kb]["weight"]:
                w.add_edge(ka, kb, weight=d)
    dist: dict[_Key, Fraction] = dict(nx.single_source_dijkstra_path_length(w, _ENTRY))
    out: dict[str, Fraction] = {}
    for iid, keys in contacts.items():
        reach = [Fraction(dist[k]) for k in keys if k in dist]
        if reach:
            out[iid] = min(reach)
    return out


def _mean(values: list[int]) -> Fraction | None:
    return Fraction(sum(values), len(values)) if values else None


def analyse(layout: Layout, prepared: PreparedInput, config: AleConfig) -> SyntaxAnalysis:
    """Space-syntax measures of ``layout`` (RD R.3 §3); never modifies its inputs."""
    sg = build_graph(layout, prepared, config)
    nodes = measures(sg.graph)
    walks = _walks(layout, sg, Consts.from_config(config).c)
    specs = dict(prepared.instances)
    module_mm = layout.grid.module_mm
    rooms: list[RoomSyntax] = []
    for iid in sg.room_ids:
        m = nodes[iid]
        spec = specs.get(iid)
        rooms.append(
            RoomSyntax(
                instance_id=iid,
                zone=spec.macro_zone if spec is not None else None,
                depth=m.depth,
                mean_depth=m.mean_depth,
                relative_asymmetry=m.relative_asymmetry,
                integration=m.integration,
                control=m.control,
                walk_m=walks[iid] * module_mm / 1000 if iid in walks else None,
            )
        )
    zone_mean: dict[MacroZone, Fraction] = {}
    for zone in MacroZone:
        mean = _mean([r.depth for r in rooms if r.zone is zone and r.depth is not None])
        if mean is not None:
            zone_mean[zone] = mean
    walk_values = [r.walk_m for r in rooms if r.walk_m is not None]
    return SyntaxAnalysis(
        rooms=tuple(rooms),
        nodes=nodes,
        entrance_inferred=sg.entrance_inferred,
        mean_depth=_mean([r.depth for r in rooms if r.depth is not None]),
        max_walk_m=max(walk_values) if walk_values else None,
        zone_mean_depth=zone_mean,
    )
