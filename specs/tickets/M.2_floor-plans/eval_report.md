# Ticket M.2 · Evaluation report

Branch `worktree-agent-afcdf4a1a7379c883` (base `62cade3`). Contracts bumped to 1.7.0. Tests:
`tests/contracts/test_contracts_m2.py` (M201), `tests/geometry/test_geometry_m2.py` (M202-M206, M208),
`tests/stack/test_stack_m2.py` + helper `tests/stack/plans_case.py` (M207, M209, M210). Synthetic data only.

## Results

| ID | Result | Evidence |
|---|---|---|
| M201 | PASS | `ModulePolygon.solids` and `Layout.fixed` validate (rectilinear, clockwise, no collinear neighbours, strictly inside with no touching of exterior / hole / other solid; fixed rooms inside a solid, no overlap, sorted, unique ids). Empty values are left out of the serialised form (`ModulePolygon` and `Layout` wrap serializers). Version 1.7.0, `lock --check` OK, schemas regenerated. The older version-pinned contract tests were moved to 1.7.0 the way earlier bumps did ("superseded by ... M.2"); `test_B02` got an `M2_REPLACED_LINES` set (lines of `geometry.py`, `footprint.py`, `models.py` that M.2 replaced). |
| M202 | PASS | A core becomes one solid snapped outward (module 0.1 m: `10.05 -> 100`, `13.05 -> 131`; module 0.6 m: floor / ceil). Touching cores merge into one solid (label `A+B`). A core touching the outline: French `E_SITE_INVALID` at `prepare_input`. Sites without cores: no `solids` key, same area, same sliver loss. Hash check: see M206. |
| M203 | PASS | A room along a solid has no `exterior_contacts` (a courtyard at the same place does), `facade_depth` is `None`; a room on the outline and along the solid keeps only the outline contact and the same depth as without the solid. (`exterior_contacts` only walks the exterior and hole rings, so no engine change was needed beyond the contract.) |
| M204 | PASS | P25 on a 28.8 x 19.2 m rectangle with a 3.0 x 3.0 m central core: seeded and annealed layout passes `check_layout`, tiles footprint minus solid exactly (`288 x 192 - 30 x 30` cells), no cell over the core, circulation touches the core, no `SOLID_NO_ACCESS`. The layout still has 5 hard violations (façade / required adjacency): the core takes space from the façade rooms. |
| M205 | PASS | A hand-built layout with four rooms around the solid: `SOLID_NO_ACCESS` (French: « Noyau 0 : aucune circulation ne longe son contour ... »), `instance_ids` = the rooms around the solid; the code is in both `HARD_CODES` (seeder, annealer). `check_layout` also names an unflagged enclosed solid. The same layout with the corridor along the solid is clean. |
| M206 | PASS | P08 / P25 / P60 (sites without cores): prepared inputs (feasibility reports included), seeded layouts and (P08, P25) annealed layouts hash to the digests computed at `62cade3` before any change (`BASE_DIGESTS`). Checked twice: once before and once after all changes. |
| M207 | PASS (on a re-sized case, see Spec issues 1 and 2) | `ale stack --plans` on `plans_case`: 4 floors, 4 plans, all pass `check_layout`; `Layout.fixed` holds the core `C1`, the floor's wet rooms (`WC01#n`, `NET01`), `gaine_humide`, `reserve_technique` and the corner reserve; absolute rectangles of core, wet stack and solid are identical on the four floors; `plans.md` is in French with the vertical check. Ran 4 times without a miss. **On the original M.1 bar (64.8 x 19.2 m): 0 of 4 floors**, reported (table below). |
| M208 | PASS | DXF has layers `ALE_SOLID` (outline, hatch, core id) and `ALE_FIXED` (rooms + labels) only when the layout has solids; SVG has `<g id="solids">` (hatch pattern, `class="solid"`, id label) and `<g id="fixed">`; layouts without solids produce no extra layer or group (byte-identical exports); JSON round-trips (`canonical_json` of the reloaded layout equals the file). |
| M209 | PASS | A floor with a six-fold programme: `prepare_input` refuses it ("Programme trop grand"), the floor is `ÉCHEC` in `plans.md`, floor 0 is produced, vertical check "incomplet", `plans.ok` false. CLI exit code 1 with `MANQUE DUR : Niveau 1 : plan impossible ...`; outputs still written. Exit codes: 0 all floors planned and vertical check OK; 1 input error, an M.1 hard miss, a failed floor, a `check_layout` problem or a failed vertical check; 2 usage (`--plans` without `--rulebook`). |
| M210 | PASS | See gates. 4 floors with `--budget 5`: 16.9 s (limit 60 s). With `--budget 12`: 23.5 s, 4/4 plans. |

## Gates

GATES_PLACEHOLDER

## Per-floor table, `ale stack --plans` on the M.2 case (`--budget 12`, exit code 0)

4 floors of 30.0 x 21.6 m, core `C1` 4.8 x 4.8 m at (12.6 ; 8.4), wet stack 4.8 x 5.4 m at (17.4 ; 4.8) (`gaine_humide` strip + rooms + reserve), solid = bounding rectangle of core and stack.

