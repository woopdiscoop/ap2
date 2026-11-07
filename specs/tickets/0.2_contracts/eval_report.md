# Ticket 0.2 — Data Contracts · Eval report

Revision 2 (2026-11-07). This revision applies the Router's spec update: taxonomy v1.1.0
(75 types, SPECIAL = `outdoor_space` and `unknown`); program rooms and rulebook types now
reject every SPECIAL and CIRCULATION type; T01, T05 and M11 are updated; T03 has 11 new
rows; A03 is corrected.

Environment: Python 3.13, pydantic 2.14.3, shapely 2.2.0, jsonschema 4.26.0, pytest 9.2,
hypothesis 6.170, ruff 0.17.4, mypy 2.4.1 (+ types-PyYAML, types-shapely).
Command: `PYTHONPATH=src pytest --timeout=60 tests/contracts`. There is no `src/ale/__init__.py`
and no `pyproject.toml` in this tree. Both belong to Ticket 0.1. Implicit namespace packages
were used, and the suite was run in that state.

**Result: 203 passed, 0 failed, 0 xfailed, 0 skipped. Wall time about 6 s.**

## Test results

| ID | Test(s) in `tests/contracts/` | Result |
|---|---|---|
| U01 | `test_units.py::test_U01_exact_modules` | PASS |
| U02 | `test_units.py::test_U02_rounding_modes` | PASS |
| U03 | `test_units.py::test_U03_roundtrip_property` (Hypothesis, 300 examples, derandomized) | PASS |
| U04 | `test_units.py::test_U04_area_exact` | PASS |
| U05 | `test_units.py::test_U05_module_range` (×5), `test_U05_input_types` | PASS |
| U06 | `test_units.py::test_U06_no_float_modulo`, `test_U06_checker_detects_planted_violations` (×9) | PASS |
| A01 | `test_area_rule.py::test_A01_directive_table` (×6), `test_A01_delta_7_5` | PASS |
| A02 | `test_area_rule.py::test_A02_cap_gap` | PASS |
| A03 | `test_area_rule.py::test_A03_bounds_exact` | PASS (corrected values: 97×10 and 10×112 valid; 19×51 and 19×59 invalid) |
| A04 | `test_area_rule.py::test_A04_pct_regime` | PASS |
| A05 | `test_area_rule.py::test_A05_check_fields` | PASS |
| A06 | `test_area_rule.py::test_A06_narrow_band` | PASS |
| A07 | `test_area_rule.py::test_A07_min_side` | PASS |
| A08 | `test_area_rule.py::test_A08_bounded` | PASS (< 1 ms) |
| A09 | `test_area_rule.py::test_A09_rounds_up`, `test_A09_below_target_fallback` | PASS |
| A10 | `test_area_rule.py::test_A10_fine_grid` | PASS: 5 801 targets, none missing, none below target, max overshoot 0.11 m², about 1.8 s |
| O01 | `test_orientation.py::test_O01_bearings_north_up` (×4) | PASS |
| O02 | `test_orientation.py::test_O02_bearings_rotated` | PASS |
| O03 | `test_orientation.py::test_O03_bins` (×11) | PASS |
| O04 | `test_orientation.py::test_O04_normals` | PASS |
| T01 | `test_taxonomy.py::test_T01_load_valid` | PASS (75 types, version 1.1.0, SPECIAL = outdoor_space and unknown, byte-identical to `taxonomy.v1.yaml`) |
| T02 | `test_taxonomy.py::test_T02_integrity_errors` (×8), `test_T02_lists_every_problem` | PASS |
| T03 | `test_taxonomy.py::test_T03_normalisation_table` (×35) | PASS (all 35 rows match, including the 11 new v1.1 rows) |
| T04 | `test_taxonomy.py::test_T04_canonical_forms` (×35), `test_T04_canonical_extra_rules` | PASS |
| T05 | `test_taxonomy.py::test_T05_room_type_validator` | PASS (kitchen, unknown, outdoor_space and circulation rejected) |
| M01 | `test_models.py::test_M01_roundtrip_json` (×7 models) | PASS |
| M02 | `test_models.py::test_M02_roundtrip_yaml` (×3), `test_M02_yaml_field_order_and_dates` | PASS |
| M03 | `test_models.py::test_M03_strict_ints` | PASS |
| M04 | `test_models.py::test_M04_frozen_extra` (all 29 contract models found by introspection) | PASS |
| M05 | `test_models.py::test_M05_program_rules`, `test_M05_site_rules` | PASS |
| M06 | `test_models.py::test_M06_module_polygon`, `test_M06_module_polygon_rejected` (×8), `test_M06_float_geometry` | PASS |
| M07 | `test_models.py::test_M07_rect_overlap` | PASS |
| M08 | `test_models.py::test_M08_placed_room`, `test_M08_layout_rules` | PASS |
| M09 | `test_models.py::test_M09_polish_expression`, `test_M09_polish_valid` (×6), `test_M09_polish_invalid` (×7) | PASS |
| M10 | `test_models.py::test_M10_plan_geometry`, `test_M10_extraction_parts` | PASS |
| M11 | `test_models.py::test_M11_rulebook_rules` | PASS (`types` keys circulation, outdoor_space, unknown and kitchen rejected) |
| M12 | `test_models.py::test_M12_rulebook_hash` (subprocess) | PASS |
| J01 | `test_serialization.py::test_J01_canonical_bytes`, `test_J01_float_rounding` | PASS |
| J02 | `test_serialization.py::test_J02_schema_no_drift` (subprocess + tmp copy), `test_J02_export_in_process` | PASS |
| J03 | `test_serialization.py::test_J03_schemas_validate` (×7), `test_J03_taxonomy_schema` | PASS (see note 6) |
| J04 | `test_serialization.py::test_J04_validate_cli` (subprocess), `test_J04_validate_in_process`, `test_J04_rulebook_all_types_present` | PASS |
| J05 | `test_serialization.py::test_J05_lock` (subprocess, tmp copy), `test_J05_lock_in_process` | PASS |
| J06 | `test_serialization.py::test_J06_import_light` | PASS (about 0.2 s; no numpy/networkx/pandas/torch) |

