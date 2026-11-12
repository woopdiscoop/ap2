# Ticket M.1 · Evaluation report

Branch `worktree-agent-a017985ed8b259958` (based on `d3581dc`). Tests: `tests/stack/test_stack_m1.py`
(35 tests, synthetic data only, helper module `tests/stack/stack_case.py`).

## Results

| ID | Result | Evidence |
|---|---|---|
| M101 | PASS | `building.yaml` loads; French errors for non-contiguous levels, upper outline not inside the lower, core outside an outline, zero core, two cores (plus schema, shape, orthogonality, access edge); clockwise ground ring is reoriented with `access_edge` remapped. G.2's `parti_NN/building.yaml` (written by `ale parti`) loads for every parti of a 6-parti run. |
| M102 | PASS | Default groups = letters before the digits (`ACC SAL PRES DAP DGS DRH DFI DSI LOG SOC`); explicit `groups` override (id, spec id or prefix; longest entry wins); wet rooms (sanitary, cleaning_room, technical_room) excluded; each non-wet instance in exactly one group. |
| M103 | PASS | PRES, DAP, DGS on the top floor; ACC01/ACC02 (anchor entrance) on level 0; loads 102 % / 45 % / 45 % / 46 % (all <= 110 %); no group split in the synthetic case, split groups use contiguous floors in the forced-split test; two runs give the same assignment. |
| M104 | PASS | 10 random cases (<= 5 groups, <= 3 floors, <= 9 units, random pins / together / keep_whole): the stacking objective equals brute force; also 40/40 on a second seed. See "Spec issues" 3: plain greedy + local search alone was not enough, seeded perturbations were added. |
| M105 | PASS | Pins PRES, DAP, DGS, SAL, DFI on top: hard miss "Niveau 3 : charge ... manque N m²" with the shortfall, stacking and all outputs still produced, `ale stack` exits 1 with `MANQUE DUR :` lines, no traceback. |
| M106 | PASS | Core and wet-stack cells read back from each floor diagram's `CORE_CELL` cells are identical on the 4 floors (receding top floor offset by 10 cells handled); wet stack touches the core (3 cells or more of shared side, checked in metres with shapely) and lies inside the top outline; each wet room >= target; every occupied floor has >= 1 sanitary room; the no-fit case (wet demand far larger than the outline) is a reported hard miss, not a crash. |
| M107 | PASS | One diagram per floor; no room cell on core / wet cells; 0 fragmented rooms after repair; repaired rooms counted in `stacking.md` (equals the sum of `FloorResult.repaired`); facade-missing / off-circulation / short counts recomputed from the owner grid match. |
| M108 | PASS | `stacking.md` (French, all RD §7 items), `stack.svg` parses as XML, `floor_NN/site.yaml` loads as `SiteSpec` with two cores (`core`, `shaft`), `floor_NN/programme.xlsx` round-trips through `read_program` (per-spec quantities add up to the input programme, `floor` = level), `diagram.svg` parses; two runs byte-identical for every file (including the .xlsx, whose zip timestamps and `modified` stamp are normalised). |
| M109 | PASS | Hand-made 2-floor case: 2/6; 3-floor case: 4/8; the figure of the synthetic case equals an independent recount. |
| M110 | PASS | See gates. Synthetic case (4 floors, 40 room rows, ~100 instances): 0.9 s for `run_stack`. |

## Gates

| Gate | Result |
|---|---|
| `ruff check .` | clean |
| `ruff format --check .` | 314 files formatted |
| `mypy` (strict, 158 files) | no issues |
| `python -m ale.contracts.lock --check` | OK (no contract change) |
| `pytest tests/stack --cov=src/ale/stack` | 35 passed, coverage 98 % (assign 99, building 97, floors 99, report 96, rules 100, skeleton 99) |
| `pytest -m "not slow"` | 1489 passed, 11 skipped, 3 xfailed (pre-existing), 35 deselected; 523 s |

## Stacking table of the synthetic case

4 floors (R+3, 64.8 x 19.2 m, top floor 52.8 x 16.8 m receding on all four sides), core 28.8 m², wet stack 86.4 m²,
circulation share 25 %. Rules: PRES, DAP, DGS pinned to the top floor.

