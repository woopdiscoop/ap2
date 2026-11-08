# Ticket 1.3 — Vector-PDF reader · Requirements
> **Worker brief.** Context = this file, `eval.md`, the contracts (`src/ale/contracts/`: `PlanGeometry`, `Wall`, `Opening`, `LabelledPolygon`, `TextItem`, `Polygon`, `LineString`, enums, `taxonomy`), `ale.guards`, `ale.config`, test helpers. **Library only** — no CLI wiring (a later integration ticket wires `ale extract`/`ale review`). Do not modify contracts or other packages. All loops bounded; public functions never raise on bad input (problems → warnings).
## Files
`src/ale/pdfread/{__init__,read,walls,scale,rooms}.py`, `tests/pdfread/**`, `specs/tickets/1.3_vector-pdf-reader/eval_report.md`. Dependency: PyMuPDF (extra `pdf`), shapely.
## API
`read_pdf_page(path, page, *, source_sha256, config) -> PdfReadResult(plans: tuple[PlanGeometry,...], warnings, is_plan_likely: bool, plan_score: float)`
## Rules
- Native units = PDF points, frame `Y_DOWN` (PyMuPDF page space). `source_kind PDF_VECTOR`.
- Paths from `page.get_drawings()`; texts from `page.get_text("dict")` spans → `TextItem(source="PDF")`.
- **Walls**: line segments; pair parallel segments (angle ≤ 1°, overlap ≥ 50 %, distance 2–25 pt) into walls (centreline + thickness); filled rectangles/polygons with min side 2–25 pt and length ≥ 5× width → walls; stroke width ≥ 1.5 × median stroke → wall candidates. Keep walls whose length ≥ 15 pt.
- **Openings**: arcs (curves approximating ¼ circles, radius 15–60 pt) next to a wall → doors (width = radius).
- **Rooms**: polygonize wall faces + door spans (as 1.2): faces between 1.5 m² and 2000 m² once scale known (else 200–2·10⁶ pt²), drop the outer face and thin faces.
- **Labels**: span text inside a room → `normalize_label` → type with `label_source PDF_TEXT` (exact 1.0 / prefix 0.8); area texts → `area_text_m2`.
- **Scale** (`scale.py`): find tokens `1/100`, `1:50`, `Ech. 1/200`, `ÉCHELLE 1:100` (canonical, accents removed). Several → the one whose text box is nearest the walls' bbox; none → UNKNOWN. With `1:N`: metres per point = N × 0.0254 / 72. Method `TITLE_BLOCK`, confidence 0.9 (0.6 if several candidates).
- **Plan-likeness** (`is_plan_likely`): score = walls ≥ 8 and rooms ≥ 2 and wall length ≥ 20 % of page diagonal × 3 → likely; report `plan_score` ∈ [0,1] (documented formula). Non-plan pages return `plans=()` with `is_plan_likely False`.
