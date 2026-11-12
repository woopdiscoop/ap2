# Ticket R.8 — Evaluation

| ID | Check | Pass |
|---|---|---|
| R801 | Synthetic corpus with constructed depths/widths per type (helper in `tests/rulebook/`) | learned p50/p90 equal the constructed values within one module (0.1 m) |
| R802 | Type with < 5 façade samples | fields None, report says « échantillon insuffisant », realiser uses `facade.max_depth_m` |
| R803 | Contract 1.8.0 | old rulebook files (seed rulebook, test fixtures) load unchanged; schema + lock regenerated; `lock --check` OK |
| R804 | Realiser: a type with learned p90 = 5.4 m on a plate where the config says 7.2 m | rooms of that type deeper than 5.4 m get `FACADE_DEPTH` (soft); other types unchanged |
| R805 | Byte-identity with no learned depths: P08/P25/P60 digests (M206) | unchanged |
| R806 | Reports: rulebook report per-type table; plan report « votre plan / plans construits » | present, French |
| R807 | Real corpus run (if a scaled corpus exists in the workspace; otherwise state it): number of types with ≥ 5 samples and office depth p50/p90 | figures in the eval report |
| R808 | Gates: ruff, ruff format, mypy, lock --check, full `-m "not slow"` (`-q`, count visible) | green |
