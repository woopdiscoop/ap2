"""Adjacency graph of a prepared program (RD 3.2 section 4) and its planarity diagnostic.

Nodes: one per room instance (attributes ``spec_id``, ``type``, ``zone``, ``area_m2``,
``needs_facade``, ``service_core``) plus the node ``CORE``. Edges carry ``kind`` (one of
``required``, ``avoid``, ``preferred``, ``core``) and ``weight``:

- REQUIRED (weight 1): ``adjacent_to`` expanded over instances, each instance of A linked to
  the instance of B nearest by index (ties → the lower index);
- AVOID (weight -1): ``avoid`` expanded over every pair of instances;
- PREFERRED (weight ``p``): rulebook pairs with ``p ≥ 0.6`` between instances of different
  types, at most 3 per node (highest ``p`` first);
- CORE (weight 1): ``CORE`` to every ``service_core`` room.

An edge already present keeps its first kind (REQUIRED, then AVOID, PREFERRED, CORE).
"""

from __future__ import annotations

from collections.abc import Sequence

import networkx as nx  # type: ignore[import-untyped]  # no stubs in the dev extra
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr

from ale.contracts.models import RoomSpec, Rulebook
from ale.contracts.taxonomy import load_taxonomy
from ale.program.models import PreparedInput

__all__ = [
    "AVOID",
    "CORE",
    "CORE_KIND",
    "PREFERRED",
    "PREFERRED_MIN_P",
    "REQUIRED",
    "TopologyReport",
    "build_graph",
    "edges_of_kind",
    "planarity",
]

CORE = "CORE"
"""Name of the service-core node."""

REQUIRED = "required"
AVOID = "avoid"
PREFERRED = "preferred"
CORE_KIND = "core"

PREFERRED_MIN_P = 0.6
"""Smallest rulebook probability that makes a PREFERRED edge."""
_PREFERRED_PER_NODE = 3

Edge = tuple[str, str]


class TopologyReport(BaseModel):
    """Graph statistics and the required adjacencies that cannot be honoured.

    ``conflicts``: REQUIRED edges of a Kuratowski subgraph (each pair sorted, list sorted),
    ``()`` when the REQUIRED graph is planar. ``unsatisfiable_required``: REQUIRED pairs whose
    rooms were seeded into blocks whose regions share no boundary of door length.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_nodes: StrictInt
    n_required: StrictInt
    n_avoid: StrictInt
    planar: StrictBool
    conflicts: tuple[tuple[StrictStr, StrictStr], ...]
    unsatisfiable_required: tuple[tuple[StrictStr, StrictStr], ...] = ()


def _pair(a: str, b: str) -> Edge:
    return (a, b) if a <= b else (b, a)


def _instances_by_spec(instances: Sequence[tuple[str, RoomSpec]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for iid, spec in instances:
        out.setdefault(spec.id, []).append(iid)
    return out


def _nearest(index: int, targets: list[str]) -> str:
    """The instance of ``targets`` nearest to 0-based ``index`` (ties → lower index)."""
    return targets[min(index, len(targets) - 1)]


def build_graph(prepared: PreparedInput, rulebook: Rulebook) -> nx.Graph:
    """The adjacency graph of ``prepared`` (see the module docstring)."""
    tax = load_taxonomy()
    graph = nx.Graph()
    instances = prepared.instances
    for iid, spec in instances:
        graph.add_node(
            iid,
            spec_id=spec.id,
            type=spec.type,
            zone=str(spec.macro_zone),
            area_m2=float(spec.target_area_m2),
            needs_facade=bool(spec.needs_facade),
            service_core=bool(tax.get(spec.type).service_core),
        )
    graph.add_node(
        CORE,
        spec_id=CORE,
        type=CORE,
        zone="",
        area_m2=0.0,
        needs_facade=False,
        service_core=False,
    )
    by_spec = _instances_by_spec(instances)

    def add(a: str, b: str, kind: str, weight: float) -> None:
        if a != b and not graph.has_edge(a, b):
            graph.add_edge(a, b, kind=kind, weight=weight)

    for kind_name in (REQUIRED, AVOID):
        for _, spec in instances:
            own = by_spec[spec.id]
            refs = spec.adjacent_to if kind_name == REQUIRED else spec.avoid
            for ref in refs:
                targets = by_spec.get(ref, [])
                if not targets:
                    continue
                for i, iid in enumerate(own):
                    if kind_name == REQUIRED:
                        add(iid, _nearest(i, targets), REQUIRED, 1.0)
                    else:
                        for other in targets:
                            add(iid, other, AVOID, -1.0)

    # PREFERRED: candidate pairs between different types, best p first, ≤ 3 per node.
    candidates: list[tuple[float, Edge]] = []
    ids = [iid for iid, _ in instances]
    types = {iid: spec.type for iid, spec in instances}
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if types[a] == types[b]:
                continue
            p = rulebook.adjacency.p(types[a], types[b])
            if p >= PREFERRED_MIN_P:
                candidates.append((p, (a, b)))
    candidates.sort(key=lambda c: (-c[0], c[1]))
    degree: dict[str, int] = {}
    for p, (a, b) in candidates:
        if degree.get(a, 0) >= _PREFERRED_PER_NODE or degree.get(b, 0) >= _PREFERRED_PER_NODE:
            continue
        if graph.has_edge(a, b):
            continue
        add(a, b, PREFERRED, p)
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1

    for iid in ids:
        if graph.nodes[iid]["service_core"]:
            add(CORE, iid, CORE_KIND, 1.0)
    return graph


def edges_of_kind(graph: nx.Graph, kind: str) -> tuple[Edge, ...]:
    """Edges of ``kind`` (each pair sorted), sorted."""
    return tuple(sorted(_pair(a, b) for a, b, k in graph.edges(data="kind") if k == kind))


def planarity(graph: nx.Graph) -> tuple[bool, tuple[Edge, ...]]:
    """``(planar, conflicts)`` of the REQUIRED subgraph; conflicts = Kuratowski edges."""
    sub = nx.Graph()
    sub.add_edges_from(edges_of_kind(graph, REQUIRED))
    planar, certificate = nx.check_planarity(sub, counterexample=True)
    if planar:
        return True, ()
    return False, tuple(sorted(_pair(a, b) for a, b in certificate.edges()))
