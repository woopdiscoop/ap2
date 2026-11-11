"""Form-finding (Ticket G.3): the building's outline by cell growth on the plot."""

from __future__ import annotations

from ale.form.grow import FormResult, grow_form
from ale.form.metrics import FormMetrics, compute_metrics, rank_key
from ale.form.outline import Outline, OutlinePolygon, outline_from_cells

__all__ = [
    "FormMetrics",
    "FormResult",
    "Outline",
    "OutlinePolygon",
    "compute_metrics",
    "grow_form",
    "outline_from_cells",
    "rank_key",
]
