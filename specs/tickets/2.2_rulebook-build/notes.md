# 2.2 — Router notes

Status: BLOCKED on 2.1 and 0.3.
Blend rule `final = blend(seed, mined, n/(n+k))` with `k = rulebook.blend_k`; blend each quantile linearly with the same weight; because seed and mined quantiles are each ordered, the result keeps p10 ≤ p50 ≤ p90 without re-sorting.

## Review log
- 2026-11-09 — b171fba (redone in a fresh worktree after the limit; nothing had been lost). Router spec errors found: seed counted twice (Laplace prior + blend) → neutral prior; version contained the date → content hash only. Gap for integration ticket: `north_angle_deg` column missing from `ale.corpus.meta.COLUMNS`. Other readings accepted (Hazen quantiles, clip all three quantiles, same-type pairs need ≥ 2 rooms, config-sourced weights). Rework requested.
