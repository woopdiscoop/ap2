# Ticket R.1 · Evaluation (deterministic iteration budgets, as in Q.3)
| ID | Test | Pass condition |
|---|---|---|
| M01 | stable_P60 | P60, total budgets {1000, 1100, 1200, 1300, 1500} iterations, starts=4: final `NO_FACADE ≤ 6` and hard ≤ 10 at **every** budget (today 6–10 / 9–13). |
| M02 | no_regression | P25 final hard ≤ 5; P8 final hard 0 for seeds 1–5. |
| M03 | deterministic | Same inputs → identical best plan in two fresh processes (plain and under coverage). |
| M04 | best_kept | Best result never worse than the best single chain it ran (asserted from the per-start list). |
| M05 | generate | `ale generate` uses 4 starts; total time per variant ≤ `time_budget_s` + 1 s; summary unchanged in format. |
| M06 | gates | ruff, format, mypy strict; coverage of `multistart.py` ≥ 95 % (path-form); lock --check; whole suite passes. |
