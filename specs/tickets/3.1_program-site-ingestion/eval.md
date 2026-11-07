# Ticket 3.1 — Program & Site Ingestion · Evaluation

Every ID is a named pytest test under `tests/program/`. Numbers were computed by the Router with the
frozen contract functions (0.10 m grid, default `AleConfig`).

## 0. Harness rules

pytest-timeout 60 s/test; suite of this ticket ≤ 60 s. No network. Workbooks and DXFs are **generated in
the tests** (openpyxl / ezdxf), never committed (except the template). `lock --check` passes; whole repo suite passes.

**Test rulebook** `tests/program/data/rulebook_test.yaml` (owned by this ticket): `kind: seed`, author `test`,
date `2026-11-07`; the 13 fixture types with aspect `{p10: 1.0, p50: 1.4, p90: 2.0}`, area `{p10: 2, p50: 12, p90: 80}`,
orientation all 0.0; adjacency `default_p: 0.5`, no pairs; core offset 0/0.

**Workbook helper** `program_to_xlsx(program, path)` (test utility): writes a `Program` into the §4 columns
(types as `label_fr`, zones in French, `Oui/Non`).

## 1. Program reading

| ID | Test | Pass condition |
|---|---|---|
| X01 | roundtrip_fixtures | For P8, P25, P60: `read_program(program_to_xlsx(p))` returns a `Program` equal to the fixture and a report with 0 errors. |
| X02 | type_resolution | `Type` given as key `meeting_room`, as label `Salle de réunion`, as synonym `S. REUNION` → all `meeting_room`. `Bureau paysager nord` (prefix match) → `E_UNKNOWN_TYPE` whose message names `open_office`/`Plateau de bureaux`. `Circulation` → `E_FORBIDDEN_TYPE`; `Terrasse` → `E_FORBIDDEN_TYPE`. |
| X03 | numbers_fr | `Surface` `"12,5"` → 12.5; `12` (int cell) → 12.0; `"abc"`, `0`, `-3`, `10001` → `E_AREA`. `Quantité` `3.0` → 3; `3.5`, `0`, `501` → `E_QUANTITY`. |
| X04 | zone_and_facade | `Zone` `administratif`, `ADMINISTRATIVE` → ADMINISTRATIVE; blank with type `office` → ADMINISTRATIVE + `W_ZONE_DEFAULTED`; `Bureaux` → `E_ZONE`. `Façade` `Oui`, `o`, `X`, `1`, `Vrai` → True; blank, `Non`, `0` → False; `peut-être` → `E_FACADE`. |
| X05 | orientation | `Orientation S = 1`, others blank → `{N:0, E:0, S:1, W:0}`; all blank → `None`; `1.5` → `E_ORIENTATION`; the `O` column maps to `Bearing.W`. |
| X06 | refs | `Adjacent à` `"R02; R03 ,R04"` → `("R02","R03","R04")`; unknown `R99` → `E_REF_UNKNOWN`; own id → `E_SELF_REF`; R01 requires R02 while R02 avoids R01 → `E_REQ_AVOID_CONFLICT`. |
| X07 | error_catalogue | One workbook with 12 bad rows (rows 2–13), one per code: `E_EMPTY_ID, E_BAD_ID ("R 1"), E_DUP_ID, E_EMPTY_NAME, E_UNKNOWN_TYPE, E_FORBIDDEN_TYPE, E_AREA, E_QUANTITY, E_ZONE, E_FACADE, E_MIN_WIDTH (-1), E_FLOOR (1)`. The report lists **exactly** these 12 `(code, row)` pairs (all collected in one call), `Program is None`. |
| X08 | headers | Headers `id`, `NOM`, ` type `, `Surface (m2)`, `quantite` match. Missing `Surface` column → single `E_MISSING_COLUMN`, no row issues. Extra column `Budget` → `W_UNKNOWN_COLUMN`. Sheet named `Feuil1` → `W_SHEET_NAME`, still read. |
| X09 | comments_blank | Blank rows and a row with ID `#note` are skipped; row numbers of later issues still refer to real Excel rows. |
| X10 | never_raises | Fuzz: 50 workbooks with random cell types/values (seeded) → `read_program` never raises; every issue has a code from the frozen list. |

## 2. Site

