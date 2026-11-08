# 3.4 — Router notes

Status: BLOCKED on 3.2, 3.3.
Moves M1–M3 must preserve normalisation (Wong–Liu); M4 restricted to same macro-zone and areas within 25 %. Uses `ale.guards.bounded`.

## U-6 (2026-11-07)
Moves are grammar moves G1–G6 (design note §6), not Wong–Liu M1–M3. Metropolis acceptance, cooling and `bounded(...)` unchanged.

## Review log
- 2026-11-08 — 02286ce: O01–O10 pass, 95 % coverage, generate works (3 variants). Worker found the SA design flaw (Router error): median-rule T0 with the ×1000 hard penalty → T0 ≈ 9000, never cools → random walk (P25 13 → 13 hard). Spec amended: lexicographic (n_hard, cost) acceptance, separate T_h / T_c, progress-fraction schedule, throughput target with caching. New gates: P25 strict improvement, P8 ≤ 1 hard. Rework requested.
