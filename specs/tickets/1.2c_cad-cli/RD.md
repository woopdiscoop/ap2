# Ticket 1.2c — Wire the CAD reader to the corpus (`ale layers`, `ale extract` for DXF/DWG) · Requirements

> **Worker brief.** Context = this file, `eval.md`, contracts, and the public interfaces of `ale.corpus`
> (DB schema, ingest), `ale.cad` (`propose_layer_map`, `LayerMap` load/save, `convert_dwg`, `read_cad`),
> `ale.workspace`, `ale.config`, and the CLI stubs `src/ale/cli/commands/layers.py`, `extract.py`.

## 1. Files
```
src/ale/corpus/extract.py                 # run_extract(...) → ExtractReport (CAD kinds only in this ticket)
src/ale/cli/commands/layers.py, extract.py   # replace stub bodies (keep options)
tests/cli/test_cli_surface.py             # ONLY: remove `layers` and `extract` from the stub list
tests/corpus_extract/**
specs/tickets/1.2c_cad-cli/eval_report.md
```

## 2. `ale layers --workspace W`
- For every unit with kind DXF (status ≠ EXCLUDED) and every DWG unit whose conversion succeeds or is cached,
  collect layer names (model space) — use the corpus path from `inputs` + `file_paths` (first path still present;
  if none exists any more → skip with a warning).
- Merge with the existing `layer_map.yaml` (user entries win) via `propose_layer_map`, save it back (YAML, sorted
  keys), print a French table: layer, role, number of files using it, "nouveau" for new entries.
- Exit 0; nothing to do → prints so and exits 0.

## 3. `ale extract --workspace W [--only-new] [--kind dwg|dxf|pdf|raster]`
- Selects units: kind filter if given; `--only-new` → status NEW only; default → NEW and FAILED (retry).
- DXF: `read_cad` with the workspace `layer_map.yaml`, `units_override` from `files.meta_json` (`units`) if any.
- DWG: `convert_dwg` into `cache/dxf/` then as DXF (source_kind DWG); NEEDS_TOOL stays NEEDS_TOOL with reason.
- Output per plan: `extracted/<sha256>/<page>/<plan_index>/plan.json` = `canonical_json(PlanGeometry)`;
  rewriting is atomic (temp file + replace). Unit → EXTRACTED (0 plans → FAILED reason `no plan found`);
  exceptions → FAILED with the exception type + message; never aborts the run.
- PDF / RASTER units in the selection → skipped, counted as `not_implemented` (Tickets 1.3/1.4).
- Events written to `events` (`extracted`, `extract_failed`). Summary printed in French; exit 0.
- Same inputs twice → identical `plan.json` bytes; a second `--only-new` run touches nothing.

## 4. Out of scope
PDF/raster extraction, labelling (1.5), scale reconciliation (1.6).
