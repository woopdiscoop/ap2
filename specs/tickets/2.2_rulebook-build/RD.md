# Ticket 2.2 — Rulebook build (`ale rulebook build`) · Requirements

> **Worker brief.** Context = this file, `eval.md`, the contracts (`Rulebook`, `TypeStats`, `Quantiles`, `Adjacency`,
> `AdjEntry`, `CoreOffset`, `Fidelity`, `Bearing`, `taxonomy`, `serialization`, `orientation`), the public API of
> `ale.mining` (`extract_topology`, `PlanTopology`, `Contact`), `ale.corpus` (DB schema), `ale.workspace`, `ale.config`,
> and the CLI stub `src/ale/cli/commands/rulebook.py`.

## 1. Files
```
src/ale/rulebook/{__init__,stats,blend,build,report}.py
src/ale/cli/commands/rulebook.py          # replace the `build` stub body (keep options)
tests/cli/test_cli_surface.py             # ONLY: remove `rulebook build` from the stub list
tests/rulebook/**
specs/tickets/2.2_rulebook-build/eval_report.md
```

## 2. Inputs
`build_rulebook(topologies: Sequence[PlanTopology], plans_metric: Sequence[PlanGeometry], seed: Rulebook | None, config) -> BuildResult(rulebook, report_md)`.
CLI `ale rulebook build --workspace W [--seed-rulebook S] [--min-support N]`: loads every `extracted/**/plan.json`
whose unit is EXTRACTED and not excluded, runs `extract_topology` (skipping plans with unknown scale), builds, writes
`rulebook/rulebook.yaml` (via `dump_yaml`), `rulebook/report.md`, and `rulebook/rulebook.sqlite` (tables
`plans`, `rooms`, `contacts` dumping the inputs for audit).

## 3. Statistics (`stats.py`) — every plan weighted by `rulebook.fidelity_weights[fidelity]`
- **Adjacency** for each unordered type pair (a, b) (typed rooms only; `unknown`/SPECIAL/CIRCULATION excluded):
  `support` = Σ weights of plans containing both types; `hits` = Σ weights of plans where ≥ 1 pair of such rooms has a
  contact (WALL or DOOR); `p = (hits + α·p0) / (support + α)` with `α = rulebook.laplace_alpha`, `p0 = seed.adjacency.p(a,b)`
  if a seed is given else 0.5; `n_support = round(support)` (integer). Pairs with `n_support < min_support` keep the seed
  value (or are omitted without seed).
- **Aspect & area** per type, from rooms in plans of fidelity CAD or PDF_VECTOR only: aspect = long/short side of the
  room's minimum rotated rectangle; area m². Weighted quantiles p10/p50/p90 (linear interpolation on the weighted CDF);
  `n` = number of rooms. Aspect p90 clipped to `shape.aspect_max` (hard rule) with a note in the report if clipped.
- **Core offset**: per plan, footprint = union of rooms' bbox; core centroid = area-weighted centroid of rooms whose type
  has `service_core`; `dx_norm = (cx − fx) / W`, `dy_norm = (cy − fy) / H`; weighted mean over plans; `n` = plans used.
- **Orientation** per type: only plans whose north is known (meta `north_angle_deg` in `files.meta_json`; otherwise
  skipped): share of façade length per bearing (N/E/S/W) for that type minus the type-independent share, scaled to
  [−1, 1] by dividing by the max absolute value over bearings; types with < 3 plans keep the seed values.

## 4. Blend (`blend.py`)
For every statistic present in both seed and mined: `final = seed + w × (mined − seed)` with `w = n / (n + rulebook.blend_k)`
(`n` = support / room count / plan count as above). Quantiles blended per quantile (order preserved). Types only in the seed
are kept; types only mined are added if their `n ≥ min_support`. `kind = "blended"` with a seed, else `"mined"`;
`version = "mined-<UTC date>-<first 8 hex of content hash of the inputs>"`; `n_plans`; `source_mix` (count per fidelity).

## 5. Report (`report.md`, French)
Summary (plans used/skipped with reasons, source mix), then one table per statistic with value, support and source
(seed / mined / blended) — every number traceable.

## 6. Determinism
Same inputs → byte-identical `rulebook.yaml` and `report.md`.
