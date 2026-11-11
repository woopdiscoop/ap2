# Ticket R.3 · Evaluation report

Files: `src/ale/analysis/{__init__,syntax}.py`, `src/ale/export/report.py` (new section only),
`tests/analysis/**`, `tests/export/test_export_syntax.py`. No contract change
(`python -m ale.contracts.lock --check`: OK). Layout JSON, DXF content and SVG unchanged.

## Results

| ID | Test | Result |
|---|---|---|
| S301 | `test_S301_hand_values`, `test_S301_measures_small_graphs` | pass: 6 rooms on one corridor, depth 2, MD 13/7, RA 2/7, integration 7/2, control 1/7 for every room; CIRC: MD 1, RA 0, integration `None`, control 7 (exact `Fraction`s) |
| S302 | `test_S302_required_door` | pass: REQUIRED pair gets the edge from share 12 (= c) up, none at 11, 10 or no contact; non-required pair sharing 40 gets none |
| S303 | `test_S303_walk` (+ `_vertical_corridor`, `_two_contacts`) | pass: hand Manhattan distances 20.5, 21.5, 47, 53.5 modules equal `walk_m` exactly; vertical corridor 31 / 81 modules; module size scaling |
| S304 | `test_S304_entrance_*`, `test_S304_two_components_and_longest_contact`, `test_S304_vertical_access_edge` | pass: touching the access edge → not inferred; otherwise inferred (nearest rectangle, clamp point) and still computed; no circulation → no crash |
| S305 | `test_S305_fixtures` | pass: P8, P25, P60 seed-3 layouts: every room finite depth and walk, two runs equal |
| S306 | `test_S306_report`, `_existing_sections_untouched`, `_sentence_variants` | pass: section, one row per room, zone means, French format, two sentences; the 25 existing export tests unchanged and green |
| S307 | `test_S307_unchanged` | pass: `layout.json` and `preview.svg` sha256 identical to the pre-change run; DXF content hash identical (see issue 3) |
| S308 | `test_S308_gates` + gate run | pass: ruff check and format clean, mypy strict on src (119 files) clean, lock --check OK, `ale.analysis` coverage 99 % (line 100 %, branch 71/72, path-form `--cov=src/ale/analysis`), whole suite 1239 passed, 13 skipped, 3 xfailed (xfails and skips pre-date this ticket) |

## Spec issues

1. **Section heading level.** RD §4 asks for a section "Lecture spatiale (space syntax)", but the
   existing test `test_X08_report_sections` pins the exact list of `#` / `##` headings of
   `report.md`, and S306 requires the existing report tests to stay unchanged. Following the
   intent of both, the block is a `###` heading appended after `## Fichiers`, so the existing
   heading list and the table parsers of the other sections are untouched.
2. **Share-length helper location.** RD context names the helpers in `ale.geometry.evaluate`; the
   function (`share_length`) lives in `ale.geometry.checks` and `evaluate.py` imports it. The
   analysis imports it from `checks`.
3. **S307 "byte-identical" for DXF.** ezdxf output is not byte-stable even for identical input
   (creation timestamps, GUID handles and object/layout ordering differ from one process to the
   next, before this ticket as well). JSON and SVG are compared byte for byte (sha256); the DXF is
   compared through a hash of its layers and entities (kind, layer, geometry). Verified equal with
   the pre-change `report.py`.
4. **Unspecified numerics.** The RD does not say what RA and integration are for graphs of fewer
   than 3 nodes, nor for a node unreachable from the entrance: `mean_depth` needs k >= 2, RA
   k >= 3 (else `None`); unreachable nodes have `depth` `None`; the report prints "—". RA = 0 gives
   integration `None` as asked (the report also prints "—"). k and MD are taken over the node's
   connected component, `ENTRANCE` and `CIRC` included.
5. **Several circulation components.** The RD says one component in a valid layout; for several the
   nodes are named `CIRC#1`, `CIRC#2`… (plain `CIRC` when there is one). `ENTRANCE` links to every
   component touching the access edge, else only to the nearest rectangle's component.
6. **Walking model.** "Manhattan along circulation centrelines through shared boundaries" is
   made precise in the `syntax.py` docstring: a rectangle's centreline is parallel to its longer
   side (horizontal when square), rectangles are crossed at the midpoint of their common boundary,
   the entrance point is the midpoint of the longest access-edge contact. A room narrower than c on
   the corridor gets no door, hence no depth and no walk (room R06 of the export fixture).
7. **Coverage.** `ale.analysis` line and branch coverage: the one partial branch in `_walks`
   (an already-present edge of equal or shorter weight in the walking graph) cannot occur, since
   two circulation rectangles never share two distinct marked points.
