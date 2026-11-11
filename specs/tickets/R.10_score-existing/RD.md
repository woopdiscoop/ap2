# Ticket R.10 — `ale score`: score an existing scheme against a programme · Requirements Document

> Context = this file, `eval.md`, `ale.pdfread` (`read_pdf_page`), `ale.cad` (`read_cad`), `ale.join` (`resolve_scale`),
> `ale.program` (`read_program`, Annexe import P.2), contracts (`PlanGeometry`, `LabelledPolygon.area_text_m2`), user
> decisions U-14/U-15 on the board (one stairwell; sketch tolerance; terraces; depth judged by façade contact). The
> first use is the user's manual AREP-MS sheet (Archicad PDF, areas written in rooms, no names, several plans on one
> sheet); **that file is never committed**: tests use synthetic PDFs/DXFs. No contract changes.

## 1. Files (ownership)
`src/ale/score/__init__.py`, `src/ale/score/match.py`, `src/ale/score/report.py`, `src/ale/cli/commands/score.py`
(+ its registration line in `src/ale/cli/__init__.py`), `tests/score/**`, `specs/tickets/R.10_score-existing/eval_report.md`.

## 2. Command
`ale score --plan FILE [--page N] --programme FILE.xlsx [--out DIR] [--tolerance-pct 5]` (also accepts an Annexe file
via `--annexe`, through P.2). Reads every plan on the page/drawing (vector PDF or DXF/DWG), takes each room's area
from `area_text_m2` when present (the written value), else from its polygon with the resolved scale.

## 3. Matching (`match.py`)
Programme instances ↔ drawn rooms by minimum-cost one-to-one assignment (Hungarian; cost = |area − target| / target;
a room whose text label matches a programme name gets cost × 0.5); pairs with relative gap > 25 % are not matched.
Plans of one sheet are scored together (a programme is spread over floors); report which plan each match is on.

## 4. Scores (`report.py`, French `score.md` + `score.json`)
- **Programme coverage**: matched / unmatched programme lines, unmatched drawn rooms.
- **Areas (U-15)**: gap per match; |gap| ≤ tolerance → "à ajuster" (not a failure); below −tolerance → "sous le
  programme"; above +10 % → "au-dessus de la tolérance". Totals per plan and per building.
- **Façade (U-15)**: for programme lines that need a façade, whether the matched room touches the plan's outer
  boundary (the union of its rooms' outline).
- **Vertical circulation (U-14)**: count of stair cores per plan detected from the stair geometry the reader exposes;
  one stairwell = OK.
- No depth or "shape change between floors" penalty (U-15).
- Section "Limites" stating what could not be checked (names absent, matching by area).
