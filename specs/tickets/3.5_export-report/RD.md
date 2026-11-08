# Ticket 3.5 — Export & Report · Requirements Document

> **Worker brief.** Context = this file, `eval.md`, the contracts (`Layout`, `PlacedRoom`, `GridSpec`,
> `ModulePolygon`, `Program`, `RoomSpec`, `SiteSpec`, `canonical_json`, `units`, `taxonomy`), the public
> interfaces of `ale.program` (`PreparedInput`, `ModuleFootprint`), `ale.config`, and the test helpers in
> `tests/conftest.py`, `tests/fixtures/`. Do not modify contracts or other tickets' files.

## 1. Purpose
Write a generated `Layout` to the run folder: `layout.json`, `layout.dxf`, `preview.svg`, `report.md`.

## 2. Files
```
src/ale/export/__init__.py
src/ale/export/run.py        # export_run(...) → RunFiles
src/ale/export/dxf.py        # layered DXF (ezdxf, extra "cad")
src/ale/export/svg.py        # dependency-free SVG writer
src/ale/export/report.py     # report.md (French)
tests/export/**
specs/tickets/3.5_export-report/eval_report.md
```

## 3. API
```python
class RunFiles(BaseModel, frozen=True):
    layout_json: Path; layout_dxf: Path | None; preview_svg: Path; report_md: Path
def export_run(layout: Layout, prepared: PreparedInput, out_dir: Path, *,
               rulebook_version: str, run_id: str, dxf: bool = True) -> RunFiles
```
- Creates `out_dir` if missing; refuses (FileExistsError) if it already contains any of the four files.
- `dxf=False` or ezdxf not installed → `layout_dxf = None` and a line in the report saying DXF was skipped.
- Coordinates: metres = modules × `grid.module_mm` / 1000, plus `prepared.footprint.origin_m` (back to site
  drawing axes). Exact via `ale.contracts.units`; written with ≤ 4 decimals.

## 4. `layout.json`
`canonical_json(layout)` bytes, unchanged (the contract serialisation is the format).

## 5. `layout.dxf` (ezdxf, DXF R2018, units metres: `$INSUNITS = 6`)
Layers (exact names, colours ACI): `ALE_FOOTPRINT` (7), `ALE_ROOM` (5), `ALE_CIRC` (8), `ALE_LABEL` (2),
`ALE_GRID` (9, off by default).
- Footprint: closed LWPOLYLINE of the module footprint.
- Each room: closed LWPOLYLINE (4 vertices, CCW) on `ALE_ROOM`; each circulation rect on `ALE_CIRC`.
- Each room label on `ALE_LABEL`: MTEXT at the room centre, height 0.25 m, attachment middle-centre, 3 lines:
  `name` · `label_fr of type` · `placed area m² (Δ +x.xx)`, area with 2 decimals and `,` as decimal separator.
  (Name/type from the `RoomSpec` of `spec_id`; instance suffix `#k` appended to the name when quantity > 1.)
- Grid: lines every 1.2 m (12 modules at 0.10 m; `ceil(1.2 / module)` modules in general) clipped to the footprint bbox.
- Document passes `doc.audit()` with 0 errors and 0 fixes.

## 6. `preview.svg`
Plain SVG 1.1 written by hand (no dependency), `viewBox` in metres with y flipped (SVG y down), stroke widths
in metres. Rooms filled by macro-zone (PUBLIC `#f4d35e`, ADMINISTRATIVE `#9ad1d4`, SERVICES `#c8c8c8`),
circulation `#ffffff` with grey hatch-free fill `#eeeeee`, footprint outline black, labels (`name` + area)
`font-size` 0.25 m centred. A north arrow from `site.north_angle_deg` in the top-right corner. Valid XML.

## 7. `report.md` (French)
Sections, in order: `# Rapport de génération — <run_id>`; `## Résumé` (seed, rulebook version, contracts version,
module, footprint area, Σ net, Σ placed, circulation area and ratio, total overshoot, total cost);
`## Surfaces` (Markdown table, one row per room instance sorted by instance id: ID, Nom, Type, Zone, Cible m²,
Placée m², Δ m², Δ %, Dimensions `L × l` m, Façade oui/non, Statut `OK`/codes); `## Contraintes non
respectées` (violations grouped by code, or `Aucune.`); `## Coût` (table of `cost_breakdown` with weights from
config and weighted values, plus total); `## Fichiers`. All numbers with `,` decimal separator and 2 decimals.

## 8. Out of scope
Generating layouts, CLI wiring of `ale generate` (Ticket 3.4 wires it).
