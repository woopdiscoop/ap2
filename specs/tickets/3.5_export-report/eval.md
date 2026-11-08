# Ticket 3.5 — Export & Report · Evaluation

Tests build small `Layout`s by hand (valid tilings) plus a `PreparedInput` via `prepare_input` on fixture P8 /
site_rect_small and `tests/program/data/rulebook_test.yaml`.

| ID | Test | Pass condition |
|---|---|---|
| X01 | files | `export_run` writes the 4 files; second call into the same folder → FileExistsError, files unchanged. |
| X02 | json | `layout.json` bytes == `canonical_json(layout)`; reloads to an equal `Layout`. |
| X03 | dxf_audit | DXF opens with ezdxf; `audit()` 0 errors/0 fixes; the 5 layers exist with the specified colours; `$INSUNITS == 6`. |
| X04 | dxf_geometry | Every room/circulation rect has exactly one closed 4-vertex LWPOLYLINE on the right layer; its vertices equal modules × module / 1000 + origin (tolerance 1e-9); count equals rooms + circulation. |
| X05 | dxf_labels | One MTEXT per room on `ALE_LABEL` at the room centre; third line shows the placed area with comma decimals (e.g. `12,00 m² (Δ +0,00)`). |
| X06 | dxf_optional | With `dxf=False` (and with ezdxf import monkeypatched to fail) → `layout_dxf is None`, report mentions the skip. |
| X07 | svg | Parses with `xml.etree`; one `<rect>` (or `<polygon>`) per room and circulation rect; zone colours as specified; north arrow present; viewBox matches footprint bbox in metres. |
| X08 | report | Sections in the specified order; `## Surfaces` has one row per instance; values recomputed in the test match (2 decimals, comma); violations listed by code, or `Aucune.` when none. |
| X09 | origin_offset | A footprint with `origin_m = (0.05, 0.0)` shifts every DXF coordinate by +0.05 in x. |
| X10 | deterministic | Two exports of the same inputs → identical `layout.json`, `preview.svg`, `report.md` bytes (DXF compared entity-by-entity, not bytes: it carries a timestamp). |
| X11 | gates | ruff, ruff format, mypy strict clean; coverage of `ale.export` ≥ 90 % line; `lock --check` 0; whole suite passes. |
