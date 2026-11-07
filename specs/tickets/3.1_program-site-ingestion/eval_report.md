# Ticket 3.1 — Program & Site Ingestion · Evaluation Report

Environment: Linux, Python 3.13.18, `pip install -e ".[dev,excel,cad]"` (openpyxl 3.1.5, ezdxf 1.4.5).
Ticket suite: `pytest tests/program` → **56 passed** in ≈ 5 s (budget 60 s).

## 1. Test IDs

| ID | Test | Result |
|---|---|---|
| X01 | `test_X01_roundtrip_fixtures[program_08/25/60]` | PASS (3/3) |
| X02 | `test_X02_type_resolution` | PASS |
| X03 | `test_X03_numbers_fr` | PASS |
| X04 | `test_X04_zone_and_facade` | PASS |
| X05 | `test_X05_orientation` | PASS |
| X06 | `test_X06_refs` | PASS |
| X07 | `test_X07_error_catalogue` | PASS |
| X08 | `test_X08_headers` | PASS |
| X09 | `test_X09_comments_blank` | PASS |
| X10 | `test_X10_never_raises` | PASS |
| Y01 | `test_Y01_yaml_fixtures[site_rect_small/site_rect/site_L]` | PASS (3/3) |
| Y02 | `test_Y02_module_exact` | PASS |
| Y03 | `test_Y03_inward_snap_rect` | PASS |
| Y04 | `test_Y04_inward_snap_L` | PASS |
| Y05 | `test_Y05_normalise_and_access` | PASS |
| Y06 | `test_Y06_site_errors` | PASS |
| Y07 | `test_Y07_dxf_mm` | PASS |
| Y08 | `test_Y08_dxf_errors` | PASS |
| Z01 | `test_Z01_fixtures_fit[...]` | PASS (3/3) |
| Z02 | `test_Z02_not_feasible` | PASS |
| Z03 | `test_Z03_room_infeasible` | PASS |
| Z04 | `test_Z04_rulebook_coverage` | PASS |
| Z05 | `test_Z05_facade` | PASS |
| Z06 | `test_Z06_band_fallback` | PASS |
| Z07 | `test_Z07_exact_arithmetic` | PASS |
| P01 | `test_P01_prepare_ok` | PASS |
| P02 | `test_P02_collects_all` | PASS |
| P03 | `test_P03_deterministic` | PASS |
| P04 | `test_P04_template_content` | PASS |
| P05 | `test_P05_template_example_reads` | PASS |
| P06 | `test_P06_cli_check` | PASS |
| P07 | `test_P07_cli_template` | PASS |
| P08 | `test_P08_cli_registration_only` | PASS (two added lines: one import, one `add_typer`) |

Additional edge-case tests (all PASS): `test_canon_header`, `test_unreadable_workbook`,
`test_empty_sheet_and_no_rooms`, `test_cell_type_variants`, `test_bad_cell_types`,
`test_duplicate_header_and_blank_header`, `test_issues_from_validation_error`,
`test_normalise_rotation_and_duplicates`, `test_site_schema_details`,
`test_module_footprint_edge_cases`, `test_dxf_variants`, `test_room_fit_missing_type_and_empty_band`,
`test_overshoot_counted`, `test_template_module_main`, `test_cli_check_workspace_and_usage`,
`test_load_rulebook_errors`, `test_prepare_input_rejects_infeasible`.

Every number of eval.md was reproduced exactly (no expectation disputed).

## 2. Gates

| Gate | Result |
|---|---|
| `ruff check .` | clean |
| `ruff format --check .` | clean (69 files) |
| `mypy` (strict, `src/ale`) | clean (43 files) |
| `python -m ale.contracts.lock --check` | exit 0 (`OK`) |
| Coverage `ale.program` | **99 %** (1019 stmts, 14 missed; 306 branches, 5 partial) — line ≈ 98.6 %, branch ≈ 98.4 % |
| Ownership | only RD §3 paths + this report; `src/ale/cli/__init__.py`: two added lines (import + registration), nothing removed |

Whole repository suite:

| Install | Result |
|---|---|
| `.[dev]` (what `ci.yml` installs today) | 429 passed, 11 skipped (ticket tests needing openpyxl / ezdxf skip) |
| `.[dev,excel]` | 461 passed, 8 skipped (only the 3 DXF tests skip) |
| `.[dev,excel,cad]` (this ticket's prescribed env) | 461 passed, 5 skipped, **3 failed**: `tests/cli/test_doctor.py::test_D01_clean_machine`, `test_D06_never_executes`, `test_D09_no_network` |

The 3 doctor failures are pre-existing and unrelated to this ticket: they assert the
`pip install "ale[cad]"` hint, i.e. they assume ezdxf is **not** installed. Verified by running
`tests/cli/test_doctor.py` from the base commit `38f7624` (untouched tree) in the same
environment: same 3 failures.

## 3. Spec issues / ambiguities (literal reading implemented)

1. **Doctor tests vs. `cad` extra (cross-ticket).** Ticket 0.1's D01/D06/D09 fail whenever ezdxf
   is installed, while this ticket's tests may assume `.[dev,excel,cad]`. CI (`ci.yml`, not owned)
   installs only `.[dev]`. To keep CI green either way, the ticket tests use
   `pytest.importorskip("openpyxl")` / `("ezdxf")` (reported as SKIPPED). Recommended Router action:
   install `.[dev,excel,cad]` in CI and make the doctor tests independent of installed extras.
2. **CLI registration (resolved at review).** The RD now allows two added lines; the
   `__import__` one-liner was replaced by `from ale.cli.commands import program as program_cmd`
   plus `app.add_typer(program_cmd.app, name="program")`. P08 checks exactly these two lines.
3. **Codes not named by the RD.** The frozen list has no code for an unreadable input file, a
   malformed `site.yaml` (both/none of `footprint`/`footprint_dxf`, unknown keys, bad values) or an
   invalid rulebook file. Added (exported as `EXTRA_ERROR_CODES`): `E_FILE_UNREADABLE`,
   `E_SITE_SCHEMA`, `E_RULEBOOK_INVALID`. None can be produced by a readable workbook (X10 asserts
   only the frozen list).
4. **`ModuleFootprint` location.** Not in contracts nor in the RD's `models.py` list; defined in
   `ale/program/models.py` (with `RoomFit` for `per_room` entries).
5. **P02 rulebook errors with an unparsable program.** Feasibility runs only when all three inputs
   parse; to still report rulebook coverage (P02), `ProgramReport.types` lists the types resolved on
   any row and coverage is checked against it when the program failed.
6. **Other literal choices:** duplicate ids inside one `Adjacent à`/`Éviter` cell are de-duplicated
   silently (contract forbids duplicates, RD has no code); a name > 120 characters (contract limit)
   → `E_EMPTY_NAME`; a blank or non-text `Type` → `E_UNKNOWN_TYPE`; a duplicated header → the first
   is used, later ones `W_UNKNOWN_COLUMN`; `E_MISSING_COLUMN` has `row = 1`; the sheet name must be
   exactly `Programme`; `north_angle_deg` and `access_edge` default to 0 when omitted; DXF `layer`
   is required (matched case-insensitively), a polyline whose last vertex repeats the first counts
   as closed, arcs (bulges) → `E_SITE_NOT_ORTHOGONAL`; module polygons (like normalised sites) start
   at the lowest-then-leftmost vertex; `InputError.issues` carries errors **and** warnings;
   `ale program template` copies the committed template and exits 1 when the target exists without
   `--force`.
