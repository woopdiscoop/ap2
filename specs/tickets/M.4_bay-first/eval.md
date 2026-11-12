# Ticket M.4 — Evaluation

Cases: the loaded bar `tests/stack/bar_case.py` at the M.2b load (×1.7) **and** at full load (programme scaled so
fill ≈ 0.95), the M.1 case, M.2 `plans_case` (not a bar: must route to the engine). Deterministic: no wall-clock
dependence in the bay planner.

| ID | Check | Pass |
|---|---|---|
| M401 | Bar at full load (≈ 0.95) and at ×1.7 | every floor planned; `check_layout` clean; 0 hard violations |
| M402 | Room areas | every room within its area window ± U-15 tolerance (default 10 %); count and list any reserve bays |
| M403 | Façade partitions on a bay line | 100 % (by construction) on every floor |
| M404 | Columns inside rooms < 30 m² not on a partition | 0 |
| M405 | Plan-level stackability (room type same as directly below), floors 1–3 | ≥ 70 % on both loads |
| M406 | Façade rooms have a façade; no-façade rooms placed in the central band or against the core; groups contiguous | 0 façade rooms without façade; split groups reported |
| M407 | Routing: `plans_case` and other non-bar plates use the engine; `--planner engine` on the bar gives today's output | byte-identical to 8c65473 for engine paths (M206 digests too) |
| M408 | Report: `plans.md` states planner, section type, bay, per-floor fill, reserve bays, stackability; DXF/SVG as today | present, French |
| M409 | Determinism and runtime | same input → identical files; bay planner ≤ 10 s per floor |
| M410 | Gates: ruff, ruff format, mypy, lock --check, full `-m "not slow"` (`-q`, count visible) | green |

If a target is out of reach, stop and report the figures reached and why.
