# Ticket R.10 · Evaluation (synthetic fixtures only)
| ID | Test | Pass condition |
|---|---|---|
| S1001 | match | Synthetic vector PDF with 2 plans and 12 rooms whose written areas are programme values ±(0–8) %: every room matched to the right line (unique sizes), plan index reported. |
| S1002 | tolerance | Gaps of −3 % → « à ajuster », −8 % → « sous le programme », +12 % → « au-dessus de la tolérance » with the default 5 %; `--tolerance-pct 10` reclassifies −8 % as « à ajuster ». |
| S1003 | unmatched | A programme line with no room within 25 % and a drawn room with no line are both listed. |
| S1004 | facade | A façade-required line matched to an interior room → flagged; to an edge room → OK. |
| S1005 | stairs | One stair core on a plan → OK (U-14); stair count reported. |
| S1006 | annexe | `--annexe` with a synthetic Annexe file works like `--programme`. |
| S1007 | outputs | `score.md` (French) and `score.json` written; deterministic; no file outside `--out`. |
| S1008 | gates | ruff, format, mypy strict; coverage of `ale.score` ≥ 90 % (path-form); lock --check; whole suite passes. |
