# Ticket M.3 · Evaluation report (WIP)

## Diagnosis (M301)

Measured at `e03a2a3` before any code change (scripts outside the repository; bar = `tests/stack/bar_case.py`,
`--plans --budget 10`, seed 0, 80 s wall clock for 4 floors).

### Cell level (`stackability`, M.1 definition)

| Case | Stackability | Upper bound for the same assignment | Wet cells (always stacked) |
|---|---|---|---|
| M.1 case (pins PRES, DAP, DGS on top) | 18.75 % | 27.7 % | 696 of 5471 (12.7 %) |
| Loaded bar (x 1.7, no pins) | 29.9 % | 71.8 % | 696 of 9016 (7.7 %) |

The bound is `sum over floors and types of min(area of the type on floor k, area of the type on floors k-1 and k+1)`
divided by all room cells: no cell layout can exceed it. Two causes:

1. **The cell diagrams of different floors are independent.** `cellgrow.grow` is run per floor with the same seed but a
   different programme, a different outline (floor 3 recedes) and a different footprint, so a type that exists on two
   floors lands in unrelated cells (M.1: 18.75 % against a bound of 27.7 %, bar: 29.9 % against 71.8 %).
2. **The assignment (`assign.py`) groups by entity code and ignores room types.** Floor type mixes of the M.1 case:
   L0 office 329 / open_office 267 / entrance_hall 222 / sanitary 144 ...; L1 archive 305 / storage 167 / office 264 ...;
   L2 multipurpose 417 / training 333 / office 198 ...; L3 office 739 / open_office 500 / meeting 345 ... Most large types
   exist on one floor only (archive, multipurpose, training, entrance hall), so the bound itself is 27.7 %.

### Plan level (exact plans, bar, `--plans`)

Share of a floor's room area (rooms + fixed rooms with a type) whose type equals the type at the same module directly
below (absolute coordinates, floor 3 recedes):

| Floor | Plan-level stackability |
|---|---|
| 1 | 10.0 % |
| 2 | 32.6 % |
| 3 | 46.8 % |
| mean 1-3 | 29.8 % |

Cause: `plans._generate_floor` calls `seed_plan` with the default spring seeder (`embed`), a seeded force layout that
knows nothing of the other floors, then anneals independently; the order of the rooms along the bands and the band
structure differ from floor to floor, and `cellgrow` is not even used (`seeder="spring"`).

### Rhythm

Façade partition positions (a room edge ending inside an exterior edge, both rooms counted; 134 on the 4 floors) within
0.30 m of a bay line (lines `x0 + n b`, `y0 + n b`, origin = ground floor corner):

| bay b (m) | 2.4 | 3.0 | 3.6 | 4.2 | 4.8 |
|---|---|---|---|---|---|
| share on a bay line | 35.1 % | 21.6 % | 12.7 % | 16.4 % | 11.9 % |

Cause: room widths on the façade come from `area / depth` rounded to the 0.60 m module; nothing ties them to a common
module. There is no column grid at all (no code, no output); the core (24.0 ; 3.6) of the bar and the wet stack are the
only fixed elements.

### Consequence for the targets
M302 (>= 60 % on the M.1 case) cannot be reached by a better cell layout alone (bound 27.7 %); it needs a type-aware
assignment. M303 (>= 50 % at plan level) needs the floors to share their band structure and room order.
