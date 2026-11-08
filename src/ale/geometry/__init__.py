"""Corridor-grammar realisation and evaluation (Tickets 3.3 and 3.3b: bands).

Public API: :func:`realize` (``CorridorPlan`` → ``Layout``), :func:`evaluate` (cost and
violations), :func:`check_layout` (geometric invariants) and :func:`greedy_plan` (a simple
baseline plan).
"""

from __future__ import annotations

from ale.geometry.checks import check_layout
from ale.geometry.evaluate import evaluate
from ale.geometry.greedy import greedy_plan
from ale.geometry.realize import Failure, Realization, realize

__all__ = ["Failure", "Realization", "check_layout", "evaluate", "greedy_plan", "realize"]
