# ALE 2.2 — Contracts (human-readable summary)

The normative definition is `specs/tickets/0.2_contracts/RD.md` (data model) and
`specs/tickets/0.1_scaffolding-cli/RD.md` §6 (configuration). After both tickets merge, the code in
`src/ale/contracts/` is the source of truth and is frozen by `CONTRACTS.lock` (version `1.0.0`).
Any change goes through a contract-amendment ticket issued by the Router.

## Units and frames

| Where | Unit | Frame |
|---|---|---|
| Excel program, `site.yaml`, reports, DXF export | m, m² | site drawing axes, +y up |
| `ale.geometry`, `Layout`, `PolishExpression` realisation | **integer modules** (1 module = `grid.module_mm`, default **100 mm**, user decision U-1) | origin = lower-left of the footprint grid, +y up |
| `PlanGeometry` (Phase 1) | source native units (mm, drawing units, px, pt) | `Frame.Y_UP` (CAD) or `Frame.Y_DOWN` (raster, PDF page) |
| `PlanGeometry.to_metric()` | m | +y up |

Conversions only through `ale.contracts.units` (Decimal/int arithmetic; float `%` forbidden).
Compass: `north_angle_deg` = clockwise angle from drawing +y to true north; façade bearings binned to N/E/S/W.

## The area rule (architect decision D1)

`valid ⇔ −3 % × T ≤ A − T ≤ +max(3 % × T, 1.2 m²)`, implemented once in `ale.contracts.area_rule`
(`area_bounds_mm2`, `check_area`, `best_buildable_rect`) with exact integer mm² bounds.
`best_buildable_rect` rounds **up**: smallest area ≥ target first; only if none exists, the largest area below target (≥ −3 %).

## The proportion rule (user decision U-2)

Every room satisfies `long side / short side ≤ shape.aspect_max` (default **2.0**, i.e. between 1:2 and 2:1).
This is **hard**, like the area rule; circulation is exempt. Per-type rulebook bands (p10–p90, inside the
hard limit) are only preferences. On the 0.10 m grid both hard rules can always be met together
(Router check: every target from 0.5 to 500 m² has a rectangle, never below target, overshoot ≤ 0.18 m²).

## Models

| Model | Phase | Purpose |
|---|---|---|
| `RoomSpec`, `Program` | 3 in | Excel rows; `Program` checks ids, references, REQUIRED/AVOID consistency, expands quantities (`R1#01…`). |
| `SiteSpec` | 3 in | Buildable footprint (m), north angle, access edge index, optional core hint. |
| `GridSpec`, `ModuleRect`, `ModulePolygon` | 3 | Integer geometry; rectilinear CCW footprint. |
| `PlacedRoom`, `Layout`, `LayoutMetrics`, `Violation` | 3 out | Result; area/bbox methods take `GridSpec`. |
| `PolishExpression` | 3 | Normalised postfix slicing tree; `a b V` = a left of b, `a b H` = a below b. |
| `PlanGeometry`, `Wall`, `Opening`, `LabelledPolygon`, `TextItem` | 1 out | One per plan (file × page × plan_index). |
| `Rulebook`, `TypeStats`, `Quantiles`, `Adjacency`, `AdjEntry`, `CoreOffset` | 2 out / 3 in | Seed, mined or blended statistics. |
| `Taxonomy`, `RoomTypeDef`, `LabelMatch` | all | 25 canonical types, FR synonyms, deterministic label normalisation (exact, then longest token prefix; no fuzzy matching). |
| `AleConfig` | all | `ale.toml` (Ticket 0.1). |

Enums: `SourceKind, FileStatus, ScaleMethod, LabelSource, MacroZone, Bearing, EdgeKind, ContactKind, OpeningKind, Fidelity, TypeCategory, Frame`.

## Router refinements of directive §4 (for the user's information)

1. Geometry is plain data, not Shapely objects (serialisable, hashable, schema-exportable); Shapely only in helpers.
2. Added `Program`, `SiteSpec`, `GridSpec`, `Violation`, `Wall` (centreline + thickness — Ticket 2.1 needs thickness), `PolishExpression` (shared by 3.2–3.4).
3. `PlacedRoom.area_m2` etc. are methods taking `GridSpec`, because the module size is configurable.
4. Rulebook statistics grouped per type, adjacency as a sorted pair list (either order accepted on input), plus `author`/`date` for the seed.
5. `Bearing` has 4 values, `MacroZone` has 3 — both pending confirmation (board O-6, O-7).
6. Serialisation is canonical (sorted keys, fixed separators, 9 significant digits) so that "byte-identical `layout.json`" is testable.
