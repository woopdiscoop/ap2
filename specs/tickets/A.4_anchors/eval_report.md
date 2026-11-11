# Ticket A.4 — Evaluation report

Contracts 1.4.0 → **1.5.0**, backward compatible. Environment: Linux, Python 3.13, venv in the worktree (`pip install -e ".[dev,excel,cad,pdf,raster,vlm]"`).

## Results per eval ID

| ID | Test(s) | Result |
|---|---|---|
| A401 | `tests/contracts/test_contracts_a4.py::test_A401_version_and_locks`, `test_A401_defaults_reproduce_today`, `test_A401_compat_layouts_byte_identical` | PASS. Version 1.5.0, `lock --check` OK, `export_schemas --check` OK, schemas carry the new fields. Every fixture site and programme has the defaults (no entrances, cores, setbacks, party edges, anchor; mode footprint; floor 0). P8 / P25 / P60 (seed-3 start, annealing seed 6, Q.3 iteration budgets): SHA-256 of the canonical start and final layouts equal the digests I computed at base commit `be5d115` before changing anything (they also equal Q.4's `BEFORE_Q4`). |
| A402 | `test_A402_site_fields_valid`, `test_A402_site_fields_invalid`, `test_A402_room_fields`, `test_A402_l_shaped_site` (contract); `test_A402_site_yaml_valid`, `test_A402_site_yaml_invalid[*]` (15 cases), `test_A402_site_yaml_edges_follow_normalisation` (`site.yaml`) | PASS. Off-boundary entrance, two `main`, core outside / overlapping / bad kind / duplicate id, wrong setback count, setbacks with mode footprint, party edge out of range or duplicated: each is refused with a French message naming the key (`entrances[0]`, `cores[0].kind`, `setbacks`, `party_edges`, ...; code `E_SITE_SCHEMA` from `site.yaml`). |
| A403 | `test_A403_room_anchor_parsed[*]`, `test_A403_room_anchor_error_has_row[*]`, `test_A403_column_optional_and_template` | PASS. « coin », « Entrée », « ENTREE », « Entree » parsed; blank = none; unknown value → `E_ANCHOR` with row and column; workbooks without the column still load; the committed template and a freshly written one have the column, a `Coin,Entrée` drop-down and an « Aide » row. |
| A404 | `test_A404_floors` | PASS. « Niveau » accepts integers ≥ 0 (contract and Excel); `prepare_input` raises `E_FLOORS_MULTIPLE` (French, names the levels, row of the first room on another level) for multi-floor programmes; single-floor programmes give the same `PreparedInput` as before. |
| A405 | `test_A405_check_lists_anchors`, `test_A405_plot_mode_warning` | PASS. `ale program check` prints « Ancrages (n) » with each anchored room and the number of site entrances and cores; `W_ANCHOR_NO_ENTRANCE` for an `entrance` room with no site entrance; `W_ANCHOR_CORNERS` when there are more corner rooms than convex corners (two corner rooms on a rectangle: no warning). |
| A406 | `test_A406_round_trip_contract` (JSON and YAML), `test_A406_round_trip_files` (`site.yaml` and `programme.xlsx`) | PASS. Site and programme with every new field: equal after round trip, canonical JSON identical. |
| A407 | `tests/program/test_program_a4.py::test_A407_gates` + the runs below | PASS (see Gates). |

## Gates
- `ruff check` and `ruff format --check` (src, tests): clean.
- `mypy` strict on `src` (125 files): clean.
- `python -m ale.contracts.lock --check`: OK; `export_schemas --check`: OK.
- Whole suite under `--cov=src/ale`: **1368 passed, 13 skipped, 3 xfailed** (21 min 56 s). The 3 xfails and the skips are pre-existing, none added by this ticket.
- Coverage of touched modules (statements + branches): `contracts/models.py` 99 %, `program/excel.py` 99 %, `program/template.py` 98 %, `program/prepare.py` 98 %, `program/models.py` 98 %, `program/site.py` 95 %, `cli/commands/program.py` 100 %. Whole package 98 %.

## Design notes
- `SiteSpec` validation (in the model, so it also protects YAML and JSON loaders) uses shapely lazily inside the validator; importing the contracts still imports no numpy.
- In `site.yaml`, `party_edges` and `setbacks` index the **input** edges, like `access_edge`, and are remapped onto the normalised ring (merged collinear edges, reorientation). Merged edges with different setbacks are refused.
- New issue codes: `E_ANCHOR`, `E_FLOORS_MULTIPLE`, `W_ANCHOR_NO_ENTRANCE`, `W_ANCHOR_CORNERS`, `W_SITE_PLOT_MODE`.
- The `--json` output of `ale program check` is unchanged (its key set is frozen by P06); anchors appear in the text output and, as warnings, in `issues`.
- « Ancrage » is column P (after « Niveau », before « Remarques »); the programme template has 17 columns.

## Existing tests changed (and why)
- `tests/contracts/test_contracts_q4.py::test_D01_contract`, `tests/contracts/test_corridor_plan.py` (`test_K01_version` and the two other version asserts), `tests/contracts/test_serialization.py::test_version_and_layout_schema_version`: `CONTRACTS_VERSION` is now `"1.5.0"` (comment "superseded by ... A.4").
- `tests/contracts/test_corridor_plan.py::test_K02_existing_unchanged`: the list of files changed since 1.0.0 now also contains `models.py` and the `Program`, `RoomSpec`, `SiteSpec` schemas (as Q.4 added `config.py`).
- `tests/contracts/test_corridor_plan.py::test_B02_footprint_unchanged`: `models.py` legitimately differs from the A.2 base now. `footprint.py` and `geometry.py` must still be identical; for `models.py` the test now asserts that the only lines removed since the base are the four replaced by A.4 (the `floor == 0` validator and the `SiteSpec` docstring), everything else being additions.
- `tests/contracts/test_models.py`: `test_M05_program_rules` expected `floor=1` to be refused; it now refuses `floor=-1` and accepts `floor=1` (RD §3). `_instances` (used by `test_M04_frozen_extra`, which requires a sample of every model) gains `Entrance` and `CoreSpec`; imports added.
- `tests/program/program_helpers.py`: `HEADERS` and `row()` have the « Ancrage » column; `program_to_xlsx` writes anchors; `site_to_yaml` writes the new site keys when set; X07 row 13 uses `Niveau=-1` (it was `1`, now valid) so `E_FLOOR` is still exercised.
- `tests/program/test_program_excel.py`: `FROZEN_CODES` gains the five new codes; the fuzz and blank-row tests use 17 columns instead of 16.
- No test was weakened and no xfail was added.

## Spec issues
- RD §2 lists `src/ale/program/data/*` for the template; the committed template is `src/ale/templates/programme_template.xlsx` (regenerated by `python -m ale.program.template`). I also had to touch two files outside the §2 list: `src/ale/program/models.py` (issue-code registries) and `src/ale/cli/commands/program.py` (the `check` output required by §4).
- RD §3 says the entrance tolerance is "one module", but the contract has no grid (the module is a config value, 100 mm by default). The contract uses a fixed 0.1 m (`ENTRANCE_TOLERANCE_M`); a stricter check against the real module can come with the engine that uses it.
- RD §3 does not say which indices `party_edges` / `setbacks` use in `site.yaml`; I followed `access_edge` (input edges, remapped), see above.
- RD §3 "reject programmes with rooms on several floors": a programme whose rooms are all on the same non-zero level is accepted (single-floor engine, nothing changes).
- RD §4 says the column « Niveau » "now accepts integers ≥ 0"; a numeric text such as "1" is accepted, a non-integer or negative value gives `E_FLOOR` (message changed from "Seul le niveau 0 est accepté en v1" to "Le niveau doit être un entier ≥ 0").
- With `mode: plot`, `prepare_input` still treats the polygon as the building outline (no engine uses the mode yet); `ale program check` warns with `W_SITE_PLOT_MODE`.
