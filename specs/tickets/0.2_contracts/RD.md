# Ticket 0.2 — Data Contracts · Requirements Document

> **Worker brief.** This file, `eval.md`, and `taxonomy.v1.yaml` (same folder) are your
> entire context. You are writing the **frozen contracts** every later ticket depends on:
> precision matters more than breadth. Do not add fields, types or behaviour that are not
> specified here. If something here is ambiguous, stop and report it instead of guessing.

## 1. Purpose

Create `ale.contracts`: the shared data model (pydantic v2), unit conversions,
the area-tolerance rule, the room-type taxonomy with label normalisation,
orientation helpers, canonical serialisation, JSON Schemas, and a contract lock file.

## 2. Environment

- Python 3.11+. Dependencies (already declared by Ticket 0.1's `pyproject.toml`):
  `pydantic>=2.6,<3`, `PyYAML>=6`, `shapely>=2.0`, `jsonschema>=4.21`; dev: `pytest`, `hypothesis`.
- If Ticket 0.1 has not merged yet, run tests with `PYTHONPATH=src pytest tests/contracts`.
- No network, no filesystem access outside the package except in the CLI helpers of §12.

## 3. File ownership

Create exactly these files; touch nothing else.

```
src/ale/contracts/__init__.py          # EMPTY (also created empty by Ticket 0.1 — keep it empty)
src/ale/contracts/version.py           # CONTRACTS_VERSION = "1.0.0"
src/ale/contracts/units.py
src/ale/contracts/enums.py
src/ale/contracts/geometry.py
src/ale/contracts/orientation.py
src/ale/contracts/taxonomy.py
src/ale/contracts/taxonomy.yaml        # verbatim copy of taxonomy.v1.yaml from this ticket folder
src/ale/contracts/area_rule.py
src/ale/contracts/models.py
src/ale/contracts/serialization.py
src/ale/contracts/schemas/*.json       # generated (§11)
src/ale/contracts/export_schemas.py    # python -m ale.contracts.export_schemas
src/ale/contracts/validate.py          # python -m ale.contracts.validate KIND FILE
src/ale/contracts/lock.py              # python -m ale.contracts.lock [--check]
tests/contracts/**
```

`src/ale/contracts/config.py` and `config.schema.json` belong to Ticket 0.1: do not create them.

## 4. Global rules

- Every model: `model_config = ConfigDict(extra="forbid", frozen=True)`. Do **not** set model-wide
  `strict=True` (it would reject enum values given as strings when loading YAML).
  Instead, every `int` field is `StrictInt` (rejects `1.0`, `True` and `"3"`), every `bool` field is
  `StrictBool`, and every `str` field is `StrictStr`. `float` fields accept ints (YAML/Excel write `12` for `12.0`)
  but reject strings and bools (`Annotated[float, BeforeValidator(_no_str_no_bool)]`).
- Collections are `tuple[...]` (immutable), serialised as JSON arrays.
- Public functions are pure and deterministic. No global mutable state except the cached taxonomy (§7).
- All docstrings state units. External units are **metres and m²**; `ale.geometry` internals use
  **integer modules**; conversion only through `units.py`.

## 5. `units.py` — exact conversions

Internally use `decimal.Decimal` (constructed from `str(x)` for floats) or `int`; never float arithmetic.

```python
class Rounding(StrEnum): EXACT, FLOOR, CEIL, NEAREST     # NEAREST = round-half-even
class NotOnGridError(ValueError): ...

def m_to_mm(x: float | int | str | Decimal) -> int          # round-half-even to 1 mm
def mm_to_m(mm: int) -> float                               # float(Decimal(mm) / 1000)
def m2_to_mm2(x: float | int | str | Decimal) -> int        # round-half-even to 1 mm²
def mm2_to_m2(mm2: int) -> float
def mm_to_modules(mm: int, module_mm: int, mode: Rounding = Rounding.EXACT) -> int
def m_to_modules(x: float | int | str | Decimal, module_mm: int, mode: Rounding = Rounding.EXACT) -> int
def modules_to_mm(n: int, module_mm: int) -> int
def modules_to_m(n: int, module_mm: int) -> float
def cells_to_m2(n_cells: int, module_mm: int) -> float      # n module² cells → m²
```

- `EXACT` raises `NotOnGridError` (message includes value and module) when not a whole number of modules.
- `module_mm` must be an `int` in `100..1200`; otherwise `ValueError`.
- Floating-point modulo (`%` on floats) is forbidden anywhere in `ale.contracts` (checked by a test).

## 6. `enums.py`

All `StrEnum`, values equal to names unless shown.

```python
SourceKind   = DWG | DXF | PDF_VECTOR | PDF_SCANNED | RASTER
FileStatus   = NEW | EXTRACTED | FAILED | EXCLUDED | NEEDS_TOOL
ScaleMethod  = DRAWING_UNITS | META_CSV | TITLE_BLOCK | SCALE_BAR | DIMENSION_TEXT | DOOR_MEDIAN | UNKNOWN
LabelSource  = CAD_TEXT | CAD_ZONE | PDF_TEXT | VLM | MANUAL
MacroZone    = PUBLIC | ADMINISTRATIVE | SERVICES
Bearing      = N | E | S | W
EdgeKind     = REQUIRED | PREFERRED | AVOID            # program/topology graph edges (§3.A of directive)
ContactKind  = WALL | DOOR                             # extracted topology edges (Ticket 2.1)
OpeningKind  = DOOR | WINDOW
Fidelity     = CAD | PDF_VECTOR | RASTER               # source fidelity class (Ticket 2.2 weights)
TypeCategory = ROOM | CIRCULATION | VERTICAL | SPECIAL
Frame        = Y_UP | Y_DOWN                           # native coordinate frame of a PlanGeometry
```

Plus `def fidelity_of(kind: SourceKind) -> Fidelity`: DWG, DXF → CAD; PDF_VECTOR → PDF_VECTOR; PDF_SCANNED, RASTER → RASTER.

## 7. `taxonomy.py` + `taxonomy.yaml`

`taxonomy.yaml` is a verbatim copy of `taxonomy.v1.yaml` from this ticket folder.

```python
RoomTypeKey = Annotated[str, AfterValidator(_check_known_type)]   # must be a key in the taxonomy
UNKNOWN: Final = "unknown"

class RoomTypeDef(BaseModel):     # one entry of taxonomy.yaml
    key: str; label_fr: str; label_en: str
    category: TypeCategory
    default_macro_zone: MacroZone | None
    service_core: bool
    synonyms: tuple[str, ...]

class Taxonomy(BaseModel):
    version: str
    types: tuple[RoomTypeDef, ...]
    def get(self, key: str) -> RoomTypeDef            # KeyError if absent
    def keys(self) -> tuple[str, ...]                 # in file order
    def normalize_label(self, raw: str) -> LabelMatch

class LabelMatch(BaseModel):
    key: str                                          # a type key, or "unknown"
    rule: Literal["exact", "prefix", "none"]
    matched_synonym: str | None                       # the synonym as written in the YAML
    canonical_input: str                              # canonical form of `raw` (below)

def load_taxonomy(path: Path | None = None) -> Taxonomy   # default: packaged file, cached (functools.cache)
```

Taxonomy load-time validation (raise `ValueError` listing every problem):
keys match `^[a-z][a-z0-9_]*$` and are unique; `unknown` exists with category `SPECIAL` and no synonyms;
every non-SPECIAL type has ≥ 1 synonym; **no two types share a canonical synonym**; `version` is semver.

**Canonical form** `canon(s)` — applied identically to labels and synonyms:
1. Unicode NFKC (turns `²` into `2`), then NFD and drop all combining marks (accents), then `upper()`.
2. Replace every character that is not `A–Z` or `0–9` with a space.
3. Split on whitespace into tokens.
4. Remove an area expression: tokens matching `^\d+$` followed by optional `^\d+$` and then `M2` (e.g. `12 40 M2` from `12,40 m²`); also a single token `^\d+M2$`.
5. Remove leading and trailing tokens that are room numbers: `^\d+[A-Z]?$` or `^[A-Z]\d+$` (e.g. `12`, `3A`, `B12`, `R01`). Repeat until none remain at either end.
6. Merge every run of ≥ 2 consecutive single-letter tokens into one token (`S D R` → `SDR`, `WC H F` → `WC HF`).
7. Join with single spaces.

**Matching** (`normalize_label`):
1. `rule="exact"`: `canon(raw)` equals the canonical form of a synonym → that type.
2. `rule="prefix"`: otherwise, among synonyms whose token list is a **proper prefix** of the label's
   token list, take the one with the most tokens (then the longest string) → that type.
3. Otherwise `key="unknown"`, `rule="none"`. Empty canonical input → `unknown`.
No fuzzy/edit-distance matching.

## 8. `geometry.py` — plain-data geometry

Native-unit / metric geometry (floats) and module geometry (ints). Shapely is used only
in conversion helpers, never stored in models.

```python
Point2 = tuple[float, float]

class LineString(BaseModel):  coords: tuple[Point2, ...]          # ≥ 2 points, no consecutive duplicates
class Polygon(BaseModel):     exterior: tuple[Point2, ...]; holes: tuple[tuple[Point2, ...], ...] = ()
    # rings NOT closed in storage (first point not repeated); ≥ 3 points; validated with shapely is_valid
class ModuleRect(BaseModel):  x: int; y: int; w: int; h: int      # w ≥ 1, h ≥ 1 (strict ints)
    def area_cells(self) -> int; def x2(self) -> int; def y2(self) -> int
    def intersection_cells(self, other: "ModuleRect") -> int      # exact integer overlap area
class ModulePolygon(BaseModel): exterior: tuple[tuple[int, int], ...]
    # strict ints; rectilinear (every edge axis-parallel); counter-clockwise; simple; ≥ 4 vertices; no collinear consecutive vertices
    def area_cells(self) -> int                                    # shoelace, exact int
    def edges(self) -> tuple[tuple[tuple[int,int], tuple[int,int]], ...]   # edge i = (v[i], v[i+1 mod n])

def to_shapely(g: LineString | Polygon | ModulePolygon | ModuleRect) -> shapely.Geometry
def polygon_from_shapely(p: shapely.Polygon) -> Polygon            # drops closing point, keeps orientation
```

**Coordinate conventions (frozen):**
- `Layout` / module geometry: origin = lower-left corner of the footprint's module grid, +x right, **+y up**,
  1 unit = 1 module. `ModuleRect(x, y, w, h)` covers `[x, x+w] × [y, y+h]`.
- `PlanGeometry` coordinates are in the source's **native units** and native frame (`Frame.Y_UP` for CAD,
  `Frame.Y_DOWN` for raster pixels and PyMuPDF page space). `PlanGeometry.to_metric()` (§9.4) is the only
  conversion to metres, y-up.

