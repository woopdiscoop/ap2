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
| G302 | `test_g302_areas` | pass: the shortfall reported in the metrics equals the recount; 4 of 6 candidates have every room at its count, 2 have one room short by at most 7 % of its cells (enclosed by other rooms); core cells untouched (55 core cells) |
| G303 | `test_g303_anchors` | pass: the hall holds the front-line cell nearest the entrance, circulation touches both cores |
| G304 | `test_g304_courtyard` | pass: 19 x 19 courtyard in the 6 candidates, 4 open (U) and 2 enclosed (hole of the outline); the state is checked against the polygon holes |
| G305 | `test_g305_outline`, `test_g305_notches_are_removed` | pass for the 12 outlines (6 plain + 6 courtyard): one polygon, orthogonal, closed, on the 0.60 m grid, area equal to the simplified cells and within 1 % of the built cells (largest deviation 0.18 %), no notch narrower than 2 cells, vertices before/after reported |
| G306 | `test_g306_yaml` | pass: `form_kk.yaml` loads as `SiteSpec` (mode footprint), cores equal, entrance snapped to the outline, `access_edge` valid |
| G307 | `test_g307_deterministic` | pass: two fresh processes and the in-process run give byte-identical files (13 files); 6 distinct outlines for K = 6 |
| G308 | `test_g308_ranking` | pass: `forms.md` order equals the sort by the RD section 5 key, recomputed independently from `form_kk.yaml` and the cell grid (short rooms, facade rooms without facade, rooms off circulation, vertices, compactness, footprint, coverage, facade length) |
| G310 | `test_g310_contiguity` | pass: every room and the circulation zone is one 4-connected region in the 12 candidates (0 fragmented rooms); a room that cannot reach its count is reported short, never scattered |
| G309 | `test_g309_gates` + gates below | pass: lock check OK; a P25-size case (25 rooms, plot 40 x 30 m) runs in well under 10 s per candidate (about 0.5 s); ruff, format, mypy and coverage below |

## K = 6 candidates on the test case (ranking order, no courtyard)

| Rank | Candidate | Short rooms | Facade rooms without facade | Rooms off circulation | Vertices | Compactness | Footprint m2 | Facade m | Coverage |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 04 | 0 | 0 | 17 | 128 | 2.114 | 821.5 | 238.8 | 0.469 |
| 2 | 03 | 0 | 2 | 13 | 88 | 1.619 | 879.5 | 190.2 | 0.503 |
| 3 | 06 | 0 | 6 | 12 | 50 | 1.362 | 820.1 | 154.2 | 0.469 |
| 4 | 01 | 0 | 8 | 16 | 64 | 1.256 | 821.5 | 144.0 | 0.469 |
| 5 | 05 | 1 | 6 | 13 | 78 | 1.612 | 821.2 | 184.8 | 0.469 |
| 6 | 02 | 1 | 8 | 5 | 56 | 1.312 | 816.8 | 150.0 | 0.468 |

Fragmented rooms in the 12 candidates (6 plain, 6 courtyard): 0.

With `--courtyard` (19 x 19 cells): ranks 03 (enclosed), 02 (open), 05 (open), 01 (enclosed),
04 (open), 06 (enclosed); vertices 72 to 104, compactness 1.78 to 2.15.

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
- A room is always ONE 4-connected region. A stuck room first takes one circulation cell next to it
  (circulation stays in one piece, keeps its cores, keeps at least 75 %, 50 % as last resort), then
  one cell from a neighbour that still has a free way out (the neighbour stays in one piece and
  regrows elsewhere), then is released and reseeded as one piece on the mass edge (up to 10 times,
  only when the outside stays connected). Otherwise it is reported short. Circulation may exceed its
  16 % target (up to 3 times) when a core is not yet touched (reported as `circ_extra`).
- Outline: notches (outside cell with building on two opposite sides) are filled, or the wall
  on one side is cut, whichever changes less area (tie: fill); cores are never cut, the building
  must stay in one piece and every outside cell must still reach the margin or a courtyard.

## Gates

- ruff check: clean. ruff format --check: 273 files already formatted. mypy strict on `src`: no issues (133 files).
- `python -m ale.contracts.lock --check`: OK.
- Whole suite once under `--cov=src/ale` (on the committed tree): 1410 passed, 13 skipped, 3 xfailed
  (pre-existing), 0 failed, 75 min. Total coverage 98 %.
- Coverage of `ale.form` (path form `src/ale/form/`): `grow.py` 97 %, `metrics.py` 100 %, `outline.py` 99 %,
  `__init__.py` 100 %; `cli/commands/form.py` 97 %.

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
7. **G310 added by the Router** (contiguity: every room and the circulation zone is one 4-connected
   region). Consequence for G302: a room enclosed by others can end a few cells short, which is
   reported (`short` in the metrics and `forms.md`); the circulation may give cells to stuck rooms
   (not below 50 % of its target, tested), so `Rooms off circulation` is higher than before.
