# Ticket 1.4 — Evaluation (images rendered in tests from a declared ground truth with OpenCV/Pillow)
| ID | Test | Pass condition |
|---|---|---|
| R1 | synthetic_plan | 1200×800 px, 3 rooms, walls 8 px thick, 2 door gaps → 3 rooms; wall IoU (rasterised walls vs ground truth mask) ≥ 0.85; room-polygon IoU ≥ 0.9 each; 2 doors, widths ± 3 px. |
| R2 | noise_and_skew | Same with Gaussian noise σ=10, salt-pepper 0.5 %, 2° skew → wall IoU ≥ 0.75, room count exact. |
| R3 | scanned_pdf | The image embedded as a full-page image in a PDF → `rasterize_pdf_page` at 150 dpi + `read_raster` → same room count. |
| R4 | not_a_plan | Photo-like noise image and a text page image → `plans == ()` or plan_score < 0.3. |
| R5 | robustness | Blank, all-black, 1×1, 10 000×10 000 (memory-capped downscale) → no exception, bounded time. |
| R6 | contract | PlanGeometry round-trips; frame Y_DOWN; scale UNKNOWN. |
| R7 | real_corpus_smoke (optional) | With `ALE_CORPUS_DIR`: run on 20 `floor_plan_images` drawings (deterministic pick) and report room/wall counts; never in CI. |
| R8 | gates | ruff, format, mypy strict; coverage ≥ 85 %; lock --check; whole suite (tests skip cleanly without the `raster` extra). |
