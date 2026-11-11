# Ticket G.1 · Evaluation
| ID | Test | Pass condition |
|---|---|---|
| N01 | compat | Contracts 1.6.0; rectangles and L shapes: `decompose_footprint` output and P8/P25/P60 layouts byte-identical to before; old CorridorPlans load. |
| N02 | decompose | U, T, H, comb (3 fingers), Z and a courtyard ring decompose deterministically into the documented pieces/junctions (hand-checked fixtures); > 12 pieces → error. |
| N03 | realise | A P25-size programme realises with `check_layout == ()` on U, T, comb and courtyard footprints (seeded plans, iteration budgets). |
| N04 | circulation | Circulation is one connected set across all pieces; every room touches circulation (contact ≥ c). |
| N05 | multi_junction | A parent with two J1 children hosts two junction fingers (`junction_to` set) aligned with each child's spine. |
| N06 | anneal | `anneal` on the U fixture (iteration budget) keeps `check_layout == ()` and does not increase hard count. |
| N07 | gates | ruff, format, mypy strict; coverage ≥ 90 % on touched modules (path-form); lock --check; whole suite passes. |
