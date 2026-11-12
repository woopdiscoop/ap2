# Ticket M.4 — Evaluation

Tests: `tests/bayplan/**` (kernel, section, catalogue, properties) and `tests/stack/test_stack_m4.py` (through
`run_stack` + `run_plans(planner="bay")` and the CLI). None of them is `slow`: the bay planner has no time budget.

## Cases
| Case | Input | Role |
|---|---|---|
| A | `tests/stack/bar_case.py` with factor 1.3 (helper in `tests/bayplan/`, do not mutate the module global) | everything fits |
| B | `bar_case` at its factor 1.7 (the M.2b load) | saturation: some floors are over capacity |
| C | the M.1 case `tests/stack/stack_case.py` (pins, core at x = 30.0) | uneven loads, top floor over capacity |
| D | M.2 `tests/stack/plans_case.py` (30.0 × 21.6 m, not a bar) | routing to the engine |
| E | unit fixture: plate 64.8 × 19.2 m, one solid 16.8 × 6.0 m at (24.0 ; 6.6) (inside the band), bay 2.4 m; groups AA and BB: 15 offices 12 m² and 2 meeting rooms 24 m² each (façade); AA one open office 150 m² (façade); AA one archive 30 m², BB one archive 30 m², one storage 20 m², one print room 20 m² (no façade) | clean section, kernel called directly |
| F | E transposed (plate 19.2 × 64.8 m) | bar along y |

"Plate" below = outline minus solid. "Placed share" = target area of the placed programme rooms / target area of
the floor's programme (`prepared.instances`). "Window" = the sketch window of RD §3 (10 %). Figures in brackets
are what the Planner's probe (plain first-fit, no improvement step) reached; they are not targets.

