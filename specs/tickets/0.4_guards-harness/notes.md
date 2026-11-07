# 0.4 — Router notes

Status: BLOCKED on 0.1 and 0.2 being merged (imports `ale.contracts`, `ale.config`, `ale.workspace`, runs `ale init`). Spec complete: RD + eval + fixtures.

## Decisions taken while specifying
- External-process runner lives in `ale.proc` (`run_tool` → `ProcessReport`), never raises for a failed tool; whole process tree killed on timeout (POSIX process group; Windows `taskkill /T /F`).
- `bounded(..., on_exhaust="stop")` added so the SA optimizer (3.4) can end cleanly at its time budget and return the best layout found, instead of catching an exception.
- No threads or signals in guards: identical behaviour on Windows.
- Fixtures written by the Router (verified: instance counts 8/25/60, net 75/334/962 m², all references valid, no REQUIRED/AVOID contradictions, only the 13 seed-guaranteed types).
- Third site `site_rect_small` (10 × 10 m) added: P8 on the 24 × 18 m rectangle would fill only 21 % of it. Fill ratios with default config: P8 0.899, P25 0.923, P60 0.936 (≤ max_fill 0.95).

## Review log
_(empty)_
