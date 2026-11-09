# Ticket A.3 — Evaluation report

Environment: Linux, Python 3.13, venv outside the worktree (`pip install -e ".[dev,excel,cad,pdf]"`).

## Results per eval ID (`tests/contracts/test_corridor_plan.py`)

| ID | Test(s) | Result |
|---|---|---|
| I01 | `test_I01_version_schema` | PASS: `CONTRACTS_VERSION == "1.3.0"`, an `inner` plan validates against the regenerated schema, `export_schemas --check` 0, `lock --check` OK |
| I02 | `test_I02_backward[*]` (7 plans) | PASS: plans from the existing tests validate and round-trip (JSON, YAML, dict). For `sample_plan` and `b03_plan`, the canonical JSON SHA-256 equals the value the 1.2.0 contract produced (golden values computed with `git show HEAD:corridor_plan.py`) |
| I03 | `test_I03_validators[*]`, `test_I03_validators_ok` | PASS: inner + 1 band, marker in `start`/`none` piece, block with 0 markers, block with 2 markers → error; valid 2-band inner plan → ok |
| I04 | `test_I04_locate_and_ids` | PASS |
| I05 | `test_I05_zones` | PASS |
| I06 | `test_I06_J2` | PASS: `("primary connector must be on the cut side (end)",)`; also tests the secondary rule and where `inner` is allowed |
| I07 | `test_I07_gates` + runs outside the test file | See below |

## Gates
- ruff check / ruff format --check (src, tests): clean.
- mypy strict `src/ale/contracts`: clean.
- Coverage of `src/ale/contracts/corridor_plan.py`: 100 % (statements and branches).
- Whole suite: 793 passed, 7 skipped, 2 xfailed, **2 failed**. Both failures are in files outside this ticket's ownership, so they were not edited:
  - `tests/contracts/test_serialization.py::test_version_and_layout_schema_version` asserts `CONTRACTS_VERSION == "1.2.0"`. It needs the RD-mandated `"1.3.0"`.
  - `tests/contracts/test_models.py::test_M04_frozen_extra` requires a sample instance of every contract model in `_instances`. It needs `ConnectorBay()` added.
- mypy on all of `src`: 9 errors, all from the wider `Bay` union and the wider `connector` Literal, in packages this ticket may not edit:
  - `geometry/realize.py:177,200,201,212`: `tuple[RoomBay | FingerBay | ConnectorBay, ...]` passed where `tuple[RoomBay | FingerBay, ...]` is expected
  - `geometry/realize.py:282,298`: `connector` Literal now includes `'inner'`; `_PieceOut` expects `Literal['none','start','end']`
  - `optimize/moves.py:109`: `list[RoomBay | FingerBay]` built from the new tuple
  - `optimize/moves.py:110`: `_Piece` connector Literal
  - `optimize/fastreal.py:115`: `Solver.block` argument

## Ambiguities / readings chosen
- K01 and B01 (existing tests in the owned file) asserted `"1.2.0"`. They now assert `"1.3.0"`, because I01 supersedes them.
- A marker in a piece whose connector is `"none"` is also rejected ("a ConnectorBay may only appear in a piece whose connector is inner").
- "inner requires ≥ 2 bands" uses the existing 1-band check (`a 1-band piece has no connector`), which already covers `"inner"`.
- J2: no code change was needed. The existing `connector != cut_side` comparison already rejects `"inner"` where a cut-side connector is required. `"inner"` satisfies "a piece with 2+ bands needs a connector".
- Zones: each side of the marker is checked on its own. A zone split on both sides is reported once per block (the message format has no side).
- `ConnectorBay` sits in the same block lists as other bays, so `zone_violations` finger indices also count markers, consistent with `locate`.
