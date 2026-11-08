"""Topology & seeding (Ticket 3.2): adjacency graph, seeded embedding, first valid plan.

Public API: :func:`build_graph` (program → ``networkx.Graph``), :func:`seed_plan`
(``PreparedInput`` → :class:`SeedResult` with a first valid ``CorridorPlan``) and the
:class:`TopologyReport` / :class:`SeedResult` models.
"""

from __future__ import annotations

from ale.topology.graph import TopologyReport, build_graph
from ale.topology.seed import SeedResult, seed_plan

__all__ = ["SeedResult", "TopologyReport", "build_graph", "seed_plan"]
