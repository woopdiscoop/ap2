# Ticket X.3 · Evaluation
| ID | Test | Pass condition |
|---|---|---|
| X301 | holes_intake | A ring footprint with one courtyard loads; invalid holes (outside, overlapping, < 3 × 3 modules, non-orthogonal) → French errors with the hole index. |
| X302 | facade_n | Façade length on U, comb (3 fingers) and ring equals the hand-computed value; rectangles and L unchanged (byte-identical feasibility report). |
| X303 | end_to_end | `ale program check` then `ale generate` on the ring footprint with a P25 programme (2 s budget) produce a valid layout. |
| X304 | gates | ruff, format, mypy strict; coverage of touched modules ≥ 90 %; lock --check; whole suite passes. |
