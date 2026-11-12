# Ticket M.3 — Room stacking, shared bay rhythm, column grid · Requirements

> Context = this file, `eval.md`, M.1 (`ale.stack`, `stackability`), M.2 and M.2b eval reports (per-floor plans
> inside the skeleton, the loaded bar case `tests/stack/bar_case.py`), contracts 1.7.0. User decisions U-10
> (stackability first: same shafts and wet stacks, same rooms stacked, regular structure), U-15 (sketch tolerance),
> U-16 (strong parti that solves several problems at once). **No contract changes.**

## 1. Purpose
M.1 fixes the core and the wet stack, but the other rooms of floor k are laid out independently of floor k−1:
stackability is 18.8 % on the M.1 case, partitions do not line up and there is no structure. M.3 makes a building read
as one building: **a typical floor** whose rooms repeat vertically, **one bay module** shared by every floor's façade
partitions, and **one column grid** that is the same on every floor and fits the plans.

## 2. Parti (strong, U-16)
One decision should drive all three: choose the column grid and the bay module first (both multiples of 0.60 m, the
bay dividing the span), then lay out floors **from the most loaded floor down and up**, each floor using the floor
already laid out as a prior (same cells for the same room group where the programme allows; corridors in the same
place). Partitions on the façade snap to bay lines; columns sit on partitions, corridor edges or inside large rooms.
Prefer this over a post-hoc repair. Do the diagnosis first: measure why the current pipeline does not stack (cell
level and exact plans), record it in `eval_report.md` § Diagnosis, commit, then change code.

## 3. Changes
- `src/ale/stack/**`: grid and bay choice (`grid.py` or in `skeleton.py`), floor ordering + prior, stacking metrics at
  cell and plan level, report section, SVG overlay of the grid.
- Optional overrides in the stacking rules YAML: `bay_m`, `grid_m: [sx, sy]`, `typical_floor: <level>`. Invalid values
  → French error, never a crash.
- `src/ale/topology/cellgrow.py`: an optional prior argument (cells → group) that biases growth; **with no prior the
  output must be byte-identical** to today.
- `src/ale/topology/**`, `src/ale/geometry/**` only if needed to reuse a floor's corridor plan or snap partitions;
  every call path outside `ale stack` stays byte-identical (M206 digests).
- Defaults: span candidates 5.40–9.00 m, bay candidates 2.40–4.80 m dividing the span; choose by a stated score
  (columns in small rooms, partitions off bay, façade rooms lost), ties to the larger span.

## 4. Files (ownership)
`src/ale/stack/**`, `src/ale/topology/**` and `src/ale/geometry/**` under the byte-identity rule above,
`tests/stack/**`, `tests/topology/test_topology_m3.py`, `specs/tickets/M.3_stacking-rhythm/eval_report.md`.
Do not modify `src/ale/contracts/**`, `src/ale/export/**`, the CLI registration file. Test helpers must not be
imported as `conftest`. Never weaken a test. Commit early and often.
