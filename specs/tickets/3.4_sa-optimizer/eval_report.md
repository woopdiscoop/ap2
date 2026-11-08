# Ticket 3.4 — Simulated-Annealing Optimiser + `ale generate` · Evaluation report

Environment: Linux, Python 3.13, `pip install -e ".[dev,excel,cad,pdf]"`.

## Results

| ID | Test(s) | Result |
|---|---|---|
| O01 | `test_optimize_moves.py::test_O01_moves_valid`, `test_O01_weights` | pass. A 2 000-step seeded random walk (`propose`) from the seeded P25 plan: every non-None result re-validates from its dump, passes `check_against`, and adds no zone violation. G1–G7 each produced at least one plan. |
| O02 | `test_O02_g1_swaps_two_rooms_of_one_zone`, `test_O02_g6_flips_stacks`, `test_O02_g7_split_then_merge` (+ G2/G3/G4/G5 semantics tests) | pass |
| O03 | `test_optimize_anneal.py::test_O03_improves[P8/P25/P60]` | pass (table below) |
| O04 | `test_O04_deterministic` | pass. Two fresh processes (different `PYTHONHASHSEED`), P8, `max_iter=500`, gave the same plan JSON, iterations, accepted count and cost. |
| O05 | `test_O05_budget` | pass. P60 with `time_budget_s=30`: `stopped_by=time_budget` after 234 iterations, 30.1 s wall (limit 31 s). |
| O06 | `test_O06_metropolis[...]` (3 (Δ, T) pairs) | pass. The uphill acceptance frequency over 10 000 trials is within 3σ of `exp(−Δ/T)`. |
| O07 | `test_optimize_generate.py::test_O07_generate_cli` | pass. `ale generate` on P25 with `--variants 3 --seed 1` and `time_budget_s = 3` in the workspace config: exit 0, 3 variant folders each with the 4 files, `summary.md` lists variants 01–03. |
| O08 | `test_O08_generate_errors` | pass. The X07 workbook gives exit 1, French issue lines on stderr (`Erreurs (n) :`, `[E_…] ligne …`, `ÉCHEC : …`), and `--out` is not created. |
| O09 | `test_O09_variants_distinct` | pass. 3 variants of P25 (2 s budget) gave at least 2 distinct final plans; `duplicate_of` is flagged correctly (also covered by `test_generate_failed_and_duplicate_variants`). |
| O10 | gates | pass: `ruff check` clean, `ruff format --check` clean, `mypy` (strict) clean on 82 files, `python -m ale.contracts.lock --check` gives OK (exit 0). Whole suite: **766 passed, 7 skipped, 2 xfailed** (the xfails come from earlier tickets) in 352 s. The `generate` stub entry was removed from `STUB_TICKETS` in `tests/cli/test_cli_surface.py`. |

Coverage of `ale.optimize` (branch coverage): `__init__` 100 %, `anneal.py` 99 %, `generate.py` 100 %,
`moves.py` 92 %. Package total is about 95 %.

### O03: seed-3 starts, 15 s budget each, default config otherwise

| Fixture | initial_hard → final_hard | total_cost initial → final | iterations | stopped_by |
|---|---|---|---|---|
| P8 / site_rect_small | 6 → 3 | 1.448 → 1.888 | 1 958 | time_budget |
| P25 / site_rect | 13 → 13 | 1001.048 → 1001.048 | 345 | time_budget |
| P60 / site_L | 35 → 34 | 9000.656 → 7000.831 | 125 | time_budget |

Start violation types: P8 has ASPECT ×4 and AREA_OVER ×2. P25 has NO_FACADE ×7, AREA_UNDER ×2, ASPECT ×2, MIN_WIDTH, REQUIRED_ADJ. P60 has
NO_FACADE ×21, REQUIRED_ADJ ×7, ASPECT ×4, AVOID_ADJ ×2, MIN_WIDTH. The energy never rises and
`final_hard ≤ initial_hard` in every run. Because P60 hits the time budget, its iteration count
depends on machine speed, so its result can vary between runs (another run gave 35 → 30).

