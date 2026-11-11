# Ticket X.2 — Vector PDF: read filled zones as rooms (Archicad / Revit exports) · Requirements Document

> Context = this file, `eval.md`, `ale.pdfread` (`read_pdf_page`, plan-likeness, room tracing), contracts
> (`PlanGeometry`, `LabelledPolygon.area_text_m2`, `raw_label`), `ale.score` (R.10, first consumer). No contract changes.

## 1. Why
The user's Archicad sheet draws each room as a **filled polygon** (a "zone", colour by type) with its area written
inside, while walls are single strokes. `read_pdf_page` builds rooms only from closed wall loops, so it finds 0 rooms
and calls the page "not a plan". Many architectural exports use zones this way.

## 2. Files (ownership)
`src/ale/pdfread/zones.py` (NEW), `src/ale/pdfread/read.py` (ONLY: call it, plan-likeness update), `tests/pdfread/test_zones*.py`,
`specs/tickets/X.2_pdf-filled-zones/eval_report.md`.

## 3. Behaviour
- Collect filled paths (rectangles and orthogonal polygons, any colour except white/near-white and the page
  background) larger than a minimum (0.5 m² once scaled, or 6 pt² when unscaled); merge identical overlapping
  duplicates; drop fills that contain other fills entirely when they are frames (> 80 % covered by children).
- Each zone → `LabelledPolygon`: polygon in native units; `area_text_m2` from an area text (`12,34 m2`, `12.34 m²`,
  rotated or not) whose anchor lies inside the zone (the nearest to the centroid if several); `raw_label` from a
  non-area text inside it; the fill colour recorded in the room id suffix or a warning-free field already available
  (no contract change: put it in `raw_label` as `fill=#RRGGBB` when no other label exists).
- Use zones when wall-loop tracing finds fewer than 3 rooms and at least 3 zones exist; otherwise keep today's path.
  Plan-likeness counts zones as rooms. Several separate clusters of zones on one page remain one `PlanGeometry`
  (the caller, e.g. `ale score`, splits them).
- Scale: unchanged logic; when unknown, areas still come from the texts.
