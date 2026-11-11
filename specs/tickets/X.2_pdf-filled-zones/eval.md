# Ticket X.2 · Evaluation (synthetic PDFs built with PyMuPDF in the tests)
| ID | Test | Pass condition |
|---|---|---|
| Z01 | zones | A page with 12 filled rectangles (4 colours), area texts inside, walls as single strokes → 12 rooms, `area_text_m2` exact, page classified as a plan. |
| Z02 | rotated_text | Area texts rotated 90° are attached to the right zone. |
| Z03 | frames | A large light fill behind the rooms (a frame) is dropped; duplicates merged. |
| Z04 | unchanged | Existing pdfread fixtures (wall-loop plans) give byte-identical `PlanGeometry` to before. |
| Z05 | score | `ale score` on a synthetic zone sheet with 2 plan clusters matches the programme (end-to-end). |
| Z06 | gates | ruff, format, mypy strict; coverage of `zones.py` ≥ 90 % (path-form); lock --check; whole suite passes. |