### One real `ale generate` run on P25

The run used a workspace with `[optimizer] time_budget_s = 15.0`:
`ale generate --program programme.xlsx --site site.yaml --rulebook rulebook_test.yaml --out p25_run --seed 1 --variants 3 --workspace ws`.
It exited with 0 and printed one line per variant plus the summary path. `summary.md`:

```
# Synthèse de génération — p25_run

- Graine de base : 1
- Variantes : 3 (réussies : 3, échouées : 0)

| Variante | Statut | Coût final | Violations | Circulation (%) | Durée (s) | Remarque |
|---|---|---|---|---|---|---|
| 01 | réussie | 1000.757 | 9 | 21.6 | 15.5 |  |
| 02 | réussie | 4001.718 | 12 | 38.7 | 15.9 |  |
| 03 | réussie | 1001.048 | 13 | 24.2 | 15.6 |  |
```

Each `variant_0k/` folder holds `layout.json`, `layout.dxf`, `preview.svg` and `report.md`.

## Ambiguities and the literal readings chosen

1. **T0 median rule with hard energy.** T0 is set so that `exp(−median(Δ⁺)/T0) = initial_acceptance`,
   using up to 50 finite uphill Δ sampled from the start. The sampling is capped at 250 proposals
   and 20 % of the time budget. Under the RD energy (`+ H × n_hard`, H = 1000), most uphill Δ are
   multiples of 1000. On P25 this gives T0 ≈ 9 000. With the default `moves_per_temperature = 200`
   and only about 125–2 000 proposals per 15 s, the temperature barely cools. The run is then close
   to a random walk, and only the best-seen tracking makes progress. This is why P25 shows no gain.
   It is a spec/config tension, not a code defect. I did not change any expectation. Possible
   remedies for a later ticket: a lower `initial_acceptance`, fewer moves per temperature, or
   computing T0 from soft-cost Δ only.
2. **"Return the best plan seen".** The best is the lowest-energy plan among plans with
   `n_hard ≤ initial_hard`. The RD energy alone does not strictly guarantee `final_hard ≤ initial_hard`
   (the `required_adjacency` cost term can move by more than H). This filter makes both O03
   properties hold. Fewer hard violations still win through the energy.
3. **Convergence.** "No improvement of the best for 20 consecutive temperature steps" is checked at
   each cooling step. `iterations` counts main-loop proposals only, not the T0 samples.
4. **Moves.** A move result is also `None` when it equals the input or adds macro-zone violations
   (`zone_violations` count grows). A zone run is a maximal sequence of same-zone non-junction bays,
   and a junction finger breaks runs. G3, G4 and G5 never move a junction finger. G2 may use a
   junction finger's stacks, since the contract allows an empty junction finger. G7 "redistributes
   bays in order" as follows. A split cuts block A + block B of the band into 4 contiguous chunks:
   lower A, lower B, upper A, upper B. A merge cuts the 2 bands' bays into 2 chunks: A, B. Cut points
   are near even splits, ±1. Connectors are then reassigned, preferring the current ones, to the
   first assignment that passes the piece rule and `check_against`.
5. **Generate.** `seed_plan` gets `time_budget_s = min(20, optimizer.time_budget_s)`. A failed seed
   means `realization.layout is None`, recorded as `"<code>: <detail>"`. "Circulation %" is
   circulation area / footprint area. `variants < 1` raises `ValueError` in the API (the CLI
   already enforces `min=1`). A variant folder that already holds run files makes `export_run`
   raise `FileExistsError`. The CLI reports it in French with exit 1. Input issues go to stderr in
   the `ale program check` line format.
6. **CLI.** `--workspace` (optional, `$ALE_WORKSPACE`) supplies the config, otherwise `AleConfig()`
   is used. `--seed` defaults to `determinism.seed`. The exit code is 0 when at least one variant
   succeeded, else 1.
7. `ale.optimize.generate` the submodule is shadowed by the `generate` function on the package.
   Tests get the module with `importlib.import_module`.