## 9. `models.py`

### 9.1 Program & site (inputs of Phase 3)

```python
RoomId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,32}$")]

class RoomSpec(BaseModel):                          # immutable input row
    id: RoomId; name: str (1..120 chars, stripped)
    type: RoomTypeKey                                # must not be "unknown" nor category CIRCULATION
    target_area_m2: float                            # 0 < x ≤ 10_000
    quantity: int = 1                                # 1..500
    macro_zone: MacroZone
    needs_facade: bool = False
    orientation_override: dict[Bearing, float] | None = None   # each value in [-1, 1]; ≥ 1 key if not None
    min_width_m: float | None = None                 # > 0
    adjacent_to: tuple[RoomId, ...] = ()             # REQUIRED edges
    avoid: tuple[RoomId, ...] = ()                   # AVOID edges
    floor: int = 0                                   # v1: must be 0
    # validators: no self-reference; adjacent_to ∩ avoid = ∅; no duplicates inside each tuple

class Program(BaseModel):
    rooms: tuple[RoomSpec, ...]                      # ≥ 1
    # validators: ids unique; every id in adjacent_to/avoid exists;
    # REQUIRED/AVOID are undirected: A.adjacent_to ∋ B and B.avoid ∋ A → error
    def instances(self) -> tuple[tuple[str, RoomSpec], ...]
    # expands quantity: instance id = id if quantity == 1 else f"{id}#{k}" for k = 1..quantity (k zero-padded to width of quantity)

class SiteSpec(BaseModel):
    footprint: Polygon                               # metres, y-up, buildable area after setbacks; v1: rectilinear
    north_angle_deg: float                           # [0, 360): angle from drawing +y to true north, CLOCKWISE positive
    access_edge: int                                 # index i of the edge (exterior[i] → exterior[i+1]) holding the main access
    core_hint: Point2 | None = None                  # metres
```

