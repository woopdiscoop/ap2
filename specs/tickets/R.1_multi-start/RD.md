# Ticket R.1 — Multi-start annealing · Requirements Document

> Context = this file, `eval.md`, `specs/design/research_roadmap.md` (item 1), `specs/tickets/Q.3_cache-and-reliability/eval_report.md`
> (budget sensitivity: P60 NO_FACADE 6–10 depending on the iteration count), `ale.optimize` (`anneal`, `polish`,
> `generate`), `ale.topology.seed_plan`. No contract changes.

## 1. Purpose
One long annealing chain is sensitive to its budget and its start. Run **K shorter chains** from different seeds with
the same total iteration budget, keep the best by `(n_hard, cost)`, then polish once. Deterministic.

## 2. Files (ownership)
`src/ale/optimize/multistart.py` (NEW), `src/ale/optimize/generate.py` (ONLY: use it), `src/ale/optimize/__init__.py`
(export), `tests/optimize/test_optimize_r1*.py`, `specs/tickets/R.1_multi-start/eval_report.md`.

## 3. API
`multi_start(prepared, rulebook, config, *, seed, starts: int = 4, max_iter: int | None = None, time_budget_s: float | None = None) -> AnnealResult`
- Start k (k = 0..K−1) uses seed `seed·1000 + k` for seeding (with `max_attempts` as in Q.3) and annealing, each with
  `max_iter // K` iterations (or `time_budget_s / K` when only a time budget is given).
- Keep the chain with the lowest `(n_hard, total_cost, k)`; run `polish` on it once; return its result with
  `starts`, the per-start `(initial_hard, final_hard, cost)` list, and `best_start`.
- `generate` uses `multi_start` with `starts = 4` by default; the per-variant time budget is unchanged (seed share as in
  Q.3, the rest split across starts).