Extra tests: `test_area_rule_preconditions`, `test_label_match_model` and
`test_version_and_layout_schema_version` all pass.

## Static gates

| Gate | Result |
|---|---|
| `ruff check --line-length 100 --target-version py311 --select E,F,W,I,B,UP,SIM,PTH,RUF src/ale/contracts tests/contracts` | clean |
| `ruff format --check --line-length 100 src/ale/contracts tests/contracts` | clean (20 files) |
| `mypy` (`strict = True`, `plugins = pydantic.mypy`), `-p ale.contracts` | 0 errors (14 source files) |
| Coverage `--cov=ale.contracts --cov-branch` | **99.7 % line** (1160/1163), **98.5 % branch** (337/342) |
| `python -m ale.contracts.export_schemas --check` | exit 0 (taxonomy v1.1 does not change any schema, so no files were regenerated) |
| Ownership | only RD §3 paths plus this report. No `CONTRACTS.lock`, `src/ale/__init__.py` or `pyproject.toml` |

## Spec issues, ambiguities and decisions

1. **A03 (resolved).** The Router confirmed the original rectangles were wrong and corrected eval.md
   to 97×10, 10×112, 19×51 and 19×59. The strict-xfail test with the old values is deleted.
2. **Shapely typing.** Shapely 2.2 ships no `py.typed`. Strict mypy passes here because
   `types-shapely` is installed. Ticket 0.1's dev dependencies or mypy config should add
   `types-shapely`, or set `ignore_missing_imports` for `shapely.*`. Without one of these, mypy
   reports `import-untyped`. Shapely is imported lazily, so importing the models never pulls in numpy.
3. **`load_yaml` keeps ISO dates as strings.** It uses a `yaml.SafeLoader` subclass with the
   timestamp resolver removed. Without this, a hand-written `date: 2026-11-07` would load as a
   `datetime.date` and be rejected by the `StrictStr` field. Otherwise it behaves like `safe_load`.
4. **`ModuleRect` accepts positional arguments.** `ModuleRect(x, y, w, h)` works as well as the
   keyword form, because eval.md and the RD both use positional notation. Validation and
   extra-field rejection are unchanged.
5. **`PlanGeometry.to_metric()`:**
   - coordinates, wall thickness, text height and `width_native` are multiplied by the scale in
     exact decimal arithmetic, so 90 × 0.01 gives exactly 0.9.
   - `width_native` is converted to metres. It has to be, because the scale becomes 1.0 and the
     width consistency rule must still hold.
   - for `Y_DOWN` input, `TextItem.rotation_deg` is negated. Mirroring about y = 0 maps an angle θ
     to −θ. The RD does not mention rotation.
6. **J03 for `PolishExpression`.** RD §11 exports no schema file for `PolishExpression`. The test
   validates it against `PolishExpression.model_json_schema()` instead. Exported schemas include
   the model docstrings as descriptions, so a docstring change shows up as schema drift.
7. **Lock paths** are relative to `src/ale/contracts/`, for example `schemas/Rulebook.schema.json`,
   with POSIX separators. The RD says only "relative path".
8. **Literal readings and small additions:**
   - only the packaged default taxonomy is cached. An explicit `path` is re-read on every call.
   - `SiteSpec` checks that every ring of the footprint is rectilinear ("v1: rectilinear"), and
     that `access_edge` is a valid index.
   - `PlanGeometry` checks that `LabelledPolygon` ids are unique ("unique within the plan").
   - the area functions raise `ValueError` for a target of 0 m² or less.
   - `compass_bearing_deg(0, 0, …)` is not rejected. It returns the bearing of `atan2(0, 0)`.
   - `bearing_bin` wraps inputs outside [0, 360) first.
   - the units helpers raise `ValueError` for a bad `module_mm`, including the float `600.0`.
9. **Canonical form.** `M2` on its own matches the room-number pattern `^[A-Z]\d+$`, so a leading
   or trailing `M2` without a number before it is dropped as a room number. This follows the
   literal rules.
10. **Notation in M08.** `PlacedRoom(rect=…, target_area_m2=7.5)` leaves out the required
    `instance_id` and `spec_id`, which have no defaults in the RD. The test supplies them.
