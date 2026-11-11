# Ticket X.3 · Evaluation report

Base commit `c3f8b33`. No contract change (contracts 1.6.0, `lock --check` OK).

## Results

| ID | Test | Result |
|---|---|---|
| X301 | `test_X301_holes_intake` | pass. `footprint: {exterior, holes}` loads; the ring (24 x 24 m, 8 x 8 m courtyard) gives a module footprint with one clockwise hole. Errors name the hole (`Cour intérieure k (holes[k])`): outside, crossing, touching the outline, overlapping another hole, non-orthogonal, degenerate; schema errors (unknown key, missing `exterior`, bad `holes`); too small (< 3 x 3 modules after snapping) is `E_SITE_TOO_SMALL`, checked at the grid. Holes snap outward (the material shrinks); holes that merge after snapping are refused. |
| X302 | `test_X302_facade_n`, `test_X302_rectangles_and_l_unchanged` | pass. Hand-computed values (s = 2, one band per piece, comments in the test): U 88, comb (3 fingers) 126, ring 120 modules; ring perimeter 160 modules (exterior 120 + courtyard 40). Rectangles and 5 L orientations equal a copy of the pre-X.3 single-cut formula; the feasibility reports of P25 on a rectangle and an L have the same sha256 as at `c3f8b33` (`1ded6e18cb96c834`, `9d1be35f679ec01b`, computed by running the base source). |
| X303 | `test_X303_end_to_end` | pass. `ale program check` prints `Emprise : 4 pièces, 3 jonctions, 1 cours intérieures`; `ale generate` with P25 (`time_budget_s = 2.0`, seed 3) writes a layout that passes `check_layout` and tiles the footprint exactly. |
| X304 | `test_X304_gates` + gates below | see numbers below. |

## Changes

- `program/site.py`: `footprint` accepts a list (as before) or `{exterior, holes}`; hole normalisation and geometric checks; `to_module_footprint` snaps holes, keeps them in `ModulePolygon.holes`, sliver loss includes them; `module_perimeter_mm` adds the hole perimeters (unchanged without holes).
- `program/feasibility.py`: `facade_usable_mm` subtracts the cut lengths of all junctions (`fp.junctions`); identical to the legacy formula for at most two pieces.
- `program/prepare.py`: `InputCheck.structure` (pieces, junctions, courtyards).

## Gates

- `ruff check`, `ruff format --check` (283 files), `mypy --strict` on src (138 files): clean. `python -m ale.contracts.lock --check`: OK.
- Whole suite under coverage (`--cov=ale.program`, no marker filter, so slow tests included): 1474 passed, 13 skipped, 3 xfailed (pre-existing xfails), 63 min.
- Coverage of the touched modules: `program/feasibility.py` 100 %, `program/prepare.py` 96 %, `program/site.py` 96 %.

## Spec issues

1. **`ale program check` lives in `cli/commands/program.py`**, which the RD "Files" list does not include. The report line needs it, so a 4-line edit there prints `InputCheck.structure`. No other CLI change; the JSON output is untouched (the feasibility report model has no new field, which keeps reports byte-identical).
2. **"Each hole at least 3 x 3 modules"** is not defined for non-rectangular holes: implemented as the bounding box of the snapped hole.
3. **Open contacts of a ring** (two pieces that touch but are not a tree edge) are not junctions, so the façade estimate still counts both faces; this follows the RD ("all junctions"), at the price of a slight over-estimate on rings.
4. **G.1 spec issue 4 (cut of more than two pieces)** is closed by the change in `facade_usable_mm`; issue 1 (courtyards refused at intake) is closed by the intake change.
