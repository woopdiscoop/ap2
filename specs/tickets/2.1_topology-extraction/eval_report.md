# Ticket 2.1 — Evaluation report

Library `ale.mining` (`src/ale/mining/{__init__,topology}.py`): `Contact`, `PlanTopology`,
`extract_topology(plan, config)`. No CLI wiring. Tests in `tests/mining/`.

## Results

| ID | Test(s) | Result |
|---|---|---|
| T1 | `test_T1_grid_plan`, `test_T1_grid_plan_millimetres[Y_UP, Y_DOWN]` | PASS — 7 contacts, all shared lengths exact (4.0/5.0/6.0/3.5 m vs truth, 0 % error), 3 DOOR (1 opening each); P = R = 1. Same in mm, Y-up and Y-down. |
| T2 | `test_T2_thin_touch` | PASS — 0.4 m facing → no contact; control at 1.0 m → one WALL contact of 1.0 m. |
| T3 | `test_T3_exterior` | PASS — façade lengths of the 6 perimeter rooms exact (0 % error). |
| T4 | `test_T4_noisy[0..9]` | PASS — ±3 cm vertex jitter, 10 seeds: contact P = R = 1 on every seed (≥ 0.9 required); door pairs P = R = 1; lengths within ~1.5 %. |
| T5 | `test_T5_no_scale` | PASS — unknown scale → `None`. |
| T6 | `test_T6_determinism[0..4]` | PASS — shuffled rooms and walls → identical model and JSON. |
| T7 | `test_T7_gates` + full run | PASS — ruff, ruff format --check, mypy strict clean (repo-wide too); `python -m ale.contracts.lock --check` → 0; whole suite 813 passed, 8 skipped, 2 xfailed; coverage `ale.mining` **99 %** (topology.py 197 stmts, 0 missed, 2 partial branches). |

Extra unit tests (`test_mining_units.py`): windows are not doors, fidelity per source kind,
default thickness, walls without thickness / far walls ignored, rooms drawn to the centreline
(gap 0), oblique and slanted edges, room with a hole + separate building, empty plan,
unconvertible plan (warning + `None`), edge budget (warning + skip), helper functions.

## Implementation notes and spec readings (please review)

1. **Shared length formula — deviation from the "implement as" hint.** Real room polygons
   are drawn on the wall faces (`ale.cad.rooms` polygonizes wall faces), so buffering each
   room by half the wall thickness makes the two buffers merely *touch* at the wall
   centreline: `area(buffer_a ∩ buffer_b)` is ≈ 0, and the hint's `area / (2·h)` cannot be
   applied literally. Any buffer large enough to overlap also adds rounded end caps that
   inflate a contact by ≈ 1.2–1.6·h at each end (≈ +0.25 m: +6 % on a 4 m wall — fails the
   2 % of T1 — and it would make the T2 0.4 m touch exceed 0.6 m). Implemented instead
   (same concept, the centreline length of the strip between the rooms): two rooms touch
   where their edges face each other (lines within 30°, overlapping orthogonal projection)
   across a gap ≤ `h_a + h_b + 0.10 m` (0.10 m = tolerance for drawing noise, needed by T4);
   the facing intervals are merged per edge and `shared_m` is the mean of the two rooms'
   facing lengths. Truth used by the tests: the length along which the two rooms face each
   other. Works both for face-drawn rooms and for rooms drawn to the centreline (gap 0).
2. **Default thickness**: "default 0.10 m if none" read literally as the *thickness*
   (half = 0.05 m), not the half-thickness. With the 0.10 m tolerance, face-drawn rooms
   with no nearby wall thickness touch only if the gap ≤ 0.20 m.
3. **Doors**: only openings of kind `DOOR` are counted (`openings` = number of door
   midpoints in the shared region); a window between two rooms does not make a DOOR
   contact. The spec says "opening"; literal reading would count windows. Shared region =
   quadrilaterals between the facing edge parts, widened by 0.05 m.
4. **Exterior**: the outer boundary is the exterior ring(s) of the union of the rooms grown
   by their half thickness (closing with the 0.10 m tolerance bridges wall gaps); holes of
   that union (courtyards) are not façade (literal "outer boundary"). The façade length uses
   the same facing-edge rule within 0.3 m; without it the perpendicular edges would add up
   to 0.2 m per corner (+5 % on a corner room). A room is listed when its façade length > 0.
5. `config` is accepted but unused (no relevant setting in `AleConfig`; thresholds are
   module constants). `PlanTopology` has no warnings field: problems are logged on
   `ale.mining.topology`. If `to_metric()` fails (`ValueError`), the result is `None`
   with a warning (the RD only names the unknown-scale case).
6. Bounded loops: O(rooms²) with a bbox prefilter; edge comparisons per pair capped at
   1 000 000 (pair skipped with a warning). Lengths/areas rounded to 1e-6 m; rooms
   processed in id order (deterministic regardless of input order).
