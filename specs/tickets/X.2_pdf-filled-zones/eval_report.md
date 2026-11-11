# Ticket X.2 · Evaluation report

Tests: `tests/pdfread/test_zones_eval.py` (helpers `tests/pdfread/zone_helpers.py`); every fixture is built with PyMuPDF.

| ID | Test | Result |
|---|---|---|
| Z01 | `test_Z01_zones` (+ name / unknown-scale variant) | pass: 12 zones, 4 colours, `area_text_m2` exact, plan-likely, score 1.0 |
| Z02 | `test_Z02_rotated_text` (+ nearest-area-text variant) | pass: texts rotated 90° attach to the right zone |
| Z03 | `test_Z03_frames` | pass: light frame dropped, duplicates merged, 12 rooms |
| Z04 | `test_Z04_unchanged` | pass: plan + warnings + verdict of 4 pre-X.2 fixtures hash identically to the pre-change reader; zone path never entered for wall-loop plans |
| Z05 | `test_Z05_score` | pass: `ale score` on a 2-cluster zone sheet, 12/12 lines matched, plans 1 and 2 |
| Z06 | gates | pass: ruff, format, mypy strict (133 files), lock --check OK; suite without tests/topology (another Worker, too slow under load): 1358 passed, 13 skipped, 3 xfailed (pre-existing), total coverage 97 %; `zones.py` 99 % (branch) |

## Implementation notes
- `read.py` records every fill with its RGB (`_Page.zone_fills`, separate from `filled`, so wall extraction is untouched).
- Near-black fills (wall material) and slivers (< 0.3 m / 2 pt short side) are excluded in addition to RD §3 so filled-wall plans never produce zones.
- `zones_credible`: zone mode needs at least half of the zones to carry an area text or a name; otherwise a coloured bar chart would read as a plan.

## Spec issues
1. RD §3 says plan-likeness "counts zones as rooms", but the existing formula also needs `W >= 4` merged walls and wall length >= 0.6 D. Z01's walls are single strokes, which `extract_walls` does not read as walls (0 walls), so the formula can never pass on such a sheet. Following the intent, a zone-mode page is plan-likely (score 1.0) once zones are credible, with no wall requirement.
2. RD asks for the colour "in the room id suffix or a warning-free field": it is put in `raw_label` (`fill=#RRGGBB`) when no name text exists, as the RD's own fallback says.
3. RD §3 wants frames dropped at > 80 % child coverage; with the 0.2 m gaps first drawn in the fixture the children cover at most 79.7 %, so the fixture uses 0.1 m gaps (the rule itself is unchanged). A frame needs at least two children.
4. "Near-white" is defined here as every channel >= 0.96; a "large light" frame must therefore be darker than that (the fixture uses 0.9 grey).
