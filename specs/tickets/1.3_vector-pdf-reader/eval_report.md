# Ticket 1.3 — Vector-PDF reader · Evaluation report

Implementation: `src/ale/pdfread/{__init__,read,walls,scale,rooms}.py`; tests:
`tests/pdfread/` (`pdf_helpers.py` builds every PDF with PyMuPDF at test time; no corpus
file is committed). Python 3.13, PyMuPDF 1.28.6, shapely 2.2.

| ID | Test | Result |
|---|---|---|
| P1 | `test_pdfread_eval.py::test_P1_two_room_plan` | PASS — 1 plan, 8 walls (0.2 m), rooms office / meeting_room (PDF_TEXT, conf 1.0), scale 0.0254·100/72 (TITLE_BLOCK, 0.9), areas 22.04 / 33.64 m² (exact to 1e-3), door 0.89999 m, `area_text_m2` 33.64 |
| P2 | `test_pdfread_eval.py::test_P2_filled_walls` | PASS — same rooms and areas (±2 % of the line version and of ground truth) |
| P3 | `test_pdfread_eval.py::test_P3_scale_choice` | PASS — `1:100` near the plan + `1:500` in a corner inset → 1:100, confidence 0.6; no scale text → UNKNOWN, `width_m` None |
| P4 | `test_pdfread_eval.py::test_P4_not_a_plan` | PASS — text page score 0.0; bar chart (20 pt bars, axes, grid) score 0.667, `plans == ()` |
| P5 | `test_pdfread_eval.py::test_P5_robustness` | PASS — empty page, 20 000 random segments (≈ 3.5 s), AES-256 encrypted, corrupt, non-PDF, missing file, page out of range: no exception |
| P6 | `test_pdfread_eval.py::test_P6_contract` | PASS — 4 plans round-trip `canonical_json`; `Y_DOWN`; `PDF_VECTOR` |
| P7 | `test_pdfread_gates.py::test_P7_real_corpus_smoke` | Skipped without `ALE_CORPUS_DIR`; run locally (below) |
| P8 | `test_pdfread_gates.py::test_P8_gates` + commands | PASS (below) |

Unit tests (`test_pdfread_units.py`, 26 cases): scale tokens, scale choice, score formula,
pairing thresholds (distance, angle, overlap, angle-bin wrap-around), thick strokes,
filled shapes, Bézier-chain arc fitting (1-3 pieces), door rules and closures,
polygonize filters, labels (exact / prefix / unknown / area text), path collection
(quads, closed polylines, subpaths, malformed items), truncation limits, internal errors.

## Gates (P8)

- `ruff check .` — All checks passed; `ruff format --check .` — 160 files already formatted
- `mypy` (strict, `src/ale`) — Success: no issues found in 88 source files
- `python -m ale.contracts.lock --check` — OK (exit 0)
- Whole suite: `pytest --cov=ale` — 809 passed, 9 skipped, 2 xfailed; total coverage 97 %
- Coverage of `ale.pdfread`: `__init__` 100 %, `read` 97 %, `rooms` 89 %, `scale` 99 %,
  `walls` 95 % (≥ 85 % target)

## P7 smoke (local corpus, not committed)

`ALE_CORPUS_DIR=<corpus> pytest tests/pdfread -k P7 -s`: the three HABS PDFs
(Fallingwater, Farnsworth, Robie) are **scanned** (0 vector paths, 1 full-page image per
page): first pages (and pages 0-3) give `plan_score 0.000`, 0 walls, 0 rooms,
`is_plan_likely False` — correct for this reader (they belong to the raster pipeline).
Extra probe: sampled pages of other corpus PDFs (Arlington site plan, BIS catalogue with
14 197 paths on page 0, Westminster report): none plan-likely, scores ≤ 0.667,
worst page time 1.0 s.

## Interpretations and spec issues (literal readings, to be confirmed)

1. **Plan-likeness length criterion** — "wall length ≥ 20 % of page diagonal × 3" read
   literally as total wall centreline length ≥ 0.6 × page diagonal.
   `plan_score = (min(1, W/8) + min(1, R/2) + min(1, L/(0.6·D))) / 3`, so the score is 1
   exactly when the page is plan-likely (documented in `read.py`).
2. **"walls ≥ 8" counts wall pieces.** Collinear paired walls are deliberately *not*
   merged (unlike 1.2) — merging would leave the P1 plan with ~6 walls and make a 2-room
   plan non-plan-likely. The P1 plan yields exactly 8 walls; for P2 the walls are drawn
   as 8 rectangles (top/bottom split at the partition, partition split by the door) — a
   single rectangle per façade would give 6 walls and fail the literal threshold. A
   2-room plan sits right at the threshold; real plans have far more pieces.
3. **Unpaired thin lines are not walls** (unlike 1.2, where layers say which lines are
   walls); faces used for polygonize are only the *paired parts* of segments (+0.5 pt
   extension), filled-wall outlines and thick-stroke bands. Using whole paired segments
   let a bar chart's grid lines (paired with bar tops) close faces.
4. **Extra face filter** — faces lying ≥ 50 % inside wall material (wall cavities,
   filled shapes such as chart bars) are dropped, in addition to the outer face and thin
   faces. Thin = narrower than 0.5 m (scale known) or 5 pt (scale unknown; the RD gives
   no unknown-scale width).
5. **Scale confidence** — 0.6 is applied when several *distinct* denominators are found;
   the same value written twice keeps 0.9. Bare tokens (`1/100`) are accepted only for
   usual scales (10, 20, 25, 50, 75, 100, 125, 150, 200, 250, 300, 400, 500, 750, 1000,
   1250, 1500, 2000, 2500, 5000, 10000) so that sheet numbers like `1/12` or dates are not
   scales; after a keyword (`ECH`, `ECHELLE`, `SCALE`) any N in 2..100 000 is accepted.
   Matching is on text *lines* (spans joined) so a title split into spans still matches.
6. **Thick strokes** apply to segments left unpaired (pairing runs first), so bold
   parallel wall faces still pair instead of becoming two walls.
7. **Doors** — "next to a wall" = hinge (arc centre) within 25 pt of a wall centreline;
   arcs are Bézier chains of 80-100° sweep; `host_wall` = wall nearest to the door
   segment midpoint within one radius.
8. **One plan per page** (`plan_index` 0); `units_label "pt"`; `config` is accepted but
   unused (no `AleConfig` tunable applies yet), as in 1.2.
