# Ticket 2.2 — Evaluation (synthetic PlanTopology / PlanGeometry inputs)
| ID | Test | Pass condition |
|---|---|---|
| K1 | adjacency_p | 4 CAD plans (weight 1) containing office+meeting_room, 3 with contact → with α = 1, no seed: p = (3 + 0.5)/(4 + 1) = 0.7, n_support 4. |
| K2 | fidelity_weights | Same with one plan RASTER (weight 0.5) and its contact → hits/support computed with weights (asserted). |
| K3 | min_support | Pair with support 2 and min_support 5 → seed value kept (with seed) / omitted (no seed). |
| K4 | quantiles | Weighted quantiles of known values match a hand computation; RASTER rooms ignored for aspect/area; aspect p90 clipped to 2.0 with a report note. |
| K5 | core_offset | Plans with the core at a known position → dx_norm, dy_norm exact. |
| K6 | orientation | Plans with north known and offices facing S → office.orientation S = 1.0 after scaling; < 3 plans → seed kept. |
| K7 | blend | Seed p = 0.8, mined p = 0.4 with n = 10, k = 10 → 0.6; quantile order preserved after blending. |
| K8 | output_valid | Result validates as `Rulebook` (round-trip YAML), `kind`, `version` format, `source_mix` correct. |
| K9 | deterministic | Shuffled inputs → identical YAML and report bytes. |
| K10 | cli | Workspace with ingested+extracted synthetic DXF plans (as in tests/corpus_extract) and a `plans_meta.csv` giving north: `ale rulebook build --seed-rulebook` writes the 3 files; exit 0; no scale → plan skipped and reported. |
| K11 | gates | ruff, format, mypy strict; coverage of `ale.rulebook` ≥ 90 %; lock --check; whole suite. |
