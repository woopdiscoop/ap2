# Ticket M.4 — Evaluation report

## Diagnosis

Script kept outside the repository (scratchpad `diag/diag.py`, `diag/smoke.py`). Cases A (factor 1.3), B (1.7), C
(M.1 case), strict stacking (`run_stack(..., strict_solids=True)`). Bay 2.4 m on A, B, C (rhythm: span 12 cells,
bay 4 cells); the solid is core + wet stack: x 24.0-40.8 (A, B) / 30.0-46.8 (C), y 3.6-10.8 (16.8 x 7.2 m).
Floors 0-2: plate 64.8 x 19.2 = 1123 m2 (outline minus solid); floor 3: 52.8 x 16.8 = 766 m2.

Section (all cases): d_f = 4.8 m (facade target area with an in-window F shape: A 1062, B 1388, C 830 m2).
Rows 19.2 m: S 0-4.8, cS 4.8-6.6, M 6.6-12.6, cN 12.6-14.4, N 14.4-19.2. Rows 16.8 m: M 6.6-10.2, cN 10.2-12.0,
N 12.0-16.8. Core segment (span snapped outward + one flank bay each side): A, B u 21.6-43.2 (wings 21.6 + 21.6 m on
floors 0-2, 15.6 + 15.6 m on floor 3); C u 26.4-50.4 (wings 26.4 + 14.4 m; floor 3: 20.4 + 8.4 m). All 12 floors
eligible (single rectangle, long side >= 2x short, one solid, both wings >= 2 whole bays, cN passes the span;
on floor 3 cN keeps 1.2 m beside the solid).

| Case / floor | Rooms | Façade bays demanded (F) / available (S+N) | Heads (D/T chosen) | Band demanded / available (m, B-equiv.) | No admissible shape |
|---|---|---|---|---|---|
| A0 | 26 | 27.5 / 45 | D4.5 | 11.4 / 39.6 | ACC01 80 |
| A1 | 32 | 29.0 / 45 | D4 | 12.6 / 39.6 | PRES03 15 x3 |
| A2 | 22 | 26.0 / 45 | D3.5 | 25.8 / 39.6 | - |
| A3 | 6 | 11.0 / 35 | D6 | 7.2 / 27.6 | - |
| B0 | 35 | 31.5 / 45 | - | 58.2 / 39.6 (spills to facade bays) | ACC01 80 |
| B1 | 30 | 36.0 / 45 | D5.5 x2 (11 bays of S row) | 8.4 / 39.6 | PRES03 15 x3 |
| B2 | 24 | 26.5 / 45 | D5, D5.5 x2 | 0 / 39.6 | - |
| B3 | 22 | 23.0 / 35 | D5.5 x2 | 0 / 27.6 | - |
| C0 | 5 | 7.0 / 44 | D5 | 4.8 / 37.2 | ACC01 80 |
| C1 | 7 | 3.5 / 44 | - | 38.4 / 37.2 | - |
| C2 | 30 | 27.5 / 44 | D3 | 19.2 / 37.2 | - |
| C3 | 28 | 32.0 / 34 | D4, D3.5 | 0 / 25.2 | PRES03 15 x2 |

(Shapes per room: catalogue of RD 4.5 recomputed with the 10 % sketch window of `Consts.from_config`; a facade room takes
the F/D/T shape of smallest area deviation, other rooms B/b first.) Predicted circulation (RD 4.4, floors 0-2, no head):
367.2 m2 = 32.7 % of the plate, measured on the smoke layout below; floor 3 about 33 %. Tight spots (not misses): B1
(36 F bays demanded against 45 minus 11 under the two D rooms), C3 (32 of 34 minus 7.5 under D4 + D3.5), B0 (band demand
above the band, rooms spill to facade bays). The targets of `eval.md` (placed share B >= 90 %, C >= 85 %) are not
predicted missed by these counts; the packing will say.

Spec remark: RD 4.5 lists `D = 30.24 k, 2.5 <= k` but D2.5 (6.0 x 12.6 m) has aspect 2.1 > 2.0; the catalogue used here
follows the aspect rule (D from k = 3 on the 19.2 m plate; 2.5 on the 16.8 m plate: 6.0 x 10.2 = 1.7).

Smoke layout (floor 1 of B): circulation of RD 4.4 (cS, cN, two flank links, palier, M part, two end links) and every
other cell a reserve room (27 + 18 + 18 facade bays, 4 band pieces). Result: `evaluate` 0 violations, circulation
367.2 m2, `check_layout` = `()`, `export_run` wrote `layout.json`, `layout.dxf`, `preview.svg`, `report.md`.
No predicted miss, smoke passes: proceed to code.

## Result

