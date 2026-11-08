# Ticket Q.2a — Evaluation
| ID | Test | Pass condition |
|---|---|---|
| F1 | rect | site_rect (24×18, spine X): usable = 2 × 24 − ends; computed value asserted from the formula in the test. |
| F2 | L | site_L: only primary/secondary edges parallel to their spines and not on the cut count; value recomputed in the test. |
| F3 | tight_warning | P60 on site_L → `W_FACADE_TIGHT` present (demand > usable), no new error; P8 on site_rect_small → absent. |
| F4 | gates | Existing 3.1 tests still pass; ruff, format, mypy; lock --check; whole suite. |
