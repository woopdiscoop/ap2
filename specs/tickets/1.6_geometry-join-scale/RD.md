# Ticket 1.6 — Scale reconciliation & review flags · Requirements
> **Worker brief.** Context = this file, `eval.md`, the contracts (`src/ale/contracts/`: `PlanGeometry`, `Wall`, `Opening`, `LabelledPolygon`, `TextItem`, `Polygon`, `LineString`, enums, `taxonomy`), `ale.guards`, `ale.config`, test helpers. **Library only** — no CLI wiring (a later integration ticket wires `ale extract`/`ale review`). Do not modify contracts or other packages. All loops bounded; public functions never raise on bad input (problems → warnings).
## Files
`src/ale/join/{__init__,scale,review}.py`, `tests/join/**`, `specs/tickets/1.6_geometry-join-scale/eval_report.md`.
## API
`resolve_scale(plan, *, meta: dict | None, config) -> PlanGeometry` and `review_flags(plan, config) -> tuple[str, ...]`.
## Scale hierarchy (first available wins)
1. `DRAWING_UNITS` already set by the CAD reader (confidence kept).
2. `plans_meta.csv` (`meta`: `scale_1_to` + paper units, or `units` for CAD) → `META_CSV`, confidence 1.0. For PDF: m/pt = N·0.0254/72; for raster: needs dpi in meta (`dpi`), m/px = N·0.0254/dpi.
3. `TITLE_BLOCK` already set by the PDF reader.
4. **Dimension text**: TextItems that are plain numbers (e.g. `3.60`, `360`) placed along a wall — pair each with the nearest parallel wall segment (distance ≤ 3 × text height); candidate scale = value / segment length (try m, cm, mm); take the median of the largest consistent cluster (≥ 3 values within 3 %) → `DIMENSION_TEXT`, confidence 0.7.
5. **Door median**: ≥ 3 doors; reject widths outside [0.5, 2] × median; scale = 0.90 m / median native width → `DOOR_MEDIAN`, confidence 0.5.
6. Else UNKNOWN.
Once a scale is set: fill `Opening.width_m`; keep everything else in native units (contract).
## Review flags
`scale_unknown`, `scale_low_confidence` (< `extract.review_confidence`), `area_mismatch` (room with `area_text_m2` differing > 5 % from its metric area), `many_untyped` (> 30 % rooms untyped), `tiny_rooms` (rooms < 1 m²).
