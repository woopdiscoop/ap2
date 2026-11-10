# Ticket R.3 · Evaluation
| ID | Test | Pass condition |
|---|---|---|
| S301 | hand_values | A 6-room hand-built layout (single corridor, 3 rooms each side): depth, MD, RA, integration and control equal hand-computed values (exact fractions, tolerance 1e-9). |
| S302 | required_door | Two rooms with a REQUIRED adjacency sharing ≥ c get a room–room edge; without it they do not. |
| S303 | walk | `walk_m` on the fixture equals the hand-measured Manhattan distance (module-exact). |
| S304 | entrance | Circulation touching the access edge → not inferred; otherwise `entrance_inferred` true and still computed. |
| S305 | fixtures | P8/P25/P60 seeded layouts: every room has finite depth; measures deterministic (two runs identical). |
| S306 | report | `report.md` contains the section, one row per room, zone means; French number format as the rest of the report; existing report tests unchanged. |
| S307 | unchanged | Layout JSON, DXF and SVG byte-identical to before on the export fixtures. |
| S308 | gates | ruff, format, mypy strict; coverage `ale.analysis` ≥ 95 % (path-form `--cov`); lock --check; whole suite passes. |
