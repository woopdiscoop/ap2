# Ticket Q.3 · Evaluation

All quality tests use iteration/attempt budgets (§3.2) and must give identical results with and without coverage.

| ID | Test | Pass condition |
|---|---|---|
| Q301 | facade_P60 | P60 (seed-3 start, anneal seed 6, iteration budget): final `NO_FACADE ≤ 6` (Q.2's G804, now strict, no xfail). |
| Q302 | no_regression | P8 final hard 0; P25 final hard ≤ 6; P60 total hard ≤ 14. |
| Q303 | O03_strict | 3.4 O03 restored as originally written (P25 `final_hard < initial_hard`; P8 ≤ 1); the Q.1 "start ≤ 8" weakening removed. |
| Q304 | P8_seeds | P8 seeds 1–5: `final_hard ≤ 1` each. |
| Q305 | deterministic | Q301/Q302 runs repeated in fresh processes → identical canonical plan JSON; identical under `--cov`. |
| Q306 | depth_key | Unit: a 1-band rect where the old key picks exact-area shallow depths and leaves a `needs_facade` room without façade; the new key gives it façade, all area/aspect rules still met. |
| Q307 | budget_split | `generate` with `time_budget_s=8`: seed called with ≤ 2 s, anneal with ≤ 6 s; wall time per variant ≤ 9 s. |
| Q308 | invariants | Hypothesis (≥ 100 cases) over random valid plans incl. inner connectors: `check_layout == ()` for every successful realisation (3.3 §7). |
| Q309 | perf | `realize` P60 ≤ 1.0 s per call (3.3 §9) still holds; anneal throughput P25 ≥ 30 it/s (Linux, no coverage, reported). |
| Q310 | gates | ruff, format, mypy strict clean; coverage geometry/topology/optimize ≥ 90 % each incl. fastreal; lock --check; whole suite passes twice in a row (report both). |
