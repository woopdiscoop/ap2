# Ticket 3.3 — Grammar Realisation · Evaluation report

Environment: Linux, Python 3.13, default `AleConfig` (s = c = 12, f = 24).

## Eval IDs

| ID | Test | Result |
|---|---|---|
| E01 | `test_geometry_exact.py::test_E01_single_room_bay` | PASS |
| E02 | `test_geometry_exact.py::test_E02_finger_bay` | PASS |
| E03 | `test_geometry_exact.py::test_E03_overflow` | PASS |
| E04 | `test_geometry_exact.py::test_E04_axis_Y` | PASS |
| E05 | `test_geometry_exact.py::test_E05_room_bay_rules` | PASS |
| E06 | `test_geometry_exact.py::test_E06_plan_invalid` | PASS |
| G01 | `test_geometry_inverse.py::test_G01_realizable` (150 ex., derandomized) | PASS |
| G02 | `test_geometry_inverse.py::test_G02_invariants` | PASS |
| G03 | `test_geometry_inverse.py::test_G03_zero_overshoot` | PASS |
| G04 | `test_geometry_inverse.py::test_G04_L_shapes[J1]`, `[J2]` | PASS |
| R01 | `test_geometry_robust.py::test_R01_fixtures_never_raise[...]` (3 fixtures) | PASS |
| R02 | `test_geometry_robust.py::test_R02_random_plans_never_raise` | PASS |
| R03 | `test_geometry_robust.py::test_R03_deterministic` (2 subprocesses + in-process) | PASS |
| R04 | `test_geometry_robust.py::test_R04_performance` — best of 3: **0.09 s** | PASS |
| V01 | `test_geometry_eval.py::test_V01_violations` | PASS |
| V02 | `test_geometry_eval.py::test_V02_cost_terms` | PASS |
| V03 | `test_geometry_eval.py::test_V03_circulation_budget` | PASS |

Plus 18 unit tests in `test_geometry_units.py`, for 38 tests in `tests/geometry`, all passing.
No xfail. All exact values in eval.md matched.

R01 outcomes with the greedy baseline: P25/site_rect gives a valid layout. P8/site_rect_small
and P60/site_L end in `PLAN_OVERFLOW` (allowed: the RD says the baseline may overflow).

## Gates

- Whole repo suite: 539 passed, 5 skipped (the Windows-only or root-only skips that already existed).
- `ruff check`, `ruff format --check`: clean. `mypy` (strict, `src/ale`): clean.
- `python -m ale.contracts.lock --check`: OK. No change to contracts or pyproject.toml.
- Coverage of `ale.geometry`: 760/766 lines (99.2 %), 247/250 branches (98.8 %).
- Ownership: only `src/ale/geometry/**`, `tests/geometry/**` and this report.

## Spec issues / interpretations

1. **Depth-search criterion (RD 5.1), the main deviation.** Read literally, "Σ overshoot
   cells + Σ circulation strip cells" with end strips included is constant for a given
   depth pair. Exact tiling fixes it to `L·(P−s) − s·Σ(fingers × depth) − ΣT + undershoot`,
   so the criterion cannot see overshoot. The tie-break `|D_A − D_B|` then picks balanced
   depths with overshooting rooms, and G03 fails (a counter-example was found and shrunk).
   Implemented instead: `Σ |placed − T|` (cells) + **stack-end** strip cells only. With this,
   the generated geometry scores 0 and is found again (G03/G04). The absolute deviation also
   stops the proportional stack fallback, which undershoots, from looking cheaper than an
   exact fit.
2. **Stack depth lower bound.** A block's search bound is `max(smallest room wmin, k·c for
   each k-room stack)`, so a depth too shallow to realise a stack is never tried. If a stack
   still cannot reach `k·c`, that becomes the failure `STACK_TOO_SHALLOW`; the alternative
   was rooms without corridor access, which breaks invariant 4. For J2, primary depths are
   also skipped when a non-empty secondary block would be shallower than this bound.
   Otherwise `BLOCK_TOO_SHALLOW` showed up for P60 and broke R01.
3. **Stack width (RD 5.3).** The first criterion equals `w_s·D − ΣT_i`, which rises strictly
   with `w_s`. So the first accepted width is the optimum and the later tie-breakers never
   matter. The scan uses this, plus exact pruning (it starts at `ceil(ΣT/D)` and stops once
   `k·ceil(w/amax) > D`). The proportional fallback gives heights ≥ c.
4. **Extra failure codes** outside the RD: `PIECE_TOO_SMALL`, `FOOTPRINT_UNSUPPORTED`,
   `BLOCK_TOO_SHALLOW`, `STACK_TOO_SHALLOW`, `DEPTH_SEARCH_TIMEOUT`. The depth loop uses
   `bounded(..., on_exhaust="stop")` so that `realize` never raises.
5. **Evaluation details.** These were not fixed by the RD:
   - REQUIRED counts once per (instance of A, required spec B), and the violation lists
     only A's instance.
   - AVOID counts unordered instance pairs.
   - Circulation access and invariant 4 use contact with a single circulation rectangle.
   - NO_FACADE uses the total exterior contact.
   - "Longest exterior contact": ties go to the first footprint edge.
   - A missing `orientation_override` bearing counts as 0.
   - `ZONE_SPLIT` violations have `instance_ids = ()`.
   - Σ net in `circulation_length` covers all program instances.
6. **Circulation ids** start at `circ-001`.
7. **Greedy (RD 8).** Blocks are filled by estimated capacity, with zone runs kept
   contiguous. This replaces a strict "one block per zone", which cannot hold three zones
   in two blocks. The J1 junction finger goes at the first bay boundary whose estimated
   position reaches the secondary piece.
8. "tests/geometry" helpers do not import `tests/program/program_helpers.py`. Without an
   `__init__.py` it can only be imported when that directory is collected. They read
   `rulebook_test.yaml` by path instead.
