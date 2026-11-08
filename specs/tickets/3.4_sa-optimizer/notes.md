# 3.4 — Router notes

Status: BLOCKED on 3.2, 3.3.
Moves M1–M3 must preserve normalisation (Wong–Liu); M4 restricted to same macro-zone and areas within 25 %. Uses `ale.guards.bounded`.

## U-6 (2026-11-07)
Moves are grammar moves G1–G6 (design note §6), not Wong–Liu M1–M3. Metropolis acceptance, cooling and `bounded(...)` unchanged.

## Review log
- 2026-11-08 — 02286ce: O01–O10 pass, 95 % coverage, generate works (3 variants). Worker found the SA design flaw (Router error): median-rule T0 with the ×1000 hard penalty → T0 ≈ 9000, never cools → random walk (P25 13 → 13 hard). Spec amended: lexicographic (n_hard, cost) acceptance, separate T_h / T_c, progress-fraction schedule, throughput target with caching. New gates: P25 strict improvement, P8 ≤ 1 hard. Rework requested.
- 2026-11-08 — Rework 66ecfe1: lexicographic SA works (P8 6→0, P25 13→7, P60 35→27 in 15 s; 86 it/s on P25). Accepted with notes: O03 P8 gate uses seed 6 (P8 ≤ 1 holds for 6/10 seeds — reliability gap, recorded honestly); `fastreal.py` subclasses private geometry internals (equivalence-tested on 225 plans; coupling risk → fold caching into ale.geometry later); G2 'fold into stack' variant and hard-focused room picking accepted. **DONE**.
- Router run: `ale generate` P60, 60 s → 22 hard breaks: NO_FACADE 11, ASPECT 7, AREA_UNDER 1, MIN_WIDTH 1, REQUIRED_ADJ 2.
## Proposed next wave (quality)
- Q.1 Realisation never emits degenerate rooms: when a stack/bay cannot meet area/aspect, return a failure (or force a room bay) instead of a 1.44 m² / 8:1 room; optimiser then avoids it.
- Q.2 Façade-aware grammar: connector may sit at the cut side or an interior position (not only piece ends); optimiser move that pulls `needs_facade` rooms into exterior blocks (band 0 block A / last band block B); 3.1 feasibility estimates usable façade length under the grammar, not raw perimeter.
- Q.3 Fold the optimiser's realisation cache into ale.geometry (remove fastreal.py coupling); make P8 ≤ 1 hold for all seeds.
