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
