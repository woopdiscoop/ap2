# Ticket 3.3b — Grammar realisation with bands (rework of 3.3 for contracts 1.2.0) · Requirements

> **Worker brief.** Context = this file, `eval_bands.md`, the existing `RD.md`/`eval.md` of 3.3 (still valid
> unless overridden here), the contracts (1.2.0 — read the `corridor_plan.py` docstring: bands & connectors),
> and the existing code in `src/ale/geometry/`. Same ownership as 3.3 (`src/ale/geometry/**`, `tests/geometry/**`,
> `specs/tickets/3.3_slicing-tree-realization/eval_report_bands.md`). Do not modify contracts.

## 1. Changes

1. **Model**: plans are `pieces → bands → blocks A/B → bays` (see the contract). Port all code and tests.
2. **Connector**: in a piece with ≥ 2 bands, a circulation rect of width `s` spanning the full piece depth `P`
   at `u ∈ [0, s)` (`start`) or `[L − s, L)` (`end`). Bands then use `u ∈ [s, L)` (start) / `[0, L − s)` (end);
   each band's spine starts at the connector edge. 1-band pieces: unchanged.
3. **Band depths** (`P_0 … P_{n−1}`, ordered from min `v`, `Σ P_i = P`): start from equal depths (remainder to the
   last band); realise each band independently with the 3.3 depth search (§5.1, amended criterion) inside its
   `P_i`; then **coordinate descent**: for each internal boundary, try shifting it by `±1 … ±24` modules and keep a
   shift if the piece score `(n_failures, Σ |placed − target| + Σ stack-end strips)` strictly improves; repeat
   passes until no improvement. Wrap in `bounded(max_iter=40·n·P, time_budget_s=5.0, label="band-search",
   on_exhaust="stop")`. A band whose blocks are both empty is spine + end strip.
4. **L shapes**:
   - J2, both pieces 1 band → as in 3.3.
   - J2, primary ≥ 2 bands (connector on its cut side) → the secondary is realised independently; its spines
     end on the cut and touch the primary connector.
   - J2, primary 1 band, secondary ≥ 2 bands (secondary connector on its cut side) → restrict the primary's depth
     search to values where its spine band overlaps the secondary connector along the cut by ≥ `s`; none → failure
     `JUNCTION_MISALIGNED`.
   - J1 → junction finger in the primary band adjacent to the cut (contract rule); secondary (1 band) spine aligned
     with it as in 3.3.
5. **Circulation numbering**: per piece: connector, then per band (ascending) spine, then block A then B fingers
   and strips in `u` order.
6. **`greedy_plan`**: bands per piece `n = max(1, round((P − s) / (2·D_t + s)))`, capped at 6, where
   `D_t = ceil(sqrt(median target cells of the program × 1.4))`; connector `"start"` (or the cut side where the
   contract requires it); then fill bands in order as before.
7. **`evaluate`/`check_layout`**: unchanged rules; `ZONE_SPLIT` now per band block (contract messages).

## 2. Unchanged
API signatures, cost terms, invariants, performance target (P60 ≤ 1.0 s), determinism.
