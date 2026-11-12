# Ticket M.3b · Evaluation report

Branch `worktree-agent-afd3f9fee67b85a76` (base `681987b`). The diagnosis (B301) is committed before the first code
change. Tests: `tests/geometry/test_geometry_m3b.py`, `tests/stack/test_stack_m3b.py`. Synthetic data only.

## Diagnosis

Measured at `681987b` before any code change. Case: the loaded bar (`tests/stack/bar_case.py`), `ale stack --plans
--budget 10`, seeds 0, 1, 2 (the plan figures reproduce the M.3 report: seed 0 = 32 / 88 façade partitions on a bay
line). Scripts live outside the repository.

### What the realiser does

* The module of the exact-plan engine is 0.10 m (`grid.module_mm = 100`, U-1); the 0.60 m cell is the stacking grid
  only. The bay lines (2.4 m = 24 modules for the bar, grid 7.2 x 7.2 m) are therefore a sparse lattice for the
  realiser: a partition is "on" when it lies within 3 modules of a line, so a random partition is on with probability
  about 0.25-0.30 (measured 35-40 %).
* A room bay gets one width: `Solver.room_bay_width` (target area / depth, rounded up, or the area-rule minimum for
  `needs_facade` rooms in an exterior block). The width does not depend on where the bay stands along the spine, so
  nothing ties partitions to the lattice. The band depth search (`D_A`) minimises (failures, no-façade, area
  deviation), not the lattice.
* The annealer (`ale.optimize`, not part of this ticket) realises through its own cache (`fastreal`), which calls
  `Solver.block` directly; the post-pass `snap.py` cannot move a wall because each neighbour is at the edge of its
  area window (M.3 report).

### Width windows

For a room of area `T` in a block of depth `D` the widths allowed by the area rule (-3 % / +max(3 %, 1.2 m²)), the
aspect limit and `wmin` form a window of 3 to 10 widths (0.3-1.0 m; bar floors, rooms of 12-150 m², depths 4-9 m;
median 4). Lattice lines are 24 modules apart, rooms are 25-60 modules wide: a room's two ends cannot both be on a line
unless the window contains a multiple of 24 plus or minus 6; most do not.

### Façade rows (maximal runs of rooms touching one exterior edge), bar, seeds 0-2

A small dynamic programme over the widths of each row (order fixed, windows of the real depth of each room, start
position fixed, last end free because the end strip absorbs it) gives, per row, whether an assignment exists with every
interior partition on a bay line, and the largest number of partitions that can be on a line:

| Seed | Rows | Rooms | Partitions (interior ends) | On a line now | Rows with all on a line at the current depth (free end / end fixed) | Max on a line, depth as now | Max on a line, depth free per row |
|---|---|---|---|---|---|---|---|
| 0 | 25 | 70 | 91 | 36 (40 %) | 8 / 5 | 50 (55 %) | 80 (88 %) |
| 1 | 26 | 61 | 85 | 37 (44 %) | 9 / 6 | 48 (56 %) | 62 (73 %) |
| 2 | 30 | 77 | 103 | 43 (42 %) | 10 / 5 | 56 (54 %) | 83 (81 %) |

Reading: with the depth the engine chose, only 8-10 rows of 25-30 can be fully on the lattice and 55 % of the
partitions at best; the width windows alone cannot reach 80 %. When the block depth is also chosen for the lattice
(a block has 40-150 admissible depths) 73-88 % is reachable if rows were independent. In the real plan the two blocks
of a piece share `D_A + s + D_B = P`, so that figure is an upper bound.

### Columns (M.3 M305)

Columns stand at 7.2 m spacing on both axes; 18-25 % of them fall inside rooms smaller than 30 m² and not on a wall.
A column line crossing a small room is avoidable only by moving the room's side onto it, i.e. the same width
decision as the partitions. The cost of a room is the number of column lines strictly inside it (more than 0.15 m from
its sides) times the number of cross lines inside its depth, for rooms below 30 m².

### Consequence

The realiser must choose, per block, widths inside the windows and the depth so that room ends fall on the lattice:
a DP over the bays (state = running position along the spine) with the lattice cost, evaluated at every admissible
depth, then the existing depth key with the lattice cost ahead of the area deviation. Where no lattice-friendly
assignment exists the old widths stay (counted). Because the annealer realises through `fastreal` (outside this
ticket's ownership) the hint is applied in a final realisation of the annealed plan, which keeps the annealer's
plan (room order, bands, fingers) and re-chooses depths and widths on the lattice.
