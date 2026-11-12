# Ticket M.3b — Evaluation

Cases: the loaded bar (`tests/stack/bar_case.py`) and M.2 `plans_case`; seeds 0–9 for rates (slow tests allowed, a
3-seed smoke under `-m "not slow"`).

| ID | Check | Pass |
|---|---|---|
| B301 | Diagnosis committed before the first code change | § Diagnosis with per-row feasibility figures |
| B302 | Façade partitions within 0.30 m of a bay line (M.3 M304) | ≥ 80 % on every planned floor, ≥ 8/10 seeds |
| B303 | Columns inside rooms < 30 m² not on a wall (M.3 M305) | ≤ 10 % of columns, ≥ 8/10 seeds |
| B304 | Plans still produced and valid | bar `--plans` ≥ 4/4 floors on ≥ 8/10 seeds; 0 hard violations; areas within U-15 tolerance |
| B305 | Plan-level stackability (M.3 M303) | not lower than M.3 (≈ 31 %); report the figure |
| B306 | Byte-identity without hint: P08/P25/P60 digests (M206), `cellgrow` with no prior | unchanged |
| B307 | Runtime | `--plans` on the bar ≤ 1.5 × M.3 (≈ 75 s at budget 10) |
| B308 | Gates: ruff, ruff format, mypy, lock --check, full `-m "not slow"` suite (`-q`, count visible) | green |

If a target is out of reach, stop and report the rates reached and why.
