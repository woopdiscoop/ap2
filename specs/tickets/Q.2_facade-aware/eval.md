# Ticket Q.2 — Evaluation
| ID | Test | Pass condition |
|---|---|---|
| G801 | inner_exact | Rectangle 120 × 116 (spine X), 2 bands, connector inner; band 0 block B = [room 12 m², marker, room 12 m²], band 1 block B = [room 12 m², marker] (other blocks: marker only) → `check_layout == ()`; connector at x = 30 (`u_c` = 30), width 12; band 1's second segment is end strip; tiling exact. |
| G802 | inner_inverse | Hypothesis (150, derandomized): generate valid inner-connector layouts first (2–4 bands, markers anywhere), derive the program → realise succeeds with zero overshoot; circulation connected. |
| G803 | moves | G8/G9/G10 produce contract-valid plans (2 000 random applications); G10 round-trips start → inner → start to an equal plan when no bay moved. |
| G804 | facade_P60 | P60 (15 s, seed-3 start, same config as 3.4 O03): `NO_FACADE` count at the end ≤ 6 (Q.1 baseline: most of ≈ 19 hard breaks are NO_FACADE — report exact before/after per code). |
| G805 | no_regression | P8 final_hard = 0; P25 final_hard ≤ 6 (Q.1 baseline); 3.2 T03–T05 and all earlier tests pass. |
| G806 | gates | Whole suite, ruff, mypy strict (0 errors incl. the former A.3 ones), coverage of touched packages ≥ 90 %, lock --check (contracts 1.3.0). |
