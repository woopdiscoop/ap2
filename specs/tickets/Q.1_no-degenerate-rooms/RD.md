# Ticket Q.1 — Realisation never emits rule-breaking room shapes · Requirements

> **Worker brief.** Context = this file, `eval.md`, the 3.3 specs (`specs/tickets/3.3_slicing-tree-realization/RD.md`,
> `RD_bands.md`), the contracts (1.2.0), and the code of `ale.geometry`, `ale.topology`, `ale.optimize`.
> Ownership: `src/ale/geometry/**`, `tests/geometry/**`, plus **only expectation updates** in `tests/topology/**`
> and `tests/optimize/**` when a number changes because of this ticket (report each one), and
> `src/ale/optimize/fastreal.py` only if needed to stay equivalent to `realize`.

## 1. Problem
When a room bay or a stack cannot satisfy the area rule, `amax` and `min_width`, 3.3 §5.2/§5.3 fall back to
shapes that break those hard rules (seen on P60: a 1.44 m² office, 8:1 rooms). The optimiser then has to fight
geometry that should never have been produced.

## 2. Change
- **Room bay**: if no width satisfies area rule + aspect + `wmin` at depth `D`, the block realisation fails with
  `ROOM_INFEASIBLE` (`detail: <instance_id> in piece p band b block X: no compliant width at depth D`).
- **Stack**: the solver searches every stack width in `[wmin_stack, 2·D]` and, for each, distributes heights so
  that **every** room satisfies area rule + aspect + `wmin` (heights may absorb slack up to each room's `hi`);
  rest → stack-end strip. If no width works → `STACK_INFEASIBLE` (`detail` lists the rooms).
- Depth search / band descent treat these as failures (same ordering key as other failures), so they pick depths
  that avoid them when possible.
- Consequence: a successful `realize` never yields `AREA_UNDER`, `AREA_OVER`, `ASPECT` or `MIN_WIDTH` violations.
- `greedy_plan`, `seed_plan` and `anneal` are unchanged in code; their behaviour adapts through failures.

## 3. Must still hold
3.3/3.3b eval (ported: E05 now expects `ROOM_INFEASIBLE` for the 6 m² room at D = 40), 3.2 T03–T05 (valid plans for
P8/P25/P60), 3.4 O03 (with whatever new hard counts result — report them).
