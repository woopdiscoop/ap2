# Ticket 1.2c — Evaluation
Fixtures generated in tests: DXF plans via ezdxf (as in tests/cad), ingested with `ingest` into a tmp workspace.

| ID | Test | Pass condition |
|---|---|---|
| W01 | layers_cmd | Two DXFs with layers `MUR`, `PORTES`, `TEXTE LOCAUX`, `Mobilier` → `layer_map.yaml` gets those 4 with roles wall/door/room_label/furniture; a pre-existing user entry `MUR: ignore` is kept; table printed; exit 0. |
| W02 | extract_dxf | `ale extract --kind dxf` → each unit EXTRACTED, `plan.json` files exist at the specified paths and reload as `PlanGeometry` (room count equals the generated ground truth). |
| W03 | multi_plan_paths | A DXF with 2 plans → `…/0/0/plan.json` and `…/0/1/plan.json`. |
| W04 | failures | An empty DXF → FAILED `no plan found`; a DXF that raises (monkeypatched `read_cad`) → FAILED with exception type; run continues and exits 0. |
| W05 | dwg_paths | DWG unit with fake ODA (as in tests/cad D11) → converted, extracted with `source_kind DWG`; no converter → stays NEEDS_TOOL. |
| W06 | idempotent | Second `--only-new` run: no file rewritten (mtimes unchanged), no new events. Re-run without flag retries FAILED only. |
| W07 | other_kinds | PDF and RASTER units → counted `not_implemented`, status unchanged. |
| W08 | meta_units | `plans_meta.csv` `units=cm` on a DXF without $INSUNITS → scale 0.01 used. |
| W09 | gates | ruff, ruff format, mypy strict; coverage of `ale.corpus.extract` ≥ 90 %; lock --check; whole suite (stub list updated). |
