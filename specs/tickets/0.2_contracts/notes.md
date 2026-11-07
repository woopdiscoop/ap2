# 0.2 — Router notes

## Refinements of directive §4 (all recorded in specs/contracts.md)
- Geometry stored as plain data (`Polygon`, `LineString`, `ModuleRect`, `ModulePolygon`), never Shapely objects.
- Added: `Program`, `SiteSpec`, `GridSpec`, `Violation`, `Wall` (centreline + thickness, needed by 2.1), `PolishExpression` (shared by 3.2–3.4), `Frame`, `Fidelity`, `ContactKind`, `TypeCategory`.
- `PlacedRoom` area/bbox are methods taking `GridSpec` (module size is configurable; no hidden default).
- `Rulebook`: per-type grouping and sorted adjacency list (human-editable YAML, exact round-trip). `author`/`date` added for the seed.
- `Bearing` = 4 cardinal directions (decision O-6 on the board; 8 would double the architect's orientation inputs).
- `MacroZone` = PUBLIC | ADMINISTRATIVE | SERVICES (decision O-7).

## Verified by the Router before dispatch
- Taxonomy v1: 25 types, 160 synonyms, **no canonical collisions**; every row of the eval T03 table checked with a reference implementation of the canonical form.
- Area-rule expectations (A01–A08) computed exactly with `fractions.Fraction`.

## Review log
_(empty)_
