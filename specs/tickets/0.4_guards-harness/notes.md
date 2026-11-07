# 0.4 — Router notes

Status: BLOCKED on 0.1 (pyproject, pytest config) and 0.2 (fixtures are `Program`/`SiteSpec` instances).

To specify:
- `ale.guards.bounded(max_iter, time_budget_s)` (context manager / iterator), `ConvergenceError(state_snapshot)`; must work on Windows (no SIGALRM — use monotonic-clock checks inside the loop).
- Subprocess runner with timeout + captured exit report (used by 1.2 for ODA / accoreconsole); kill the whole process tree on Windows.
- Shared fixtures: programs with 8, 25, 60 rooms and sites rectangle + L-shape. Fixture programs must only use the 13 types guaranteed by the seed rulebook (0.3 RD).
- pytest-timeout on Windows uses the `thread` method (signals unavailable) — set explicitly.
