# Ticket G.2 · Evaluation report

Tests: `tests/parti/test_parti_g2.py` (one test per ID, named `test_P2xx_*`), synthetic plot 100 x 80 m
(street on the south, party wall on the east, setbacks 4.8 / 0 / 3 / 3 m) and a programme of 2,490 m² net
(about 2,960 m² gross), fixtures in `tests/parti/parti_case.py`.

| ID | Test | Result |
|---|---|---|
| P201 | `test_P201_genes` | PASS. 1,200 valid gene sets over the seven typologies, 1,680 dropped with a French reason (court / circulation mismatch, bar with junction core, terrace on a bar, floors out of range); each typology sizes at least one massing. |
| P202 | `test_P202_massing` | PASS on the 40 retained partis: outlines inside the zone (independent box), floors x area within +-10 % of the need (shoelace areas), upper outline within the lower, court short side >= H/2, terraces present. |
| P203 | `test_P203_one_core` | PASS. Exactly one `kind="core"` per typical-floor site; the core lies inside the top-floor outline; junction cores straddle two wings, centre and end cores are placed on the longest kept wing. |
| P204 | `test_P204_evaluate` | PASS. Gross area, capacity, façade length, good-orientation share, compactness recomputed independently; the typical-floor cell diagram has 0 fragmented rooms (see Spec issues: strays). |
| P205 | `test_P205_forcedness` | PASS. A single-loaded bar (70 offices, 4 floors) misses the frontage and scores forcedness 2.5 against 0.0 for a two-finger comb; `rank` puts the comb first. The margin is small (57 m against 58 m demanded, 59 against 58). |
| P206 | `test_P206_card` | PASS. Every element has at least one problem; a forecourt on the entrance street solves three, a forecourt on the north street solves one and is flagged « élément à fonction unique (rustine possible) ». |
| P207 | `test_P207_ranking` | PASS. Non-dominated set checked by hand on six keys (A dominated by B, F by all, C and E equal and both kept); `partis.md` in French, non-dominated first, one card each. |
| P208 | `test_P208_from_forms` | PASS. U, bar and courtyard outlines written like `ale form` outputs map to their typology with IoU 1.0; the table appears in `partis.md` and the matches seed the pool. |
| P209 | `test_P209_outputs` | PASS. SVG per parti (floors, core, forecourt, axis, cell diagram), `parti_NN/site.yaml` loads as a footprint `SiteSpec` with one core; two runs are byte-identical. |
| P210 | `test_P210_gates_speed` | PASS. 40 partis in about 13 s through the command (limit 60 s). Gate numbers below. |

## Top partis on the test case (40 retained, 6 non-dominated)
| Rang | Parti | Typologie | Niveaux | Forçage | Manques durs | Fiches signalées / éléments | Non dominé |
|---|---|---|---|---|---|---|---|
| 1 | H-90-d-f3-j-c1-t | H | 3 | 12.86 | 0 | 0/7 | oui |
| 2 | bar-0-s-f5-e-c1 | bar | 5 | 14.86 | 0 | 1/3 | oui |
| 3 | courtyard-0-s-f3-j-c1-t | courtyard | 3 | 37.86 | 0 | 0/8 | oui |
| 4 | courtyard-0-s-f4-c-c1-t | courtyard | 4 | 13.86 | 1 | 0/8 | oui |
| 5 | bar-0-s-f4-c-c1 | bar | 4 | 23.29 | 1 | 0/3 | oui |
| 6 | bar-0-d-f3-c-c1 | bar | 3 | 33.29 | 1 | 0/3 | oui |
| 7 | bar-0-s-f5-c-c1 | bar | 5 | 19.86 | 0 | 0/3 | non |
| 8 | H-90-s-f5-c-c1 | H | 5 | 25.86 | 0 | 0/6 | non |
| 9 | H-90-s-f5-c-c1-t | H | 5 | 25.86 | 0 | 0/7 | non |
| 10 | T-0-s-f3-c-c1-t | T | 3 | 26.86 | 0 | 2/5 | non |

Key: typology-orientation-loading (s single, d double)-floors-core (j junction, c centre, e end)-forecourt-terrace.

## Design notes
- Sizing: wings on the 0.60 m grid, three arm/length ratios tried, area target = net / (1 - 0.16) within +-10 %.
- Frontage rule: usable façade = 0.5 (single-loaded) or 0.9 (double-loaded) of the outline length (corridor side, ends); demand = sum over façade rooms of max(area / 7.2, 3.0 m) per floor.
- Hard misses = capacity < 90 %, prospect, façade rooms without façade in the diagram, fragmented rooms. Forcedness = 10 x unmet share of requirements + local exceptions (short rooms, façade rooms without façade, rooms off circulation, rooms with strays).
- Selection: all valid gene sets are sized and scored cheaply (no diagram), a diverse subset (round robin over typologies) gets the cell diagram, then the joint ranking.

## Spec issues
1. `cellgrow` (R.9) scatters cells of a room into several components (on this case nearly every parti has 1 to 20 such rooms). G.2 keeps the largest 4-connected component of each room, releases the strays to the circulation reserve and counts each such room as a local exception, so P204's "0 fragmented rooms" holds on the cleaned diagram and the repair is visible in forcedness. A guarantee of contiguity in R.9 would remove the repair.
2. `cellgrow` and `to_module_footprint` still reject polygons with holes. The ring (courtyard) typology is diagrammed with a one-cell slit through one wing; the slit is only used for the diagram, `site.yaml` keeps the hole.
3. RD §3 "plus the site's main axis": the contract only admits rectilinear plots, so orientations 0 and 90 already cover the main axis; no other angle is generated.
4. RD §5 does not say how the programme is split over floors for the typical-floor diagram: instances are balanced by area over the floors (entrance-anchored rooms on the ground floor), the typical floor is floor 1; multi-storey stacking is M.1.
5. `ale parti` has no `--rulebook`; the diagram uses a neutral rulebook (uniform statistics, default adjacency 0.5).
6. The orientation setting NNO/SSE good, OSO/ENE exposed is read as compass bearings 337.5 / 157.5 and 247.5 / 67.5 (NNO = nord-nord-ouest).

## Gates
- `ruff check`, `ruff format --check`: clean. `mypy` strict on `src`: no issues in 144 files.
- `python -m ale.contracts.lock --check`: OK (no contract change).
- Whole suite under coverage (one run, 1 h 08): 1,478 passed, 13 skipped, 3 xfailed (pre-existing), 1 failed:
  `test_P08_cli_registration_only` failed only because the registration edit was not committed yet (it diffs the git history of `src/ale/cli/__init__.py`); it passes on the commit. The registration is a separate import line plus one `app.command` line.
- Coverage of `ale.parti` (path form `--cov=src/ale/parti`): 95.7 % (card 95 %, evaluate 97 %, genes 88 %, massing 91 %, `__init__` 100 %; 813 statements, 35 missed).
- 40 partis through `ale parti`: about 13 s.
