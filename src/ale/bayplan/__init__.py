"""Bay-first planning of office bars (Ticket M.4)."""

from __future__ import annotations

from ale.bayplan.catalogue import Shape, choose_facade_depth
from ale.bayplan.plan import BayResult, NotEligible, plan_bar

__all__ = ["BayResult", "NotEligible", "Shape", "choose_facade_depth", "plan_bar"]