## Checks
| ID | Check | Pass |
|---|---|---|
| M400 | Diagnosis first (RD §2) | section `## Diagnosis` committed before the first code commit; table for every floor of A, B, C; smoke layout: `check_layout` = `()` and `export_run` writes its four files |
| M401 | Validity | every floor of A, B, C (12 floors) is eligible and bay-planned; on them and on E, F: `check_layout(layout, prepared, sketch config)` = `()`, status `ok`; vertical check OK on A, B, C [12/12 floors clean] |
| M402 | Completeness | A and E, F: every room placed on every floor. B: placed share ≥ 90 % on every floor [95–100 %]. C: ≥ 85 % on every floor [88–100 %]. Unplaced rooms listed in `plans.md`; CLI exit 0 on A, exit 1 on B with all files written |
| M403 | No degenerate reserve | for every unplaced room and each of its admissible F / B / b shapes (its fallback shape if it has none): no free run of that many reserve bays in one façade run, no free band run of that width. On a floor with an unplaced room: reserve ≤ 8 % of the plate [≤ 5.1 %]. Reliquat ≤ 1.5 % of the plate on every floor. Reserve is never counted as placed |
| M404 | Hard violations | on A, B, C, E, F: 0 `ASPECT`, `MIN_WIDTH`, `NO_FACADE`, `NO_CIRCULATION_ACCESS`, `SOLID_NO_ACCESS`, `REQUIRED_ADJ`, `AVOID_ADJ`. `AREA_UNDER` / `AREA_OVER` only on rooms whose catalogue (recomputed by the test from RD §4.5, not imported from the planner) has no admissible shape (their deviation is reported); every other placed room is inside its window. Flagged rooms on B ≤ 15 % of the placed rooms [expected 14 of 111: the 15, 30, 40 and 80 m² rooms]; on E: 0 |
| M405 | Large rooms | B: the six open offices (163.2, 170 and 136 m²) and the 150 m² room are each placed as D or T inside their window, or unplaced; none is an F room |
| M406 | Façade and band | every placed `needs_facade` room has ≥ 2.4 m on an exterior side. A non-façade room placed outside the band: no free band run could take one of its admissible band shapes |
| M407 | Long-façade partitions on a bay line | new measure in `grid.py`: ends of room sides (reserve included) lying on a long side of the outline, strictly inside it, at distance 0 from an absolute bay line: **100 %** on every bay floor of A, B, C, E, F. The M.3 two-axis figure (tolerance 0.30 m) is reported, no threshold [87–92 %: gable ends follow the section, not the bay] |
| M408 | Circulation | circulation area / plate ≤ 37 % on every floor of A, B, C [24–33 %]; ≤ 27 % on E, F [24.8 % by hand]. Corridor rows are `corridor_m` wide in the wings; clear width ≥ `circulation.min_width_m` beside the solid. No circulation rectangle other than the elements of RD §4.4 (the test classifies each one) |
| M409 | Entrance | floor 0 of A, B, C: the entrance point lies on a side of a circulation rectangle; distance from each `anchor="entrance"` room to the entrance reported |
| M410 | Groups | stretches of a group on a floor = project its placed rooms on the bar axis, core segment collapsed to zero length, gaps ≤ 2 bays merged. A, B, C: no group in more than 3 stretches, and ≥ 50 % of the (floor, group) pairs in one stretch per case [64–73 %, worst group 3]; E: both groups in one stretch each side of the core at most (≤ 2). Figures reported per floor |
| M411 | Section | unit tests: d_f = 4.8 m for the programme of B with bay 2.4 m; rows of the 19.2 m and 16.8 m plates as in RD §4.2; tie broken by R.8: bay 3.0 m, façade rooms of 11.5 m² → 4.2 m with no learned depth, 3.6 m with `office.depth_m.p50` = 3.6; a 14.4 m deep plate, a plate with long side < 2 × short side, a plate with two solids → not eligible, each with its French reason |
| M412 | Columns and stacking (reported) | M.3 `plan_columns` on A, B, C: columns in rooms < 30 m² ≤ 12 % per case [5–8 %]. Plan stackability per floor pair and its type-area bound (RD §9) in `plans.md` and the report: no threshold in M.4 [B: 0.26 / 0.56 / 0.44 with independent floors; engine 0.32 mean] |
| M413 | Routing and byte identity | D: every floor planned by the engine under planner `bay` (call spy), reason in `plans.md`. A with `planner="engine"`: the bay planner is never called (spy). `ale stack` without `--plans` on B: every file byte-identical to the base commit (sha256 taken at the base commit before any change, stored in the test). M206 digests pass. Every pre-existing test passes unchanged, except the listed `--planner engine` additions |
| M414 | Report | `plans.md` of A and B, French, has for each bay floor every item of RD §4.7 (planner, section, d_f and reason, bays used / available, unplaced, « à ajuster », reserve, circulation with palier and reliquat, dead end, distance to the core, groups, stackability and bound); DXF / SVG / `report.md` per floor as today |
| M415 | Determinism and runtime | two runs of B: byte-identical `layout.json`, `preview.svg`, `report.md` per floor and `plans.md` (say in the report whether the DXF is too); F places the same rooms with the same areas as E; bay planner ≤ 5 s per floor; `ale stack --plans` on B ≤ 30 s [4 s] |
| M416 | Gates | `ruff check`, `ruff format --check`, `mypy`, `python -m ale.contracts.lock --check` (no contract change), the ticket's tests and `tests/stack` (`-q`, count visible); the full `-m "not slow"` suite runs once at review |

## Rules
- A threshold is met on every seed: the bay planner does not use the seed (it is only recorded in the layout).
- No `xfail`, no skipped check, no engine fallback on a floor of A, B, C, E, F.
- If a target is out of reach, apply RD §8: stop, report the figures reached, the floor and the cause.
- Report also, without threshold: per-floor capacity (façade bays, band length) against demand, and the load at
  which the stacking should stop filling a bay floor (for the Router: `circulation_share` of `rules.yaml`).
