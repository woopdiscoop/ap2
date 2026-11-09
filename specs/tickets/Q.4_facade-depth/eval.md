# Ticket Q.4 · Evaluation

| ID | Test | Pass condition |
|---|---|---|
| D01 | contract | contracts 1.4.0; `max_depth_m` default None; old configs load unchanged; lock --check OK; schemas regenerated. |
| D02 | off_by_default | With `max_depth_m` None: byte-identical layouts to before on P8/P25/P60 (seeded, iteration budgets of Q.3). |
| D03 | violation | Unit: a 9.6 m-deep office with max 7.2 → one `FACADE_DEPTH`; a through room 12 m deep with façades on both sides → none; module 600: limit = 12 modules. |
| D04 | big_room | A 160 m² `needs_facade` room, max 7.2, amax 2: realised with depth ≤ 7.2; its aspect > 2 is reported but not hard; `n_hard` excludes it. |
| D05 | AREP floor | The AREP-MS top-floor demo programme rebuilt synthetically in the test (16 lines, 649 m²: one 160 m² office, one 80 m² office, one 60 m², others 4–31 m²; 54 × 15.6 m bar; module 600; area 0/+10 %; max 7.2): final `FACADE_DEPTH = 0`, `NO_FACADE ≤ 1` (iteration budget). |
| D06 | no_regression | Q.3 quality tests (Q301–Q304) still pass with the rule off. |
| D07 | gates | ruff, format, mypy strict; coverage ≥ 90 % on touched packages; whole suite passes. |
