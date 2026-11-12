# Ticket M.4 — Bay-first planning of office bars (one floor at a time) · Requirements

> Context = this file, `eval.md`, the M.2b / M.3 / M.3b eval reports (why tuning the corridor-grammar engine
> reaches ≈ 83 % fill and ≤ 55 % partitions on bay lines), `ale.stack` (`skeleton.py`, `grid.py`, `plans.py`),
> R.8 (`TypeStats.depth_m`, contracts 1.8.0, merged at `dbdafa6`), `ale.geometry.checks.check_layout`,
> `ale.geometry.evaluate.evaluate`, `Layout` / `PlacedRoom` (contracts). User decisions U-9, U-10, U-14, U-15,
> U-16 and **U-18** (2026-11-12: office bars are planned bay-first, rooms = whole bays; the existing engine stays
> for other footprints). **No contract change. No new dependency. No randomness, no annealing.**
> Reviewed by the Planner (U-19) before dispatch: the original ticket was split into **M.4 (this file)** and
> **M.4b** (§9). Every target in `eval.md` was checked with a throw-away probe (plain greedy fill, not given to
> you): if you are far below a target, suspect a geometry bug, not a missing search.

## 1. Purpose
Plan a bar floor the way an architect draws one: the section first (façade rows, corridors, central band), then the
bays, then rooms as **whole numbers of bays** along each long façade. Partitions on the long façades are on bay
lines by construction. Output: a normal contract `Layout` per floor, valid for `check_layout`, exported and
reported like today. M.4 plans **each floor on its own**; making floors repeat is M.4b.

## 2. Diagnosis first (commit `M.4: diagnosis` before the first code commit)
Write `## Diagnosis` in `eval_report.md`, from a script kept outside the repository:
1. For every floor of cases A, B, C of `eval.md`: plate, solid rectangle, the rows of §4.2 with their depths, the
   core segment of §4.3, façade bays available per row, the shape chosen from the catalogue of §4.5 for every room
   (in window / not), façade bays demanded, band length demanded / available, circulation area predicted.
2. A smoke layout for floor 1 of case B: the circulation of §4.4, every other cell a reserve room; run
   `evaluate`, `check_layout` (must return `()`) and `export_run` on it.
If (1) predicts a miss of an `eval.md` target, or (2) does not pass, **stop and report** (§8) before coding.

## 3. Facts you need (checked on the R.8 head `2a119a1`)
- The exact-plan module is **0.10 m** (`grid.module_mm = 100`); the stacking cell is 0.60 m. Work in integer
  modules; every length of this ticket is a multiple of 6 modules. `Rhythm` (M.3) gives the bay (`rhythm.bay`
  cells) and the **absolute** bay lines (`bay_lines_x/y`); a floor's local origin is `prepared.footprint.origin_m`
  (the top floor of the fixtures starts at x = 6.0 m: its first bay line is at 7.2 m).
- `check_layout` requires: integer rectangles inside the footprint; no overlap; **rooms + circulation tile the
  footprint exactly** (solids excluded; `Layout.residue` does not count); every entry of `rooms` shares ≥ 1.2 m
  (`min_door_edge_m`) with a circulation rectangle; circulation connected by shared edges (a corner is not
  enough); circulation along ≥ 0.1 m of each solid; a room with aspect > `shape.aspect_max` (**2.0**) or an area
  outside the rule must carry the matching violation in `metrics.violations`. Rooms whose `instance_id` is not in
  `prepared.instances` are not area-checked but must still meet the contact and aspect rules.
- `evaluate(layout, prepared, rulebook, config)` computes `LayoutMetrics` for any `Layout`: build the layout with
  placeholder metrics (as `geometry/realize.py::_build_layout` does), evaluate, then set the metrics.
- Hard codes (`ale.optimize.anneal.HARD_CODES` + `SOLID_NO_ACCESS`): `AREA_UNDER`, `AREA_OVER`, `ASPECT`,
  `MIN_WIDTH`, `NO_FACADE`, `REQUIRED_ADJ`, `AVOID_ADJ`, `NO_CIRCULATION_ACCESS`. A 2.4 × 5.4 m office is
  `ASPECT` (2.25): the row depth must respect `aspect_max`.