### 9.2 Layout (output of Phase 3)

```python
class GridSpec(BaseModel):  module_mm: int = 600   # 100..1200

class PlacedRoom(BaseModel):
    instance_id: str                                 # from Program.instances(), or "circ-NNN" for circulation
    spec_id: str | None                              # RoomSpec.id; None for circulation
    rect: ModuleRect
    target_area_m2: float | None                     # copied from the spec; None for circulation
    def area_m2(self, grid: GridSpec) -> float
    def aspect_ratio(self) -> float                  # max(w, h) / min(w, h), ≥ 1
    def bbox_m(self, grid: GridSpec) -> tuple[float, float, float, float]   # x0, y0, x1, y1 in metres
    def area_delta_m2(self, grid: GridSpec) -> float | None                 # placed − target

class Violation(BaseModel):
    code: str                     # e.g. "AREA_UNDER", "AREA_OVER", "NO_CIRCULATION_ACCESS", "NO_FACADE", "REQUIRED_ADJ"
    instance_ids: tuple[str, ...]
    detail: str

class LayoutMetrics(BaseModel):
    total_cost: float
    cost_breakdown: dict[str, float]                 # keys = optimizer weight names (config [optimizer.weights])
    total_overshoot_m2: float                        # Σ max(0, Δ) over rooms
    circulation_area_m2: float
    residue_area_m2: float
    violations: tuple[Violation, ...]

class Layout(BaseModel):
    schema_version: Literal["ale.layout/1"] = "ale.layout/1"
    grid: GridSpec
    footprint: ModulePolygon
    rooms: tuple[PlacedRoom, ...]                    # sorted by instance_id
    circulation: tuple[PlacedRoom, ...]              # sorted by instance_id
    residue: tuple[ModuleRect, ...] = ()             # unassignable strips, reported
    seed: int
    rulebook_version: str
    metrics: LayoutMetrics
    # cheap validators only: instance_ids unique; tuples sorted; circulation entries have spec_id None.
    # Overlap/coverage checks are NOT done here (Ticket 3.3 tests them).
```

