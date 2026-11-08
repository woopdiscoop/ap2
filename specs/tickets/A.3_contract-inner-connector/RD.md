# Ticket A.3 — Contract amendment: inner connector · Requirements

> **Worker brief.** Context = this file, `eval.md`, `src/ale/contracts/` (read the `corridor_plan.py` docstring).
> Ownership: `src/ale/contracts/corridor_plan.py`, `version.py` → `"1.3.0"`, regenerated schemas and lock (LAST),
> `tests/contracts/test_corridor_plan.py`, `specs/tickets/A.3_contract-inner-connector/eval_report.md`.
> Backward compatible: every existing plan stays valid and means the same.

## 1. Why
A connector at a piece end (`start`/`end`) sits on the exterior wall and wastes ~one piece depth of façade. An
**inner** connector crosses the piece somewhere inside its length.

## 2. Model
- `PiecePlan.connector` gains the value `"inner"`.
- New bay kind `ConnectorBay(kind: Literal["connector"] = "connector")` added to the `Bay` discriminated union.
- Rules (model validators): a `ConnectorBay` may only appear in a piece whose connector is `"inner"`; when the
  connector is `"inner"`, **every** block of every band of that piece contains **exactly one** `ConnectorBay`
  (an otherwise empty block holds just the marker); `"inner"` requires ≥ 2 bands.
- Meaning (add to the docstring): with `"inner"`, the connector is a corridor strip of width `s` spanning the full
  piece depth at a position `u_c` chosen by realisation; in each block, bays listed before the marker lie at
  `u < u_c`, those after at `u ≥ u_c + s`; band spines cross the connector and run the full piece length.
- `room_ids`, `locate` skip markers (bay indices count markers so `locate(...).bay` still indexes `bays`).
  `zone_violations`: a marker splits a block into two runs for contiguity purposes (a zone may appear once on each side).
- `check_against`: J2 rules that require the primary's (or secondary's) connector on the cut side are satisfied
  only by `start`/`end` as before; `"inner"` is allowed for pieces where no cut-side connector is required.