- U-15 sketch tolerance without a contract change: for bay floors use
  `sketch = config.model_copy(update={"area": config.area.model_copy(update={"tol_down_pct": p, "tol_up_pct": p})})`
  (p = 10) for `evaluate`, `check_layout` and `export_run`; a room's window in cells is
  `Consts.from_config(sketch).req(spec).lo .. .hi`. Do not change `aspect_max` or any other limit.
- `Layout.rooms` and `.circulation` are sorted by `instance_id`; circulation has `spec_id=None`. The export accepts
  rooms with `spec_id=None` (reserve) and programme rooms absent from the layout (unplaced).
- Stacking fills floors up to 110 % of a 25 % circulation share; a bay bar with a central band uses 24–34 % on the
  fixtures (the solid sits across the south corridor), so some floors of case B are over capacity by design.

## 4. Method (`src/ale/bayplan/**`, new)
Local frame: u along the long side of the plate, v across; a plate whose long side is y is planned transposed.
Examples use the bar of `tests/stack/bar_case.py`, floors 0–2: plate 64.8 × 19.2 m, solid x 24.0–40.8, y 3.6–10.8.

### 4.1 Eligible floor (else the engine plans it, with a French reason in `plans.md`)
`rhythm` present; outline = one axis-aligned rectangle, sides multiples of 0.60 m, long side ≥ 2 × short side;
exactly one rectangular solid; the section of §4.2 exists; both flank bays of §4.3 exist and each wing has ≥ 2
whole bays; one corridor row keeps a clear width ≥ `circulation.min_width_m` beside the solid over its whole span.

### 4.2 Section (same on every floor of the building, measured from the same long façade)
- Corridor c = 1.8 m (rules key `corridor_m`, multiple of 0.60 m, ≥ `circulation.min_width_m`). Bay b from M.3.
- Façade row depth d_f, one value for the building: candidates 3.6, 4.2 … 7.2 m (≤ `facade.max_depth_m` if set)
  with d ≤ `aspect_max` × b; choose the one that maximises the target area of the building's `needs_facade` rooms
  having an in-window shape `k·b × d` with aspect ≤ `aspect_max`; ties: nearest to the reference depth
  (`rulebook.types["office"].depth_m.p50` when present, else 5.4 m), then the smaller. Bar: b = 2.4 → d_f = 4.8.
- Rows from the reference façade: `S` 0–d_f · `cS` (c) · `M` central band (rest, ≥ 2.4 m) · `cN` (c) · `N` d_f.
  Plate 19.2: S 0–4.8, cS 4.8–6.6, M 6.6–12.6, cN 12.6–14.4, N 14.4–19.2. Plate 16.8: M 6.6–10.2, cN 10.2–12.0,
  N 12.0–16.8. A plate with `D − 2·d_f − 2·c < 2.4 m` has no such section (not eligible: M.4b).

### 4.3 Along the bar
- Bay cells = intervals between consecutive absolute bay lines; a partial bay at a gable joins its neighbour (that
  end room is `k·b + r` wide; shapes there use that width).
- **Core segment** = the solid's u-extent snapped outward to bay lines (*span*) plus one bay on each side (*flank*).
  Inside the span every row keeps what lies outside the solid's v-extent: a corridor part stays circulation; a
  room-row part stays a row only if it is ≥ 3.6 m deep (band: ≥ 2.4 m) **and** borders, over the whole span, a
  corridor part ≥ `min_width_m` wide; otherwise it is circulation (« palier »). Bar: S part 0–3.6 →
  palier (its corridor is inside the solid); M part 10.8–12.6 → circulation; cN and N intact (N: 7 + 2 flank bays).
  Top floor: cN keeps 10.8–12.0 (1.2 m, reported « couloir rétréci le long du noyau »).
