# Ticket 1.2 — CAD Reader · Evaluation report

Environment: Linux, Python 3.13.18, ezdxf 1.4.5, shapely 2.2.0. No ODA / AutoCAD installed.

## Results

| ID | Test(s) (`tests/cad/`) | Result |
|---|---|---|
| D01 | `test_D01_layer_proposal`, `test_D01_layer_proposal_details` | pass (20-name table + the 8 amended whole-word cases (`test_D01_layer_proposal_whole_words`); `{"0": "WALL"}` preserved; YAML save/load round trip, 0.1 template loads) |
| D02 | `test_D02_units[4/5/6/1]`, `test_D02_units_inferred_from_doors`, `test_D02_units_override`, `test_D02_units_rules` | pass |
| D03 | `test_D03_walls_pairs` | pass (5 walls = ground truth; thickness and centreline offset within 5 mm) |
| D04 | `test_D04_walls_width_polyline`, `test_D04_width_polyline_variants` | pass (same 5 walls; LWPOLYLINE const width, POLYLINE default width, equal per-vertex widths) |
| D05 | `test_D05_rooms_polygonize`, `test_D05_rooms_polygonize_single_line_walls` | pass (2 rooms, 18.72 / 18.24 m² within 1 %; no cavity face) |
| D06 | `test_D06_rooms_zones`, `test_D06_rooms_zone_hatch_and_zone_label` | pass (areas exact, rings identical; hatch with hole; zone text → `CAD_ZONE`) |
| D07 | `test_D07_labels`, `test_D07_labels_prefix_longest_and_area_formats` | pass (office / meeting_room, `CAD_TEXT`, `area_text_m2 == 12.4`, unlabelled room `type None`) |
| D08 | `test_D08_openings`, `test_D08_openings_arc_door` | pass (2 openings, 0.900 m ± 1 mm, door host = partition; arc r=900 → door 0.9 m) |
| D09 | `test_D09_multi_plan`, `test_D09_multi_plan_top_left_first` | pass (2 plans, index 0 top; 3-line fragment → `ignored fragment`) |
| D10 | `test_D10_blocks_and_xrefs`, `test_D10_xref_bound_and_layer0_inherits`, `test_D10_xref_not_dxf_and_circular` | pass (rotation 90° + scale 2 transformed; `missing xref MISSING_REF`; xref bound from the drawing's folder) |
| D11 | `test_D11_dwg_convert*` (6 tests) | pass (fake ODA → cached DXF; 2nd call cached, tool not rerun; `NEEDS_TOOL`; timeout → `FAILED` without exception; DWG hash unchanged; accoreconsole fallback) |
| D12 | `test_D12_robustness_*`, `test_D12_internal_limits` | pass (empty, text-only, bow-tie zone, garbage file, 10 000 random lines ≈ 5 s incl. writing the DXF) |
| D13 | `test_D13_contract_valid` + `_assert_contract` in D03–D10 | pass (canonical_json round trip, `Y_UP`, `DXF`) |
| D14 | `test_D14_real_corpus_smoke` (skips without `ALE_CORPUS_DIR`) | run manually on the reference corpus: **0 DXF, 17 DWG; no ODA converter detected → DWGs not read** |
| D15 | `test_D15_gates` (lock --check) + commands below | pass |

Gates: `pytest` whole suite 647 passed, 12 skipped after the rework merge (platform/extra skips + D14); `ruff check src tests` clean;
`ruff format --check src tests` clean; `mypy` (strict) clean; `python -m ale.contracts.lock --check` OK.
Coverage of `ale.cad`: 1110 statements, 58 missed → **94.8 % line** (92 % line+branch).

## Ambiguities and the literal reading chosen

1. **Layer proposal** (reworked after review, RD §3 amended): whole-word matching on canonical tokens,
   consecutive keyword tokens, plural `S`/`X`; role order IGNORE, FURNITURE, AREA_LABEL, ROOM_LABEL, ZONE,
   DOOR, WINDOW, WALL. Two literal-reading notes: (a) the amended D01 requires `Locaux techniques` → zone,
   but `LOCAUX` is neither `LOCAL`+`S` nor `LOCAL`+`X`; the French plural `-AL` → `-AUX` is therefore also
   accepted as a plural. (b) `AREA` (AREA_LABEL) is tried before `A AREA` (ZONE), so `A-AREA-IDEN` →
   area_label and the zone keyword `A AREA` can never win. Texts on ZONE layers still label zones
   (`CAD_ZONE`, RD "zones carrying a label attribute/text"), which is principled and kept.
2. **LayerRole values** are the lower-case names of the 0.1 `layer_map.yaml` format (`wall`, `door`, …);
   loading accepts any case, so `{"0": "WALL"}` validates.
3. **Units precedence** taken literally: `$INSUNITS` → door inference → `units_override` → unknown (the
   override only applies when neither of the first two gives units). Inferred units use method
   `DRAWING_UNITS`, confidence 0.6 (RD §3; `DOOR_MEDIAN` not used). Override: `DRAWING_UNITS`, 1.0.
   Door width = longest side of the INSERT's block box. Unknown units: metric thresholds assume mm
   (warning `metric thresholds assume millimetres`).
4. **ODA through `ezdxf.addons.odafc`:** odafc runs the converter with no timeout and no tree kill, which
   D11 (timeout → FAILED) and the RD's `tools.timeout_s` rule exclude. The converter is started with
   `ale.proc.run_tool`, with odafc's command line (`<in> <out> ACAD2018 DXF 0 1 <file>`), on a copy of the
   DWG in a temp folder. A `.py` converter path runs under the current interpreter (fake converters,
   Windows-safe). The accoreconsole `-DXFOUT` script is untested against real AutoCAD.
5. **API additions (keyword-only, defaulted):** `read_cad(..., source_kind=SourceKind.DXF)` (the RD's "DWG
   when converted" needs the caller to say so); `convert_dwg(..., workspace_root=None, environ=None)`
   (relative tool paths resolve against `workspace_root`, default `cache_dir`; `environ` for detection).
   `ConvertResult.status` is `"OK" | "NEEDS_TOOL" | "FAILED"`. `config` is unused by `read_cad`.
6. **Wall pairing details** not fixed by the RD: a segment may pair with several partners on disjoint
   parts; collinear paired walls of equal thickness ≤ 0.60 m apart are merged (so D03 and D04 give the
   same 5 walls); unpaired leftovers of a partly paired segment shorter than 0.60 m are dropped
   (corner/junction artefacts). A door gap in a wall yields two wall pieces.
7. **Rooms:** "outer face" = a face whose holes enclose other room-sized faces; "thinner than 0.5 m" =
   empty after a −0.25 m buffer. Opening closures: two segments at ± thickness/2 of the host wall.
8. **Labels:** "longest canonical match" = longest canonical matched synonym (ties → exact match).
   Without a match, `raw_label` keeps the first text and `type` stays None. Every TEXT/MTEXT/ATTRIB
   becomes a `TextItem`, assigned to the nearest plan within half the gap tolerance.
9. Plan ordering "(min y desc, min x)" applied literally to the wall bounding boxes.
