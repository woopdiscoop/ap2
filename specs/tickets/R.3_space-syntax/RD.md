# Ticket R.3 — Space-syntax measures in the report · Requirements Document

> Context = this file, `eval.md`, `specs/design/literature_review_2026-11.md` (Designing with Space Syntax),
> `ale.geometry` (`Layout`, share-length helpers in `evaluate.py`), `ale.export` (`report.py`), contracts. No
> contract changes; no change to the cost function or to layouts.

## 1. Files (ownership)
`src/ale/analysis/__init__.py`, `src/ale/analysis/syntax.py` (NEW), `src/ale/export/report.py` (ONLY: new section),
`tests/analysis/**`, `tests/export/test_export_syntax.py`, `specs/tickets/R.3_space-syntax/eval_report.md`.

## 2. Graph
Nodes = rooms + one node `CIRC` per connected circulation component (one in a valid layout) + `ENTRANCE`.
Edges: room–CIRC when they share ≥ c (door possible, c as in 3.3 §4); `ENTRANCE`–CIRC when circulation touches the
site's access edge (else ENTRANCE–nearest circulation rectangle, flagged `entrance_inferred`); room–room edges only
for REQUIRED adjacencies that share ≥ c (a connecting door is plausible). Deterministic (sorted ids).

## 3. Measures (`syntax.py`, pure functions, networkx)
Per room: `depth` (steps from ENTRANCE), `mean_depth` MD, `relative_asymmetry` RA = 2(MD − 1)/(k − 2),
`integration` = 1/RA (∞ → reported as `None` when RA = 0), `control` (Hillier–Hanson), and `walk_m` = shortest walking
distance in metres from the entrance point to the room's corridor contact midpoint, measured along circulation
rectangle centrelines (Manhattan, through shared boundaries). Layout-level: mean depth, max `walk_m`, and per macro-zone
mean depth.

## 4. Report
New section "Lecture spatiale (space syntax)" in `report.md`: table per room (profondeur, intégration, contrôle,
distance depuis l'entrée m), per-zone means, and two sentences generated from the numbers (most integrated room,
deepest room, whether PUBLIC rooms are on average shallower than ADMINISTRATIVE: stated as fact, no judgement).
