# A.2 — Router notes
User decision U-7 (bands). Breaking change of CorridorPlan (only 3.3 uses it). A.2 breaks tests/geometry until the 3.3 rework lands, so A.2 and the 3.3 rework are merged **together**; main stays green.
## Review log
- 2026-11-08 — Attempt 1 (610eee9): 518 pass (minus geometry), 100 % coverage, expectations matched. Worker found J2 gap (1-band primary + multi-band secondary unsatisfiable) — Router rule error; amended (secondary connector on its cut side). Other notes accepted (B01 default check, message rewording + K07 update, ASCII minus, B09 test variant). Rework requested.
