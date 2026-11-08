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
- Metropolis: accept if Δ ≤ 0, else with probability `exp(−Δ/T)`. `T0` chosen so that
  `optimizer.initial_acceptance` of 50 sampled uphill moves from the start would be accepted (median rule);
  geometric cooling `T ← T × optimizer.cooling` every `optimizer.moves_per_temperature` proposals;
  stop by `bounded(optimizer.max_iter, optimizer.time_budget_s, on_exhaust="stop")`, or `converged` when no
  improvement of the best for 20 consecutive temperature steps. Return the **best** plan seen.
- RNG: `random.Random(seed)` only; same inputs + seed → identical result.
- Hard constraints (`REQUIRED_ADJ`, `NO_CIRCULATION_ACCESS`, `NO_FACADE`) are already weighted in the cost by
  `[optimizer.weights]`; nothing else special.

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