| Level | ACC | DAP | DFI | DGS | DRH | DSI | LOG | PRES | SAL | SOC | Total m² | Capacity m² | Load |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 3 | | 244 | | 248 | | | | 100 | | | 592 | 578.9 | 102 % |
| 2 | | | | | | 112 | | | 270 | | 382 | 846.7 | 45 % |
| 1 | | | | | 150 | | 160 | | | 74 | 384 | 846.7 | 45 % |
| 0 | 150 | | 236 | | | | | | | | 386 | 846.7 | 46 % |

No group split; stackability 18.8 % (share of room cells with a same-type room cell directly above or below;
low because the cell diagrams of different floors are independent: room stacking is M.3). Diagram metrics per floor
(facade missing / off circulation / short / repaired / fragmented): L0 0/3/0/1/0, L1 0/1/0/0/0, L2 0/1/0/0/0, L3 0/8/3/3/0.

## Spec issues (reading chosen)

1. **Floor-plate capacity vs. the load imbalance term.** The pins force 592 m² on the top floor, so the imbalance term
   cannot be reduced (45 % on the three other floors). Kept as specified; the term is soft.
2. **Wet stack sizing and capacity are circular** (capacity needs the wet area, the wet area needs the per-floor
   distribution, which needs the stacking). Resolved by iterating (at most 5 rounds, starting from 1.5 x mean wet
   demand) until the rectangle area stops changing; the report uses the capacities of the last round.
3. **"Local search must reach the brute-force optimum"**: best-improvement local search with group moves, group swaps,
   unit moves (RD) failed on over-constrained random cases (a 3-way rotation of units was needed). Added unit swaps,
   restarts from "all free units on floor f", and a fixed number of seeded perturbations (`random.Random(0)`, still
   deterministic). Reaches the optimum in 50/50 random small cases tested.
4. **Wet stack shape.** RD says "sized to the largest per-floor wet demand (+ one 0.60 m shaft strip)". I tile with
   strips of a fixed depth d (3.0 to 7.2 m); the shaft strip is the first strip, each room takes ceil(cells/d) strips;
   the rectangle is the smallest (area + 2 x elongation) that touches the core by >= 3 cells and lies inside the top
   outline (cell centres, 0.1 m margin). Leftover strips are `reserve_technique`. The stack is not drawn per room in
   `diagram.svg` (the whole rectangle is a hatched shaft cell block, as `SiteSpec.cores` says); wet rooms appear in
   `stacking.md`, `programme.xlsx` and the stackability figure.
5. **`floor_NN/programme.xlsx` holds all rooms of the floor, wet rooms included**, with `floor` set; the diagram
   programme excludes the wet rooms (they are inside the stack). Instance ids are renumbered per floor (`B01#1`...).
6. **Global 0.60 m grid.** Cells are indexed from the ground floor's minimum corner; a floor whose outline starts
   elsewhere gets an integer cell offset (rounded when the shift is not a multiple of 0.6 m, which G.2 outlines never
   produce) and the floor `site.yaml` core / shaft rectangles are expressed so that cellgrow rounds to the same global
   cells. The skeleton check reads the cells back from each diagram.
7. **Instance pins vs. group pins**: a per-room pin (anchor entrance, `floor > 0`) wins over a group pin, and the
   conflict is listed in the notes. Unknown groups in `pins` / `together` are ignored with a note, not an error. A
   `floor` beyond the top is clamped with a note.
8. **Exit codes of `ale stack`**: 0 = no hard miss; 1 = input error (nothing written) or any hard miss (outputs
   written); 2 = usage. Hard misses: floor > 110 % of capacity, skeleton mismatch / wet stack impossible, a floor
   whose diagram raised, fragmented rooms after repair.
9. **Rooms off circulation / short / facade-missing are reported, not hard misses** (U-15 sketch tolerance), unlike
   the stack-level capacity miss.
10. **`building.yaml` of G.2**: outlines are cut by the parti's slit (as `typical_floor_site(for_diagram=True)`) so they
    are hole-free; entrances are moved to the nearest point of the ground outline (plot entrances lie on the plot
    boundary); the core is `C1`. The one call is in `src/ale/cli/commands/parti.py` (`write_building`); `ale.parti`
    itself is untouched apart from the new module `building_export.py`.
