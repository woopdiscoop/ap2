# Ticket M.3b — Bay-aware realisation: partitions on bay lines, columns on walls · Requirements

> Context = this file, `eval.md`, M.3 eval report (§ Why not reached, spec issues), `src/ale/stack/grid.py`,
> `snap.py`, `src/ale/geometry/blocks.py` (realiser), contracts 1.7.0. User decisions U-10, U-15, U-16.
> **No contract changes.**

## 1. Purpose
M.3 chose one column grid and one bay module per building, but the realiser sets room widths without them: 33–42 %
of façade partitions fall on a bay line (target 80 %) and 18–25 % of columns land inside rooms < 30 m² (target
≤ 10 %). The post-pass snap moved 0 walls because every move pushes a neighbour out of its area tolerance. M.3b
moves the decision into the realiser: when a bay module is given, row widths are chosen **inside each room's
width window** so that cumulative partition positions fall on bay lines, preferring column lines; residual error is
absorbed by rooms with the widest tolerance (open plan, corridors ends, reserves), within U-15 sketch tolerance.

## 2. Diagnosis first
For the bar case, list per floor the façade rows, each room's width window and the bay lines, and show whether an
all-on-bay assignment exists per row (small DP). Write it in `eval_report.md` § Diagnosis, commit, then code.

## 3. Changes
- `src/ale/geometry/**` (realiser): an optional bay/grid hint (module, origin, column lines). With no hint, output is
  **byte-identical** (M206 digests, every call path outside `ale stack`). Row width choice by DP / exact search over
  bay multiples inside the windows; fall back to today's choice when infeasible, and count it.
- `src/ale/topology/**` only to pass the hint through, same byte-identity rule.
- `src/ale/stack/**`: pass the M.3 grid to the realiser; drop or keep `snap.py` as a fallback; report numbers.

## 4. Files (ownership)
`src/ale/geometry/**`, `src/ale/topology/**`, `src/ale/stack/**`, `src/ale/cli/commands/stack.py`, `tests/geometry/test_geometry_m3b.py`,
`tests/stack/**`, `specs/tickets/M.3b_bay-realizer/eval_report.md`. No `src/ale/contracts/**`, no export, no CLI
registration file. Test helpers not imported as `conftest`. Never weaken a test (M.3's non-strict xfails may be
turned into passing tests). Commit early and often.
