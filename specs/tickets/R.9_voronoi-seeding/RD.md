# Ticket R.9 — Whole-programme cell-growth seeding (the architect's method) · Requirements Document

> Context = this file, `eval.md`, `specs/design/research_roadmap.md` (target pipeline, phase 3), the prototype
> (Part A of the grid-sizing page; its algorithm is summarised in §3), contracts 1.5.0 (A.4: `SiteSpec.entrances`,
> `SiteSpec.cores`, `RoomSpec.anchor`), `ale.topology` (`seed.py`, `embed.py`, `depth.py`), `ale.geometry`,
> Q.3/Q.4 eval reports (deterministic budgets; D05 target moved here). No contract changes. **Do not edit
> `ale.optimize`** (R.1 is changing it): the new seeder is reached through `seed_plan(..., seeder=...)` only.

## 1. Purpose
Replace the abstract spring ordering of the seeder by the architect's method: lay the whole programme down as
module cells on the footprint, anchors first, then grow every room to its exact cell count. The grown diagram decides
**which rooms get façade, who neighbours whom and the order along each band**; the corridor grammar then realises it.
The diagram is also an output (SVG) for the architect.

## 2. Files (ownership)
`src/ale/topology/cellgrow.py` (NEW: diagram), `src/ale/topology/fromdiagram.py` (NEW: diagram → CorridorPlan
assignment), `src/ale/topology/seed.py` (ONLY: `seeder: Literal["spring", "cells"] = "spring"` + dispatch),
`src/ale/export/diagram.py` (NEW: SVG of the cell diagram), `tests/topology/test_cellgrow*.py`,
`tests/export/test_export_diagram.py`, `specs/tickets/R.9_voronoi-seeding/eval_report.md`.

## 3. Cell diagram (`cellgrow.py`), deterministic for a seed
1. Grid = module footprint cells; cores (`SiteSpec.cores`, rounded to modules) are fixed blocks; entrances from
   `SiteSpec.entrances` (main first; default: midpoint of the access edge).
2. **Façade ribbon**: walk the exterior edges from the first `anchor="corner"` room's corner (default: the corner
   nearest the access edge) and give each `needs_facade` room a frontage share = ceil(n / d) cells, d = min(depth
   limit in cells, round(sqrt(1.6 n))), depth limit = `facade.max_depth_m` if set else 7.2 m; scale shares down if
   their sum exceeds the usable perimeter; rooms ordered by macro-zone then programme order. Seed = middle of its
   share, **on the façade line**. `anchor="corner"` rooms take the corner; `anchor="entrance"` rooms take the share
   that contains the main entrance (or the nearest).
3. Non-façade rooms: seeded next to their first REQUIRED partner on the interior side (offset = half the partner's
   depth + 1); `service_core` rooms next to a core; others at the free cell nearest the footprint centre.
4. **Simultaneous growth**: each round, every unfinished room claims cells in proportion to its size (quota =
   max(1, round(4 n / n_max))) from its frontier, scoring −3·own neighbours + 0.5·distance to own centroid; façade
   rooms +0.25·distance to façade and a +10 penalty beyond the depth limit; +0.6·Manhattan distance to the entrance
   for the entrance room; +0.08·distance to REQUIRED partners' centroids; ties broken by cell index. Stop when all
   rooms have their count or no progress. Unclaimed cells = circulation reserve.
5. Output `CellDiagram(owner grid, per-room cells, checks)` with the checks of the prototype: area, façade, corner,
   entrance, adjacency, next to a core.

## 4. From the diagram to a CorridorPlan (`fromdiagram.py`)
Use the existing band/block structure chosen by the current seeder (band counts, connectors) and replace only the
**assignment and order**: a room goes to the block whose region contains most of its cells (façade rooms to the
exterior block on their façade side), ordered along the spine by the projection of its cell centroid; then the
existing capacity estimate and repair steps of 3.2 run as today. If realisation fails, fall back to the spring
seeder for that attempt (recorded).

## 5. Adoption rule (measured; deterministic budgets of Q.3)
Compare `spring` vs `cells` on P25, P60 and the AREP top-floor programme of Q.4 D05 (hard mode and soft mode), 5 seeds,
same attempts and annealing iterations: final hard count, NO_FACADE, REQUIRED_ADJ, cost. **Adopt** (`cells` as the
default in a later ticket wiring `generate`) only if the mean final hard is lower on P60 and on the AREP floor and
not higher on P25. In every case report the table. The Q.4 D05 hard-mode target NO_FACADE ≤ 1 is re-tested with
`cells` (R9-08) and kept as written.
