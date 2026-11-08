# Ticket A.2 — Contract amendment: bands · Evaluation report

Python 3.13, venv outside the worktree. Contracts version `1.1.0` → `1.2.0`; CorridorPlan schema
version `ale.corridor_plan/1` → `ale.corridor_plan/2`.

| ID | Test(s) in `tests/contracts/test_corridor_plan.py` | Result |
|---|---|---|
| B01 | `test_B01_version_schema` | PASS |
| B02 | `test_B02_footprint_unchanged` (git diff vs `3dcd970`), F01–F05 in `test_footprint.py` | PASS |
| B03 | `test_B03_roundtrip` | PASS |
| B04 | `test_B04_validators[zero_bands, seven_bands, one_band_connector, dup_across_bands, junction_p1]`, `test_B04_validators_ok` | PASS |
| B05 | `test_B05_order_locate` | PASS |
| B06 | `test_B06_zones_per_band` | PASS |
| B07 | `test_B07_connector_rules` | PASS |
| B08 | `test_B08_J2_rules`, `test_B08_J2_cut_side_variants` | PASS |
| B09 | `test_B09_J1_rules`, `test_B09_J1_facing_A` | PASS |
| B10 | `test_B10_gates` (ruff/format/mypy on A.2 files) + gates below | PASS |

## Gates

- `pytest --ignore=tests/geometry`: 518 passed, 5 skipped (platform skips). `tests/geometry` was
  **not run** as instructed (Ticket 3.3 rework): it fails at collection against the new model.
- `ruff check .`, `ruff format --check .`: clean.
- `mypy` (strict, `files = src/ale`): 10 errors, all in `src/ale/geometry/` (8 in `realize.py`, 2 in
  `greedy.py`) caused by the new `PiecePlan` shape; zero in `src/ale/contracts/`. Not fixed (out of
  scope).
- Coverage of `src/ale/contracts/corridor_plan.py`: 100 % (statements and branches).
- `python -m ale.contracts.export_schemas --check` and `python -m ale.contracts.lock --check`: exit 0.

## Spec issues / readings chosen

1. **B01 `CorridorPlan().schema_version`**: `pieces` is required, so `CorridorPlan()` raises. The test
   reads the field default (`CorridorPlan.model_fields["schema_version"].default`) and checks a built
   instance.
2. **Old facing-block message replaced.** The A.1 message `"junction finger in block X, expected facing
   block Y"` is superseded by `"junction finger must be in band k block X"` (RD lists only missing/
   unknown rooms, piece count and junction presence as unchanged). K07 updated accordingly.
3. **Docstring "verbatim"**: re-wrapped to 100 columns, `block A | spine | block B` in RST double
   backticks, and `L − s` written with an ASCII hyphen (`L - s`) because ruff RUF002 rejects U+2212.
4. **J2, 1-band primary + multi-band secondary** (found in the first pass; RD §3 / B08 amended at
   review 2026-11-08): the secondary's connector must be on the secondary's cut side, else
   `secondary connector must be on the cut side (start|end)` (site_L: "start"). Implemented and tested
   in `test_B08_J2_rules`. The module docstring keeps the original verbatim U-7 text.
5. **J1 multi-band secondary without a connector** also yields `piece 1 has 2+ bands but no connector`
   (the connector rule exempts only a J2 secondary). B09 therefore gives that secondary a connector to
   get the single expected message.
6. Band count limits are `Field(min_length=1, max_length=6)` (so they appear in the JSON schema);
   pydantic messages "at least 1" / "at most 6".
7. `specs/tickets/A.2_contract-bands/notes.md` exists but was not read (context rule).
