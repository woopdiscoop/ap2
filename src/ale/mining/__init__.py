"""Corpus mining (Ticket 2.1): room topology of extracted plans.

Public API: :func:`extract_topology` (``PlanGeometry`` → :class:`PlanTopology`) and the
:class:`Contact` model.
"""

from __future__ import annotations

from ale.mining.topology import Contact, PlanTopology, extract_topology

__all__ = ["Contact", "PlanTopology", "extract_topology"]
