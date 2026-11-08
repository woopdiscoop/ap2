# Ticket Q.2a — Evaluation report

## Result

| ID | Test(s) | Status |
|---|---|---|
| F1 | `test_F1_rect` | pass |
| F2 | `test_F2_L`, `test_F2_J1_cut_on_long_edge`, `test_F2_helpers` | pass |
| F3 | `test_F3_tight_warning`, `test_F3_non_grammar_footprint_falls_back_to_perimeter` | pass |
| F4 | `test_F4_gates` (lock --check) + commands below | pass |

Gates: whole suite `784 passed, 7 skipped, 2 xfailed` (xfails pre-existing); `ruff check .` clean;
`ruff format --check .` clean; `mypy` (strict, `src/ale`) clean; `python -m ale.contracts.lock --check` → 0.

## Computed values (default `ale.toml`: module 0.1 m, s = 12 modules = 1.2 m, f = 2.4 m, 2:1)

`D_t = ceil(sqrt(1.4 × median target cells))`, median over all instances; `n0 = max(1, round((P − s)/(2·D_t + s)))`.

| Site / program | Pieces (modules) | Parallel exterior edges | n0 per piece | Exterior short edges | `facade_usable_m` |
|---|---|---|---|---|---|
| site_rect / P25 | (0,0,240,180) spine X | 24 + 24 = 48 m | 2 (P = 180) | 2 | 48 − 2·2·1.2 = **43.2 m** |
| site_L / P60 (J2, cut x = 300, y 0..180) | primary (0,0,300,300) X; secondary (300,0,180,180) X | 30 + 30 + 18 + 18 = 96 m | 3 (P = 300), 2 (P = 180) | 1 + 1 (cut-side ends excluded) | 96 − 1.2·(3 + 2) = **90.0 m** |
| site_rect_small / P8 | (0,0,100,100) X | 20 m | 1 | 2 | **17.6 m** |

P60 façade demand `Σ max(2.4 m, w_est)` over the 40 `needs_facade` instances = **117.9 m**:
H01 40 m² → 4.5 m; B01 12 m² ×31 → 2.5 m (77.5); B02 80 m² min 6 m ×3 → 6.3 m (18.9); M01 20 m² ×4 → 3.2 m (12.8);
M02 35 m² → 4.2 m. 117.9 > 90.0 → `W_FACADE_TIGHT` on P60/site_L (no error; perimeter check 96 m ≤ 156 m unchanged).
P8 demand = 10.3 m ≤ 17.6 m → no warning.

## Readings / decisions (please review)

1. **Existing expectations changed (conflict with F3).** P60/site_L now carries `W_FACADE_TIGHT`, and so do the two
   other cases where the façade is tight, so four existing assertions that pinned the exact issue list no longer hold.
   Updated explicitly (each with a `Q.2a` comment):
   - `test_Z01_fixtures_fit`: P60 case expects `["W_FACADE_TIGHT"]` (others still `[]`).
   - `test_Z02_not_feasible`, `test_Z05_facade`: `W_FACADE_TIGHT` appended after the error.
   - **Out of ownership:** `tests/program/test_program_prepare_cli.py` — `test_P01_prepare_ok`
     (`prepared.warnings == ()` → `["W_FACADE_TIGHT"]`, a direct consequence of F3 since `prepare_input` copies the
     feasibility issues) and `test_prepare_input_rejects_infeasible` (P25 on site_rect_small: `W_FACADE_TIGHT` appended).
     There is no way to satisfy F3 and the old P01 within the owned files.
2. The warning is emitted whenever demand > usable, also alongside `E_FACADE_INSUFFICIENT`/`E_NOT_FEASIBLE`
   (literal reading; no suppression).
3. "Spine ends" literal reading: `s × n0` is subtracted for each **exterior short edge** of a piece (edge
   perpendicular to the spine axis); a short edge that touches the cut is not exterior. Long edges count their length
   minus their overlap with the cut (matters only for a J1 primary).
4. `n0` is computed for every piece (including a J1 secondary, which 3.2 forces to 1 band) and capped at
   `MAX_BANDS` = 6, as 3.2's `_n0` does; the RD formula has no cap. Median over instance targets in cells.
5. `w_est` = narrowest short side `w ≥ ceil(min_width_m/module)` (1 if absent) with some `w ≤ l ≤ aspect_max·w`
   and `w·l` inside the area tolerance — rulebook aspect bands are ignored. If no such rectangle exists (room already
   `E_ROOM_INFEASIBLE`), `w_est` = 0, i.e. the room demands `min_facade_len_m`.
6. A footprint outside the v1 grammar (neither rectangle nor L, `decompose_footprint` raises) does not raise in
   feasibility: `facade_usable_m` falls back to the raw perimeter (needed by an existing geometry test that prepares a
   U-shaped footprint).
7. `W_FACADE_TIGHT` is not added to `WARNING_CODES` (the frozen RD 3.1 §4 list; `test_X10_never_raises` pins it);
   severity comes from the `W_` prefix via `make_issue`.
8. `FeasibilityReport.facade_usable_m` is a required field (no default).