- **Wings** = the two stretches beyond the flanks (bar: 9 bays each). A wing is, from its gable inward:
  an optional **head** (at most one through room `T` at the gable, then deep rooms `D` side by side), then the
  **regular segment** (S row, cS, M, cN, N row). D rooms stand on the side opposite the corridor that passes the
  span (bar: D on S, cN passes; both pass: D on S); along a head only that corridor runs, and the other row
  keeps its F rooms. A head may fill its wing. A head never covers an entrance bay (§4.4).

### 4.4 Circulation — only these elements (leftover cells are never turned into circulation)
1. the corridor rows cS and cN where they are neither solid, nor inside a T room, nor (for the D side) inside a head;
2. one **flank link** per flank: the whole flank bay, across the band, extended to the façade on a side where the
   span has a palier (bar: x 21.6–24.0 and 40.8–43.2, y 0–12.6);
3. the palier and the other clipped parts of §4.3;
4. one **end link** per wing with a regular segment: c wide, across the band, at the outer end of the regular
   segment (closes the corridor loop);
5. **entrance bay**: for each entrance of the floor (`site.entrances`) on a long side, the bay under it is
   circulation from the façade to the nearest corridor row unless it already is; an entrance on a gable is only
   noted in the report;
6. *reliquat*: a band leftover that cannot form a legal reserve room (§4.6) joins the neighbouring link.
Bar floors 0–2 without heads: ≈ 367 m² = 32.7 % of the plate minus the solid (1123 m²).

### 4.5 Room shapes (the catalogue; a test recomputes it from these formulas)
`F k`: k bays of a façade row, k·b × row depth. `D k`: k bays × (d_f + c + band depth), in a head. `T k`: k bays ×
plate depth, at a gable. `B w`: band, w × band depth, w a multiple of 0.60 m ≥ 1.2 m. `b w`: half band (two rooms
back to back, each on its corridor), only when the band is ≥ 4.8 m deep. `needs_facade` rooms: F, D, T. Other
rooms: B, b first, then F, D. A shape is **admissible** when its area is in the room's sketch window, its aspect is
≤ `aspect_max` and it meets `min_width_m`; with `facade.max_depth_hard` also depth ≤ the limit.
Bar (19.2 m plate): F = 11.52·k m² (k ≤ 4), D = 30.24·k (3 ≤ k ≤ 10), T = 46.08·k (k ≥ 4). So 12 → F1, 24 → F2,
150 and 163.2 → D5, 170 → D6 or T4; 15, 30, 40 and 80 m² have **no** admissible shape.
- A room with an admissible shape is placed with one, or is **unplaced** (never stretched or squeezed).
- A room with none is placed with the aspect-legal shape of the smallest relative area deviation (15 → F1,
  30 and 40 → F3, 80 → D3) and carries its `AREA_UNDER` / `AREA_OVER` (listed « à ajuster »), or is unplaced.

### 4.6 Packing (deterministic; a constructive fill is enough)
Order of concern: (1) least unplaced target area; (2) rooms of one group (`ale.stack.assign.default_group`) next to
each other along the bar, a group's deep room next to its offices; (3) `anchor="entrance"` rooms nearest the
entrance, required / preferred adjacencies; (4) non-façade rooms in the band before façade bays; (5) fewest
reserve bays. Large rooms go to heads first: enumerate their assignments to a wing and a D / T shape (a few
hundred combinations at most) and keep the one with the least unplaced area, then the fewest façade bays (bar
floor 2: T4 + D5 in one wing, T4 in the other; D6 + D6 would leave the 150 m² room out). Then façade rooms into
the bay runs, group by group, then band rooms; finish with a pass that retries every unplaced room in the free
runs. Free façade bays become **reserve** rooms
(`spec_id=None`, ids `reserve-NNN`, one per bay so that aspect ≤ 2.0); free band becomes reserve pieces that each
satisfy `check_layout` (aspect, 1.2 m on a corridor). A fixed order and first fit passed every validity check in
the Planner's probe; add a bounded improvement step (no time-based stop) only if a target of `eval.md` is missed.

