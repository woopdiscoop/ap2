# Ticket M.1 — Multi-storey stacking and vertical skeleton · Requirements

> Context = this file, `eval.md`, `specs/design/research_roadmap.md` (target pipeline phase 2 "Stacking"; section
> "Multi-storey requirements"), user decisions U-10 (stackability first), U-14 (one stairwell; a core may hold several
> stairs), U-15 (sketch tolerance on areas, terraces allowed) on the board; contracts 1.6.0 (`RoomSpec.floor`,
> `RoomSpec.anchor`, `SiteSpec.cores`, `CoreSpec`); `ale.topology.cellgrow` (cell diagram inside a footprint, honours
> `SiteSpec.cores`); `ale.export.diagram`; `ale.parti` (G.2). **No contract changes.** Do not modify
> `src/ale/contracts`, `src/ale/geometry`, `src/ale/topology`, `src/ale/optimize`, `src/ale/form`.

## 1. Purpose
Liggett's two stages: **stacking** (which group of rooms on which floor) then **blocking** (lay out each floor). M.1
does stacking, fixes the **vertical skeleton** (one core and one wet stack occupying the same grid cells on every
floor) and lays out each floor as a **cell diagram** inside that skeleton. Exact per-floor plans with the skeleton
imposed on the engine are M.2; room stacking / shared bay rhythm / column grid are M.3.

## 2. Files (ownership)
`src/ale/stack/__init__.py`, `building.py`, `rules.py`, `assign.py`, `skeleton.py`, `floors.py`, `report.py`;
`src/ale/cli/commands/stack.py` (+ one import line and one `app.command` line in `src/ale/cli/__init__.py`);
`src/ale/parti/building_export.py` (+ the one call that writes it from the `ale parti` command, nothing else in
`ale.parti`); `tests/stack/**`; `specs/tickets/M.1_stacking/eval_report.md`. Test helpers must not be imported as
`conftest` (use a uniquely named helper module).

## 3. Inputs
- **Building** (`building.py`, module-local pydantic model, not a contract): `schema_version: "ale.building/1"`,
  `north_angle_deg`, `access_edge`, `entrances` (ground floor), `floor_height_m` (default 3.5), `core: CoreSpec`
  (exactly one, U-14), `floors: [{level, footprint}]` with levels 0..n contiguous; each upper outline must lie inside
  the one below (terraces recede, U-15) and every outline must contain the core. Loader errors are in French.
- `building_export.py`: G.2 writes `parti_NN/building.yaml` (per-floor outlines, its core) next to `site.yaml`.
- **Stacking rules** (`rules.py`, YAML, all optional): `groups: {name: [id prefixes or ids]}` (default: one group per
  room-id prefix, i.e. the letters before the digits, which is the Annexe import's entity code); `pins: {group:
  top | ground | <level>}` (hard); `together: [[g1, g2], ...]` (soft: same or adjacent floors); `keep_whole: true`;
  `circulation_share` (default 0.25). A room with `anchor: entrance` is pinned to the ground floor. Rooms with
  `floor > 0` in the programme are pinned to that level.

## 4. Stacking (`assign.py`)
- **Wet rooms** (types `sanitary`, `cleaning_room`, `technical_room`) are not stacked with their group: they form the
  wet stack (§5). All other instances belong to exactly one group.
- **Capacity** of floor k = (outline area − core area − wet-stack area) × (1 − circulation_share).
- **Objective**, minimised, deterministic: hard = pins violated, floors over capacity by more than 10 % (U-15 sketch
  tolerance); soft = Σ overload, number of split groups (a group is split only over **contiguous** floors and only
  when it cannot fit whole), `together` pairs more than one floor apart, load imbalance (max − min load share).
- **Method**: greedy placement by decreasing group size respecting pins, then local search (move a group, swap two
  groups, move one instance of a split group's boundary) until no improving move; ties broken by group name. Must
  reach the brute-force optimum on small cases (eval M104).
- Infeasible pins (pinned groups exceed the floor's capacity + 10 %) → report the hard miss with the shortfall in m²
  and still produce the best stacking; never crash.

## 5. Vertical skeleton (`skeleton.py`)
- **Core**: the building's `CoreSpec`, the same rectangle on every floor.
- **Wet stack**: wet instances are distributed over floors in proportion to each floor's assigned area (round-robin
  by type so every occupied floor gets sanitary rooms when the programme has enough). One rectangle on the 0.60 m grid,
  **adjacent to the core**, inside the **top floor's** outline (so it exists on every floor), sized to the largest
  per-floor wet demand (+ one 0.60 m shaft strip). Identical cells on every floor.
- Per floor, wet rooms are tiled inside the rectangle (strip partition on the grid), each ≥ its target area; leftover
  cells become `reserve_technique`. A floor whose wet demand does not fit is a hard miss (impossible by sizing, test it).

## 6. Per-floor cell diagrams (`floors.py`)
For each floor: `SiteSpec(footprint = outline, cores = (core, wet stack as kind "shaft"))`, programme = that floor's
non-wet rooms, `cellgrow.grow` → diagram. Fragmented rooms are repaired as in G.2 (keep the largest connected piece,
strays become circulation) and counted. Per floor report: façade rooms without façade, rooms off circulation, rooms
short, repaired rooms.

## 7. Metrics and outputs (`report.py`, `ale stack`)
`ale stack --program P.xlsx --building B.yaml [--rules R.yaml] --out DIR [--seed N]` writes:
- `stacking.md` (French): floor × group table (m², load %), pins met, split groups, `together` met, wet stack per
  floor, skeleton check (core and wet-stack cells identical on all floors = hard), per-floor diagram metrics, and a
  **stackability** figure: share of room cells whose cell directly above/below is occupied by a room of the same type.
- `stack.svg`: schematic section (one band per floor, groups coloured, core and wet stack drawn through all floors).
- `floor_NN/site.yaml` (outline + core + wet stack as cores), `floor_NN/programme.xlsx` (that floor's rooms, `floor`
  set to the level), `floor_NN/diagram.svg`. Deterministic (two runs byte-identical). Exit codes per `_common.py`.
