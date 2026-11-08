# Ticket 1.2 — CAD Reader · Evaluation

All DXFs are **generated in tests** with ezdxf from a declared ground truth (mm units unless stated). The user's
corpus is never committed; DWG conversion is tested with a fake converter.

| ID | Test | Pass condition |
|---|---|---|
| D01 | layer_proposal | (amended) Must include: `MUR PORTEUR` → wall, `TEXTE LOCAUX` → room_label, `Portes` → door, `PORTEUR` → wall, `Locaux techniques` → zone, `COTATIONS` → ignore, `A-WALL-FULL` → wall, `Baies vitrées` → window. Plus 20 layer names (`MUR`, `A-WALL`, `Cloisons`, `PORTES`, `A-DOOR`, `Menuiseries ext`, `TEXTE LOCAUX`, `Surfaces`, `ZONES`, `COTATIONS`, `Mobilier`, `0`, `Defpoints`, …) → expected roles (table in the test); an existing mapping `{"0": "WALL"}` is preserved. |
| D02 | units | `$INSUNITS` 4/5/6/1 → 0.001 / 0.01 / 1.0 / 0.0254 m per unit. No INSUNITS + door blocks 900 wide → mm inferred (confidence 0.6, warning). No INSUNITS, no doors, override `"cm"` → 0.01. |
| D03 | walls_pairs | Two-room plan (8 × 5 m outer, 0.20 m exterior walls drawn as parallel lines, 0.10 m partition) → recovered wall count equals ground truth; thickness within ±5 mm; centrelines within 5 mm. |
| D04 | walls_width_polyline | Same plan drawn as LWPOLYLINEs with constant width → same result. |
| D05 | rooms_polygonize | D03 plan without zone layer → 2 rooms; areas within 1 % of ground truth (3.9 × 4.8 m etc.); no wall-cavity faces. |
| D06 | rooms_zones | Closed polylines on `ZONES` → rooms exactly equal to them (area exact). |
| D07 | labels | Texts `BUREAU 12` and `S. RÉUNION` inside the rooms + `12,40 m²` → types office / meeting_room, `label_source CAD_TEXT`, `area_text_m2 == 12.4`; a room without text → `type None`. |
| D08 | openings | One door INSERT (block 900 × 50) on `PORTES` in the partition, one window INSERT on `FENETRES` → 2 openings, widths 0.900 m ± 1 mm, door `host_wall` = the partition. An ARC r=900 on the door layer without block → door 0.9 m. |
| D09 | multi_plan | Two copies of the plan 30 m apart in one model space → 2 PlanGeometry, `plan_index` 0 = top-left; a 3-line fragment far away → ignored with warning. |
| D10 | blocks_and_xrefs | Plan geometry placed inside a block inserted with rotation 90° and scale 2 → coordinates transformed correctly; a missing XREF → warning, no crash. |
| D11 | dwg_convert | Fake ODA (a Python script that copies a prepared DXF to the output folder) configured via `tools.oda_file_converter` → `convert_dwg` returns the cached DXF; second call reuses the cache without running the tool; no converter → `NEEDS_TOOL`; tool timeout → FAILED report, no exception. Source DWG unchanged (hash). |
| D12 | robustness | Empty DXF, DXF with only text, self-intersecting zone polyline, 10 000 random lines → never raises; bounded runtime (< 20 s). |
| D13 | contract_valid | Every produced `PlanGeometry` validates (round-trip `canonical_json`), `frame Y_UP`, `source_kind DXF`. |
| D14 | real_corpus_smoke (optional) | If env `ALE_CORPUS_DIR` is set, read every `*.dxf` found (none expected — the corpus has DWG only; report that) and, if an ODA converter is detected, the DWGs; print per-file plan/wall/room counts. Never in CI. |
| D15 | gates | ruff, ruff format, mypy strict clean; coverage of `ale.cad` ≥ 85 % line; `lock --check`; whole suite passes. |
