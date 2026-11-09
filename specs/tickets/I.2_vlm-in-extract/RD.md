# Ticket I.2 — Claude labelling in `ale extract` · Requirements Document

> **Starts after I.1 merges** (it extends I.1's `extract.py`). Context = this file, `eval.md`, I.1's code,
> `ale.labels` (`label_plan`, `VlmCache`, `bbox` rendering model), `ale.labels.providers` (`make_provider`,
> `prepare_image`), `ale.pdfread`, `ale.raster`, `ale.config`. No contract changes.

## 1. Purpose
I.1 labels rooms from drawing text only. When the user configures `[vlm] provider = "anthropic"` (and sets the key),
rooms left untyped after the text stage go to Claude with an image of the plan (user decision U-8).
Default behaviour (no provider) is unchanged and makes no network call.

## 2. Files (ownership)
```
src/ale/labels/render.py         # NEW: plan_image(...) → (png, extent)
src/ale/corpus/extract.py        # wire provider + image into label_plan
src/ale/cli/commands/extract.py  # --no-vlm flag; summary counts
tests/labels_render/**, tests/corpus_extract/test_extract_vlm.py
specs/tickets/I.2_vlm-in-extract/eval_report.md
```

## 3. Image per source kind (`render.py`)
The image and `extent` must follow the `ale.labels.bbox` rendering model exactly: uniform scale, centred, top row =
`y1` for `Y_UP` and `y0` for `Y_DOWN`.
- `RASTER` / `PDF_SCANNED`: the source bitmap itself (the one the reader traced), `extent = (0, 0, W, H)`, `Y_DOWN`.
- `PDF_VECTOR`: the page rendered with PyMuPDF at `extract.raster_dpi`; `extent` = page box in the plan's native units.
- `DXF`/`DWG`: drawn with Pillow from `PlanGeometry`: walls black 2 px, doors red, room outlines grey, text items at
  their insertion points (default font), white background; long side 1568 px; `extent = plan_extent(plan)` plus a 2 %
  margin.
Then `prepare_image(png)` (downscale) and the prepared bytes are what `label_plan` receives.

## 4. Wiring (`extract.py`)
`provider = make_provider(config)` once per run, unless `--no-vlm`. If it raises `MissingApiKeyError`: warn once in
French (`clé API absente : la VLM est désactivée`) and continue text-only. Do not fail the run. For each plan:
`label_plan(plan, image=prepared, provider=provider, cache=VlmCache(workspace), config=config, extent=extent)`.
Provider errors (`VlmProviderError`) become plan warnings and that plan stays text-labelled. Summary line: number of
plans sent to the VLM, cache hits, errors.

## 5. Out of scope
Prompt tuning, batching, cost reporting beyond counts.