### 4.7 Integration
- `plans.py`: in `_generate_floor`, after `prepared` and the rulebook are loaded, an eligible floor under planner
  `bay` gets its layout from `ale.bayplan` instead of seed / anneal / snap; the rest of the function (fixed rooms,
  `check_layout`, export, `FloorPlan`) is shared and uses the sketch config for that floor. Do not refactor the
  engine path. `FloorPlan` gains optional fields (planner, section, unplaced, « à ajuster », reserve, notes).
  `run_plans(..., planner="engine")` keeps today's behaviour by default (existing tests call it).
  An unplaced room is a hard miss of the run (`plans_misses`, exit 1, files still written).
- CLI `ale stack --plans --planner bay|engine`, default `bay` (bay-first on eligible floors, engine elsewhere).
- `rules.yaml`: `corridor_m`, `sketch_tolerance_pct` (0–20, default 10); invalid values as M.3's overrides
  (French message, exit 2).
- `plans.md` (French), only when the planner is `bay`: per floor the planner and, for an engine floor, why; for a
  bay floor the section (rows, depths, d_f and its reason), bay, façade bays used / available, rooms placed /
  unplaced (list), « à ajuster » (room, target, placed, %), reserve (bays, m²), circulation m² and share with the
  palier and reliquat shown apart, « couloir rétréci », entrance, groups in more than one stretch, longest
  corridor dead end and longest distance from a room to the core (flag > 10 m and > 40 m, no failure), then the
  existing « Trame et empilement » figures plus the type-area bound of §9.

## 5. Files (ownership)
`src/ale/bayplan/**` (new), `src/ale/stack/plans.py` (the branch of §4.7, `FloorPlan` fields, misses, report
lines), `src/ale/stack/grid.py` (a long-façade partition measure only), `src/ale/stack/rules.py` (the two keys),
`src/ale/cli/commands/stack.py` (`--planner`), `tests/bayplan/**`, `tests/stack/test_stack_m4.py`,
`specs/tickets/M.4_bay-first/eval_report.md`. Do not modify `src/ale/contracts/**`, `src/ale/geometry/**`,
`src/ale/topology/**`, `src/ale/optimize/**`, `src/ale/export/**`, `src/ale/stack/skeleton.py`, `assign.py`,
`floors.py`, `src/ale/ui/**`, the CLI registration file. Existing tests: no change, except adding
`--planner engine` to a CLI call that fails only because the default planner changed (list each one in the
report). Test helpers not imported as `conftest`. Never weaken a test. Commit early and often.

## 6. Byte identity
With planner `engine` (the API default, or `--planner engine`) no output changes: `ale stack` without `--plans`
is byte-identical to the base commit, the M206 digests pass, `plans.md` has no new line. Annealed plans are not
byte-reproducible (wall-clock budget, M.2 issue 4): prove the engine path by a call spy, not by file hashes.

## 7. Not architecture you may invent
Corridor width, row depths, link positions, shapes and tolerances are fixed by §4. Do not add half-bay
partitions, a second row depth, an L-shaped room, a moved core or a search over sections: propose them in the
report instead.

## 8. Stop and report (write the figures reached in `eval_report.md`, commit, end)
- a contract, a file outside §5, or a limit other than the area tolerance would have to change;
- the diagnosis predicts a miss, or the smoke layout fails;
- a bay floor of case A, B or C still fails `check_layout` after three fixes of the same message;
- a target of `eval.md` is missed after the constructive fill and one bounded improvement step.
Do not relax a threshold, mark a test `xfail` or fall back to the engine to make a case pass.

## 9. Not in this ticket (M.4b, specified after M.4's report)
Typical floor and room stacking across floors (target relative to the type-area bound
`Σ_types min(area on floor k, area on floor k−1) / area on floor k`: in case B about 0.5 for floor 1 and 0.8 for
floor 2, and the receding top floor loses half of its north row, so an absolute 70 % per floor is out of
reach); a column grid derived from the section (columns on façades and
corridor walls: `Rhythm` has one uniform span per axis today); plates with a single corridor (12–15.6 m deep); a
corridor by-pass when the solid blocks both corridors; the entrance hall merged with the palier; a second row
depth or half-bay partitions for the 15 / 30 / 40 m² rooms; a skeleton placed inside the central band.
