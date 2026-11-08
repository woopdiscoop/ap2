# Ticket 2.1 — Evaluation (synthetic plans with known topology)
| ID | Test | Pass condition |
|---|---|---|
| T1 | grid_plan | 3×2 grid of rooms (walls 0.2 m) with 3 doors → 7 contacts (shared lengths within 2 %), 3 of kind DOOR; precision = recall = 1. |
| T2 | thin_touch | Two rooms touching on 0.4 m only → no contact (< 0.6 m). |
| T3 | exterior | Façade lengths of the grid's perimeter rooms within 2 %. |
| T4 | noisy | Same grid with polygon vertices jittered ±3 cm → precision and recall ≥ 0.9. |
| T5 | no_scale | Plan with unknown scale → None. |
| T6 | determinism | Shuffled room order → identical output. |
| T7 | gates | ruff, format, mypy strict; coverage ≥ 90 %; lock --check; whole suite. |