`PlacedRoom` methods take `GridSpec` explicitly because the module size is configurable; there is no hidden default.

### 9.3 Slicing tree (shared by Tickets 3.2–3.4)

```python
class PolishExpression(BaseModel):
    tokens: tuple[str, ...]          # postfix; operators "H" and "V"; every other token is a leaf id (unique)
    # validators:
    #  - balloting: for every prefix, #operands > #operators; overall #operands = #operators + 1
    #  - normalised (Wong–Liu): no two consecutive identical operators
    #  - leaf ids match ^[A-Za-z0-9_#-]{1,40}$ and are not "H"/"V"
    def leaves(self) -> tuple[str, ...]              # in order of appearance
```
Cut semantics (frozen): `a b V` = a **left of** b (vertical cut line); `a b H` = a **below** b (horizontal cut line).

### 9.4 Phase 1 extraction

```python
class TextItem(BaseModel):
    text: str; insert: Point2; height: float | None = None; rotation_deg: float = 0.0
    layer: str | None = None; source: Literal["CAD", "PDF", "OCR"]

class Wall(BaseModel):
    centerline: LineString; thickness: float | None = None        # native units

class Opening(BaseModel):
    kind: OpeningKind
    segment: LineString                     # exactly 2 points, along the host wall, native units
    width_native: float                     # > 0
    width_m: float | None = None            # set once scale is known
    host_wall: int | None = None            # index into PlanGeometry.walls

class LabelledPolygon(BaseModel):
    id: str                                 # unique within the plan
    polygon: Polygon                        # native units
    type: RoomTypeKey | None = None         # None = not labelled yet; "unknown" = labelling failed
    label_source: LabelSource | None = None
    confidence: float = 0.0                 # [0, 1]
    raw_label: str | None = None
    area_text_m2: float | None = None       # area written on the drawing, if any
    # validator: type is None ⇔ label_source is None

class PlanGeometry(BaseModel):
    schema_version: Literal["ale.plan/1"] = "ale.plan/1"
    source_sha256: str                      # 64 lowercase hex
    page: int                               # ≥ 0 (0 for single-page formats)
    plan_index: int                         # ≥ 0
    source_kind: SourceKind
    frame: Frame
    units_label: str | None = None          # e.g. "mm", "px", "pt"
    scale_m_per_unit: float | None = None   # > 0; None until known
    scale_method: ScaleMethod = ScaleMethod.UNKNOWN
    scale_confidence: float = 0.0           # [0, 1]
    walls: tuple[Wall, ...] = ()
    openings: tuple[Opening, ...] = ()
    rooms: tuple[LabelledPolygon, ...] = ()
    texts: tuple[TextItem, ...] = ()
    warnings: tuple[str, ...] = ()
    # validators: scale_method UNKNOWN ⇔ scale_m_per_unit None; host_wall indexes valid;
    #   if scale known, every opening with width_m satisfies |width_m − width_native·scale| ≤ 1e-6·max(1, width_m)
    def to_metric(self) -> "PlanGeometry"
    # requires a known scale; returns a copy in metres, Frame.Y_UP (Y_DOWN input is flipped about y = 0),
    # units_label "m", scale 1.0 (scale_method and confidence preserved), width_m filled for every opening.
```

