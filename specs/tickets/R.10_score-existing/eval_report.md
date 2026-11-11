# Ticket R.10 · Evaluation report

Synthetic fixtures only (`tests/score/score_helpers.py`: PyMuPDF sheets with grid plans at 1:100, a
DXF, openpyxl programmes and Annexe files). No real project file is used or committed.

| ID | Test | Result |
|---|---|---|
| S1001 | `test_S1001_match` | pass: 2 plans on one page, 12 rooms (written areas = programme ±0–8 %), 12/12 matched to the right line, plan index 1/2 reported |
| S1002 | `test_S1002_tolerance` | pass: -3 % « à ajuster », -8 % « sous le programme », +12 % « au-dessus de la tolérance »; `--tolerance-pct 10` makes -8 % « à ajuster » |
| S1003 | `test_S1003_unmatched` | pass: the 100 m² line (nearest room 300 m²) and the 300 m² room are both listed |
| S1004 | `test_S1004_facade` | pass: centre cell of a 3 x 3 grid flagged, corner cell OK |
| S1005 | `test_S1005_stairs` | pass: one stair core OK; two stair rooms in one core = 1 core OK (U-14); two apart = « à vérifier »; none = absente; counts reported |
| S1006 | `test_S1006_annexe` | pass: `--annexe` gives the same coverage/matches/totals as `--programme` on the P.2 export of the same file; usage errors exit 2 |
| S1007 | `test_S1007_outputs` | pass: French `score.md` + `score.json`, byte-identical on two runs, nothing written outside `--out` (nor in the cwd), no absolute path in the JSON |
| S1008 | `test_S1008_gates` | pass (`lock --check`); other gates below |

## Gates

- `ruff check`, `ruff format --check`: clean. `mypy` (strict, `src/ale`): no issues in 129 files.
- `python -m ale.contracts.lock --check`: OK (no contract change).
- Coverage of `ale.score` under the whole suite: `__init__` 100 %, `match.py` 99 %, `report.py` 99 % (≥ 90 %).

## Spec issues

1. **One plan per PDF page.** RD §2 says "reads every plan on the page", but `read_pdf_page` returns at most one
   `PlanGeometry` per page (S1001 needs 2 plans on one sheet). Plans are therefore separated in `ale.score` by spatial
   proximity of the rooms (rooms closer than 1.5 m belong to one plan); the index is reported in reading order (top row,
   then left). The reader was not changed (outside the ownership).
2. **No stair geometry exposed.** RD §4 asks for stair cores "detected from the stair geometry the reader exposes";
   neither reader exposes stairs. Cores are the clusters of rooms labelled « escalier » (taxonomy type `stair`, rooms
   within 3 wall thicknesses form one core, so several stairs in one core count once, U-14). Unlabelled stairs are not
   seen (stated in « Limites »). Stair rooms and programme lines of type `stair` are excluded from the area matching.
3. **Gap classes not fully specified.** RD §4 defines ≤ tolerance, below -tolerance and above +10 %; a gap in
   (tolerance, +10 %] is classed « à ajuster » (the upper limit is `max(10 %, tolerance)`), and an exactly zero gap
   « conforme ».
4. **`--page` is 1-based** (the reader is 0-based); `--building SLUG` was added for an Annexe with several buildings
   (usage error listing the slugs when it is missing and there are several). Default `--out` is `./score_out`.
5. The façade test buffers rooms by the median wall thickness and takes the outer boundary of the union; a room whose
   distance to it is at most one thickness touches the façade. Courtyard faces are not counted as façade.
