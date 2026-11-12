# Ticket M.2b — Bar floor plates around the skeleton · Requirements

> Context = this file, `eval.md`, M.2 (`specs/tickets/M.2_floor-plans/eval_report.md`, spec issues 1–4 and the
> per-floor table of the M.1 bar), M.1 (`ale.stack`), G.1 (`decompose_footprint`, junctions, ring corridors),
> contracts 1.7.0 (`ModulePolygon.solids`, `Layout.fixed`). User decisions U-9 (depth from built plans, may exceed
> 7.20 m), U-10, U-14, U-15. No contract changes.

## 1. Purpose
M.2 lays out a floor around fixed solids, but only on a near-square plate (30.0 × 21.6 m, 4-piece pinwheel). On the
office **bar** that AREP-MS actually needs (M.1 case: 64.8 × 19.2 m, core and wet stack in the middle), the seeder
fails on every seed (`JUNCTION_MISALIGNED`, `BLOCK_TOO_SHALLOW`). M.2b makes bar plates with an interior skeleton
work, so `ale stack --plans` produces every floor of a realistic R+3 bar.

## 2. Diagnosis first
Before changing code, reproduce the M.1-bar failures, record for each the pieces, cuts and junctions produced by
`decompose_footprint` and why the junction check rejects them, and write it in `eval_report.md` § Diagnosis. Expected
figure for a bar with an interior solid: a corridor running along the solid's long sides (central double-loaded
spine split around the core) or a short ring around the core joining two spine halves; the bar ends are
double-loaded wings.

## 3. Changes
- Seeder / decomposition / junction handling (`src/ale/topology/**`, `src/ale/geometry/**`, `src/ale/contracts/footprint.py`
  only if the decomposition itself must change, no contract model change) so that bar plates with an interior solid
  seed reliably. Prefer a general fix (junction placement relative to the solid) over a bar special case.
- `src/ale/stack/plans.py`: drop per-floor seed retries to what is needed after the fix; keep restart bounds
  deterministic.
- `tests/stack/stack_case.py` (or a new helper): an M.1 bar case **loaded 85–100 % on every floor** (M.1's synthetic
  case is loaded 45 % on three floors, which makes the plates oversized for any engine). Keep the M.1 tests passing.

## 4. Files (ownership)
`src/ale/topology/**`, `src/ale/geometry/**`, `src/ale/contracts/footprint.py` (functions only), `src/ale/stack/plans.py`,
`tests/topology/test_topology_m2b.py`, `tests/stack/**` (new tests; helpers may be extended), 
`specs/tickets/M.2b_bar-skeleton/eval_report.md`. Outputs for sites without solids must stay byte-identical (same
digests as M206). Never weaken a test.
