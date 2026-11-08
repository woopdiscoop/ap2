# Ticket 3.2 — Topology & Seeding (first valid CorridorPlan) · Requirements Document

> **Worker brief.** Context = this file, `eval.md`, the contracts (1.2.0 — read the `corridor_plan.py`
> docstring: pieces, bands, connectors, blocks, room bays, finger bays, J1/J2), and the public interfaces of
> `ale.geometry` (`realize`, `evaluate`, `check_layout`, `greedy_plan`), `ale.program` (`PreparedInput`),
> `ale.guards`, `ale.config`, plus test helpers (`tests/conftest.py`, `tests/fixtures/`,
> `tests/program/program_helpers.py`, `tests/program/data/rulebook_test.yaml`). Do not modify contracts or
> other tickets' code.

## 1. Purpose
Produce, deterministically from a seed, a **first CorridorPlan that realises with no failures** and reasonable
quality, plus a topology report. Ticket 3.4 then optimises it. A Router experiment showed valid plans exist for
all three fixtures (random search: P8 54 %, P25 41 %, P60 3 % of random plans valid), while `greedy_plan`
overflows on all three — so the core of this ticket is a **capacity-aware construction + repair** search.

## 2. Files
```
src/ale/topology/__init__.py
src/ale/topology/graph.py      # build_graph(...) → networkx Graph; planarity diagnostic
src/ale/topology/embed.py      # seeded force layout (positions in footprint metres)
src/ale/topology/seed.py       # seed_plan(...) → SeedResult
src/ale/topology/repair.py     # overflow repair moves
tests/topology/**
specs/tickets/3.2_topology-seeding/eval_report.md
```

## 3. API
```python
class TopologyReport(BaseModel, frozen=True):
    n_nodes: int; n_required: int; n_avoid: int
    planar: bool                         # required-adjacency graph planar?
    conflicts: tuple[tuple[str, str], ...]   # required edges in a Kuratowski subgraph (sorted), () if planar
    unsatisfiable_required: tuple[tuple[str, str], ...]  # required pairs placed in different pieces/bands with no shared boundary possible (filled after seeding)
class SeedResult(BaseModel, frozen=True):
    plan: CorridorPlan; realization: Realization; report: TopologyReport
    attempts: int; elapsed_s: float
def build_graph(prepared: PreparedInput, rulebook: Rulebook) -> nx.Graph
def seed_plan(prepared: PreparedInput, rulebook: Rulebook, config: AleConfig, *, seed: int,
              time_budget_s: float = 20.0) -> SeedResult
```
`seed_plan` never raises: if no valid plan is found within the budget it returns the best (least overflow)
plan with its failing realisation.

## 4. Graph (`graph.py`)
Nodes = room instances (attrs: spec_id, type, zone, area_m2, needs_facade, service_core) + one node `CORE`.
Edges: REQUIRED (from `adjacent_to`, expanded over instances: each instance of A to the nearest-by-index
instance of B), AVOID (from `avoid`, weight −1), PREFERRED (rulebook `p ≥ 0.6`, weight p, only between
instances of different types, at most 3 per node keeping the highest p), and `CORE` edges to every
`service_core` room (weight 1). Planarity: `nx.check_planarity` on the REQUIRED subgraph; when not planar,
`conflicts` = REQUIRED edges of the counterexample.

## 5. Seeding (`seed.py`) — a bounded, seeded search
1. **Embedding** (`embed.py`): `nx.spring_layout(seed=seed)` on the graph with edge weights (AVOID edges
   excluded, repulsion added afterwards by 50 iterations of pairwise push for AVOID pairs closer than the median
   distance), scaled to the footprint bounding box; `needs_facade` rooms projected to the nearest exterior
   edge weighted by orientation preference; `CORE` pinned to the rulebook core target. Deterministic for a seed.
2. **Band counts**: candidates per piece `n ∈ {n0−1, n0, n0+1} ∩ [1, 6]` with
   `n0 = max(1, round((P − s) / (2·D_t + s)))` (as in 3.3b greedy); J1 → secondary 1 band. Connectors per the
   contract rules (cut side where required, else `start` or `end`, chosen by which end is nearer the access edge).
3. **Assignment**: order the pieces' band blocks along a serpentine path (piece by piece, band by band, block A
   then B); sort rooms by the embedding coordinate projected on that path; fill blocks in that order using a
   **capacity estimate** per block = usable length − Σ estimated bay widths, where a room bay's width =
   `ceil(T / D)` clipped to `[c, …]` with aspect ≤ amax at the block's estimated depth `D = (P_band − s) / 2`,
   and rooms with `T < 0.6·D²` are grouped two-per-stack into finger bays of the same zone. Keep zones
   contiguous inside a block whenever capacity allows.
4. **Realise** with `realize`. If failures: **repair** (`repair.py`) inside `bounded(...)`: repeatedly take the
   block with the largest overflow and apply the first improving move among (a) move its smallest room to the
   block with the most slack (same zone preferred), (b) convert two small room bays into one finger bay,
   (c) move a finger stack room to the other stack, (d) change the band count of that piece (±1) and re-assign;
   re-realise after each move; stop on success.
5. **Restarts**: if still failing, restart from step 1 with seed `seed·1000 + k` (k = 1, 2, …) until the time
   budget; keep the first valid plan, else the least-overflow plan.
6. Quality is secondary here (3.4 optimises) but required adjacencies should be honoured when capacity allows:
   after a valid plan is found, spend at most 25 % of the remaining budget on swaps that reduce
   `evaluate(...).cost_breakdown["required_adjacency"]` without breaking validity.

## 6. Determinism & limits
Same inputs + seed → identical plan (canonical JSON). All loops through `ale.guards.bounded`. `seed_plan` on P60
must finish within its `time_budget_s` (default 20 s) on one CI core.

## 7. Out of scope
Simulated annealing (3.4), export (3.5), `ale generate` wiring (3.4).