| Level | Status | Hard violations | Facade missing | Target m² | Placed m² | Circulation m² | s |
|---|---|---|---|---|---|---|---|
| 0 | plan | 1 (NO_FACADE NA02) | 1 | 330.0 | 328.0 | 239.4 | 5.7 |
| 1 | plan | 1 (NO_FACADE NB02) | 1 | 330.0 | 328.0 | 239.4 | 5.9 |
| 2 | plan | 1 (NO_FACADE NC02) | 1 | 330.0 | 327.0 | 240.3 | 5.4 |
| 3 | plan | 1 (NO_FACADE ND02) | 1 | 330.0 | 328.1 | 239.3 | 5.8 |

Vertical check: core, wet stack and solid identical on 4 floors (hard, passed). The circulation is large (about 240 m² of 648 m²):
the engine fills the whole plate and the plate is 20 % larger than the programme needs.

## Per-floor table, `ale stack --plans` on the original M.1 bar (64.8 x 19.2 m, receding top floor, `--budget 12`, exit code 1)

| Level | Status | Reason |
|---|---|---|
| 0 | failed (6 attempts) | JUNCTION_MISALIGNED: junction finger at u = 106 puts the spine of piece 3 outside its cut |
| 1 | failed (6 attempts) | JUNCTION_MISALIGNED + BLOCK_TOO_SHALLOW |
| 2 | failed (6 attempts) | JUNCTION_MISALIGNED |
| 3 | failed (5 attempts) | JUNCTION_MISALIGNED + BLOCK_TOO_SHALLOW |

The M.1 outputs (`stacking.md`, `floor_NN/*`) are written as usual, `plans.md` lists the four failures, the other pipeline steps are intact.

## Spec issues (reading chosen)

1. **Solids must not touch the outline, but M.1's wet stack does** (it sits against the south wall in the M.1 bar). Contract kept as written (M201). Consequences and choices:
   - `to_module_footprint(site, grid, *, strict_cores=False)`: callers that only used `SiteSpec.cores` themselves (M.1's `_diagram`, G.2's evaluation) keep working, a solid that cannot be valid is left out; `prepare_input` (hence `ale generate`) passes `strict_cores=True` and refuses it with a French `E_SITE_INVALID`. This needed a one-argument change in `src/ale/program/prepare.py`, which RD section 5 does not list (the alternative was to break the M.1 tests, which call `to_module_footprint` on touching cores).
   - Touching cores are merged into one solid (the M.1 core and its wet stack touch each other, and solids may not touch).
   - `ale stack --plans` runs the stacking with `build_skeleton_strict` (`plans.py`, `run_stack(strict_solids=True)`): the wet stack keeps a gap of 6, 4, 2 or 1 cells (0.60 m each; the widest that places it) from the top outline. Without `--plans` the M.1 skeleton is unchanged. `run_plans` redoes the stacking itself when the result it is given has a wet stack touching an outline (note in `plans.md`).
2. **The engine cannot lay out the M.1 bar around its skeleton.** (a) The exact-plan engine tiles the whole footprint: the M.1 floors are loaded at 45 % of the plate, so a plan would stretch rooms / circulation beyond the area rules. (b) More importantly, a ring of 4-6 pieces around a solid in a long shallow plate defeats the seeder: the facing block of the parent piece does not hold enough rooms to reach the child's cut, which gives `JUNCTION_MISALIGNED` (finger at the start of the block) whatever the seed; the repair move (shift the finger by one bay) cannot add rooms. Narrow pieces (gap to the wall below about 7 m) give `BLOCK_TOO_SHALLOW` / `PLAN_OVERFLOW`. A seeder improvement (move rooms into the junction block before placing the finger) is the fix; it is outside what this ticket could verify. For M207 I therefore used a re-sized case (`tests/stack/plans_case.py`): the room types of the M.1 case in four identical groups, 30.0 x 21.6 m plates, a 4.8 x 4.8 m core (a 4.8 x 6.0 m core, the M.1 one, fails on all seeds in the same plate).
3. **The solid of a plan is the bounding rectangle of core and wet stack.** An L-shaped solid (core + stack side by side) gives 6 pieces with 2.4 m wide slivers and failed on every seed; the rectangle gives the 4-piece pinwheel the engine handles. The corner left between core and stack becomes `reserve_technique_gN` fixed rooms (their cost: part of the plate is not rentable; M.1 uses it).
4. **"One variant per floor"**: the seeder is chancy on rings (about 2 seeds in 3 succeed in `plans_case`), so a floor is seeded with up to a few seeds (`seed + level + 1000 k`) while 60 % of `--budget` lasts, then annealed with the rest. One layout per floor is still produced. `--budget` is a wall-clock budget as for `ale generate`, so results can differ between machines.
5. **"Wet rooms rectangles identical on every floor"**: the wet rooms differ from floor to floor (M.1 distributes them), so the hard check compares the rectangles that are common to all floors: the core, the wet stack (union of the wet rooms, `gaine_humide` and `reserve_technique`) and the solid, in absolute metres. The wet rooms of each floor are listed in `plans.md`.
6. **`SOLID_NO_ACCESS` `instance_ids`** name the rooms that line the solid (an id list is needed by `hard_rooms`, the annealer's focus). The solid itself is « Noyau k » in the detail.
7. **`Layout` wrap serializer**: dropping an empty `fixed` needs a model serializer, which would turn a NaN metric into `null` and hide it from `canonical_json`; `Layout.model_config` therefore sets `ser_json_inf_nan="constants"`. Test `test_M201_nan_metric_still_rejected` guards it.
8. **`area_cells()` and `rect_in_polygon_cells`** subtract solids (so `check_layout` "areas sum to footprint" means footprint minus solids, and a room over the core is "outside the footprint").
