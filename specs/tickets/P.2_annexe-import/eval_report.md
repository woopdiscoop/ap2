# Ticket P.2 · Evaluation report

Implementation: `src/ale/program/annexe.py`, `src/ale/program/data/annexe_rules.yaml`, the
`ale program import` command in `src/ale/cli/commands/program.py`. Tests:
`tests/program_annexe/test_annexe_import.py` (fixtures built with openpyxl in
`tests/program_annexe/annexe_helpers.py`; the real AREP-MS Annexe is neither used nor committed).

| ID | Tests | Result |
|---|---|---|
| A01 | `test_A01_two_buildings`, `test_A01_building_filter` | PASS: 2 programmes (9 lines / 17 instances / 492 m², 5 / 6 / 246 m²), both totals OK, parking row skipped and reported, `--building` filter |
| A02 | `test_A02_entity_carry`, `test_A02_blank_entity_cells_and_codes`, `test_A02_id_uniqueness_and_long_names` | PASS: merged and blank ENTITE cells carried; `ESPACE COMMUN` → `EC01…`, `ESPACE CONFERENCE` → `EC201…` |
| A03 | `test_A03_mapping`, `test_A03_zones_and_facades` | PASS: each of the 21 default rules is hit; every AREP-MS name of the ticket (plus variants) maps as expected; `Local technique / Régie` → control_room, `Bureau d'ordre` → mail_room |
| A04 | `test_A04_unmatched` | PASS: exit 2, French error naming each unmatched espace, no output directory created |
| A05 | `test_A05_custom_rules`, `test_A05_rules_replace_and_errors` | PASS: a `--rules` file overrides `Salle de prière` and excludes `chauffeurs`; invalid rules files → exit 2 |
| A06 | `test_A06_round_trip`, `test_A06_write_outputs_api` | PASS: `read_program` 0 errors and equal to the in-memory program; `ale program check` → OK |
| A07 | `test_A07_totals_mismatch`, `test_A07_subtotals_and_grand_total` | PASS: a total 10 m² off → warning, files still written; ≤ 0.5 m² → OK |
| A08 | `test_A08_robustness`, `test_A08_typo_title_and_text_numbers`, `test_A08_no_header`, `test_A08_second_sheet_and_notes_before_header`, `test_A08_duplicate_building_names` | PASS: header variants and shifted columns, `PHYIQUE`, empty rows, `"16"` / `"20,5"`; no header or unreadable file → exit 2 |
| A09 | `test_A09_gates` (lock check) + gates below | PASS |

## Gates
- `ruff check src tests`, `ruff format --check src tests`: clean.
- `mypy` (strict, `src/ale`): no issues.
- `python -m ale.contracts.lock --check`: OK (no contract change).
- Coverage of `src/ale/program/annexe.py` (`--cov=src/ale/program`): 99 %.
- Whole suite: 1192 passed, 12 skipped, 4 xfailed (pre-existing, none added).

## Design choices (within the RD)
- **Rules file**: a plain list is placed *before* the defaults (first match wins, so it overrides them and
  can add exclusions); the mapping form `{rules: [...], include_defaults: false}` replaces the defaults.
- **Zone/façade defaults**: `zone` empty → the type's taxonomy default zone; `facade` absent → false.
- **Totals**: a `TOTAL` row is compared with the rows read since the previous checked total (sub-totals),
  or with the whole building when that matches (grand total). A `TOTAL` after a `(+) Circulation` row
  includes circulation and is not checked. The last number of the row is the stated total.
- **Rows with an invalid NOMBRE** (0, text) are skipped and reported like text surfaces.
- **IDs**: the counter skips an id already taken in the building (`EC` + 201 vs `EC2` + 01).
- Buildings without any importable line are dropped with a warning; no line at all → exit 2.

## Spec issues
1. **A06 "test rulebook"**: the Ticket 3.1 test rulebook only covers 13 fixture types, so a programme with
   `mail_room`, `control_room`, `auditorium`, … fails `ale program check` with `E_TYPE_NOT_IN_RULEBOOK`.
   Following the intent (the programme is accepted), A06 uses the test rulebook extended with the
   programme's missing types, with the same uniform statistics.
2. **Totals vs. excluded rows** (RD §3 "sum of the read rows"): the AREP-MS Région total includes 250 m² of
   car park that the exclusion rule drops (`arep_ms_gaps.md`). Excluded rows with a numeric surface are
   therefore counted in the compared sum, otherwise a correct Annexe would always warn.
3. **"Each default rule exercised once" (A03)**: several names hit the same rule (e.g. many → office);
   the test checks every rule is hit at least once and each listed name maps to the expected type.
