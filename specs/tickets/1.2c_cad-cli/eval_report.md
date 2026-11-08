# Ticket 1.2c — Evaluation report

Environment: Linux, Python 3.13, `pip install -e ".[dev,excel,cad,pdf]"`.

## Results

| ID | Test(s) | Result |
|---|---|---|
| W01 | `test_W01_layers_cmd`, `test_W01_layers_nothing_to_do`, `test_W01_layers_skips` | pass |
| W02 | `test_W02_extract_dxf` | pass |
| W03 | `test_W03_multi_plan_paths` | pass |
| W04 | `test_W04_failures`, `test_W04_missing_source` | pass |
| W05 | `test_W05_dwg_paths`, `test_W05_dwg_no_converter_at_ingest`, `test_W05_dwg_conversion_fails` | pass |
| W06 | `test_W06_idempotent`, `test_W06_same_bytes_other_workspace`, `test_W06_stale_plans_removed` | pass |
| W07 | `test_W07_other_kinds` | pass |
| W08 | `test_W08_meta_units` | pass |
| W09 | `test_W09_gates` (+ unit tests in `test_extract_units.py`) | pass |

Gates: `ruff check src tests` clean; `ruff format --check src tests` clean; `mypy` (strict,
`src/ale`) clean; `python -m ale.contracts.lock --check` → 0.
Coverage of `ale.corpus.extract`: **100 %** (line + branch, `tests/corpus_extract`).

Whole suite: 673 passed, 7 skipped, **1 failed**: `tests/cli/test_portability.py::
test_P01_cp1252_console_stub_message` (see issue 1).

## Spec issues and readings chosen

1. **Out-of-scope test still expects `extract` to be a stub.**
   `tests/cli/test_portability.py::test_P01_cp1252_console_stub_message` runs
   `ale extract --workspace W` and expects exit 3 with the en-dash stub message. That file
   is not in RD §1, so it was not modified. It now fails (exit 0, the extract summary).
   Suggested fix (for the Router): point the test at another stub whose message contains
   the en dash, e.g. `generate` with its required options (`Ticket 3.1–3.5`).
2. **`ale extract` needs `ale layers` first.** RD §3 says `read_cad` uses the workspace
   `layer_map.yaml`; a layer missing from the map has role `ignore`, so extracting before
   `ale layers` (or a hand-written map) finds no walls → `FAILED no plan found`. Kept
   literal (no implicit proposal); the tests run `ale layers` before `ale extract`.
3. **DWG units in NEEDS_TOOL are not retried by `ale extract`.** The default selection is
   NEW and FAILED (RD §3, literal). A DWG ingested before a converter was installed is
   picked up again by a re-ingest (Ticket 1.1 re-classification), not by `extract`.
   `ale layers` attempts the conversion for every non-EXCLUDED DWG unit (RD §2: "whose
   conversion succeeds or is cached").
4. **Layer names "model space"**: the layers used by model-space entities, block contents
   included (entities on layer `0` inside a block take the INSERT's layer, attributes
   included), XREFs not opened; the layer table itself (e.g. an unused `0`) is not listed.
5. **Readings of unspecified details**:
   - Missing source file during extract → `FAILED` with
     `FileNotFoundError: source file not found: <rel_path>` (layers: skipped + warning).
   - DWG converter failure → `FAILED` `DWG conversion failed: <message>`; NEEDS_TOOL →
     status NEEDS_TOOL, reason = converter message, no event (RD lists only `extracted` /
     `extract_failed`).
   - Unreadable DXF → `FAILED no plan found` (reader warnings in the event detail).
   - `units_override`: `meta_json.pages["<page>"].units` wins over `meta_json.units`;
     lower-cased.
   - A `plan.json` already holding identical bytes is not rewritten (mtime kept); stale
     `<plan_index>` folders beyond the new plan count are removed.
   - Invalid `layer_map.yaml` → exit 4 with `layer_map.yaml: invalid (...)`; missing →
     empty map.
   - No run-level events are written (W06 "no new events" on a second `--only-new` run).
6. Test helpers: `tests/corpus_extract/conftest.py` puts `tests/cad` and `tests/corpus` on
   `sys.path` to reuse `cad_helpers` / `corpus_helpers` (read-only reuse).