Bay-first planner `src/ale/bayplan/` (`catalogue.py`, `plan.py`, `measures.py`), integration in `ale.stack.plans`
(`planner="bay"|"engine"`), keys `corridor_m` / `sketch_tolerance_pct` in `rules.yaml`, CLI `--planner bay|engine`
(default `bay`), measure `plan_longside_partitions` in `grid.py`. No contract change, no new dependency, no randomness,
no time budget. The planner packs deterministically: heads (DP over wings), then groups in bay runs (four fixed orderings
tried, the best kept: least unplaced area, then least free bays), band rooms in two lanes (B / b), then a per-run dynamic
programme that places reserve pieces so that no column stands inside a room under 30 m2. A bay floor takes 0.02-0.3 s.

### Per-ID table (cases A, B, C = 12 floors; E, F = kernel)

| ID | Result | Figures |
|---|---|---|
| M400 | pass | `## Diagnosis` committed first (`cb3b2e9`); smoke: `check_layout` = `()`, 367.2 m2 circulation, four export files |
| M401 | pass | 12/12 floors eligible, bay-planned, `check_layout` = `()` under the 10 % sketch config; vertical check OK on A, B, C |
| M402 | pass | A 100 % every floor; B 92.5 / 90.5 / 95.5 / 97.8 %; C 100 / 100 / 100 / 85.8 %; E, F all placed. CLI: A exit 0, B exit 1 with the 4 x 4 plan files and `plans.md` written |
| M403 | pass | B reserve 3.1 / 3.8 / 6.6 / 6.2 % of the plate (limit 8 % where rooms are unplaced); C3 5.1 %; reliquat <= 1.28 % (B1) (limit 1.5 %); no free reserve run takes an unplaced room (rule below) |
| M404 | pass | 0 hard violation of the listed codes on A, B, C, E, F; `AREA_*` only on rooms without admissible shape (ACC01 80 m2 -> D3; PRES03 15 m2 -> F1.5); flagged 4 of 104 placed rooms on B (3.8 %; limit 15 %), 0 on E |
| M405 | pass | on B the open offices and the 150 m2 room are D or T inside their window, none is an F room |
| M406 | pass | every placed facade room has >= 2.4 m of exterior side; no non-facade room outside the band while a free band run could take it |
| M407 | pass | 100 % of long-side partition ends on half-bay lines on all 12 floors; share on whole bay lines (partitions on half-bay lines / on whole bay lines): A 17/17 and 16, 23/23 and 20, 23/23 and 21, 7/7 and 3; B 23 and 21, 21 and 17, 19 and 17, 21 and 2; C 11 and 6, 10 and 5, 24 and 19, 16 and 14. M.3 two-axis figure (0.30 m): A 16/20, 20/26, 21/26, 3/10; B 21/26, 17/23, 17/21, 2/23; C 6/14, 5/12, 19/27, 14/19 |
| M408 | pass | circulation 24.6-33.3 % of the plate on A, B, C (limit 37 %), 24.1 % on E and F (limit 27 %); corridor rows 1.8 m in the wings, 1.2 m beside the solid on the top floor (« couloir rétréci »); every circulation rectangle is a corridor, link, palier, clipped part, flank sliver, end link, entrance bay or reliquat |
| M409 | pass | floor 0 of A, B, C: the entrance (32.4 ; 0.0) lies on a side of the palier; distances of the `anchor="entrance"` rooms in `plans.md` (B: ACC02 12.7 m, ACC01 25.2 m) |
| M410 | pass | no group in more than 3 stretches (worst 2 on A, B, C; E, F <= 2); single-stretch share A 91 % (100 % before the column pass), B 67 %, C 83 % (limit 50 %) |
| M411 | pass | d_f = 4.8 m on B; rows of the 19.2 m and 16.8 m plates; tie by R.8 (bay 3.0 m: 4.2 m without learned depth, 3.6 m with `office.depth_m.p50` = 3.6); not eligible with a French reason: 14.4 m deep ("bande"), long side < 2x short ("barre"), two solids ("volumes pleins") |
| M412 | pass | columns in rooms < 30 m2: A 3/87 (3.4 %), B 9/87 (10.3 %), C 3/89 (3.4 %) (limit 12 %). Stackability / type-area bound (floors 0/1, 1/2, 2/3): A 0.42 0.50 0.12 / 0.71 0.69 0.35; B 0.26 0.51 0.43 / 0.45 0.72 0.96; C 0.27 0.11 0.28 / 0.27 0.23 0.67 |
| M413 | pass | D: 4 of 4 floors go to the engine (call spy), reason in `plans.md` ("barre"); `planner="engine"` never calls the bay planner (spy); `ale stack` without `--plans` on B: 14 files byte-identical to the base commit `7531321` (sha256 in the test); full existing `tests/stack` passes unchanged, **no existing test needed `--planner engine`** (the CLI tests that run `--plans` use case D, which the bay planner hands to the engine) |
| M414 | pass | `plans.md` of A and B carries every item of RD 4.7 (test lists them); DXF / SVG / `report.md` / `layout.json` per floor as before |
| M415 | pass | two runs of B: `layout.json`, `preview.svg`, `report.md` per floor and `plans.md` byte-identical. **The DXF is not** (`layout.dxf` differs between runs; the engine's DXF has the same property); F places the same rooms with the same areas as E (and the transposed rectangles); bay planner <= 0.3 s per floor; `ale stack --plans` on B 5 s |
| M416 | pass | `ruff check`, `ruff format --check`, `mypy`, `python -m ale.contracts.lock --check` clean; tests below |

Gate and test counts: see the end of this file.

### Capacity against demand (no threshold)
Façade bays used / available (S + N rows after the heads): A 27.5/38.0, 33.5/41.0, 26.0/41.5, 11.0/28.5; B 39.0/42.0,
33.5/35.0, 23.5/26.5, 22.0/25.0; C 7.0/37.5, 3.5/45.0, 27.5/42.0, 28.0/28.0. Band length available (two wings, after the
end links): B 32.4, 15.6, 6.6, 3.6 m (the heads take the rest of the wings). Unplaced on B: LOG01 (60 m2, band only: the band
is full), SAL02 x2 (40 m2, no free run of 3.5 bays), DRH01 x3 (12 m2, free runs of 3 half-bays only), DGS01#17. Unplaced
on C3: seven DGS01 offices (the east wing is 8.4 m wide and holds the heads).
Where the stacking should stop filling a bay floor (for the Router): a bay floor uses 24.6-33.3 % of the plate for
circulation and the saturated floors of B stay at 90-98 % placed with the stacking at 110 % of a 25 % `circulation_share`;
setting `circulation_share` to 0.32 (capacity = 68 % of the plate minus the solid) would load the floors to what the section
can host.

### Spec points that needed a decision
1. RD 4.5 lists `D = 30.24 k, 2.5 <= k` but D2.5 (6.0 x 12.6 m) has aspect 2.1: the catalogue follows the aspect rule.
2. M403 « no free run of that many reserve bays »: a free run takes a room when what is left is nothing or a legal reserve
   piece (a leftover half-bay, 1.2 x 4.8 m, has aspect 4 and is not legal). Placement never leaves one (the neighbour
   is widened by one half-bay when it has such a shape, else the floor would be refused: it did not happen).
3. Reserve rooms are not « one per bay »: pieces of 2 to 8 half-bays (aspect <= 2) chosen by a per-run dynamic programme so
   that no column stands inside a reserve or a room under 30 m2 (this brought M412 from 17-21 % to 3-10 %). The reserve is
   reported in rooms and m2.
4. Half-bay rooms (F1.5, F2.5, F3.5) shift the following rooms by half a bay with respect to the column lines; the
   dynamic programme and the column penalty of the shape choice absorb it. Case C has its column lines on half-bay lines
   (phase 2): there, rooms sit on odd half-units.
5. Required / preferred adjacencies (order of concern 3) are not used by the packing: the fixtures have none
   (`REQUIRED_ADJ` = 0). Entrance-anchored rooms are packed first (band near the core, nearest the entrance).
6. `b` rooms (half band) are placed in two lanes; the improvement step is the choice among four deterministic orderings.
7. `plans.md` prints « — » instead of the duration of a bay floor (a wall-clock figure would break byte identity).
8. The D head of a non-facade room is allowed (RD 4.5 lists D after B, b, F for other rooms); none occurs on the fixtures.
9. Not done (M.4b, as specified): typical floor stacking, column grid derived from the section, single-corridor plates,
   corridor by-pass, second row depth, skeleton inside the band. Proposals: (a) a kept part of the band beside the solid
   is refused (not eligible); (b) the entrance hall (80 m2, no admissible shape) lands as D3 in a head far from a
   mid-bar entrance: moving the entrance room to the entrance bay needs the section to host a head there.

### Gates and tests (final)
`ruff check .`, `ruff format --check .`, `mypy`, `python -m ale.contracts.lock --check`: clean.
`pytest tests/stack tests/bayplan -m "not slow" -q`: 143 passed, 1 xfailed (the pre-existing M302), 11 deselected
(`slow`), 348 s; of these 43 are `tests/bayplan` and 11 `tests/stack/test_stack_m4.py`. The full suite is left to the
Router's review.
