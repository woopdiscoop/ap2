"""Simulated annealing over corridor plans (RD 3.4 §3, amended at review 2026-11-08).

State = a :class:`CorridorPlan`, scored lexicographically by ``(n_hard, cost)``: ``n_hard`` the
number of hard violations (:data:`HARD_CODES`), ``cost`` the ``total_cost`` of the realised
layout; a plan whose realisation fails is never accepted. Acceptance: fewer hard violations →
accept; ``Δh`` more → ``exp(-Δh / T_h)``; equal → Metropolis on cost with ``T_c``. Both
temperatures follow ``T = T0 · (T_end / T0) ** f`` with the progress fraction ``f``
(iterations / ``max_iter`` or elapsed / ``time_budget_s``, whichever is further along) and
``T_end = T0 · 1e-3``. Realisations are memoised (:class:`ale.optimize.fastreal.RealizeCache`).
Deterministic for a seed (``random.Random(seed)`` only) when ``max_iter`` binds.
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
from ale.guards import bounded
from ale.optimize.fastreal import RealizeCache
from ale.optimize.moves import MoveContext, propose
from ale.program.models import PreparedInput

__all__ = [
    "HARD_CODES",
    "AnnealResult",
    "Scorer",
    "accept_move",
    "anneal",
    "hard_count",
    "hard_rooms",
    "initial_temperature",
    "metropolis_accept",
    "temperature_at",
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
"""Equal-hard uphill moves sampled from the start plan to calibrate ``T_c0``."""
T0_MAX_PROPOSALS = 250
"""Proposal cap of the ``T_c0`` sampling (keeps it deterministic and short)."""
T0_TIME_SHARE = 0.2
"""Share of the time budget the ``T_c0`` sampling may use at most."""
T_HARD0 = 0.5
"""Initial temperature of the hard-violation count."""
T_END_RATIO = 1e-3
"""``T_end / T0`` for both temperatures."""
CONVERGED_SPAN = 0.25
"""Progress span without improvement of the best that ends the run (``converged``)."""
_FALLBACK_T0 = 1.0
_CACHE_MAX = 50_000

Score = tuple[int, float]
"""``(n_hard, cost)``; compared lexicographically."""


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


def hard_rooms(layout: Layout) -> set[str]:
    """Rooms named by the hard violations of ``layout``."""
    return {r for v in layout.metrics.violations if v.code in HARD_CODES for r in v.instance_ids}


def metropolis_accept(delta: float, temperature: float, rng: random.Random) -> bool:
    """Accept if ``delta ≤ 0``, else with probability ``exp(-delta / T)`` (never ``+inf``)."""
    if math.isnan(delta) or delta == math.inf:
        return False
    if delta <= 0.0:
        return True
    if temperature <= 0.0:
        return False
    return rng.random() < math.exp(-delta / temperature)


def accept_move(
    d_hard: int, d_cost: float, t_hard: float, t_cost: float, rng: random.Random
) -> bool:
    """Lexicographic acceptance: fewer hard → yes; more hard → ``exp(-Δh/T_h)``; equal →
    Metropolis on cost with ``T_c``."""
    if d_hard < 0:
        return True
    if d_hard > 0:
        return metropolis_accept(float(d_hard), t_hard, rng)
    return metropolis_accept(d_cost, t_cost, rng)


def initial_temperature(uphill: list[float], acceptance: float) -> float:
    """``T0`` such that the median uphill ``Δ`` is accepted with probability ``acceptance``."""
    finite = [d for d in uphill if 0.0 < d < math.inf]
    if not finite:
        return _FALLBACK_T0
    p = min(max(acceptance, 1e-6), 1.0 - 1e-6)
    return statistics.median(finite) / -math.log(p)


def temperature_at(t0: float, fraction: float) -> float:
    """``T0 · (T_end / T0) ** f`` with ``T_end = T0 · 1e-3`` and ``f`` clamped to [0, 1]."""
    f = min(max(fraction, 0.0), 1.0)
    return float(t0 * T_END_RATIO**f)


class Scorer:
    """Memoised ``(n_hard, cost, layout)`` of plans (``layout`` is ``None`` if it fails)."""

    def __init__(
        self,
        prepared: PreparedInput,
        rulebook: Rulebook,
        config: AleConfig,
        *,
        seed: int,
    ) -> None:
        self.rulebook = rulebook
        self.seed = seed
        self.realizer = RealizeCache(prepared, config)
        self._cache: dict[CorridorPlan, tuple[int, float, Layout | None]] = {}

    def __call__(self, plan: CorridorPlan) -> tuple[int, float, Layout | None]:
        hit = self._cache.get(plan)
        if hit is not None:
            return hit
        real = self.realizer.realize(plan, self.rulebook, seed=self.seed)
        if real.layout is None:
            out: tuple[int, float, Layout | None] = (0, math.inf, None)
        else:
            out = (hard_count(real.layout), real.layout.metrics.total_cost, real.layout)
        if len(self._cache) >= _CACHE_MAX:
            self._cache.clear()
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
    """Anneal from ``start`` and return the lexicographically best plan seen.

    Raises ``ValueError`` when ``start`` does not realise.
    """
    t_start = time.monotonic()
    opt = config.optimizer
    scorer = Scorer(prepared, rulebook, config, seed=seed)
    hard0, cost0, layout0 = scorer(start)
    if layout0 is None:
        raise ValueError("the start plan does not realise")
    ctx = MoveContext.from_prepared(prepared)
    rng = random.Random(seed)

    # T_c0: median rule over up to T0_SAMPLES uphill cost deltas that keep n_hard equal.
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
            n_hard, cost, layout = scorer(cand)
            if layout is not None and n_hard == hard0 and cost > cost0:
                uphill.append(cost - cost0)
    t_cost0 = initial_temperature(uphill, opt.initial_acceptance)
    ctx = ctx.with_focus(hard_rooms(layout0))

    current: tuple[CorridorPlan, int, float] = (start, hard0, cost0)
    best: tuple[Score, CorridorPlan, Layout] = ((hard0, cost0), start, layout0)
    accepted = 0
    f_best = 0.0
    stopped_by: Literal["max_iter", "time_budget", "converged"] = "converged"
    remaining = max(1e-3, opt.time_budget_s - (time.monotonic() - t_start))
    with bounded(opt.max_iter, remaining, label="anneal", on_exhaust="stop") as budget:
        while budget.tick():
            f = max(
                budget.iterations / opt.max_iter,
                (time.monotonic() - t_start) / opt.time_budget_s,
            )
            if f - f_best >= CONVERGED_SPAN:
                break
            _, cand = propose(current[0], ctx, rng)
            if cand is None:
                continue
            n_hard, cost, layout = scorer(cand)
            if layout is None:
                continue
            t_hard = temperature_at(T_HARD0, f)
            t_cost = temperature_at(t_cost0, f)
            if accept_move(n_hard - current[1], cost - current[2], t_hard, t_cost, rng):
                current = (cand, n_hard, cost)
                ctx = ctx.with_focus(hard_rooms(layout))
                accepted += 1
                if (n_hard, cost) < best[0]:
                    best = ((n_hard, cost), cand, layout)
                    f_best = f
        if budget.exhausted_reason is not None:
            stopped_by = budget.exhausted_reason
        iterations = budget.iterations
    (final_hard, final_cost), plan, layout = best
    return AnnealResult(
        plan=plan,
        layout=layout,
        initial_cost=cost0,
        final_cost=final_cost,
        initial_hard=hard0,
        final_hard=final_hard,
        iterations=iterations,
        accepted=accepted,
        elapsed_s=time.monotonic() - t_start,
        stopped_by=stopped_by,
    )
