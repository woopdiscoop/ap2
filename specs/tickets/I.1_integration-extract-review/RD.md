# Ticket I.1 — Integration: PDF/raster extraction, labelling, scale, `ale review` · Requirements

> **Worker brief.** Context = this file, `eval.md`, and the public APIs of `ale.corpus` (DB, ingest, extract),
> `ale.cad`, `ale.pdfread` (`read_pdf_page`), `ale.raster` (`read_raster`, `rasterize_pdf_page`), `ale.labels`
> (`label_plan`, `VlmCache`), `ale.join` (`resolve_scale`, `review_flags`), `ale.workspace`, `ale.config`, the CLI
> commands `extract.py` and `review.py`. Do not modify contracts or the reader packages themselves.

## 1. Files (ownership)
```
src/ale/corpus/extract.py        # extend: PDF_VECTOR, PDF_SCANNED, RASTER kinds + label/scale/flags for every plan
src/ale/corpus/meta.py           # add columns north_angle_deg, dpi to the accepted plans_meta.csv columns
src/ale/corpus/db.py             # migration user_version 1 → 2: table review_flags
src/ale/corpus/review.py         # NEW: build the review page
src/ale/cli/commands/extract.py, src/ale/cli/commands/review.py
tests/corpus_extract/**, tests/review/**
tests/cli/test_cli_surface.py    # ONLY: remove `review` from the stub list
tests/cli/test_portability.py    # ONLY: retarget the cp1252 stub test (no stubs remain) to `ale status --workspace "<tmp>/Łódź ws"`, same intent (no crash)
specs/tickets/I.1_integration-extract-review/eval_report.md
```

## 2. `ale extract` for every kind
For each selected unit (same selection rules as 1.2c):
- `DXF`/`DWG`: as now (1.2c).
- `PDF_VECTOR`: `read_pdf_page`. If `is_plan_likely` is false → unit status `EXCLUDED`, reason `not a plan (score x.xx)`.
- `PDF_SCANNED`: `rasterize_pdf_page(path, page, dpi = meta dpi or extract.raster_dpi)` → `read_raster(..., source_kind=PDF_SCANNED)`.
- `RASTER`: `read_raster`. Plan score < 0.3 → `EXCLUDED`, reason `not a plan (score x.xx)`.
Then for **every** plan produced (all kinds): `resolve_scale(plan, meta=…)` (meta from `files.meta_json`, page-specific
entry when present) → `label_plan(plan, image=None, provider=None, cache=…)` (text-only; a VLM provider will be wired
later) → `review_flags` → write `plan.json` and store flags in `review_flags(sha256, page, plan_index, flag)`.
Unit → `EXTRACTED`; per-kind counts in the French summary.

## 3. `ale review --workspace W [--json] [--all]`
Writes `review/index.html` (one static, self-contained HTML file, UTF-8, no external assets): a table of flagged plans
(all plans with `--all`) — source file (rel_path), page, plan index, kind, scale method + confidence, room count,
typed/untyped, flags — and for each, an inline SVG preview (rooms filled by type, untyped grey, walls black, doors
red; y-up). `--json` prints the same data. Exit 0. Open the file path in the summary line.

## 4. Meta
`plans_meta.csv` accepts `north_angle_deg` (float) and `dpi` (int) and stores them in `files.meta_json` (per page when
`page` is given). (Gap reported by Ticket 2.2.)
