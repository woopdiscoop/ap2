# Ticket 1.3 — Evaluation (PDFs generated in tests with PyMuPDF; never commit the user's corpus)
| ID | Test | Pass condition |
|---|---|---|
| P1 | two_room_plan | Generated page: 2-room plan drawn with parallel lines (wall 0.2 m at 1:100), a door arc, texts `BUREAU` / `S. RÉUNION`, title `ÉCHELLE 1:100` → 1 plan, 2 rooms typed office/meeting_room (PDF_TEXT), scale 0.0254·100/72 m/pt ± 1e-9, room areas within 2 % of ground truth after `to_metric()`, 1 door width 0.9 m ± 3 %. |
| P2 | filled_walls | Same plan with walls as filled rectangles → same rooms. |
| P3 | scale_choice | Two scale texts (`1:100` near the plan, `1:500` in a corner inset) → 1:100, confidence 0.6. No scale text → UNKNOWN. |
| P4 | not_a_plan | Text-only page and a bar-chart page → `is_plan_likely False`, `plans == ()`. |
| P5 | robustness | Empty page, 20 000 random segments, encrypted/corrupt file → no exception, bounded time (< 20 s). |
| P6 | contract | Every PlanGeometry round-trips `canonical_json`; frame Y_DOWN; source_kind PDF_VECTOR. |
| P7 | real_corpus_smoke (optional) | With `ALE_CORPUS_DIR`, run on the HABS PDFs' first pages and report plan_score / rooms; never in CI. |
| P8 | gates | ruff, format, mypy strict; coverage ≥ 85 %; lock --check; whole suite. |
