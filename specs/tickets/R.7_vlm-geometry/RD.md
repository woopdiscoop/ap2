# Ticket R.7 — Claude geometry reader for raster / scanned plans · Requirements Document

> Context = this file, `eval.md`, `specs/design/literature_review_2026-11.md` (FloorplanVLM: pixels → JSON),
> `ale.raster` (`read_raster`, `RasterReadResult`), `ale.labels.render` (`plan_image`, pixel-edge extent from X.1),
> `ale.labels.bbox`, `ale.labels.providers` (Anthropic client pattern of P.1), `ale.corpus.extract` (I.2 wiring),
> `ale.join.review_flags`. No contract changes. Tests mock the client; no network; never require a real key.

## 1. Purpose
The classical CV reader under-segments rendered plans. When the VLM is configured, Claude also reads the room
**geometry** of `RASTER` / `PDF_SCANNED` plans; the result is cross-checked with the classical reader and
disagreements become review flags. Default (no provider) is unchanged.

## 2. Files (ownership)
```
src/ale/raster/vlm_reader.py       # NEW: read_rooms_vlm(png, extent, frame, provider, cache, config) → VlmRooms
src/ale/raster/compare.py          # NEW: compare(classical_rooms, vlm_rooms) → Agreement
src/ale/corpus/extract.py          # ONLY: call it for raster kinds when the VLM is on; choose / flag
tests/raster_vlm/**
specs/tickets/R.7_vlm-geometry/eval_report.md
```

## 3. Reader
One call per plan image (the same prepared PNG as I.2: `plan_image` + `prepare_image`). Structured output: list of
rooms `{label: str, polygon: [[x, y], ...] in 0..1000 normalised image coordinates (top-left origin), confidence}`,
axis-aligned or orthogonal polygons, ≤ 60 rooms. Polygons are mapped to native coordinates with the `bbox` rendering
model (pixel-edge extent), made valid (`shapely.make_valid`, keep polygons ≥ 4 px²), and clipped to the image.
Cache key = (image hash, prompt version, model id). Prompt version `geom-v1`, French/English room names accepted.

## 4. Cross-check and choice (`compare.py`)
Match rooms one-to-one by IoU (Hungarian on 1 − IoU, threshold 0.5). Agreement metrics: matched count, mean IoU,
unmatched on each side. Choice per plan:
- **classical** kept when its room count ≥ 2 and mean IoU ≥ 0.8 with the VLM rooms (VLM only confirms);
- **VLM** rooms used when the classical reader found < 2 rooms, or when the VLM finds ≥ 1.5× more rooms with mean IoU
  of the matched ones ≥ 0.6 (the under-segmentation case);
- otherwise classical kept and flag `GEOMETRY_DISAGREEMENT` added (shown in `ale review`).
The chosen source is recorded in the plan warnings (`géométrie : VLM` / `géométrie : lecteur classique`) and counted
in the extract summary. Walls and openings always come from the classical reader.
