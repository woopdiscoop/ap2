"""Simulated annealing over corridor plans (RD 3.4 §3).

State = a :class:`CorridorPlan`; energy = ``total_cost + H * n_hard`` of its realised layout
(``+inf`` when the realisation fails), ``H = optimizer.weights.required_adjacency`` and
``n_hard`` the number of hard violations (:data:`HARD_CODES`). Neighbours come from
:func:`ale.optimize.moves.propose`; acceptance is Metropolis; ``T0`` follows the median
rule; cooling is geometric. Deterministic for a seed (``random.Random(seed)`` only) as long
as the time budget is not what stops the run.
"""

from __future__ import annotations

import math
import random
import statistics
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ale.contracts.config import AleConfig
from ale.contracts.corridor_plan import CorridorPlan
from ale.contracts.models import Layout, Rulebook
from ale.geometry import realize
from ale.guards import bounded
from ale.optimize.moves import MoveContext, propose
from ale.program.models import PreparedInput

__all__ = [
    "HARD_CODES",
    "AnnealResult",
    "Energy",
    "anneal",
    "hard_count",
    "initial_temperature",
    "metropolis_accept",
]

HARD_CODES: frozenset[str] = frozenset(
    {
        "AREA_UNDER",
        "AREA_OVER",
        "ASPECT",
        "MIN_WIDTH",
        "NO_FACADE",
        "REQUIRED_ADJ",
        "AVOID_ADJ",
        "NO_CIRCULATION_ACCESS",
    }
)
"""Violation codes counted as hard (user decisions D1/U-2)."""

T0_SAMPLES = 50
"""Uphill moves sampled from the start plan to choose ``T0``."""
T0_MAX_PROPOSALS = 250
"""Proposal cap of the ``T0`` sampling (keeps it deterministic and short)."""
T0_TIME_SHARE = 0.2
"""Share of the time budget the ``T0`` sampling may use at most."""
CONVERGED_STEPS = 20
"""Temperature steps without improvement of the best that end the run."""
_FALLBACK_T0 = 1.0
_CACHE_MAX = 20_000


