# Reference corpus — inventory (2026-11-07)

Source: user's Google Drive zip "Kimi_Agent_High-End Floor Plan Hunt.zip" (554 MB, 446 files, 918 MB
uncompressed). The plans themselves are **not** in this repository (directive §7: copyrighted; keep only derived data).
They are downloaded on demand into the session scratch area.

## Contents

| Set | Files | Notes |
|---|---|---|
| `floor_plan_images/` | 366 (352 PNG, 14 JPG) | 292 drawings, 72 photos/renders, 2 magazine covers (collection metadata) |
| `habs_drawings/` | 43 TIFF | HABS measured drawings: Fallingwater, Farnsworth, Robie (houses) |
| `cad_files/` | 17 DWG + 2 ZIP + 1 RAR | landmark buildings; 5 are explicitly 3D models |
| `floor_plan_pdfs/` | 13 PDF | competition books, research reports, HABS sheets, a thesis |
| `dataset/` | `metadata.jsonl` (366 rows), `sample_annotations.jsonl` (14) | firm/project attribution; no scale, no room geometry |

## Usability for ALE (rule mining needs room polygons + room types + scale)

| Criterion | Count |
|---|---|
| Drawings typed as floor plans by the collection | 68 of 292 (141 untyped) |
| …of which office / tertiary programmes | ≈ 12 (education 3, health 1, culture 5, housing 8) |
| Drawings < 1000 px wide (web resolution) | 174 of 292 (median 900 px; 62 ≥ 2000 px) |
| Entries with a known scale | 0 |
| Plans with room labels / room polygons annotated | 0 |
| DWG files | 17 (versions R14 → 2018); 5 named 3D (Bilbao, Farnsworth, Tokyo Stadium, Villa dall'Ava 3D, Villa Savoye perspective) |
| DWG likely usable as 2D plans | ≈ 8–12 (Villa dall'Ava 2D, Fallingwater, Masieri, Villa Stein, Unité, Niemeyer collections, Ibirapuera, Ando, Ronchamp, Dom-Ino), all residential / cultural / religious |

## Assessment

- Valuable as a **development and qualitative corpus** for the Phase 1 readers (formats, DWG versions, real-world noise).
- Weak as a **statistical source for tertiary layout rules**: few office plans, mostly web-resolution rasters,
  no scales, no room labels, and the CAD set covers houses and cultural landmarks, not office/tertiary programmes.
- Does not yet meet the directive §7 **annotated test set** (≥ 12 plans with ground truth: 4 DWG/DXF, 4 vector PDF, 4 raster).
- Format mix → Phase 1 priority: raster reader (1.4) has the most material; CAD reader (1.2) has ~8–12 2D DWGs
  (needs ODA File Converter for R14–2018); vector-PDF reader (1.3) has few true vector plans.