### 9.5 Rulebook

```python
class Quantiles(BaseModel):  p10: float; p50: float; p90: float; n: int = 0    # p10 ≤ p50 ≤ p90; n ≥ 0
class TypeStats(BaseModel):
    aspect: Quantiles            # long side / short side; p10 ≥ 1.0, p90 ≤ 6.0
    area_m2: Quantiles           # p10 > 0
    orientation: dict[Bearing, float]   # exactly the 4 bearings, each in [-1, 1]
class AdjEntry(BaseModel):
    a: RoomTypeKey; b: RoomTypeKey      # input in any order; a before-validator swaps so that a ≤ b (string order);
                                        # a == b allowed (two rooms of the same type)
    p: float                            # [0, 1]
    n_support: int = 0
class Adjacency(BaseModel):
    default_p: float                    # [0, 1], used for pairs not listed
    pairs: tuple[AdjEntry, ...]         # input in any order; a before-validator sorts by (a, b);
                                        # duplicates after canonicalisation → ValidationError
    def p(self, a: str, b: str) -> float          # order-insensitive lookup, falls back to default_p
class CoreOffset(BaseModel):
    dx_norm: float; dy_norm: float      # each in [-0.5, 0.5]: (core centroid − footprint centroid) / (footprint width, height)
    n: int = 0
class Rulebook(BaseModel):
    schema_version: Literal["ale.rulebook/1"] = "ale.rulebook/1"
    version: str                        # non-empty
    kind: Literal["seed", "mined", "blended"]
    author: str | None = None           # required (non-empty) when kind == "seed"
    date: str | None = None             # YYYY-MM-DD; required when kind == "seed"
    n_plans: int = 0
    source_mix: dict[Fidelity, int] = {}
    types: dict[RoomTypeKey, TypeStats] # keys must not be "unknown" or category CIRCULATION; may be a subset of the taxonomy
    adjacency: Adjacency
    core_offset: CoreOffset
    def missing_types(self, needed: Iterable[str]) -> tuple[str, ...]   # sorted
    def content_sha256(self) -> str     # sha256 of canonical_json(self)
```
Deviation from the directive (accepted by the Router): statistics are grouped per type
(`types[t].aspect/area_m2/orientation`) instead of three parallel dicts, and adjacency is a
sorted list instead of a tuple-keyed dict, so that the YAML is human-editable and round-trips exactly.

