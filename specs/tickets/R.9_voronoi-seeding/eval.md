# Ticket R.9 · Evaluation
| ID | Test | Pass condition |
|---|---|---|
| V901 | cells | On a 20 × 10 m rectangle with 4 targets (60/20/10/10 %): every cell contiguous, cell areas within 5 % of targets after iteration, boundaries axis-aligned (L1). |
| V902 | facade | `needs_facade` rooms get exterior contact ≥ f in the diagram on P25 whenever the façade length allows (count reported). |
| V903 | deterministic | Same seed → identical diagram and plan (two fresh processes). |
| V904 | valid | Voronoi-seeded plans realise and pass `check_layout` on P8/P25/P60. |
| V905 | comparison | The comparison table of RD §4 is produced by a test (iteration budgets), written to the eval report, and the default is set by the adoption rule. |
| V906 | unchanged | With `seeder="spring"` results are byte-identical to before. |
| V907 | gates | ruff, format, mypy strict; coverage of `ale.topology.voronoi` ≥ 90 % (path-form); lock --check; whole suite passes. |
