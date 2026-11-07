# 2.2 — Router notes

Status: BLOCKED on 2.1 and 0.3.
Blend rule `final = blend(seed, mined, n/(n+k))` with `k = rulebook.blend_k`; blend each quantile linearly with the same weight; because seed and mined quantiles are each ordered, the result keeps p10 ≤ p50 ≤ p90 without re-sorting.