| ID | Test | Pass condition |
|---|---|---|
| Y01 | yaml_fixtures | The three fixture sites, written as `site.yaml` (inline `footprint`), load to `SiteSpec`s equal to `load_site(...)`. |
| Y02 | module_exact | `site_rect` → module polygon `[(0,0),(240,0),(240,180),(0,180)]`, `sliver_loss_m2 == 0.0`; `site_L` → `[(0,0),(480,0),(480,180),(300,180),(300,300),(0,300)]`, area 122 400 cells. |
| Y03 | inward_snap_rect | Footprint `(0.05,0) (10.03,0) (10.03,5.07) (0.05,5.07)` → origin `(0.05, 0.0)`, polygon `[(0,0),(99,0),(99,50),(0,50)]`, `sliver_loss_m2 == 1.0986`. |
| Y04 | inward_snap_L | Footprint `(0,0) (10.05,0) (10.05,4.02) (6.03,4.02) (6.03,8.07) (0,8.07)` → `[(0,0),(100,0),(100,40),(60,40),(60,80),(0,80)]`, 6 400 cells, `sliver_loss_m2 == 0.8225`. |
| Y05 | normalise_and_access | Clockwise input `(0,0) (0,18) (24,18) (24,0)` with `access_edge: 0` (the west edge) → normalised CCW `(0,0) (24,0) (24,18) (0,18)`, access edge **3**. Input `(0,0) (5,0) (10,0) (10,5) (0,5)` with `access_edge: 1` → 4 vertices, access edge **0**. |
| Y06 | site_errors | Both/none of `footprint` and `footprint_dxf` → error; a 30°-rotated rectangle → `E_SITE_NOT_ORTHOGONAL`; a bow-tie → `E_SITE_INVALID`; a 0.05 × 0.05 m square → `E_SITE_TOO_SMALL`; unknown key `nord` → error. |
| Y07 | dxf_mm | ezdxf-generated DXF, `$INSUNITS = 4`, closed LWPOLYLINE on layer `EMPRISE` with mm coordinates of `site_rect` → `SiteSpec` equal to `site_rect`. |
| Y08 | dxf_errors | Two closed polylines on the layer, or none → `E_SITE_DXF`; `$INSUNITS = 0` with `units: null` → `E_SITE_UNITS`; same file with `units: mm` → ok; path `emprise.dwg` → `E_SITE_DWG`. |

## 3. Feasibility (test rulebook, default config)

| ID | Test | Pass condition (m², exact to 0.001) |
|---|---|---|
| Z01 | fixtures_fit | P8 / `site_rect_small`: required 88.500, available 95.000, overshoot 0.000, fill_ratio 0.885. P25 / `site_rect`: 394.120 / 410.400 / 0.000 / 0.9123. P60 / `site_L`: 1135.160 / 1162.800 / 0.000 / 0.9274. No errors. |
| Z02 | not_feasible | P25 on `site_rect_small` → `E_NOT_FEASIBLE`, message contains `il manque 299.12 m²`. |
| Z03 | room_infeasible | A room `target 4 m²`, `Largeur min 3.0` → `E_ROOM_INFEASIBLE` on its Excel row (3.0 × 3.0 = 9 m² > 4 + 1.2). |
| Z04 | rulebook_coverage | P8 with `storage` removed from the test rulebook → exactly one `E_TYPE_NOT_IN_RULEBOOK` naming `storage`. |
| Z05 | facade | 20 offices of 4 m², all `Façade = Oui`, on `site_rect_small` → `E_FACADE_INSUFFICIENT` (48.0 m > 40.0 m) and **no** `E_NOT_FEASIBLE` (94.4 ≤ 95.0). |
| Z06 | band_fallback | Test rulebook with `office.aspect = {p10: 1.5, p50: 1.55, p90: 1.6}`. (a) A 12 m² office without min width → `per_room` rect `(28, 43)` (12.04 m², in band). (b) A 12 m² office with `Largeur min 3.0` → band infeasible (`(30, ≥45)` exceeds 13.2 m²), fallback band 1.0–2.0 → `(30, 40)`, overshoot 0.0, **no** error. |
| Z07 | exact_arithmetic | `required_m2` equals `Decimal` recomputation from instances (no float drift) for P60. |

## 4. prepare_input, template, CLI

| ID | Test | Pass condition |
|---|---|---|
| P01 | prepare_ok | `prepare_input` on P60 + `site_L` + test rulebook returns `PreparedInput` with 60 instances, module footprint of Y02, `grid.module_mm == 100`. |
| P02 | collects_all | Bad workbook (X07) + bad site (rotated) + rulebook missing a type → one `InputError` whose `issues` contain the program, site and rulebook errors together. |
| P03 | deterministic | Two `prepare_input` runs (fresh processes) → identical `canonical_json(prepared)` bytes. |
| P04 | template_content | Regenerating the template into tmp: sheets `Programme, Exemple, Aide, Listes` (`Listes` hidden); row 1 of `Programme` equals the 16 headers of RD §4 in order; the `Type` validation list resolves to exactly the 72 `label_fr` values; `Zone` and `Façade` lists as specified; committed template cell values and validations equal the regenerated ones. |
| P05 | template_example_reads | Reading the `Exemple` sheet (renamed `Programme` in a copy) gives a `Program` equal to P8. |
| P06 | cli_check | `ale program check` on P8 files → exit 0, prints `fill` ratio; on the X07 workbook → exit 1 and prints each `(row, code)`; `--json` output parses with keys `ok, issues, feasibility`. |
| P07 | cli_template | `ale program template --out t.xlsx` creates it; second call → non-zero exit unless `--force`. |
| P08 | cli_registration_only | `git diff` of `src/ale/cli/__init__.py` against the base adds exactly two lines: one import of `ale.cli.commands.program` and one `add_typer` registration (amended at review: no `__import__` tricks). |

## 5. Static gates

| Gate | Threshold |
|---|---|
| `ruff check`, `ruff format --check`, `mypy` (strict) | clean |
| Coverage of `ale.program` | ≥ 90 % line, ≥ 80 % branch |
| `python -m ale.contracts.lock --check` | exit 0 |
| Ownership | only RD §3 paths |
