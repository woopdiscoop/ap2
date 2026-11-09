# Ticket Q.2 — Façade-aware layouts (inner connector) · Requirements

> **Worker brief.** First merge `claude/new-session-2hmd3s` **and** `worktree-agent-ab1e2b4f56e59e478` (contract
> amendment A.3, contracts 1.3.0: `ConnectorBay`, connector `"inner"`). Context = this file, `eval.md`, the
> `corridor_plan.py` docstring, the 3.3/3.3b/3.2/3.4/Q.1 specs for background, and the code of `ale.geometry`,
> `ale.topology`, `ale.optimize`. Ownership: `src/ale/geometry/**`, `src/ale/topology/**`, `src/ale/optimize/**`,
> their tests, `specs/tickets/Q.2_facade-aware/eval_report.md`. Do not modify contracts.

## 1. Problem
P60 needs ~118 m of façade (Q.2a) but a connector at a piece end sits on the exterior wall, and `needs_facade` rooms
end up in inner bands. Remaining hard breaks on P60 (≈ 19 after Q.1) are mostly `NO_FACADE`.

## 2. Changes
1. **Geometry — inner connector** (A.3 semantics): in a piece with `connector = "inner"`, compute
   `u_c = max over all blocks of (Σ widths of bays before the marker)`; place the connector strip
   `[u_c, u_c + s) × full piece depth`; in each block, bays before the marker from `u = 0` (a block whose bays end
   before `u_c` gets a circulation filler strip up to `u_c`, touching the spine), bays after the marker from
   `u_c + s`; end strips as before. Overflow if any block exceeds `L`. Band spines run the full length and cross the
   connector. Fix the A.3 mypy errors (exhaustive handling of `ConnectorBay`).
2. **Seeding**: for pieces with ≥ 2 bands and no cut-side requirement, try both an end connector and `"inner"`
   (marker placed at the block's capacity midpoint) and keep the better realised plan by `(n_hard, cost)`.
   `needs_facade` rooms are assigned first to **exterior blocks**: band 0 block A and the last band's block B (for
   spine axis X: bottom/top; Y: left/right), and to room bays whose far side lies on the piece boundary.
3. **Moves** (3.4): `G8` move the marker by one bay within a block (keeping every block's marker); `G9` façade pull:
   pick a `needs_facade` room without façade contact and swap it with a same-zone non-façade room in an exterior block
   (or any zone if none, accepted only if zone contiguity holds); `G10` switch a piece's connector among
   `start`/`end`/`inner` where the contract allows (inserting/removing markers). Add them to the move table
   (probabilities rescaled: G1 .20, G2 .15, G3 .10, G4 .08, G5 .08, G6 .07, G7 .07, G8 .08, G9 .12, G10 .05).
4. All invariants of 3.3 §7 still hold (exact tiling, connectivity incl. the inner connector, contact ≥ c).

## 3. Targets
`NO_FACADE` on P60 must drop clearly; see eval.
