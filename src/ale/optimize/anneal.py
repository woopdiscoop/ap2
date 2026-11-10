"""Simulated annealing over corridor plans (RD 3.4 §3, amended at review 2026-11-08).

State = a :class:`CorridorPlan`, scored lexicographically by ``(n_hard, cost)``: ``n_hard`` the
number of hard violations (:data:`HARD_CODES`), ``cost`` the ``total_cost`` of the realised
layout; a plan whose realisation fails is never accepted. Acceptance: fewer hard violations →
accept; ``Δh`` more → ``exp(-Δh / T_h)``; equal → Metropolis on cost with ``T_c``. Both
temperatures follow ``T = T0 · (T_end / T0) ** f`` with the progress fraction ``f``
(iterations / ``max_iter`` or elapsed / ``time_budget_s``, whichever is further along) and
``T_end = T0 · 1e-3``. Realisations are memoised (:class:`ale.optimize.fastreal.RealizeCache`).
Deterministic for a seed (``random.Random(seed)`` only) when ``max_iter`` binds.

Ticket Q.3 (deterministic budgets): ``anneal(..., max_iter=N)`` binds the run to ``N``
iterations before time — progress is ``iterations / N`` only, the ``T_c0`` sampling is
bounded by its proposal count only, and the wall clock is a safety net of
:data:`SAFETY_TIME_S` — so the result is the same on any machine, with or without coverage.
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
from ale.geometry.blocks import Consts
from ale.geometry.checks import exterior_contacts
from ale.geometry.evaluate import FACADE_CODES
from ale.guards import bounded
from ale.optimize.fastreal import RealizeCache
from ale.optimize.moves import MoveContext, propose
from ale.optimize.polish import polish
from ale.program.models import PreparedInput

__all__ = [
    "HARD_CODES",
    "AnnealResult",
    "Scorer",
    "accept_move",
    "anneal",
    "focus_on",
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
        "FACADE_DEPTH",
        "REQUIRED_ADJ",
        "AVOID_ADJ",
        "NO_CIRCULATION_ACCESS",
    }
)
"""Violation codes counted as hard (user decisions D1/U-2; ``FACADE_DEPTH``: Q.4)."""

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
POLISH_EVALS = 600
"""Candidates the final polish (:mod:`ale.optimize.polish`) may evaluate (Q.3)."""
POLISH_TIME_SHARE = 0.2
"""Share of a time-bound run kept for the final polish (Q.3)."""
SAFETY_TIME_S = 3600.0
"""Time cap of a run bound by an explicit ``max_iter`` (a safety net, never reached by the
quality tests: it only stops a runaway run)."""
_FALLBACK_T0 = 1.0
_END_MARGIN_S = 1.0
_END_MARGIN_SHARE = 0.03
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


def focus_on(ctx: MoveContext, layout: Layout, min_facade: int) -> MoveContext:
    """``ctx`` focused on the hard-violation rooms of ``layout``; for the façade pull (G9):
    its ``NO_FACADE`` and ``FACADE_DEPTH`` rooms (Q.4), and the rooms without
    ``needs_facade`` that have a façade contact of at least ``min_facade`` modules."""
    lacking = {
        r for v in layout.metrics.violations if v.code in FACADE_CODES for r in v.instance_ids
    }
    spare = {
        p.instance_id
        for p in layout.rooms
        if not ctx.facade.get(p.instance_id, False)
        and sum(n for n, _ in exterior_contacts(p.rect, layout.footprint)) >= min_facade
    }
    return ctx.with_focus(hard_rooms(layout)).with_no_facade(lacking).with_on_facade(spare)


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
    max_iter: int | None = None,
) -> AnnealResult:
    """Anneal from ``start`` and return the lexicographically best plan seen.

    ``max_iter`` (Q.3): when given, the run is bound by this many iterations instead of
    ``config.optimizer`` (``max_iter`` and ``time_budget_s``); time is then only a safety
    net (:data:`SAFETY_TIME_S`) and the result is deterministic for ``seed``.
    Raises ``ValueError`` when ``start`` does not realise or ``max_iter < 1``.
    """
    t_start = time.monotonic()
    opt = config.optimizer
    if max_iter is not None:
        if max_iter < 1:
            raise ValueError(f"max_iter must be >= 1, got {max_iter}")
        opt = opt.model_copy(update={"max_iter": max_iter, "time_budget_s": SAFETY_TIME_S})
    by_count = max_iter is not None
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
    min_facade = Consts.from_config(config).f
    ctx = focus_on(ctx, layout0, min_facade)

    current: tuple[CorridorPlan, int, float] = (start, hard0, cost0)
    best: tuple[Score, CorridorPlan, Layout] = ((hard0, cost0), start, layout0)
    accepted = 0
    stopped_by: Literal["max_iter", "time_budget", "converged"] = "converged"
    # Ticket Q.2: the loop now runs to the budget (see f_best below), so it stops a margin
    # early for the last realisation in flight.
    margin = min(_END_MARGIN_S, _END_MARGIN_SHARE * opt.time_budget_s)
    end_at = t_start + opt.time_budget_s - margin
    # Q.3: a time-bound loop leaves a share of the budget to the final polish.
    keep = 0.0 if by_count else POLISH_TIME_SHARE * opt.time_budget_s
    remaining = max(1e-3, end_at - keep - time.monotonic())
    # Ticket Q.2: the convergence span counts from the start of the annealing loop, not
    # from 0 — the T_c0 sampling may use up to 20 % of the budget, which otherwise left as
    # little as 5 % of the progress before a "converged" stop.
    f_best = 0.0 if by_count else (time.monotonic() - t_start) / opt.time_budget_s

    def progress(iterations: int) -> float:
        f = iterations / opt.max_iter
        if by_count:  # Q.3: the clock never steers a count-bound run
            return f
        return max(f, (time.monotonic() - t_start) / opt.time_budget_s)

    with bounded(opt.max_iter, remaining, label="anneal", on_exhaust="stop") as budget:
        while budget.tick():
            f = progress(budget.iterations)
            if f - f_best >= CONVERGED_SPAN:
                if not by_count:
                    break
                # Q.3: a count-bound run uses its whole budget: back to the best plan.
                current = (best[1], best[0][0], best[0][1])
                ctx = focus_on(ctx, best[2], min_facade)
                f_best = f
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
                ctx = focus_on(ctx, layout, min_facade)
                accepted += 1
                if (n_hard, cost) < best[0]:
                    best = ((n_hard, cost), cand, layout)
                    f_best = f
        if budget.exhausted_reason is not None:
            stopped_by = budget.exhausted_reason
        iterations = budget.iterations
    specs = dict(prepared.instances)
    plan, score, layout, _ = polish(
        best[1],
        best[0],
        best[2],
        scorer,
        specs,
        ctx,
        min_facade=min_facade,
        hard=HARD_CODES,
        max_evals=POLISH_EVALS,
        deadline=end_at,
    )
    final_hard, final_cost = score
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
