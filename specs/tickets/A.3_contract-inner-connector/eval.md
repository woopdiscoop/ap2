# Ticket A.3 — Evaluation
| ID | Test | Pass condition |
|---|---|---|
| I01 | version_schema | `CONTRACTS_VERSION == "1.3.0"`; schemas regenerated; `export_schemas --check`, `lock --check` pass. |
| I02 | backward | Every plan built in the existing tests still validates and round-trips unchanged (JSON bytes identical for plans without markers). |
| I03 | validators | `inner` with 1 band → error; marker in a `start` piece → error; `inner` with a block lacking a marker or holding two → error; valid 2-band `inner` plan → ok. |
| I04 | locate_and_ids | Markers excluded from `room_ids`; `locate` bay index counts the marker. |
| I05 | zones | Zone P before and after the marker in the same block → no split violation; P, A, P on one side → violation. |
| I06 | J2 | site_L with primary multi-band `inner` → `primary connector must be on the cut side (end)`. |
| I07 | gates | Whole suite passes (geometry/topology/optimize never build `inner` plans yet; if mypy or runtime breaks there because of the new union member, report it — do not edit those packages). ruff, mypy on contracts, coverage ≥ 95 %. |
