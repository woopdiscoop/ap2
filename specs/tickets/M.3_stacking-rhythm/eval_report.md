# Ticket M.3 · Evaluation report

Branch `worktree-agent-af879193b8c0ee105` (base `e03a2a3`). Diagnosis committed first (`705496b`), code afterwards
(`5060129` and later). Tests: `tests/stack/test_stack_m3.py` (M301-M309, helper modules `bar_case`, `plans_case`,
`stack_case`), `tests/topology/test_topology_m3.py` (M308). Synthetic data only.

**Summary.** The structure is in place and reported: column grid + bay module chosen by a stated score, typical-floor
ordering with a prior in `cellgrow` and in the plan seeding, type-aware assignment, façade-partition snapping,
overrides with French errors, « Trame et empilement » sections, SVG grids. Three measurable targets are **not reached**:
M302 on the M.1 case (44.7 % against 60 %), M303 (0.31-0.43 against 0.50) and M304 (about 36 % against 80 %); M305's
share of columns in small rooms is 18-25 % against 10 %. Reasons below. Byte-identity (M308), overrides (M306),
reports (M307), cell-level determinism and runtime (M309) and the gates (M310) pass.

## Results

| ID | Result | Figures |
|---|---|---|
| M301 | PASS | `§ Diagnosis` below, commit `705496b` ("M.3: diagnosis (M301)") precedes the first code commit `5060129`. |
| M302 | PARTIAL | Cell-level stackability (`stackability`, M.1 definition; seeds 0-9 give the same figure, the cell diagrams do not depend on the seed): **bar 70.8 %** (baseline 29.9 %), **M.1 case 44.7 %** (baseline 18.75 %; target 60 %). Hard misses 0, pins met (PRES, DAP, DGS on the top floor), floors <= 110 % on both. The M.1 target is out of reach with this assignment: the type-area upper bound of the best assignment found is 65.7 % (51 % without the type term) because the pins fix 1,584 of the top floor's cells and most large types (archive, multipurpose, training, entrance hall) exist on one floor only; reaching 60 % means realising 91 % of the bound with a single neighbour as prior. `test_M302_m1_case_reaches_60_percent` is `xfail` (non-strict); the passing tests assert >= 40 % (M.1) and >= 60 % (bar, seeds 0-2). |
| M303 | NOT REACHED | Exact-plan stackability (share of a floor's typed room area whose type is the same as directly below), bar, `--plans --budget 10`: seed 0 floors 1/2/3 = 16.8 / 43.6 / 33.6 % (mean 31.3 %), seed 1 = - / 34.8 / 51.2 % (floor 0 failed, 3 floors planned), seed 2 = 10.6 / 46.6 / 44.5 % (mean 33.9 %). Baseline 10.0 / 32.6 / 46.8 % (mean 29.8 %). Target >= 50 % in >= 8/10 seeds: 0/3 seeds measured. **4/4 floors planned: seeds 0 and 2 yes, seed 1 no** (floor 0 seeding failure; seed 1 was not measured at the baseline). `test_M303_bar_plan_stackability_at_least_half` is `xfail`. |
| M304 | NOT REACHED | Façade partitions within 0.30 m of a bay line: seed 0 32/88 (36 %), seed 1 27/65 (42 %), seed 2 33/100 (33 %); baseline with the best bay 35 %. The post-pass (`snap.py`) found 4-17 walls per floor that reach the façade and moved **none**, see "Why". `test_M304_bar_facade_partitions_on_the_bay` is `xfail`. |
| M305 | PARTIAL | Spans are multiples of 0.60 m within 5.40-9.00 m, one grid for the building (same column lines on every floor), core west and south sides on grid lines: PASS on the M.1 case, the bar and the plans case (`test_M305_*`). Bar plans (strict skeleton): grid 7.2 x 7.2 m, bay 2.4 m, 87 columns over the 4 floors (25 + 25 + 25 + 12); columns inside a room of less than 30 m² (not on a wall: more than 0.15 m from every side): seed 0 22 (25 %), seed 1 11 of 62 (18 %), seed 2 20 (23 %). Target <= 10 %: not reached (`xfail`). Without `--plans` the choice on the unconstrained skeleton is 9.0 x 9.0 m, bay 3.0 m (50 columns, 5 in small cells of the diagrams). |
| M306 | PASS | `bay_m`, `grid_m: [sx, sy]` and `typical_floor` honoured (tests check the grid, the bay, `result.typical` and the order floors are laid out: `[2, 1, 0, 3]` for `typical_floor: 2`). 11 invalid values (not a multiple of 0.60, wrong type, wrong length, negative, bay not dividing a span, level outside the building, bay with no usable span) give a French message and exit code 2, nothing written, no traceback. |
| M307 | PASS | `stacking.md` and `plans.md` have « Trame et empilement » (spans, bay, core on grid, typical floor, columns and columns in small rooms, façade partitions on the bay, stackability per floor pair); `stack.svg` has `<g id="grid">` (column lines red, bay lines dashed grey); each plan has `grille.svg` (rooms, grid, columns, those in a small room in red). |
| M308 | PASS | `cellgrow` with `prior=None` and `prior={}`: 4 sha256 digests computed with `cellgrow.py` of `e03a2a3` (R.9 anchor fixture, AREP programme), plus 16 old-module / new-module comparisons on the stack floors, all identical. The M206 digests (P08 / P25 / P60) pass in the full suite. `seed_plan(prior=None)` returns the same plan. |
| M309 | PASS (cell level, time) / plans not re-checked | Two `ale stack` runs are byte identical in every file. `--plans` on the bar at budget 10: 75 s, 60 s (3 floors), 50 s against the limit 108 s (1.5 x 72 s; the M.2b run measured 80 s on this machine before any change). The annealer runs on a wall-clock budget, so exact plans are not byte-reproducible across machines (M.2 spec issue 4); not re-verified. |
| M310 | PASS | See Gates. |

## Gates

| Gate | Result |
|---|---|
| `ruff check .` | clean |
| `ruff format --check .` | 329 files formatted |
| `mypy` (strict) | no issues in 162 source files |
| `python -m ale.contracts.lock --check` | OK (no contract change) |
| `pytest -m "not slow" -q` | **1578 passed**, 11 skipped, 50 deselected, 4 xfailed (3 pre-existing + `test_M302_m1_case_reaches_60_percent`), 743 s |
| Slow rate tests (`tests/stack/test_stack_m3.py`, 3 seeds) | measured by hand (table below); not run as `-m slow` in full |

## What was built

- `assign.py`: soft term `type_weight x (area of a type on a floor that is on neither neighbour)` (5.0 per m²,
  `StackRules.type_weight`; 0 gives the M.1 objective exactly) and a guard of `10 x type_weight` per m² above 93 % of a
  floor's capacity (without it the term piled load on the receding top floor and the plan engine failed it).
- `cellgrow.py` + `cellprior.py`: `grow(..., prior=<cell -> type>)`. A room of type t takes the ribbon positions that
  carried t below, seeds on the free prior cell of t nearest their centroid, first takes connected prior cells of t, and
  grows with a bonus on prior cells of t and a penalty on prior cells of other types present. No prior: no change.
- `floors.py`: `build_floors(typical=...)` lays out the typical floor (default: the most loaded) first, then outwards,
  each floor using the neighbour already laid out as prior; `pair_stackability`.
- `grid.py`: `choose_rhythm` (spans 5.4-9.0 m x 5.4-9.0 m, bay 2.4-4.8 m dividing both spans, core sides on grid lines;
  score `columns in small rooms + 0.25 x façade partitions off a bay line + 2 x façade rooms narrower than a bay`, ties to
  the larger span then the larger bay), columns, plan-level metrics (`plan_stackability`, `plan_facade_partitions`,
  `plan_columns`), French override validation.
- `plans.py`: floors planned typical first; the seeding of a floor gets the positions of the rooms of the same spec (then
  type) on the neighbour, matched to the nearest spring-embedding position, on every other attempt (odd attempts are
  prior-free, so a prior never blocks a floor); `snap.py` post-pass; `grille.svg`; report section.
- `topology/seed.py`: `seed_plan(prior=...)` (room id -> position replacing the spring position). `rules.py`: `bay_m`,
  `grid_m`, `typical_floor`. `cli/commands/stack.py`: exit code 2 for `RhythmInputError`.

## Why the targets were not reached

- **M302 on the M.1 case**: the bound, not the layout, is the limit (see the table). Moving more rooms between groups
  beyond the type term would split more groups (SAL is already split) and is not "no worse".
- **M304 and M305**: the exact-plan engine sizes a room by its area rule (-3 % / +max(3 %, 1.2 m²)) and the depth of its
  band, so a room width has a window of a few modules and the walls fall where the areas put them. The snapping
  post-pass tried 6 walls on floor 1 of one run: every candidate was refused because a neighbour left its area interval
  (12 m² offices at 1,200 cells with the interval 1,164-1,320; a 0.6-1.2 m move changes them by 1.8-3.6 m²). Making walls
  land on bay lines needs the realiser (`geometry/blocks.py` `room_bay_width`, the stack widths and the seeder's overflow
  estimate, which all assume the minimal width) to choose a width inside its window so that the running position hits a
  bay line; that touches the corridor grammar and was not attempted. The bay is also chosen on the M.1 cell diagrams
  (0.60 m cells, a partition is on a line or 0.6 m off), which predicts the plan figures poorly (see Spec issue 5).
- **M303**: the prior only changes where a room is *sorted* along the bands; the band structure, the junction fingers and
  the annealer (which does not know the prior) re-order rooms, and the plan changes shape when the top floor recedes. A
  prior inside the annealer's cost, or a copy of the neighbour's corridor plan (the RD's "corridors in the same
  place") is the next step; it needs a way to give `realize` a plan instead of a seeding.

## Plans on the bar (final code, `--plans --budget 10`)

| Seed | Planned | Plan stackability floors 1/2/3 | Façade partitions on a bay line | Columns / in small rooms | Time |
|---|---|---|---|---|---|
| 0 | 4/4, vertical OK | 16.8 / 43.6 / 33.6 % | 32/88 | 87 / 22 | 75 s |
| 1 | 3/4 (floor 0 failed), vertical not OK | - / 34.8 / 51.2 % | 27/65 | 62 / 11 | 60 s |
| 2 | 4/4, vertical OK | 10.6 / 46.6 / 44.5 % | 33/100 | 87 / 20 | 50 s |

Hard violations per floor (seed 0): 16, 6, 9, 3 (baseline 10, 12, 12, 1; the NO_FACADE sketch tolerance as before).

## Spec issues (reading chosen)

1. **M302 cannot reach 60 % on the M.1 case** with its pins (bound 65.7 %). Reported, test `xfail`.
2. **"Stacking assignment no worse"** read as: hard misses and pins no worse, floors <= 110 %. The type term changes the
   soft objective: the M.1 case now splits one group (SAL), the bar two (DRH, SAL); loads moved (M.1 420/346/386/592 ->
   340/274/538/592). `type_weight: 0` restores the M.1 objective (tested). `type_weight` is not a YAML key.
3. **Ownership**: `src/ale/cli/commands/stack.py` is not in RD §4, but exit code 2 for invalid overrides needs it (two
   `except` clauses; the registration file is untouched). `src/ale/topology/seed.py` got an optional `prior` argument.
4. **Seeds**: the cell diagrams do not depend on the seed (it only drives the jitter), so "seeds 0-9" at cell level is
   one figure. Plan rates were measured on 3 seeds (about 80 s each), not 10.
5. **The grid choice scores cell diagrams** (0.60 m cells) while M304 / M305 are measured on exact plans; the chosen bay
   (2.4 m with the strict skeleton, 3.0 m without) was not validated against plan widths. The grid differs between
   `ale stack` and `ale stack --plans` because the plan skeleton keeps the wet stack off the outline.
6. **Typical floor** default = highest load / capacity; for the bar it is level 1 (level 3 with the plan-less skeleton).
7. **Floor 0 failure for seed 1** was not compared with the baseline for that seed; the prior-free alternate tries keep the
   M.2b behaviour on odd attempts.
8. **R.9 coverage test** (`cellgrow` >= 90 %) is kept green by putting the prior logic in `cellprior.py`.

## Diagnosis (M301)

Measured at `e03a2a3` before any code change (scripts outside the repository; bar = `tests/stack/bar_case.py`,
`--plans --budget 10`, seed 0, 80 s wall clock for 4 floors).

### Cell level (`stackability`, M.1 definition)

| Case | Stackability | Upper bound for the same assignment | Wet cells (always stacked) |
|---|---|---|---|
| M.1 case (pins PRES, DAP, DGS on top) | 18.75 % | 27.7 % | 696 of 5471 (12.7 %) |
| Loaded bar (x 1.7, no pins) | 29.9 % | 71.8 % | 696 of 9016 (7.7 %) |

The bound is `sum over floors and types of min(area of the type on floor k, area of the type on floors k-1 and k+1)`
divided by all room cells: no cell layout can exceed it. Two causes:

1. **The cell diagrams of different floors are independent.** `cellgrow.grow` is run per floor with the same seed but a
   different programme, a different outline (floor 3 recedes) and a different footprint, so a type that exists on two
   floors lands in unrelated cells (M.1: 18.75 % against a bound of 27.7 %, bar: 29.9 % against 71.8 %).
2. **The assignment (`assign.py`) groups by entity code and ignores room types.** Floor type mixes of the M.1 case:
   L0 office 329 / open_office 267 / entrance_hall 222 / sanitary 144 ...; L1 archive 305 / storage 167 / office 264 ...;
   L2 multipurpose 417 / training 333 / office 198 ...; L3 office 739 / open_office 500 / meeting 345 ... Most large types
   exist on one floor only (archive, multipurpose, training, entrance hall), so the bound itself is 27.7 %.

### Plan level (exact plans, bar, `--plans`)

Share of a floor's room area (rooms + fixed rooms with a type) whose type equals the type at the same module directly
below (absolute coordinates, floor 3 recedes):

| Floor | Plan-level stackability |
|---|---|
| 1 | 10.0 % |
| 2 | 32.6 % |
| 3 | 46.8 % |
| mean 1-3 | 29.8 % |

Cause: `plans._generate_floor` calls `seed_plan` with the default spring seeder (`embed`), a seeded force layout that
knows nothing of the other floors, then anneals independently; the order of the rooms along the bands and the band
structure differ from floor to floor, and `cellgrow` is not even used (`seeder="spring"`).

### Rhythm

Façade partition positions (a room edge ending inside an exterior edge, both rooms counted; 134 on the 4 floors) within
0.30 m of a bay line (lines `x0 + n b`, `y0 + n b`, origin = ground floor corner):

| bay b (m) | 2.4 | 3.0 | 3.6 | 4.2 | 4.8 |
|---|---|---|---|---|---|
| share on a bay line | 35.1 % | 21.6 % | 12.7 % | 16.4 % | 11.9 % |

Cause: room widths on the façade come from `area / depth` rounded to the 0.60 m module; nothing ties them to a common
module. There is no column grid at all (no code, no output); the core (24.0 ; 3.6) of the bar and the wet stack are the
only fixed elements.

### Consequence for the targets
M302 (>= 60 % on the M.1 case) cannot be reached by a better cell layout alone (bound 27.7 %); it needs a type-aware
assignment. M303 (>= 50 % at plan level) needs the floors to share their band structure and room order.
