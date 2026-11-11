# Ticket X.3 — Courtyards at intake and façade estimate for N pieces · Requirements Document

> Follow-ups of G.1 (see its eval report, spec issues 1 and 4). Context = `ale.program` (`site.py`, `feasibility.py`,
> `prepare.py`), contracts 1.6.0 (`ModulePolygon.holes`, `FootprintPieces.junctions`). No contract changes.

## Files (ownership)
`src/ale/program/site.py`, `src/ale/program/feasibility.py`, `src/ale/program/prepare.py` (only if needed),
`tests/program/test_program_x3.py`, `specs/tickets/X.3_courtyard-intake/eval_report.md`.

## Changes
1. `site.yaml` accepts `footprint: {exterior: [...], holes: [[...], ...]}` (orthogonal, holes inside, non-overlapping,
   each hole at least 3 × 3 modules); the module footprint keeps the holes; French errors name the hole index.
2. Feasibility: usable façade length = exterior perimeter + hole perimeters − the cut lengths of **all** junctions
   (not only the legacy single cut); a courtyard face counts as façade.
3. `ale program check` reports the number of pieces, junctions and courtyards.
