# Ticket A.4 · Evaluation
| ID | Test | Pass condition |
|---|---|---|
| A401 | compat | Contracts 1.5.0; every existing fixture, programme and site loads unchanged; P8/P25/P60 layouts byte-identical (seeded, Q.3 iteration budgets) to before. lock --check OK; schemas regenerated. |
| A402 | site_fields | Valid and invalid `entrances` (off-boundary, two `main`), `cores` (outside, overlapping, bad kind), `mode`/`setbacks` (wrong count, setbacks with mode footprint), `party_edges` (out of range) → accepted / French errors naming the key. |
| A403 | room_anchor | « Ancrage » column: « coin », « Entrée », « ENTREE » parsed; unknown value → error with row; template has the column and drop-down. |
| A404 | floors | « Niveau » 0..n accepted in the contract; `prepare_input` rejects multi-floor programmes for the single-floor engine with a French error; single-floor programmes unchanged. |
| A405 | check | `ale program check` lists anchors and warns on an `entrance` room without a site entrance. |
| A406 | round_trip | Site and programme with all new fields → serialise → load → equal (canonical JSON). |
| A407 | gates | ruff, format, mypy strict; coverage ≥ 90 % on touched modules (path-form); whole suite passes. |
