# Ticket Q.1 — Evaluation report

Status: **geometry change done; DONE criteria NOT met** — 3.2 T04/T05 (and every test that
needs seeded P25/P60 plans, including 3.4 O03) fail because `seed_plan` no longer finds a
valid plan for P25 / P60 (see §3). Not fixable inside this ticket's ownership.

## 1. Change (`src/ale/geometry/blocks.py`)
- `Solver.room_bay_width` returns `int | None`. `None` when `D < wmin` or no width satisfies
  area rule + `aspect ≤ amax` (the 3.3 §5.2 up / down searches, unchanged); the block records
  `ROOM_INFEASIBLE` with detail `<id> in piece p band b block X: no compliant width at depth D`.
  The former `w = max(wmin, ceil(T/D))` fallback is gone.
- `Solver.stack`: (1) the 3.3 §5.3 exact search (every room reaches its target), with
  `h_i ≥ wmin_i` instead of `≥ c` (so `min(w, h_i) ≥ wmin_i`); (2) if no width works, a second
  scan over `[max(wmin_stack, ⌈Σlo/D⌉), 2·D]` that allows `lo_i ≤ w·h_i < T_i`: heights start at
  their compliant minimum and are raised outermost-first toward `⌈T_i/w⌉`, then to their
  compliant maximum (`hi_i` / aspect), rest → stack-end strip; best width by
  `(Σ|w·h_i − T_i| + w·rest, w)`. No width → `None` → `STACK_INFEASIBLE` (detail lists the
  rooms). The proportional fallback is gone; `STACK_TOO_SHALLOW` is subsumed by
  `STACK_INFEASIBLE` (Q103 requires that code for 5 × 3 m² at D = 40, which is `5·c > D`).
- Depth search / band descent / fastreal unchanged: they already count block failures with
  the same key, and `RealizeCache` uses the same `Solver`, so it stays equivalent.
- Every room emitted therefore satisfies area rule, aspect and `wmin`: a successful
  `realize` has no `AREA_UNDER` / `AREA_OVER` / `ASPECT` / `MIN_WIDTH`.

## 2. Eval IDs
| ID | Test | Result |
|---|---|---|
| Q101 | `tests/geometry/test_geometry_q1.py::test_Q101_never_degenerate` (200 ex., derandomized; P25 + P60; greedy / random / hand-built starts + 0–40 grammar moves) and `test_Q101_not_vacuous` | pass |
| Q102 | `test_Q102_room_bay_infeasible`; E05 updated (`test_geometry_exact.py::test_E05_room_bay_rules`) | pass |
| Q103 | `test_Q103_stack_solver` (brute-force width check; 6/6/12 m² at D = 70 → w = 36, h = 18/18/34, all compliant; 5 × 3 m² at D = 40 → `STACK_INFEASIBLE`) | pass |
| Q104 | G01–G04, N02–N03 | pass (unchanged) |
| Q105 | 3.2 T03 pass; **T04, T05 fail**; 3.4 O03 **errors** (seeded fixture) | **fail — §3** |
| Q106 | ruff / ruff format / mypy strict clean; `lock --check` OK; coverage see §5 | see §5 |

## 3. Blocker: 3.2 seeding cannot adapt
P25 / P60 mix rooms whose compliant room-bay depths do not overlap (amax 2): e.g. P25 B02
(60 m², min width 4.8 m) needs `D ∈ [55, ~110]`, 12 m² offices `D ∈ [25, ~53]`, 4–6 m² rooms
`D ≤ ~37`. A compliant plan must group rooms by depth (or stack small ones in deep blocks).
`seed_plan`'s repair (RD 3.2 §5.4, `ale.topology.repair`) only has overflow moves; a
`ROOM_INFEASIBLE` / `STACK_INFEASIBLE` counts as a heavy "other failure" and names a block
with overflow 0, and no move lowers the count. Measured with this change:

- P25, seeds 1–3, **120 s budget each**: ~460–470 restarts each, best = 1 × `PLAN_OVERFLOW`,
  never valid.
- P60, seed 1 (20 s) / seed 3: best has `PLAN_OVERFLOW` + `STACK_INFEASIBLE` / `ROOM_INFEASIBLE`.
- P8: still valid (seeds 1–5).

The grammar itself is not the problem: a hand-built 2-band P25 plan (block depths 60/40 and
28/28; `geometry_helpers.p25_compliant_plan`) realises with zero shape violations, and the
annealer improves it (below). **Needed (outside Q.1 ownership):** a 3.2 repair move for
these failures — e.g. move the failing room to a block whose depth range admits it, or fold
small rooms into a stack, and depth-aware band assignment in `assign`.

