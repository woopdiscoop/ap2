# Ticket Q.3 — Façade-aware depths, deterministic quality gates, budget split · Requirements Document

> **Worker brief.** Context = this file, `eval.md`, `specs/tickets/Q.2_facade-aware/eval_report.md` (read it
> first: it explains why G804 was missed), `specs/design/corridor_grammar.md`, contracts 1.3.0, and the code of
> `ale.geometry`, `ale.topology`, `ale.optimize`. Do not modify contracts (`lock --check` must pass).

## 1. Purpose
Q.2 left three problems:
1. P60 still ends with ~10 `NO_FACADE`. The realiser picks block depths that give
   exact-area offices, which are wide and shallow, so the exterior frontage holds about 30 offices. Deeper
   exterior blocks with narrower bays (still inside the area and aspect rules) would fit more.
2. Quality gates (3.4 O03, Q.2 G805) run on a wall-clock budget, so they depend on machine load and
   coverage tracing. G805 passed alone and failed in a loaded full-suite run, and it is xfailed under coverage, so CI never
   enforces it. The P25 O03 gate was weakened in Q.1 to "start ≤ 8".
3. `ale generate` gives the seeder a fixed budget (`SEED_TIME_BUDGET_S`) regardless of the total.

## 2. Files (ownership)
`src/ale/geometry/**`, `src/ale/topology/**`, `src/ale/optimize/**`, `tests/geometry/**`, `tests/topology/**`,
`tests/optimize/**`, `specs/tickets/Q.3_cache-and-reliability/eval_report.md`. Nothing else.

## 3. Changes
1. **Façade-aware depth criterion (realiser).** In the block/band depth search (3.3 §5.1, 3.3b), add, as the
   **first** key after `n_failures`, the number of `needs_facade` rooms that would end with exterior contact
   `< f` (computed from the candidate geometry, cheaply: a room bay in an exterior block has façade = its
   width; a stack room has façade only if outermost and the stack is in an exterior block). Keep the rest of the key
   unchanged. In room-bay width selection (§5.2), when the bay is in an exterior block and holds a
   `needs_facade` room, prefer the **smallest** width satisfying the area and aspect rules. Document the new key
   in the module docstring and in 3.3 RD §5.1 is *not* yours to edit: put the amendment text in the eval report;
   the Router will apply it.
2. **Deterministic budgets.** `seed_plan(..., max_attempts: int | None = None)` and the existing
   `anneal` `max_iter`: when given, they bind before time (keep a generous time cap as a safety net). The
   quality tests (O03 strict as originally specified, including **P25 `final_hard < initial_hard`**; G804; G805)
   use iteration and attempt budgets, so they give the same result on any machine, with or without coverage. Remove the
   coverage xfail from G805. Pick budgets so that each quality test runs in ≤ 60 s without coverage on one core.
3. **Budget split in `generate`.** Seed budget = `min(SEED_TIME_BUDGET_S, 0.25 × optimizer.time_budget_s)`;
   anneal gets the remainder (pass an `AleConfig` copy with the reduced `time_budget_s`). Total per variant
   ≤ `time_budget_s` + 1 s.
4. **fastreal.** Bring `ale.optimize.fastreal` line coverage to ≥ 90 % (tests), or fold its cache into
   `ale.geometry` if simpler. The memoised result must equal `realize` exactly (existing tests).
5. **P8.** `final_hard ≤ 1` for seeds 1–5 (iteration budget).

## 4. Out of scope
Contracts, the seed rulebook switch (awaits the architect), CLI flags beyond §3.3.
