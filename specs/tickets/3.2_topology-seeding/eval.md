# Ticket 3.2 — Topology & Seeding · Evaluation

Fixtures via `prepare_input` on P8/site_rect_small, P25/site_rect, P60/site_L with `tests/program/data/rulebook_test.yaml`.

| ID | Test | Pass condition |
|---|---|---|
| T01 | graph | P25 graph: 26 nodes (25 rooms + CORE); REQUIRED edges match the expanded `adjacent_to` (count checked against the fixture); AVOID edges for `avoid`; CORE edges to every service_core room. |
| T02 | planarity | A synthetic program whose REQUIRED graph is K5 → `planar False`, `conflicts` = the 10 edges; P25 → `planar True`, `conflicts ()`. |
| T03 | **valid_P8** | `seed_plan(P8, seed=1)` → `realization.failures == ()` and `check_layout == ()`. |
| T04 | **valid_P25** | Same for P25. |
| T05 | **valid_P60** | Same for P60 within `time_budget_s=20` (measured `elapsed_s ≤ 20`). |
| T06 | seeds | For seeds 1–5 on P25: all valid; at least 2 distinct plans (canonical JSON). |
| T07 | deterministic | Same seed twice (fresh processes) → identical plan bytes. |
| T08 | never_raises | A program that cannot fit (P25 on site_rect_small) → returns the least-overflow plan with failures, `attempts ≥ 1`, no exception, within budget. |
| T09 | required_adjacency | On P25 the seeded plan's `required_adjacency` term is ≤ that of the best of 50 random valid plans generated in the test with the same contract rules (seeded). |
| T10 | beats_greedy | For each fixture, the seeded plan realises while `greedy_plan` does not (documents the improvement; if greedy ever realises, assert seeded total_cost ≤ greedy's). |
| T11 | gates | ruff, ruff format, mypy strict clean; coverage of `ale.topology` ≥ 90 % line; lock --check; whole suite passes. |
