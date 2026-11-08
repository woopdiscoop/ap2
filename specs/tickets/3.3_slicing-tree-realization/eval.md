# Ticket 3.3 — Grammar Realisation · Evaluation

Every ID is a named pytest test under `tests/geometry/`. Exact values were computed by the Router with an
independent implementation of RD §5. Default `AleConfig` (0.10 m module → s = c = 12, f = 24) unless stated.

## 0. Harness

pytest-timeout 60 s/test. Tests build `PreparedInput` objects directly (module footprint + instances) or via
`prepare_input` on the fixtures with `tests/program/data/rulebook_test.yaml`. Whole repo suite passes;
`lock --check` passes.

## 1. Exact cases

| ID | Test | Pass condition |
|---|---|---|
| E01 | single_room_bay | Rectangular footprint 60 × 52 modules (spine axis X). Plan: block A empty, block B = [room bay `r1` (12 m², no min width)]. → depths (0, 40); spine `(0,0,60,12)`; `r1 = (0,12,30,40)`; end strip `(30,12,30,40)`; 2 circulation rects; 0 failures; `check_layout` empty. |
| E02 | finger_bay | Footprint 110 × 52. Block A empty; block B = [room bay `r1` 12 m², finger bay left = (`r2` 6 m², `r3` 6 m²), right = (`r4` 12 m²)]. → `r1 (0,12,30,40)`, `r2 (30,12,30,20)`, `r3 (30,32,30,20)`, `r4 (72,12,30,40)`; circulation: spine `(0,0,110,12)`, finger `(60,12,12,40)`, end strip `(102,12,8,40)`. Stack width chosen 30 (left) and 30 (right). |
| E03 | overflow | E02 on a 100 × 52 footprint → `layout is None`, one failure `PLAN_OVERFLOW` with detail mentioning `over by 2`. |
| E04 | axis_Y | E01 rotated: footprint 52 × 60 (spine axis Y) → same rooms with x/y swapped: `r1 = (12,0,40,30)`, spine `(0,0,12,60)`. |
| E05 | room_bay_rules | Room bay at D = 40: a 12 m² room → w = 30 (12.00 m², aspect 1.33). A 6 m² room (no min width) → no width meets both area rule and aspect (w ≥ 20 needed for 2:1 → 8.00 m² > 7.20 m²; none in [5.82, 6.00)), so the last fallback gives w = 15 (6.00 m², aspect 2.67) and `evaluate` reports an `ASPECT` violation for it. |
| E06 | plan_invalid | Plan missing one program room → `PLAN_INVALID`, no geometry. |

## 2. Inverse generation (property tests, Hypothesis, `max_examples=150`, `derandomize=True`)

A test generator builds a **valid grammar layout first** — random rectangular footprint (L 80–400, P 60–200),
random block depths, random bays (room bays and finger bays with 1–3-room stacks, all sizes ≥ 12, aspect ≤ 2),
end strip ≥ 0 — then derives the program from it: each room's target = its realised area exactly.

| ID | Test | Pass condition |
|---|---|---|
| G01 | realizable | `realize` succeeds (0 failures) for every generated case. |
| G02 | invariants | `check_layout` returns `()` for every case. |
| G03 | zero_overshoot | Every room's placed area equals its target (the original geometry is reachable and optimal). |
| G04 | L_shapes | Same with L footprints (both J1 and J2 generated): G01–G03 hold, and the secondary spine shares ≥ s with the primary spine (J2) or with the junction finger (J1). |

## 3. Fixtures, robustness, evaluation

| ID | Test | Pass condition |
|---|---|---|
| R01 | fixtures_never_raise | `greedy_plan` + `realize` for P8/site_rect_small, P25/site_rect, P60/site_L: never raises; result is either a layout with `check_layout == ()` or failures only from {`PLAN_OVERFLOW`, `JUNCTION_MISALIGNED`}. |
| R02 | random_plans_never_raise | 200 random valid plans (random room placement, seeded) on P25/site_rect: never raises; every success passes `check_layout`. |
| R03 | deterministic | Same inputs twice (fresh processes) → identical `canonical_json(layout)`. |
| R04 | performance | P60 realisation (greedy plan) ≤ 1.0 s. |
| V01 | violations | A layout where a `needs_facade` room is an inner stack room → `NO_FACADE`; REQUIRED pair placed apart → `REQUIRED_ADJ`; AVOID pair touching → `AVOID_ADJ`; a plan with a split zone → `ZONE_SPLIT`. |
| V02 | cost_terms | On E02 with a hand-made rulebook (`p(office, meeting_room) = 0.9`, all orientation weights S = 1.0, core offset 0/0): each `cost_breakdown` term equals the value recomputed in the test from RD §6 (tolerance 1e-9); `total_cost` = Σ weight × term. |
| V03 | circulation_budget | `circulation_length` = 0 when circulation ≤ budget; positive and exact otherwise. |

## 4. Static gates

ruff, ruff format, mypy strict clean · coverage of `ale.geometry` ≥ 90 % line / 80 % branch · `lock --check` · ownership (RD §2 only).
