# Ticket M.2 — Exact per-floor plans inside the vertical skeleton · Requirements

> Context = this file, `eval.md`, `specs/design/research_roadmap.md` ("Multi-storey requirements"), user decisions
> U-10, U-14, U-15 on the board, M.1 (`ale.stack`: stacking, core + wet stack, `floor_NN/site.yaml` with the two
> cores, `floor_NN/programme.xlsx`), G.1/X.3 (footprints with courtyard holes: `ModulePolygon.holes`,
> `decompose_footprint`, ring corridors), contracts 1.6.0.

## 1. Purpose
M.1 fixes one core and one wet stack on identical cells on every floor but the exact-plan engine ignores
`SiteSpec.cores`, so a per-floor plan would put rooms over the stairs. M.2 makes the engine lay out each floor
**around fixed solids** (core, wet stack) and assembles complete floor plans in which the core and the wet rooms
sit at the same place on every floor (U-10).

## 2. Contracts 1.7.0 (bump, regenerate the lock, update the contract tests)
- `ModulePolygon.solids: tuple[ring, ...] = ()`: rectilinear clockwise rings strictly inside the exterior, not
  touching the exterior, a hole or another solid (same validation as `holes`; empty → left out of the serialised form,
  so existing polygons serialise exactly as before). A solid is **not tiled** (like a hole) but is **not exterior**:
  its edges never count as façade, daylight or `exterior_contacts`.
- `Layout.fixed: tuple[PlacedRoom, ...] = ()`: rooms placed by the skeleton inside solids (core, wet rooms,
  `reserve_technique`), sorted by `instance_id`, empty → left out of the serialised form. Not part of the tiling
  invariant; must lie inside a solid; no overlap.
- `SiteSpec` docstring: `cores` are now used: `to_module_footprint` turns each core rectangle into a solid (snapped
  **outward** to the grid, like courtyards). Sites without `cores` are unchanged (byte-identical outputs).

## 3. Engine (`src/ale/contracts/footprint.py`, `src/ale/program/site.py`, `src/ale/geometry/**`, `src/ale/topology/**`, `src/ale/optimize/**`, `src/ale/export/**` as needed)
- `decompose_footprint` treats solids as holes for the piece decomposition (ring corridors around a central core
  are the expected figure).
- `exterior_contacts`, façade checks, depth-from-façade (Q.4) and orientation ignore solid edges.
- **Hard rule** (new code, French message): every solid is touched by circulation along ≥ 1 module of its boundary
  (stairs and wet stack reachable). A solid entirely surrounded by rooms is a hard violation.
- DXF/SVG/JSON exports draw solids (hatched, labelled with the core id) and `Layout.fixed` rooms.

## 4. Floor assembly (`src/ale/stack/plans.py`, `ale stack --plans`)
`ale stack ... --plans [--budget S]`: after M.1, for each floor run `generate` on `floor_NN/programme.xlsx` minus
the wet rooms, with `floor_NN/site.yaml` (core and wet stack as solids), the CLI rulebook (`--rulebook`, default as
`ale generate`) and one variant per floor; then put the core and the floor's wet rooms (from M.1's tiling) into
`Layout.fixed`. Writes `floor_NN/plan/layout.json`, `.dxf`, `.svg`, and `plans.md` (French: per floor hard
violations, façade misses, areas, and a **vertical check**: core and wet-room rectangles identical on every floor =
hard). A floor whose generate fails is reported, the others still run.

## 5. Files (ownership)
Contracts and lock as in §2; engine files as in §3; `src/ale/stack/plans.py`, `src/ale/stack/report.py`,
`src/ale/cli/commands/stack.py`; `tests/contracts/**` (new tests + lock updates only), `tests/stack/**`,
`tests/geometry/test_geometry_m2.py`, `specs/tickets/M.2_floor-plans/eval_report.md`. Test helpers must not be
imported as `conftest`. Never weaken an existing test; existing outputs for sites without cores must stay
byte-identical (P25/P60 sample outputs, feasibility reports).
