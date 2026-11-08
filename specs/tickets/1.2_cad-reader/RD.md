# Ticket 1.2 — CAD Reader (DXF; DWG via converter) · Requirements Document

> **Worker brief.** Context = this file, `eval.md`, the contracts (`PlanGeometry`, `Wall`, `Opening`,
> `LabelledPolygon`, `TextItem`, `Polygon`, `LineString`, `SourceKind`, `ScaleMethod`, `LabelSource`, `Frame`,
> `taxonomy`), `ale.proc.run_tool`, `ale.guards.bounded`, `ale.config`, `ale.doctor` (tool detection). Library
> only: CLI wiring (`ale extract`, `ale layers`) is a follow-up once Ticket 1.1 is merged. Do not modify contracts.

## 1. Files
```
src/ale/cad/__init__.py
src/ale/cad/convert.py     # DWG → DXF (ODA via ezdxf.addons.odafc, fallback accoreconsole), cached
src/ale/cad/layers.py      # LayerMap model, keyword proposal, YAML load/save (layer_map.yaml format of 0.1)
src/ale/cad/units.py       # $INSUNITS → m per unit; inference from door blocks
src/ale/cad/read.py        # read_cad(...) → CadReadResult (list of PlanGeometry + warnings)
src/ale/cad/walls.py       # wall extraction (parallel-pair centrelines, polylines with width)
src/ale/cad/rooms.py       # zone polylines/hatches, else polygonize
src/ale/cad/openings.py    # door/window block inserts, arcs fallback
src/ale/cad/cluster.py     # several plans in one model space
tests/cad/**
specs/tickets/1.2_cad-reader/eval_report.md
```
Dependency: `ezdxf` (extra `cad`), shapely.

## 2. API
```python
class LayerRole(StrEnum): WALL, DOOR, WINDOW, ROOM_LABEL, AREA_LABEL, ZONE, FURNITURE, IGNORE
class LayerMap(BaseModel, frozen=True):  version: Literal[1] = 1; layers: dict[str, LayerRole]   # keys = exact layer names
def propose_layer_map(layer_names: Iterable[str], existing: LayerMap | None = None) -> LayerMap
def convert_dwg(dwg: Path, cache_dir: Path, config: AleConfig) -> ConvertResult   # .dxf path or NEEDS_TOOL / FAILED report
class CadReadResult(BaseModel, frozen=True):  plans: tuple[PlanGeometry, ...]; warnings: tuple[str, ...]; layer_names: tuple[str, ...]
def read_cad(path: Path, *, source_sha256: str, layer_map: LayerMap, config: AleConfig,
             units_override: str | None = None) -> CadReadResult
```

## 3. Rules
- **Layer proposal** *(amended at review 2026-11-08 — whole-word matching)*. Canonicalise the layer name
  (accents removed, upper case, every non-alphanumeric char → space) and split into tokens. A keyword (itself
  canonicalised, possibly several tokens) matches when its tokens appear **consecutively** in the name's tokens,
  each name token equal to the keyword token or to it plus a trailing `S` or `X` (plural). No substring matching
  (`PORTEUR` is not `PORTE`). Roles are tried in this order, first match wins:
  1. IGNORE: `COTE`, `COTATION`, `DIM`, `DIMENSION`, `AXE`, `DEFPOINTS`, `VIEWPORT`, `HACHURE` (when the name has no zone keyword);
  2. FURNITURE: `MOBILIER`, `EQUIPEMENT`, `FURN`, `A FURN`;
  3. AREA_LABEL: `SURFACE`, `AREA`, `M2`;
  4. ROOM_LABEL: `TEXTE`, `TEXT`, `NOM`, `LIBELLE`, `A ANNO`, `ETIQUETTE`;
  5. ZONE: `ZONE`, `LOCAL`, `ROOM`, `A AREA`, `ESPACE`;
  6. DOOR: `PORTE`, `DOOR`, `A DOOR`;
  7. WINDOW: `FENETRE`, `MENUISERIE`, `WINDOW`, `A GLAZ`, `CHASSIS`, `BAIE`;
  8. WALL: `MUR`, `CLOISON`, `WALL`, `A WALL`, `VOILE`, `MACONNERIE`, `BETON`, `PORTEUR`;
  anything else IGNORE. Existing entries are kept (user decisions win).
- **Model space only**; paper space ignored; XREFs: bound if the file sits next to the drawing, else warning
  `missing xref <name>`. Blocks are exploded virtually (`ezdxf` virtual entities) with their transforms.
- **Units**: `$INSUNITS` (1 in, 2 ft, 4 mm, 5 cm, 6 m) → metres per unit; else infer from door block widths
  (median of INSERT bbox widths on DOOR layers: 700–1100 → mm, 70–110 → cm, 0.7–1.1 → m) with warning
  `units inferred from doors`; else `units_override`; else unknown (scale_method UNKNOWN, warning).
- **Walls**: LWPOLYLINE with constant width > 0 → centreline + thickness; LINE/LWPOLYLINE segments on WALL layers
  → pair parallel segments (angle ≤ 1°, overlap ≥ 50 % of the shorter, distance 0.05–0.60 m) into one wall
  (centreline = midline of the overlap, thickness = distance); unpaired segments become walls with thickness None.
- **Rooms**: closed polylines / hatch boundaries on ZONE layers → rooms directly. Otherwise polygonize wall
  linework (both faces) plus door/window spans closed by segments; keep faces with 1.5 m² ≤ area ≤ 2000 m², drop the
  outer face and faces thinner than 0.5 m (wall cavities). Polygons valid (shapely `make_valid` if needed).
- **Labels**: TEXT/MTEXT on ROOM_LABEL layers (plain text, MTEXT codes stripped) whose insertion point lies in a room
  → `normalize_label`; exact/prefix match → `type`, `label_source = CAD_TEXT`, confidence 1.0 / 0.8, `raw_label`
  kept; several texts in one room → the longest canonical match wins. Area texts (`12,40 m²`, `S=12.4m2`) on
  AREA_LABEL or ROOM_LABEL layers → `area_text_m2`. Zones carrying a label attribute/text → `CAD_ZONE`.
  Every text becomes a `TextItem` (source `CAD`).
- **Openings**: INSERTs on DOOR/WINDOW layers → `Opening` (segment = the bbox side nearest to the closest wall,
  width = bbox extent along that wall); ARCs on DOOR layers without an INSERT nearby → door with width = radius.
  `host_wall` = nearest wall within 0.6 m.
- **Several plans**: cluster wall geometry by connectivity with a gap tolerance of max(5 m, 0.03 × drawing
  diagonal); each cluster ≥ 3 walls and ≥ 1 room → one `PlanGeometry` with `plan_index` ordered by (min y desc,
  min x) — top-left first; smaller clusters → warning `ignored fragment`.
- `PlanGeometry`: `source_kind` DXF (or DWG when converted), `frame Y_UP`, native units, `scale_m_per_unit` from
  units (method `DRAWING_UNITS`, confidence 1.0, or 0.6 when inferred).
- **DWG**: convert to `cache_dir/<sha256>.dxf` (reuse if present); ODA through `ezdxf.addons.odafc` with the
  executable path from `ale.doctor`'s detection; fallback accoreconsole with a generated script (`-DXFOUT`) via
  `ale.proc.run_tool` (timeout `tools.timeout_s`); none → `NEEDS_TOOL` (never raises). The source DWG is never written.
- All loops bounded (`ale.guards`); `read_cad` never raises for a readable DXF (problems → warnings).

## 4. Out of scope
CLI wiring, VLM labelling (1.5), scale reconciliation across sources (1.6), PDF/raster.
