# Ticket G.3 · Evaluation report

Test case (`tests/form/case_helpers.py`): plot 54 x 42 m (90 x 70 cells of 0.60 m), setbacks
4.8 / 0 / 3 / 3 m (south street, east party wall, north and west streets), main entrance on the
south edge, two cores (stair 3.0 x 3.6 m, lift 3.0 x 3.0 m), programme of 30 rooms, 690.0 m2 net
(2 270 cells, circulation target 16 % = 306 cells). Tests: `tests/form/test_form_g3.py`
(G301..G309) and `tests/form/test_form_units.py` (edge cases of outline, growth, CLI).

## Results by ID

| ID | Test | Result |
|---|---|---|
| G301 | `test_g301_one_mass` | pass: 6 candidates, one connected building (independent flood fill), outside connected to the streets (independent check + `outside_cells_connected`), no room cell closer to an edge than its setback (shapely distance) |
| G302 | `test_g302_areas` | pass: every room reaches its cell count in all 6 candidates, shortfall count in the metrics equals the recount, core cells untouched (55 core cells) |
| G303 | `test_g303_anchors` | pass: the hall holds the front-line cell nearest the entrance, circulation touches both cores |
| G304 | `test_g304_courtyard` | pass: 19 x 19 courtyard in the 6 candidates, 4 open (U) and 2 enclosed (hole of the outline); the state is checked against the polygon holes |
| G305 | `test_g305_outline`, `test_g305_notches_are_removed` | pass for the 12 outlines (6 plain + 6 courtyard): one polygon, orthogonal, closed, on the 0.60 m grid, area equal to the simplified cells and within 1 % of the built cells (largest deviation 0.18 %), no notch narrower than 2 cells, vertices before/after reported |
| G306 | `test_g306_yaml` | pass: `form_kk.yaml` loads as `SiteSpec` (mode footprint), cores equal, entrance snapped to the outline, `access_edge` valid |
| G307 | `test_g307_deterministic` | pass: two fresh processes and the in-process run give byte-identical files (13 files); 6 distinct outlines for K = 6 |
| G308 | `test_g308_ranking` | pass: `forms.md` order equals the sort by the RD section 5 key, recomputed independently from `form_kk.yaml` and the cell grid (short rooms, facade rooms without facade, rooms off circulation, vertices, compactness, footprint, coverage, facade length) |
| G309 | `test_g309_gates` + gates below | pass: lock check OK; a P25-size case (25 rooms, plot 40 x 30 m) runs in well under 10 s per candidate (about 0.5 s); ruff, format, mypy and coverage below |

## K = 6 candidates on the test case (ranking order, no courtyard)

| Rank | Candidate | Short rooms | Facade rooms without facade | Rooms off circulation | Vertices | Compactness | Footprint m2 | Facade m | Coverage |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 05 | 0 | 0 | 6 | 58 | 1.174 | 818.6 | 134.4 | 0.469 |
| 2 | 06 | 0 | 0 | 8 | 70 | 1.384 | 818.3 | 157.8 | 0.469 |
| 3 | 04 | 0 | 0 | 10 | 76 | 1.405 | 818.6 | 159.0 | 0.469 |
| 4 | 01 | 0 | 0 | 13 | 52 | 1.248 | 818.3 | 142.8 | 0.469 |
| 5 | 03 | 0 | 0 | 15 | 62 | 1.291 | 913.0 | 156.0 | 0.523 |
| 6 | 02 | 0 | 1 | 7 | 74 | 1.446 | 819.4 | 165.6 | 0.469 |

With `--courtyard` (19 x 19 cells): ranks 06 (open), 02 (open), 04 (enclosed), 03 (open),
01 (enclosed), 05 (open); vertices 78 to 104, compactness 1.81 to 1.98.

## Method notes (decisions inside the spec)

- Growth: one mass; hall at the front-line cell nearest the main entrance; circulation seeded on
  the hall, compact (neighbour count, penalty on façade cells) and attracted to the nearest
  untouched core; the next room is seeded once the previous reached 60 % of its count (for the
  circulation: and every core is touched). Rooms grow in balance (lowest filled fraction first).
  Scores: own compactness, façade (touches outside) for rooms that need it and a small penalty
  for the others, circulation contact, partner and core attraction, party-wall attraction for
  storage and archive, avoid penalty, a mass term (compactness and no narrow notch), hash noise.
- Outside rule: local simple-point test on the 8-ring; when more than one run of outside cells
  touches the cell, a flood fill from each outside neighbour must reach a street cell or a
  courtyard cell. A local-only test would forbid rooms from joining (a room closing a ring of
  a pocket that is still anchored elsewhere), so the global check decides the ambiguous cases.
- Stuck rooms reseed on the mass edge (up to 8 times); circulation may exceed its 16 % target
  (up to 3 times) when a core is not yet touched (reported as `circ_extra`).
- Outline: notches (outside cell with building on two opposite sides) are filled, or the wall
  on one side is cut, whichever changes less area (tie: fill); cores are never cut, the building
  must stay in one piece and every outside cell must still reach the margin or a courtyard.

## Gates

- ruff check: clean. ruff format --check: 273 files already formatted. mypy strict on `src`: no issues (133 files).
- `python -m ale.contracts.lock --check`: OK.
- Whole suite once under `--cov=src/ale`: 1408 passed, 13 skipped, 3 xfailed (pre-existing), 1 failed
  (`test_P08_cli_registration_only`, which diffs `src/ale/cli/__init__.py` while the registration was
  still uncommitted; it passes on the committed tree). Total coverage 98 %.
- Coverage of `ale.form`: `grow.py` 98 %, `metrics.py` 100 %, `outline.py` 99 %, `__init__.py` 100 %
  (path form `src/ale/form/`), `cli/commands/form.py` 97 %.
- The whole suite takes 77 min under coverage in this environment (not caused by G.3: `tests/form` runs in about 20 s).

## Spec issues

1. **Entrance "touches" the hall (G303).** With setbacks the main entrance lies on the plot edge
   and the buildable zone starts one setback further in, so the hall cannot touch the entrance
   point. Interpreted as: the hall holds the front-line cell nearest to the entrance (distance
   from the entrance to the hall equals the distance to the nearest buildable cell).
2. **Entrances in `form_kk.yaml` (RD section 2, "entrances carried over").** A `footprint` site
   requires entrances on the outline (tolerance 0.1 m, contract 1.5.0) while the plot entrance
   is on the street edge. The entrances are carried over (same label and `main` flag) and
   snapped to the nearest point of the outline; `access_edge` is the outline edge nearest to the
   main entrance.
3. **Rooms "short of their area" (RD section 5, G302).** A room is short when it has fewer cells
   than `round(area / 0.36 m2)`; circulation is not counted as a room. Programme rooms of type
   stair or lift are grown like any room (the site cores are separate fixed cells).
4. **"Area within 1 % of the built cells" (G305)** holds on the test case (at most 0.18 %), but it
   is not guaranteed in general: a long one-cell channel that leads to a wider pocket can only be
   cut, which may exceed 1 % on a small building. The outline reports cells filled and cut, and
   the area always equals the simplified cells exactly.
5. **Courtyard state (RD section 5)** is read on the simplified outline (a courtyard whose neck
   was filled counts as enclosed, a hole of the outline), not on the raw growth grid.
6. **Courtyard size** is 19 x 19 cells by default and is reduced to half the shorter side of the
   buildable zone when the zone is too small for it (minimum 3 cells); the RD does not say what
   to do then.
