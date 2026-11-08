# Ticket 3.3 — Grammar Realisation · Requirements Document

> **Worker brief.** Context = this file, `eval.md`, the frozen contracts (`src/ale/contracts/`, version
> 1.1.0 — read the module docstring of `corridor_plan.py` first: it defines the corridor grammar), and the
> public interfaces of `ale.program` (`PreparedInput`, `ModuleFootprint`), `ale.config`, `ale.guards`,
> and the test helpers in `tests/conftest.py`, `tests/fixtures/`, `tests/program/program_helpers.py`.
> Do not modify contracts (`lock --check` must pass) or other tickets' files.

## 1. Purpose

Turn a `CorridorPlan` (which room goes where in the grammar) into an exact integer-module `Layout`
(contract), and score it. This is the geometry engine Ticket 3.4 calls after every optimiser move, so it
must be **deterministic, exact and fast**.

## 2. Files

```
src/ale/geometry/__init__.py
src/ale/geometry/realize.py      # realize(...) → Realization
src/ale/geometry/blocks.py       # room-bay widths, stack solving, block layout
src/ale/geometry/junction.py     # L-shape J1/J2 alignment
src/ale/geometry/evaluate.py     # evaluate(...) → LayoutMetrics (cost function, violations)
src/ale/geometry/checks.py       # geometric invariant checks (§7), usable by tests and 3.4
src/ale/geometry/greedy.py       # greedy_plan(...) → CorridorPlan (simple baseline)
tests/geometry/**
specs/tickets/3.3_slicing-tree-realization/eval_report.md
```

## 3. Public API

```python
class Failure(BaseModel, frozen=True):  code: str; detail: str
class Realization(BaseModel, frozen=True):
    layout: Layout | None                 # None iff failures is non-empty
    failures: tuple[Failure, ...]
    depths: tuple[tuple[int, int], ...]   # (D_A, D_B) per piece, as chosen

def realize(prepared: PreparedInput, plan: CorridorPlan, rulebook: Rulebook,
            config: AleConfig, *, seed: int = 0) -> Realization
def evaluate(layout: Layout, prepared: PreparedInput, rulebook: Rulebook,
             config: AleConfig, plan: CorridorPlan | None = None) -> LayoutMetrics
def check_layout(layout: Layout, prepared: PreparedInput, config: AleConfig) -> tuple[str, ...]   # §7 invariants, () if all hold
def greedy_plan(prepared: PreparedInput, rulebook: Rulebook, config: AleConfig) -> CorridorPlan
```
`realize` never raises for a valid plan: problems become `failures`. `Layout.metrics` is filled by
`evaluate`. `Layout.seed = seed`, `rulebook_version = prepared.rulebook_version`, `residue = ()`.

## 4. Constants (from `AleConfig`, in modules; `m = grid.module_mm`)

`s = ceil(circulation.min_width_m·1000 / m)` (spine/finger width, 12 at 0.10 m) ·
`c = ceil(circulation.min_door_edge_m·1000 / m)` (min corridor contact = min room side touching it, 12) ·
`amax = shape.aspect_max` (2.0) · `f = ceil(facade.min_facade_len_m·1000 / m)` (24) · area tolerance from `[area]`.
For a room: `T` = target in cells (m² × 10⁶ / m², exact), bounds `[lo, hi] = area_bounds_mm2(T)` converted to
cells (lo rounded up, hi down), `wmin = max(c, ceil(min_width_m·1000/m))`.

## 5. Realisation algorithm

Work in each piece's local frame: `u` along the spine (length `L`), `v` across (depth `P`), origin at the
piece's min corner; block A occupies `v ∈ [0, D_A)`, the spine `[D_A, D_A+s)`, block B `[D_A+s, P)`.
Convert to footprint coordinates at the end (spine axis X: `x = u, y = v`; axis Y: `x = v, y = u`).

### 5.1 Block depths
- Empty block → depth 0 (spine against that side). Both empty → the piece is spine + one end strip.
- Otherwise search `D_A` over every integer in `[wmin_block, P − s − wmin_block]` (wmin_block = smallest room
  `wmin` in that block), realise both blocks for each, and keep the depth with the lowest
  `(n_failures, Σ overshoot cells + Σ circulation strip cells, |D_A − D_B|, D_A)`. Wrap the loop in
  `ale.guards.bounded(max_iter=P + 1, time_budget_s=5.0, label="depth-search")`.

### 5.2 Room bay (depth D)
Width `w` = smallest integer `w ≥ wmin` with `w·D ≥ T`, `w·D ≤ hi`, `max(w,D)/min(w,D) ≤ amax`. If none: take
the largest `w ≥ wmin` with `lo ≤ w·D < T` and aspect OK; if still none → `w = max(wmin, ceil(T / D))`
and the evaluator will report the violations (area / aspect). `D < wmin` also yields `MIN_WIDTH`.

### 5.3 Stack (rooms `r_1…r_k` from the spine outward, depth D)
For each candidate stack width `w_s` in `[wmin_stack, 2·D]` (wmin_stack = max `wmin` of its rooms):
1. `h_i` = smallest integer `≥ c` with `w_s·h_i ≥ T_i`; raise `h_i` while the aspect exceeds `amax` and
   `w_s·(h_i+1) ≤ hi_i`. If the aspect still exceeds `amax` or `w_s·h_i > hi_i` → candidate rejected.
2. `R = D − Σ h_i`; `R < 0` → rejected.
3. Distribute `R` from the **outermost** room inward: raise each `h_i` one cell at a time while
   `w_s·(h_i+1) ≤ hi_i` and the aspect stays `≤ amax`. Any rest becomes a **stack-end strip** (circulation,
   `w_s × R_rest`, at the outer end of the stack, touching the finger).