class AnnealResult(BaseModel):
    """Outcome of :func:`anneal`: the best plan seen and its layout."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan: CorridorPlan
    layout: Layout
    initial_cost: float
    final_cost: float
    initial_hard: int
    final_hard: int
    iterations: int
    accepted: int
    elapsed_s: float
    stopped_by: Literal["max_iter", "time_budget", "converged"]


def hard_count(layout: Layout) -> int:
    """Number of hard violations of ``layout`` (codes in :data:`HARD_CODES`)."""
    return sum(1 for v in layout.metrics.violations if v.code in HARD_CODES)


def metropolis_accept(delta: float, temperature: float, rng: random.Random) -> bool:
    """Accept if ``delta ≤ 0``, else with probability ``exp(-delta / T)`` (never ``+inf``)."""
    if math.isnan(delta) or delta == math.inf:
        return False
    if delta <= 0.0:
        return True
    if temperature <= 0.0:
        return False
    return rng.random() < math.exp(-delta / temperature)


def initial_temperature(uphill: list[float], acceptance: float) -> float:
    """``T0`` such that the median uphill ``Δ`` is accepted with probability ``acceptance``."""
    finite = [d for d in uphill if 0.0 < d < math.inf]
    if not finite:
        return _FALLBACK_T0
    p = min(max(acceptance, 1e-6), 1.0 - 1e-6)
    return statistics.median(finite) / -math.log(p)


class Energy:
    """Energy of plans, memoised: ``(energy, cost, n_hard, layout or None)``."""

    def __init__(
        self,
        prepared: PreparedInput,
        rulebook: Rulebook,
        config: AleConfig,
        *,
        seed: int,
    ) -> None:
        self.prepared = prepared
        self.rulebook = rulebook
        self.config = config
        self.seed = seed
        self.h = config.optimizer.weights.required_adjacency
        self._cache: dict[CorridorPlan, tuple[float, float, int, Layout | None]] = {}

    def __call__(self, plan: CorridorPlan) -> tuple[float, float, int, Layout | None]:
        hit = self._cache.get(plan)
        if hit is not None:
            return hit
        real = realize(self.prepared, plan, self.rulebook, self.config, seed=self.seed)
        if real.layout is None:
            out: tuple[float, float, int, Layout | None] = (math.inf, math.inf, 0, None)
        else:
            cost = real.layout.metrics.total_cost
            n_hard = hard_count(real.layout)
            out = (cost + self.h * n_hard, cost, n_hard, real.layout)
        if len(self._cache) < _CACHE_MAX:
            self._cache[plan] = out
        return out


def anneal(
    prepared: PreparedInput,
    rulebook: Rulebook,
    config: AleConfig,
    start: CorridorPlan,
    *,
    seed: int,
) -> AnnealResult:
    """Anneal from ``start`` and return the best plan seen (RD 3.4 §3).

    "Best" = lowest energy among the plans with at most the start's number of hard
    violations, so the energy never rises and ``final_hard ≤ initial_hard``. Raises
    ``ValueError`` when ``start`` does not realise.
    """
    t_start = time.monotonic()
    opt = config.optimizer
    energy = Energy(prepared, rulebook, config, seed=seed)
    e0, cost0, hard0, layout0 = energy(start)
    if layout0 is None:
        raise ValueError("the start plan does not realise")
    ctx = MoveContext.from_prepared(prepared)
    rng = random.Random(seed)

    # T0: median rule over up to T0_SAMPLES uphill moves from the start.
    uphill: list[float] = []
    with bounded(
        T0_MAX_PROPOSALS,
        opt.time_budget_s * T0_TIME_SHARE,
        label="anneal-t0",
        on_exhaust="stop",
    ) as sampling:
        while len(uphill) < T0_SAMPLES and sampling.tick():
            _, cand = propose(start, ctx, rng)
            if cand is None:
                continue
            delta = energy(cand)[0] - e0
            if 0.0 < delta < math.inf:
                uphill.append(delta)
    temperature = initial_temperature(uphill, opt.initial_acceptance)

    current, e_cur = start, e0
    best, e_best, best_layout, best_cost, best_hard = start, e0, layout0, cost0, hard0
    accepted = 0
    steps_without_gain = 0
    gained_this_step = False
    stopped_by: Literal["max_iter", "time_budget", "converged"] = "converged"
    remaining = max(1e-3, opt.time_budget_s - (time.monotonic() - t_start))
    with bounded(opt.max_iter, remaining, label="anneal", on_exhaust="stop") as budget:
        while budget.tick():
            _, cand = propose(current, ctx, rng)
            if cand is not None:
                e_new, cost, n_hard, layout = energy(cand)
                if metropolis_accept(e_new - e_cur, temperature, rng):
                    current, e_cur = cand, e_new
                    accepted += 1
                    if layout is not None and n_hard <= hard0 and e_new < e_best:
                        best, e_best, best_layout = cand, e_new, layout
                        best_cost, best_hard = cost, n_hard
                        gained_this_step = True
            if budget.iterations % opt.moves_per_temperature == 0:
                temperature *= opt.cooling
                steps_without_gain = 0 if gained_this_step else steps_without_gain + 1
                gained_this_step = False
                if steps_without_gain >= CONVERGED_STEPS:
                    break
        if budget.exhausted_reason is not None:
            stopped_by = budget.exhausted_reason
        iterations = budget.iterations
    return AnnealResult(
        plan=best,
        layout=best_layout,
        initial_cost=cost0,
        final_cost=best_cost,
        initial_hard=hard0,
        final_hard=best_hard,
        iterations=iterations,
        accepted=accepted,
        elapsed_s=time.monotonic() - t_start,
        stopped_by=stopped_by,
    )
