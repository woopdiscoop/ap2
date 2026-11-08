# Ticket 3.4 — Optimiser & generate · Evaluation
Fixtures via `prepare_input` (P8/site_rect_small, P25/site_rect, P60/site_L, test rulebook). Tests may lower
`optimizer.time_budget_s` / `max_iter` through `AleConfig.model_copy(update=…)` to keep CI fast.

| ID | Test | Pass condition |
|---|---|---|
| O01 | moves_valid | 2 000 random move applications (seeded) on the seeded P25 plan: every non-None result passes the contract validators and `check_against`; each move type G1–G7 is applied at least once. |
| O02 | moves_semantics | Hand plans check: G1 swaps exactly two rooms of one zone; G6 flips stacks; G7 split then merge returns an equal multiset of bays per piece. |
| O03 | improves | For P8, P25, P60: `final_cost ≤ initial_cost` (budget 10 s each); best layout passes `check_layout`. |
| O04 | deterministic | Same seed twice (fresh processes, budget by `max_iter=500` not time) → identical plans. |
| O05 | budget | P60 with `time_budget_s=30` stops within 31 s; `stopped_by` reported. |
| O06 | metropolis | Unit test with a stub energy: uphill acceptance frequency at fixed T matches `exp(−Δ/T)` within 3 σ over 10 000 trials. |
| O07 | generate_cli | `ale generate` on P25 (xlsx from `program_to_xlsx`, site.yaml, test rulebook) with `--variants 3 --seed 1` and a small budget → exit 0; 3 variant folders each with the 4 export files; `summary.md` lists 3 variants. |
| O08 | generate_errors | Invalid workbook → exit 1 with French issue lines; nothing written to `--out` except nothing (folder not created). |
| O09 | variants_distinct | 3 variants of P25 → at least 2 distinct final plans. |
| O10 | gates | ruff, ruff format, mypy strict; coverage of `ale.optimize` ≥ 90 %; lock --check; whole suite (stub list updated). |
