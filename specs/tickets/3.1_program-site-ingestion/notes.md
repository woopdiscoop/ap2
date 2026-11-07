# 3.1 — Router notes

Status: spec complete (RD + eval) 2026-11-07. Deps 0.2, 0.4 DONE → READY. DWG sites deferred to after 1.2 (`E_SITE_DWG`).

Parked:
- Metric footprint → module footprint: snap **inward** to the module grid (0.10 m by default); the lost sliver area is reported. Grid origin and axes: aligned with the (rectilinear) footprint edges.
- Feasibility "expected overshoot" = Σ over rooms of the overshoot of `best_buildable_rect` (contract function), so 3.1 and 3.3 use the same arithmetic.

## Decisions taken while specifying (2026-11-07)
- openpyxl only (no pandas): keeps Excel row/column for error messages; directive named pandas — deviation noted.
- Program input accepts a type as key, `label_fr`, or an *exact* synonym; prefix matches are errors with a suggestion (a program is authored, not mined, so silent guessing is wrong).
- Site: rectilinear in drawing axes only (v1); inward snapping rule by edge direction; canonical vertex order (CCW, start at min-y-then-min-x) so `access_edge` is unambiguous.
- New CLI group `ale program template|check` (one registration line in `ale/cli/__init__.py`) so the architect can validate programs before generation exists.
- Verified numbers (contract functions, 0.10 m grid): P8 88.500/95.000, P25 394.120/410.400, P60 1135.160/1162.800 required/available m², zero overshoot; Y03 loss 1.0986 m², Y04 loss 0.8225 m²; Z06 (28,43) and fallback (30,40); 72 allowed types with canonically unique `label_fr`.
