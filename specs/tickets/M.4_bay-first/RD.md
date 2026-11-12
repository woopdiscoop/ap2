# Ticket M.4 — Bay-first planning of office bars · Requirements

> Context = this file, `eval.md`, the M.2b / M.3 / M.3b eval reports (why tuning the corridor-grammar engine
> reaches ≈ 83 % fill and ≤ 55 % partitions on bay lines), `ale.stack` (skeleton, `grid.py` rhythm, `plans.py`),
> R.8 (`TypeStats.depth_m`, `facade_width_m`, contracts 1.8.0), `ale.geometry.checks.check_layout`, `Layout`
> (contracts). User decisions U-9, U-10, U-14, U-15, U-16 and **U-18** (user, 2026-11-12: plan office bars
> bay-first; the existing engine stays for other footprints). **No contract changes.**

## 1. Purpose
Plan a bar floor the way an architect draws one: column grid and bay first, then rooms as **whole numbers of bays**
along each façade, corridor(s) parallel to the façades, the core and wet stack in the skeleton's place. One planner
that solves fill, rhythm, columns and stacking together (U-16): partitions are on bay lines by construction; columns
sit on partitions or in corridors by construction; a typical floor repeats.

## 2. Scope
Floors whose usable plate (outline minus skeleton) is a **bar**: a rectangle, or a rectangle minus solids touching
or inside it, depth 12–22 m. Other footprints keep the current engine (`ale stack --plans` picks bay-first for bars
unless `--planner engine`). Output is a normal contract `Layout` per floor, valid for `check_layout`, exported
(DXF/SVG) and reported exactly like today.

## 3. Method (`src/ale/bayplan/**`, new)
1. **Section** across the bar from M.3's grid and R.8 depths: single-loaded / double-loaded / double-loaded with a
   central band (« bande active »: meeting, archives, sanitary, copy) chosen by depth; façade zone depth from the
   corpus office depth p50 (fallback 5.4 m, then the 7.20 m config cap); corridor 1.8 m default (`circulation`
   rules).
2. **Bays**: bay module b from M.3 (2.4 m default; multiple of 0.60). Each façade zone is a sequence of bays
   interrupted by the skeleton.
3. **Packing**: assign the floor's rooms to bay runs: room width = k bays (k ≥ 1), area = k·b·depth must fall in the
   room's area window extended by U-15 sketch tolerance (default ±10 %, configurable); rooms that need no façade go
   in the central band or against the core. Exact or DP/ILP search per floor (bounded, deterministic); objective:
   groups contiguous (same entity together), adjacency priors, façade orientation, unused bays minimal.
4. **Typical floor**: plan the most loaded floor first; other floors reuse its bay assignment where the programme
   matches (room type per bay index), so plan-level stackability is high by construction.
5. **Columns**: columns at the M.3 grid; a column may not fall inside a room < 30 m² unless on its partition line
   (choose grid span = whole bays so this holds by construction).
6. Leftover bays become `reserve` rooms (reported) rather than stretched rooms.

## 4. Files (ownership)
`src/ale/bayplan/**` (new), `src/ale/stack/plans.py` and `src/ale/stack/grid.py` (planner selection and grid
coupling only), `src/ale/cli/commands/stack.py` (`--planner bay|engine`, default bay for bars), `tests/bayplan/**`,
`tests/stack/test_stack_m4.py`, `specs/tickets/M.4_bay-first/eval_report.md`. Do not modify `src/ale/contracts/**`,
`src/ale/geometry/**`, `src/ale/topology/**`, `src/ale/optimize/**`, the CLI registration file. With
`--planner engine` the outputs are byte-identical to today. Test helpers not imported as `conftest`. Never weaken a
test. Commit early and often.
