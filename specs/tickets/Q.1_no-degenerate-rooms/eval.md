# Ticket Q.1 — Evaluation
| ID | Test | Pass condition |
|---|---|---|
| Q101 | never_degenerate | Property test (Hypothesis 200, derandomized): random valid plans on P25/site_rect and P60/site_L → every successful realisation has **zero** AREA_UNDER/AREA_OVER/ASPECT/MIN_WIDTH violations; failures only from the documented codes. |
| Q102 | room_bay_infeasible | 6 m² room, depth 40 → `ROOM_INFEASIBLE` (E05 updated accordingly). |
| Q103 | stack_solver | Stack (6 m², 6 m², 12 m²) at D = 70 → a width exists (find it in the test by brute force over widths with the area/aspect rules) and `realize` uses a compliant one; a stack (3 m² × 5) at D = 40 → `STACK_INFEASIBLE`. |
| Q104 | inverse_still_exact | 3.3 G01–G04 and 3.3b N02–N03 still pass (zero overshoot on generated layouts). |
| Q105 | downstream | 3.2 T03–T05 pass; 3.4 O03 passes; report P8/P25/P60 initial_hard → final_hard (15 s, seed-3 starts) before/after this ticket. |
| Q106 | gates | Whole suite, ruff, mypy, coverage of ale.geometry ≥ 90 %, lock --check. |
