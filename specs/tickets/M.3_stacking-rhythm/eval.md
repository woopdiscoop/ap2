# Ticket M.3 — Evaluation

Cases: the M.1 case (`tests/stack/stack_case.py`), the loaded bar (`tests/stack/bar_case.py`, ×1.7, 4 floors planned
in M.2b) and M.2's `plans_case`. Seeds 0–9 where a rate is asked. Rate tests may be `slow`; a 3-seed smoke version
runs under `-m "not slow"`.

| ID | Check | Pass |
|---|---|---|
| M301 | Diagnosis committed before the first code change | `eval_report.md` § Diagnosis with figures; commit order |
| M302 | Cell-level stackability (`stackability`) on the M.1 case and the bar case | ≥ 60 % on both (M.1 was 18.8 %); stacking assignment, pins and hard misses no worse than before |
| M303 | Plan-level stackability: share of each floor's room area whose type is the same as directly below (exact plans) | ≥ 50 % on the bar case, mean over floors 1–3, ≥ 8/10 seeds; still 4/4 floors planned |
| M304 | Bay rhythm: one module b (multiple of 0.60, divides a span) per building | On every planned floor ≥ 80 % of façade partition positions within 0.30 m of a bay line |
| M305 | Column grid: spans multiples of 0.60 within 5.40–9.00 m (or the YAML override), identical on every floor, core aligned to grid lines | All floors; columns inside rooms < 30 m² (not on a wall) ≤ 10 % of columns on the bar case; count reported |
| M306 | Overrides and errors: `bay_m`, `grid_m`, `typical_floor` honoured; invalid values give a French message and exit code 2 | Tests for each |
| M307 | Report: `plans.md` / `stack.md` section « Trame et empilement » (span, bay, columns in small rooms, stackability per floor pair); SVG shows the grid | Present, French |
| M308 | Byte-identity: `cellgrow` with no prior, and P08/P25/P60 generate digests (M206) | Unchanged |
| M309 | Determinism and runtime: same seed → same outputs; `--plans` on the bar case ≤ 1.5 × the M.2b time (72 s at budget 10) | Pass |
| M310 | Gates: ruff, ruff format, mypy, lock --check, full `-m "not slow"` suite | Green |

If a target is out of reach, stop, report the rates reached and why (as M.2b did) rather than loosen a check.
