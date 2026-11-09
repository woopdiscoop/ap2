# Ticket X.1 — `ale extract --force` and exact raster extent · Requirements Document

> Follow-ups of I.2 (see `specs/tickets/I.2_vlm-in-extract/eval_report.md`, spec issues 1–2). Context = this file,
> `eval.md`, `src/ale/corpus/extract.py`, `src/ale/cli/commands/extract.py`, `src/ale/labels/render.py`,
> `src/ale/labels/bbox.py`, `src/ale/raster/read.py`, and their tests. No contract changes.

## 1. Files (ownership)
```
src/ale/corpus/extract.py          # ONLY: selection for force
src/ale/cli/commands/extract.py    # ONLY: --force flag
src/ale/labels/render.py           # ONLY: raster / scanned-PDF extent
tests/corpus_extract/test_extract_force.py   # NEW
tests/labels_render/**             # adjust V202 expectations if needed (never weaken)
specs/tickets/X.1_extract-followups/eval_report.md
```

## 2. `--force`
`ale extract --force [--kind K]` re-extracts the selected units whatever their status (EXTRACTED and EXCLUDED
included, still filtered by `--kind`); `--force` and `--only-new` together → usage error (exit 2, French message).
A forced unit overwrites its `plan.json` atomically, replaces its `review_flags` rows, and records an event
`extract_forced`. The VLM cache is reused, so a forced re-run costs no provider call when nothing changed.

## 3. Raster extent
The raster reader puts pixel centres on integer coordinates, so a `W × H` bitmap spans native
`(-0.5, -0.5, W - 0.5, H - 0.5)`. `plan_image` must return that extent for `RASTER` and `PDF_SCANNED` (Y_DOWN), so
`bbox` conversions are exact to the pixel edge. Document the convention in the module docstring.
