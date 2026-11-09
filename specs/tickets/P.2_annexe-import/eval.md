# Ticket P.2 · Evaluation (synthetic fixtures built in the tests; the real Annexe is never committed)

| ID | Test | Pass condition |
|---|---|---|
| A01 | two_buildings | A synthetic file shaped like the AREP-MS Annexe (2 building titles, repeated headers, merged ENTITE cells, totals, a parking row with text surface) → 2 programmes; line, instance and m² counts as constructed; totals check passes. |
| A02 | entity_carry | Merged/blank ENTITE cells are carried down; codes unique, including two entities with the same initials (`ESPACE COMMUN` / `ESPACE CONFERENCE`). |
| A03 | mapping | Each default rule exercised once; first match wins (`Local technique / Régie` → control_room; `Bureau d'ordre` → mail_room, not office). |
| A04 | unmatched | An unknown espace → exit 2, French error naming it, no file written. |
| A05 | custom_rules | `--rules` file overrides a default and adds an exclusion. |
| A06 | round_trip | Every written programme passes `read_program` with 0 errors; `ale program check` with a matching site and the test rulebook → OK. |
| A07 | totals_mismatch | A stated total 10 m² off → warning, still written. |
| A08 | robustness | Accents/case variants in headers, a `PHYIQUE` typo title, empty rows, numbers stored as text ("16") → parsed; a sheet with no header → exit 2 with a clear message. |
| A09 | gates | ruff, format, mypy strict; coverage of `ale.program.annexe` ≥ 90 % (path-form `--cov`); lock --check; whole suite passes. |