## 4. Q105 hard counts (15 s, anneal seed 6, seed-3 starts)
| Fixture | before (initial → final) | after (initial → final) |
|---|---|---|
| P8 | 6 → 0 (AREA_OVER 2, ASPECT 4 → none) | **0 → 0** |
| P25 | 13 → 7 (AREA_UNDER 2, ASPECT 2, MIN_WIDTH 1, NO_FACADE 7, REQUIRED_ADJ 1 → ASPECT 2, MIN_WIDTH 1, NO_FACADE 3, REQUIRED_ADJ 1) | seed-3 start does not realise (`PLAN_OVERFLOW`) |
| P60 | 35 → 27 (ASPECT 4, AVOID_ADJ 2, MIN_WIDTH 1, NO_FACADE 21, REQUIRED_ADJ 7 → ASPECT 5, NO_FACADE 16, REQUIRED_ADJ 6) | seed-3 start does not realise (`PLAN_OVERFLOW`, `STACK_INFEASIBLE`) |
| P25 hand-built start (info) | — | 17 → 12 (AVOID_ADJ 1, NO_FACADE 10, REQUIRED_ADJ 6 → NO_FACADE 9, REQUIRED_ADJ 3), 0 shape violations |

## 5. Gates
- ruff check, ruff format --check, mypy strict (`src/ale`): clean. `python -m ale.contracts.lock --check`: OK.
- Coverage of `ale.geometry` (whole suite): 98 % (blocks.py and realize.py 100 %; 1019 stmts, 10 missed).
- Whole suite: 756 passed, 8 skipped, 2 xfailed, **10 failed, 14 errors** — all of them
  need a valid seeded P25/P60 plan: 3.2 T04, T05, T06, T09, T10[P25, P60]; 3.4 errors from the
  `seeded` / seed-backed fixtures (O03 ×3, O05, stop_by_* ×3, start_must_realise, hard_rooms,
  fastreal ×4, O01) and generate O07, O09, default_seed, failed_and_duplicate_variants
  (timeouts: seed spends its full budget). `tests/geometry`: 59 passed, 2 xfailed (pre-existing).

## 6. Expectation changes (all forced by Q.1)
`tests/geometry` (owned):
- `test_geometry_exact.py::test_E05_room_bay_rules` — 6 m² at D = 40 → `ROOM_INFEASIBLE` (Q102).
- `test_geometry_units.py::test_stack_rules` — fallback stack → `None`; added undershoot-pass case (4 m² × 2 at D = 28 → w 28, h 14/14).
- `test_geometry_units.py::test_room_bay_branches` — 12 m² at D = 59 → `None` (was 21); D < wmin → `None`.
- `test_geometry_units.py::test_stack_too_shallow_and_shallow_piece` — `STACK_TOO_SHALLOW` → `STACK_INFEASIBLE`; 9-deep blocks → `ROOM_INFEASIBLE` ×2 (was a layout with MIN_WIDTH/ASPECT).
- `test_geometry_units.py::test_evaluate_core_hint_override_and_missing_type` — MIN_WIDTH now checked by evaluating a layout realised without r2's min width (realize refuses it).
- `test_geometry_units.py::test_greedy_single_zone_rect` — footprint 120×60 → 120×64 (no compliant depth at 60).
- `test_geometry_bands.py::test_N01_end_connector_and_literal_reading` — literal 60×116 reading now fails (`ROOM_INFEASIBLE` / `BLOCK_TOO_SHALLOW`).
- `test_geometry_bands.py::test_j2_secondary_spine_off_primary_connector` / `test_j2_primary_spine_off_secondary_connector` — the lone room of the 148-deep block is 120 m² (12 m² is infeasible there).
- `test_geometry_bands.py::test_greedy_j1_multiband`, `test_geometry_robust.py::test_R01_*` — allowed failures += `ROOM_INFEASIBLE`, `STACK_INFEASIBLE`.
- `test_geometry_robust.py::test_R02_random_plans_never_raise` — 0 of 200 random P25 plans realise now; `successes > 0` dropped, failure codes checked against the documented set.
- `test_geometry_robust.py::test_R03_deterministic` — uses the hand-built P25 plan (no random plan realises).

`tests/optimize`:
- `test_optimize_anneal.py::test_O03_improves` — `start_score[0] > 0` waived for P8 (its seed-3 start now has 0 hard).

`tests/topology`: none changed (T04/T05 fail — not an expectation update).

## 7. Spec issues
1. RD §3 / eval Q105 assume `seed_plan` "adapts through failures"; it does not (§3).
2. Q103 "3 m² × 5 at D = 40 → `STACK_INFEASIBLE`" is a depth `< k·c` case that 3.3 called
   `STACK_TOO_SHALLOW`; the two codes are merged into `STACK_INFEASIBLE`.
3. RD §2 stack: "heights so that every room satisfies the area rule" — implemented as
   target-reaching first (3.3 behaviour, keeps G/N inverse cases exact), then undershoot within
   `lo` only when no width reaches every target.
