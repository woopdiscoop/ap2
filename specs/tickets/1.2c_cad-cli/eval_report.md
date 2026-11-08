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
| W10 (Router) | `test_W10_empty_layer_map_proposes` | pass |
| W11 (Router) | `test_W11_dwg_needs_tool_retried` | pass |

Gates: `ruff check src tests` clean; `ruff format --check src tests` clean; `mypy` (strict,
`src/ale`) clean; `python -m ale.contracts.lock --check` → 0.
Coverage of `ale.corpus.extract`: **99 %** (line + branch, `tests/corpus_extract`).

Whole suite: 710 passed, 7 skipped, 2 xfailed (after merging `claude/new-session-2hmd3s`).

## Spec issues and readings chosen

1. **Out-of-scope test expected `extract` to be a stub** — resolved by the Router:
   `test_P01_cp1252_console_stub_message` now targets `ale review` (Ticket 1.6) with a
   workspace path containing `Łódź` (cp1252 console, no crash, exit 3).
2. **Empty `layer_map.yaml`** — Router decision: when the map has no layer entries,
   `ale extract` proposes roles in memory (`propose_layer_map` over the model-space layers
   of the selected CAD units), uses them for this run, prints a French warning advising
   `ale layers`, and never writes the file. A non-empty map is used as is.
3. **DWG units in NEEDS_TOOL** — Router decision: the default selection (no `--only-new`)
   also includes DWG units in NEEDS_TOOL; the converter is re-detected; if found the unit
   is converted and extracted, else it is left unchanged (no status/reason/updated_at
   change, no event). `--only-new` selects NEW only.
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
