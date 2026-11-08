# 3.2 — Router notes

Status: BLOCKED on 3.1 and 0.3.
Output: initial `PolishExpression` (contract) + planarization conflict report.

## U-6 (2026-11-07)
Output is an initial `CorridorPlan` (contract A.1): zones → blocks ordered by the spring embedding along the spine axis; rooms → room bays or finger stacks by size vs block depth. Planarity diagnostic stays a report.

## Review log
- 2026-11-08 — 2ac54c3 (after a rate-limit interruption and resume): 21 tests, 97 % coverage. Accepted search extensions (fill-target scan, swap-phase cap for determinism, J1 junction shift), AVOID expansion over all instance pairs, networkx type: ignore. **DONE**.
