# Ticket 3.4 — Simulated-Annealing Optimiser + `ale generate` · Requirements Document

> **Worker brief.** Context = this file, `eval.md`, the contracts (1.2.0; `corridor_plan.py` docstring), and the
> public interfaces of `ale.topology` (`seed_plan`, `SeedResult`), `ale.geometry` (`realize`, `evaluate`,
> `check_layout`), `ale.program` (`prepare_input`, `PreparedInput`, `InputError`), `ale.export` (`export_run`),
> `ale.guards`, `ale.config`, the `generate` CLI stub, and the test helpers. Do not modify contracts.

## 1. Files
```
src/ale/optimize/__init__.py
src/ale/optimize/moves.py      # grammar moves G1–G7 on CorridorPlan (pure functions, seeded RNG)
src/ale/optimize/anneal.py     # anneal(...) → AnnealResult
src/ale/optimize/generate.py   # generate(...) → GenerateResult (seed → anneal → export, N variants)
src/ale/cli/commands/generate.py   # replace the stub body (keep options)
tests/cli/test_cli_surface.py      # ONLY: remove `generate` from the stub list
tests/optimize/**
specs/tickets/3.4_sa-optimizer/eval_report.md
```

## 2. Moves (`moves.py`) — each returns a new valid-by-contract plan or `None` (not applicable)
`G1` swap two rooms of the same zone with areas within 25 %; `G2` move a room between a room bay and a stack, or
between stacks, within its zone (creating/removing finger bays as needed, never leaving an empty non-junction
finger); `G3` reorder two adjacent bays inside a zone run of a block; `G4` swap two zone runs inside a block;
`G5` move a whole zone run to another block (any band/piece); `G6` flip a finger bay's stacks or reverse the
order inside a stack; `G7` split a band into two (n < 6) or merge two adjacent bands of a piece, redistributing
their bays in order, and fixing the connector per the contract rules. Every produced plan must satisfy the
contract validators and `check_against`; moves that would violate them return `None`.
Move selection probabilities (config-free constants): G1 .25, G2 .20, G3 .15, G4 .10, G5 .10, G6 .10, G7 .10.

## 3. Annealing (`anneal.py`)
```python
class AnnealResult(BaseModel, frozen=True):
    plan: CorridorPlan; layout: Layout; initial_cost: float; final_cost: float
    iterations: int; accepted: int; elapsed_s: float; stopped_by: Literal["max_iter","time_budget","converged"]
def anneal(prepared, rulebook, config, start: CorridorPlan, *, seed: int) -> AnnealResult
```
- State = plan; energy = `total_cost` of `evaluate(realize(...).layout)`; a plan whose realisation fails gets
  energy `+inf` and is never accepted. The start plan must realise (else `ValueError`).
- **Acceptance (amended at review 2026-11-08 — lexicographic, replaces the single-energy Metropolis rule):**
  state score = `(n_hard, cost)` with `n_hard` as defined below and `cost = total_cost` of `evaluate`.
  - `n_hard` decreases → accept.
  - `n_hard` increases by `Δh` → accept with probability `exp(−Δh / T_h)`; `T_h` starts at 0.5 and follows the same
    schedule fraction as `T_c` (so hard regressions are allowed early, almost never late).
  - `n_hard` equal → Metropolis on cost: accept if `Δc ≤ 0`, else with `exp(−Δc / T_c)`.
  - `T_c0` = calibrated on **cost deltas only** (the median of 50 sampled uphill moves that keep `n_hard` equal,
    chosen so `optimizer.initial_acceptance` of them would be accepted); end temperature `T_c0 × 1e-3`.
  - **Schedule by progress fraction** `f` ∈ [0, 1]: `T = T0 × (T_end / T0) ** f`, with `f = iterations / max_iter`
    when `max_iter` binds first, else `elapsed / time_budget_s` (so the run always cools fully within its budget;
    determinism is guaranteed when `max_iter` binds, as in O04). `moves_per_temperature` and `cooling` are ignored.
  - Best = lexicographically smallest `(n_hard, cost)` seen; stop by `bounded(..., on_exhaust="stop")` or
    `converged` (no best improvement during the last 25 % of the progress).
- `n_hard` = number of violations with codes `AREA_UNDER`, `AREA_OVER`, `ASPECT`, `MIN_WIDTH`, `NO_FACADE`,
  `REQUIRED_ADJ`, `AVOID_ADJ`, `NO_CIRCULATION_ACCESS` (user decisions D1/U-2 and the directive).
  `AnnealResult` reports `initial_hard`, `final_hard`.
- **Throughput**: `anneal` must reuse realisation work where possible (e.g. cache realised blocks keyed by the
  block's bay tuple and depth); target ≥ 30 iterations/s on P25 on one CI core.
- RNG: `random.Random(seed)` only.

## 4. Generate (`generate.py`, `ale generate`)
```python
def generate(program: Path, site: Path, rulebook: Path, out: Path, *, seed: int, variants: int,
             config: AleConfig) -> GenerateResult        # runs + their metrics
```
- `prepare_input` (InputError → CLI prints all issues in French, exit 1).
- For `k in range(variants)`: `seed_k = seed + k`; `seed_plan(seed=seed_k)`; if it fails → record a failed variant
  with its failures; else `anneal(seed=seed_k)`; export with `export_run` to `out/variant_<k+1:02d>/`
  (run_id = `<out name>-v<k+1>`). Variants whose final plans are identical (canonical JSON) are kept but flagged
  `duplicate_of`.
- Writes `out/summary.md` (French): table variant → status, final cost, violations count, circulation %, elapsed.
- CLI: options as in the stub (`--program --site --rulebook --out --seed --variants`, plus optional
  `--workspace` for config; default `AleConfig()`); exit 0 if ≥ 1 variant succeeded, else 1. `--seed` default
  `determinism.seed` from config.

## 5. Out of scope
New cost terms, multi-storey, GUI.
