# 3.3 — Router notes

Status: BLOCKED on 0.2, 0.3, 0.4 (consumes a `PolishExpression`; does not need 3.2's code, only a tree — could be dispatched in parallel with 3.2).

O-2 resolved (2026-11-07): **two hard rules** — area (−3 % / +max(3 %, 1.2 m²)) and proportion ≤ `shape.aspect_max` = 2:1 (circulation exempt). Per-type p10–p90 bands are soft inside the hard limit; if a band is infeasible for a target, fall back to 1.0–2.0 and cost the deviation. Verified jointly feasible on the 0.10 m grid for every target 0.5–500 m² (overshoot ≤ 0.18 m², never below target). Residual-strip merges must not push a room past 2:1. Historical analysis at 0.60 m:
- When no rectangle within a type's aspect band meets the area rule (e.g. 7.43 m² in a 1:1–1:2 band; ~11 % of targets in a 1.5–2.0 band), which constraint gives way: aspect band (soft) or area rule (report violation)?
- Directive §3.B.5 says the largest overshoot needed in the 1:2 band is +1.14 m²; exact computation gives +1.217 m² at T ≈ 7.423 m² (gap 7.423–7.439 m²). The 1:2.5 band's maximum is +1.04 m², not ≤ 0.9 m² (cap still never reached).

## U-6 (2026-11-07)
Re-scoped: realises a `CorridorPlan` (contract A.1) instead of a free Polish expression. Spec to follow design note §4; depends on A.1. The area/aspect analysis above still applies per room (room bay: w × D; stack room: w_s × h_i).

## Spec (2026-11-08)
RD + eval written for the corridor-grammar realisation. E01/E02/E05 values verified with an independent implementation of RD §5. Inverse-generation property tests (G01–G04) guarantee the realiser reaches known-optimal geometry.

## Review log
- 2026-11-08 — Attempt 1 (7fbaed4): Router re-run: tests/geometry 38/38, 99 % coverage, whole suite 539, gates clean, ownership clean. Worker found RD 5.1 depth criterion wrong (Router error) — amended. Extra failure codes accepted (PIECE_TOO_SMALL, FOOTPRINT_UNSUPPORTED, BLOCK_TOO_SHALLOW, STACK_TOO_SHALLOW, DEPTH_SEARCH_TIMEOUT). **DONE** (merged).
- Manual fixture run (greedy plan): P25 valid layout (checks pass, 0.03 s); P8 overflows by 12 modules; P60 overflows by 86 / 84 modules (0.09 s). Risk for 3.2: grammar circulation (spine + fingers + strips) may exceed the 18 % budget at 0.93 fill — 3.2 must include a grammar-aware feasibility estimate.

## 3.3b (bands rework) specified 2026-11-08: RD_bands.md / eval_bands.md. To be merged together with A.2.

## 3.3b review (2026-11-08)
52028ea: 55 geometry tests + 2 strict xfails; N01 was a Router error (axis + depths) — corrected case added; band descent is local (17/150 shifted optima missed, documented xfail; generators use equal splits); J2 deep-secondary → JUNCTION_MISALIGNED; R03 uses a seeded random plan. Merged with A.2. Greedy fits none of P8/P25/P60, but random search shows valid plans exist for all three.
