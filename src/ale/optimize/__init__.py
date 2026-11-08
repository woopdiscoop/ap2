"""Simulated-annealing optimiser and variant generation (Ticket 3.4).

Public API: the grammar moves (:mod:`ale.optimize.moves`), :func:`anneal` →
:class:`AnnealResult`, and :func:`generate` → :class:`GenerateResult` (seed → anneal →
export, N variants).
"""

from __future__ import annotations

from ale.optimize.anneal import HARD_CODES, AnnealResult, anneal
from ale.optimize.generate import GenerateResult, VariantResult, generate
from ale.optimize.moves import MOVE_WEIGHTS, MOVES, MoveContext, propose

__all__ = [
    "HARD_CODES",
    "MOVES",
    "MOVE_WEIGHTS",
    "AnnealResult",
    "GenerateResult",
    "MoveContext",
    "VariantResult",
    "anneal",
    "generate",
    "propose",
]