## 10. `area_rule.py` and `orientation.py`

```python
class AreaTolerance(BaseModel):
    down_pct: float = 3.0; up_pct: float = 3.0; up_abs_m2: float = 1.2      # all ≥ 0

def area_bounds_mm2(target_m2: float, tol: AreaTolerance) -> tuple[int, int]
    # inclusive integer bounds [lo, hi] in mm²:
    # lo = ceil(T·(1 − down_pct/100)),  hi = floor(T + max(T·up_pct/100, up_abs_m2)), with T in mm² (exact Decimal)

class AreaCheck(BaseModel):
    valid: bool; placed_m2: float; delta_m2: float; delta_pct: float; overshoot_m2: float   # overshoot = max(0, delta)

def check_area(rect: ModuleRect, grid: GridSpec, target_m2: float, tol: AreaTolerance) -> AreaCheck

def smallest_valid_rect(target_m2: float, grid: GridSpec, aspect_min: float, aspect_max: float,
                        tol: AreaTolerance, min_short_side_modules: int = 1,
                        max_side_modules: int = 200) -> tuple[int, int] | None
    # returns (short, long) in modules with short ≤ long, aspect long/short in [aspect_min, aspect_max],
    # area within area_bounds_mm2; minimises area, then |long/short − 1|, then short.
    # None if no rectangle satisfies all constraints.  Bounded loops only (≤ max_side_modules²).
```

```python
def compass_bearing_deg(dx: float, dy: float, north_angle_deg: float) -> float
    # bearing in [0, 360) of direction (dx, dy) given in drawing coords (+y up), clockwise from true north.
    # north_angle_deg is the clockwise angle from drawing +y to true north.
def bearing_bin(bearing_deg: float) -> Bearing
    # N = [315, 45), E = [45, 135), S = [135, 225), W = [225, 315)
def edge_outward_normals(poly: ModulePolygon) -> tuple[tuple[int, int], ...]
    # unit axis vectors, one per edge (polygon is CCW, so outward = edge direction rotated −90°)
```

## 11. `serialization.py`, schemas

```python
def canonical_json(model: BaseModel) -> bytes
    # model_dump(mode="json"), then json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    # allow_nan=False) + b"\n"; floats rounded to 9 significant digits before dumping.
def dump_yaml(model: BaseModel) -> str           # yaml.safe_dump(sort_keys=False, allow_unicode=True), field order of the model
def load_yaml(cls: type[M], text: str) -> M      # yaml.safe_load + cls.model_validate (non-strict for YAML number coercion only)
```

`python -m ale.contracts.export_schemas` writes one JSON Schema per model
`RoomSpec, Program, SiteSpec, Layout, PlanGeometry, Rulebook, Taxonomy` to
`src/ale/contracts/schemas/<Name>.schema.json` (`json.dumps(indent=2, sort_keys=True)` + `"\n"`).
With `--check` it exits 1 if any file differs from what it would write.

## 12. Helpers

- `python -m ale.contracts.validate {rulebook|program|site|layout|plan|taxonomy} FILE` — loads YAML or JSON
  (by extension), validates, prints `OK` or one line per error as `<dotted.path>: <message>`; exit 0/1.
  For `rulebook`, also prints the list of taxonomy room types (category ROOM or VERTICAL) that are absent
  from `types` as an informational line (not an error).
- `python -m ale.contracts.lock` writes `src/ale/contracts/CONTRACTS.lock`: one line
  `<sha256>  <relative path>` per file under `src/ale/contracts/` (sorted, excluding the lock file itself
  and `__pycache__`). `--check` exits 1 on any difference. The Router generates and commits the lock
  after both 0.1 and 0.2 are merged; from then on every ticket's eval runs `--check`.

## 13. Out of scope

Config model (0.1), any reading of real plans, Excel parsing, geometry algorithms, guards.
