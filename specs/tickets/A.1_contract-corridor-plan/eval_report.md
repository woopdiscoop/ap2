# Ticket A.1 — Contract amendment: CorridorPlan & footprint decomposition · Eval report

Base commit: `f08853f`. Environment: Linux, Python 3.13, venv outside the worktree.

## Results

| ID | Test(s) | Result |
|---|---|---|
| K01 | `test_K01_version` | PASS |
| K02 | `test_K02_existing_unchanged` (SHA-256 of every 1.0.0 contract file except `version.py` / `export_schemas.py` unchanged; `SCHEMA_MODELS` = 1.0.0 list + 2 appended; only the 4 new files added) + whole pre-existing suite | PASS |
| K03 | `test_K03_roundtrip` | PASS |
| K04 | `test_K04_validators[duplicate, three_pieces, zero_pieces, empty_finger, junction_1_piece, junction_piece1, two_junctions]`, `test_K04_validators_raw_data` | PASS |
| K05 | `test_K05_room_ids_locate`, `test_K05_room_ids_two_pieces` | PASS |
| K06 | `test_K06_zone_violations`, `test_K06_zone_violations_details` | PASS |
| K07 | `test_K07_check_against`, `test_K07_check_against_counts_and_junction_kinds` | PASS |
| F01 | `test_F01_rect` | PASS |
| F02 | `test_F02_site_L_J2` | PASS |
| F03 | `test_F03_J1`, `test_F03_J1_variants`, `test_F03_tie_breaks` | PASS |
| F04 | `test_F04_rotations[identity, mirror_x, mirror_y, rot180]`, `test_F04_quarter_turns[1, 3]` | PASS |
| F05 | `test_F05_unsupported`, `test_F05_models_strict` | PASS |
| S01 | `test_S01_schemas` | PASS |
| S02 | `test_S02_lock` | PASS |
| S03 | `test_S03_gates` (ruff check, ruff format --check, mypy on the new modules) + coverage below | PASS |

Ticket tests: 33 passed. Whole suite: 441 passed, 5 skipped (platform-specific skips that were
already there).

## Gates

- `ruff check .`: clean. `ruff format --check .`: clean. `mypy` (strict, `src/ale`): clean.
- `python -m ale.contracts.export_schemas --check`: exit 0 (9 schemas, including
  `CorridorPlan.schema.json` and `FootprintPieces.schema.json`).
- `python -m ale.contracts.lock --check`: exit 0 (27 files).
- Coverage (ticket tests only): `corridor_plan.py` 100 % line / 100 % branch,
  `footprint.py` 100 % line / 100 % branch.

## Spec issues / interpretations

1. **`tests/contracts/test_serialization.py` edited (outside RD §2).** The existing
   `test_version_and_layout_schema_version` asserted `CONTRACTS_VERSION == "1.0.0"`, so the
   version bump RD §2 requires breaks it. I changed only that one literal to `"1.1.0"`. The
   alternative was to leave the whole suite failing.
2. **F04 "4 orientations".** I read these as identity, mirror in x, mirror in y and 180°
   rotation. All four keep the cut vertical, and the result is J2 as expected. Under the RD §5
   rules a **90° / 270° rotation gives J1**, not J2: the square 300×300 primary takes the tie
   axis "X", and the cut becomes horizontal, so it is parallel to the primary's spine. The
   tests `test_F04_quarter_turns` record this behaviour. If J2 is wanted there, the rule
   for the primary's tie axis would need to change, for example to "perpendicular to the cut".
3. **`decompose_footprint` signature.** It takes a `ModulePolygon`, as RD §5 says. eval.md
   shows a bare list of points as shorthand, so the tests wrap the points in `ModulePolygon(exterior=...)`.
4. **`cut` "on the secondary's side".** I implemented `cut` as the segment the two pieces share
   on the cut line: from the reflex vertex to the opposite boundary, lower/left endpoint first.
   This gives the expected values in F02 and F03. It is a full side of the secondary in those
   cases, but not in every L. When the arm is the larger piece, it is a full side of the primary.
5. **Junction finger in `zone_violations`.** "Junction finger ignored" is applied to the
   contiguity runs: the rooms of a junction finger are skipped and do not break a run. The
   "mixes zones" check still applies to every finger bay, the junction finger included.
6. **Message wording not fixed by the RD.** I chose these messages:
   `"plan has N piece(s), footprint has M"`, `"J1 footprint needs a junction finger"`,
   `"junction finger in block A, expected facing block B"` and
   `"junction finger on a J2 footprint (J1 only)"`.
7. **Strictness.** `FingerBay.junction` uses `StrictBool` and `RoomPosition` ints use
   `StrictInt`, following the global strict-field rule. `FootprintPieces.cut` uses
   `ModulePoint` (StrictInt pairs). `FootprintPieces` has no model validators because the
   RD lists none.
8. **Project rule `# int-mod`.** `test_U06_no_float_modulo` requires every `%` to carry the
   marker. The single integer modulo in `footprint.py` has it.
9. **K02 digests.** The test pins the 1.0.0 SHA-256 values. A later amendment that is allowed
   to edit one of those files must update `FROZEN_1_0_0`.
