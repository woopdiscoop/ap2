# Ticket 1.6 — Evaluation (synthetic PlanGeometry objects)
| ID | Test | Pass condition |
|---|---|---|
| J1 | hierarchy | Each level wins over the lower ones (5 crafted plans); CAD drawing units untouched. |
| J2 | meta | PDF plan with meta `scale_1_to=50` → 50·0.0254/72; raster with `dpi=300, scale_1_to=100` → 100·0.0254/300. |
| J3 | dimensions | Raster plan with walls of 360 px / 480 px and texts `3.60`, `4.80`, `3.60` near them → 0.01 m/px ± 0.5 %; an outlier text `12` ignored. |
| J4 | doors | Doors of 90, 92, 88, 300 px → outlier 300 rejected, scale 0.9/90 m/px, confidence 0.5; 2 doors → not used. |
| J5 | widths | After resolution every opening has `width_m == width_native × scale` (contract validator). |
| J6 | flags | Crafted plans trigger exactly the expected flags. |
| J7 | gates | ruff, format, mypy strict; coverage ≥ 90 %; lock --check; whole suite. |
