# 0.4 — Router notes

Status: BLOCKED on 0.1 and 0.2 being merged (imports `ale.contracts`, `ale.config`, `ale.workspace`, runs `ale init`). Spec complete: RD + eval + fixtures.

## Decisions taken while specifying
- External-process runner lives in `ale.proc` (`run_tool` → `ProcessReport`), never raises for a failed tool; whole process tree killed on timeout (POSIX process group; Windows `taskkill /T /F`).
- `bounded(..., on_exhaust="stop")` added so the SA optimizer (3.4) can end cleanly at its time budget and return the best layout found, instead of catching an exception.
- No threads or signals in guards: identical behaviour on Windows.
- Fixtures written by the Router (verified: instance counts 8/25/60, net 75/334/962 m², all references valid, no REQUIRED/AVOID contradictions, only the 13 seed-guaranteed types).
- Third site `site_rect_small` (10 × 10 m) added: P8 on the 24 × 18 m rectangle would fill only 21 % of it. Fill ratios with default config: P8 0.899, P25 0.923, P60 0.936 (≤ max_fill 0.95).

## Review log
- 2026-11-07 — Attempt 1 (commit 1b074cc): Router re-run in a clean checkout + fresh venv: whole suite 408 pass / 5 skip (2 Windows-only twins here), ruff/format/mypy clean, lock --check OK, guards 100 % / proc 99 % coverage, all 27 eval IDs present, 6 fixtures byte-identical, ownership clean. **DONE** (merged).
- Worker-reported issues, accepted, to carry forward:
  - `ale` logger has `propagate=False` after any in-process CLI call → hides `ale.*` records from pytest `caplog`. Later tickets must use the same workaround; candidate for a small 0.1 amendment (restore propagation in tests or attach caplog handler directly).
  - 0.1's absolute-path lint flags short command switches like `/T`; `ale.proc` builds them as f-strings. Candidate refinement of P02 regex (require ≥ 2 path characters or a second separator).
  - `bounded_range(..., on_exhaust="raise")` raises when consumed to the cap — intended for convergence loops that must `break`; use `on_exhaust="stop"` for fixed-length loops.