Choose the candidate minimising `(Σ (w_s·h_i − T_i) + w_s·R_rest, |w_s − ΣT_i / D|, w_s)`. No candidate →
use `w_s = wmin_stack`, `h_i` proportional, and let the evaluator report violations.

### 5.4 Block layout
Bays in plan order from `u = 0`: room bay = `w`; finger bay = `w_left + s + w_right` (an empty stack has
width 0). Rooms span the block depth; the finger spans the block depth at `u ∈ [u0 + w_left, u0 + w_left + s)`.
`E = L − Σ widths`: `E > 0` → **end strip** (circulation) `[L−E, L) × block`; `E < 0` → failure `PLAN_OVERFLOW`
with detail `piece p block X over by E modules`.

### 5.5 L shapes (`FootprintPieces` from `decompose_footprint(prepared.footprint.polygon)`)
- **J2** (collinear spines): the secondary's spine occupies the same absolute band across the spine as the
  primary's. Search the primary's `D_A` as in 5.1; the secondary's `D_A` follows. Skip values for which
  the secondary's band does not fit inside its piece.
- **J1** (junction finger): realise the primary first; the junction finger in the primary's
  `facing_block` fixes an absolute band along the primary spine, which becomes the secondary spine's band.
  If that band does not fit inside the secondary piece → failure `JUNCTION_MISALIGNED`.
- The primary's search includes the secondary's cost (joint minimisation).

### 5.6 Output
Rooms → `PlacedRoom(instance_id, spec_id, rect, target_area_m2)`. Circulation → `PlacedRoom(instance_id=
"circ-NNN", spec_id=None, …)`, numbered in this order: per piece (primary first) spine, then block A then B,
fingers and strips in `u` order. Both tuples sorted by `instance_id` (contract rule).
Plan problems (`plan.check_against(...)` non-empty) → failure `PLAN_INVALID` (no geometry).

## 6. Evaluation (`evaluate`) — cost and violations

"Share length" = length of the common boundary of two rectangles (integer modules).
Terms (each a float; `cost_breakdown` keys = `[optimizer.weights]` names; `total_cost = Σ weight × term`):

| Term | Definition |
|---|---|
| `required_adjacency` | (# REQUIRED instance pairs not sharing ≥ c) + (# AVOID pairs sharing ≥ 1). REQUIRED A→B with quantities: each instance of A must share ≥ c with **some** instance of B. |
| `rulebook_adjacency` | Σ over unordered room pairs sharing ≥ 1 of `(0.5 − p(type_a, type_b))`, divided by the number of rooms. |
| `aspect` | Σ over rooms of `max(0, a − p90) + max(0, p10 − a)` (band from rulebook type, clipped to `[1, amax]`), divided by the number of rooms. |
| `area_overshoot` | Σ max(0, placed − target) m² / Σ target m². |
| `facade_orientation` | − Σ over rooms touching the exterior of the orientation weight of their longest exterior contact (bearing via `compass_bearing_deg`/`bearing_bin`, `site.north_angle_deg`; weights = `orientation_override` or rulebook type), divided by the number of rooms. |
| `core_distance` | mean over `service_core` rooms of the distance from the room centre to the core target, divided by the footprint bounding-box diagonal. Core target = `site.core_hint` (converted to modules) if set, else bbox centre + `(dx_norm·W, dy_norm·H)` from the rulebook. |
| `circulation_length` | `max(0, circulation_area / (Σ net × circulation.ratio) − 1)`. |

**Violations** (`Violation(code, instance_ids, detail)`): `AREA_UNDER`, `AREA_OVER` (outside the area rule),
`ASPECT` (> amax), `MIN_WIDTH`, `NO_CIRCULATION_ACCESS` (no circulation share ≥ c), `NO_FACADE`
(`needs_facade` and exterior share < f), `REQUIRED_ADJ`, `AVOID_ADJ`, `ZONE_SPLIT` (from
`plan.zone_violations`, only if `plan` is given). Sorted by (code, instance_ids).
Also fill `total_overshoot_m2`, `circulation_area_m2`, `residue_area_m2 = 0.0`.

## 7. Invariants (`check_layout`) — must hold for every successful realisation

1. All coordinates and sizes are ints; every rectangle lies inside the module footprint.
2. Pairwise overlap between all rectangles (rooms and circulation) is 0 cells.
3. Σ areas of rooms + circulation == module footprint area (exact).
4. Every room shares ≥ c with circulation.
5. Circulation rectangles form one connected component (adjacency = share ≥ 1).
6. Every room has aspect ≤ amax **or** an `ASPECT` violation; area within the rule **or** an `AREA_*` violation.

## 8. `greedy_plan` (baseline, not optimised)

Deterministic: one block per macro-zone run, zones in the order PUBLIC, ADMINISTRATIVE, SERVICES; rooms sorted by
descending target; rooms whose target is below `0.5 × D_est²` (D_est = (P − s) / 2) go into finger-bay stacks
(two rooms per stack, filled left then right), others into room bays; blocks filled A then B, piece by piece;
for J1 a junction finger is inserted in the facing block. It may overflow — that is fine; 3.2 and 3.4 do better.

## 9. Performance & determinism

`realize` for the P60 fixture with any plan: ≤ 1.0 s on one CI core. Same inputs → identical `canonical_json(layout)`.
No randomness is used (`seed` is only recorded).

## 10. Out of scope

Choosing good plans (3.2, 3.4), export (3.5), non-rectilinear or > 2-piece footprints.
