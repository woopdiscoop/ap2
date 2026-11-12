# Ticket M.2b · Evaluation (synthetic; no real files)
| ID | Test | Pass condition |
|---|---|---|
| B201 | diagnosis | `eval_report.md` § Diagnosis explains the M.1-bar failures (pieces, cuts, junctions, rejecting check). |
| B202 | bar_central | Bars 54.0 × 15.6 m and 64.8 × 19.2 m with a central solid (core + wet stack bounding rectangle) and a programme loading the plate 85–100 %: ≥ 9 of 10 seeds give a seeded plan passing `check_layout` (hard violations other than NO_FACADE = 0). |
| B203 | bar_offcentre | Same with the solid at one third of the length and with the solid against one long corridor side: ≥ 8 of 10 seeds. |
| B204 | stack_bar | `ale stack --plans` on the reloaded M.1 bar (R+3, receding top floor): 4 of 4 floors planned, vertical check passes, `plans.md` French. |
| B205 | unchanged | Digests of P08/P25/P60 prepared inputs, feasibility reports and seeded plans without solids identical to the base commit; M.2 `plans_case` still 4/4. |
| B206 | gates | ruff, format, mypy strict, lock --check unchanged; whole suite (`-m "not slow"`) passes; `--plans` on the 4-floor bar with `--budget 10` ≤ 90 s. |
