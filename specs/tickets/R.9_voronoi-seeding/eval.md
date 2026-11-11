# Ticket R.9 · Evaluation (deterministic budgets)
| ID | Test | Pass condition |
|---|---|---|
| R9-01 | diagram_counts | On P25, P60 and the AREP top floor: every room gets exactly its cell count when space allows (else the shortfall is reported), cores untouched, unclaimed = reserve; deterministic for a seed (two fresh processes). |
| R9-02 | anchors | `anchor="corner"` room owns the corner cell; `anchor="entrance"` room touches the main entrance; REQUIRED pairs adjacent; service rooms next to a core (fixture built for it). |
| R9-03 | facade_share | Façade rooms all touch the façade when the shares fit; when they do not, the report names the rooms without façade. |
| R9-04 | plan | `fromdiagram` produces a CorridorPlan that passes `check_against`; realisation passes `check_layout` on P8/P25/P60. |
| R9-05 | unchanged | `seeder="spring"` (default) → results byte-identical to before. |
| R9-06 | svg | `export/diagram.py` writes an SVG: one colour per room type, cores hatched, entrance marked; deterministic bytes. |
| R9-07 | comparison | The RD §5 table is produced by a test and written to the eval report; the adoption verdict is stated. |
| R9-08 | D05_target | AREP top floor, hard depth mode, `seeder="cells"`: assert NO_FACADE ≤ 1 and FACADE_DEPTH = 0 (as Q.4 D05 originally wrote). Keep as written even if it fails; report. |
| R9-09 | gates | ruff, format, mypy strict; coverage of the new modules ≥ 90 % (path-form); lock --check; whole suite passes (except R9-08 if unmet, reported). |
