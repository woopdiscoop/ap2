# Ticket 3.2 — Topology & Seeding · Evaluation report

Environment: Linux, Python 3.13, one core. Fixtures from `prepare_input` with
`tests/program/data/rulebook_test.yaml`, default `AleConfig` (module 0.10 m, s = c = 12).

## Results

| ID | Test (tests/topology/) | Result |
|---|---|---|
| T01 | `test_topology_graph.py::test_T01_graph` (+ `test_T01_preferred_edges`) | PASS — 26 nodes, 7 REQUIRED, 6 AVOID, CORE → every service_core room |
| T02 | `test_topology_graph.py::test_T02_planarity` | PASS — K5: planar False, 10 conflicts; P25 planar, `()` |
| T03 | `test_topology_seed.py::test_T03_valid_P8` | PASS |
| T04 | `test_topology_seed.py::test_T04_valid_P25` | PASS |
| T05 | `test_topology_seed.py::test_T05_valid_P60` | PASS — elapsed well under 20 s |
| T06 | `test_topology_seed.py::test_T06_seeds` | PASS — seeds 1–5 valid, ≥ 2 distinct plans |
| T07 | `test_topology_seed.py::test_T07_deterministic` | PASS — two fresh processes, identical canonical JSON |
| T08 | `test_topology_seed.py::test_T08_never_raises` | PASS — failures returned, attempts ≥ 1, no exception |
| T09 | `test_topology_seed.py::test_T09_required_adjacency` | PASS — seeded 1.0 vs best of 50 random valid ≈ 4–5 |
| T10 | `test_topology_seed.py::test_T10_beats_greedy[prep_8/25/60]` | PASS — greedy overflows on all three |
| T11 | `test_topology_gates.py::test_T11_gates` | PASS — ruff, ruff format, mypy (strict), lock --check 0 |

Whole suite: 732 passed, 7 skipped, 2 xfailed. Coverage of `ale.topology`: 97 % (line+branch;
embed 95 %, graph 97 %, repair 97 %, seed 98 %). `mypy` on all of `src/ale` clean.

## Per-fixture seeding (seed = 1, default budget 20 s)

| Fixture | attempts | elapsed_s | bands | required_adjacency |
|---|---|---|---|---|
| P8 / site_rect_small | 1 | 0.07 | [1] | 0 |
| P25 / site_rect | 1 | 0.49 | [2] | 1 |
| P60 / site_L (J2) | 1 | 1.55 | [3, 2] | 5 |

Seeds 1–7: all valid on all three fixtures at the first attempt (P60 1.6–2.5 s).

## Changes to the specified method (deterministic, bounded)

- **Assignment fill ratio (§5.3)**: instead of one fixed proportional fill, the fill target ρ is
  scanned over 33 values in [0.7, 1.5] × (demand / capacity); the bay grouping whose estimated
  overflow (then worst block fill ratio) is lowest is kept. No realisation involved. Without it
  the last serpentine block collected the estimation error (P60 needed 2 attempts / ~8 s); with
  it the first assignment realises on every tried seed.
- **Swap phase (§5.6)**: besides the 25 %-of-remaining time cap, an iteration cap
  `clamp(720 // n_rooms, 10, 60)` realisations, so the time cap does not bind in practice and
  results stay deterministic (T07). Candidate swaps are ordered by area difference; swaps that
  add a zone split are rejected.
- The repair moves (a)–(d) are as specified; a J1 junction-shift move (±1 bay) is added, tried
  only when a realisation reports `JUNCTION_MISALIGNED`.

## Ambiguities and readings chosen

- **AVOID expansion**: §4 specifies nearest-by-index only for REQUIRED; AVOID is expanded over
  every instance pair (matches `evaluate`, which penalises any touching pair). P25 → 6 edges.
- **Edge collisions**: an edge keeps its first kind (REQUIRED, AVOID, PREFERRED, CORE).
- **CORE pinning**: spring layout with `CORE` fixed at the normalised core target, then scaled
  to the bbox; CORE is set exactly to the target afterwards.
- **J2 secondary connector**: when the primary carries the connector (2+ bands) a multi-band
  secondary gets `"none"` (contract allows it; its spines run full length to the primary
  connector) — maximises usable length.
- **Capacity estimate**: room-bay width = `max(wmin, ceil(T/D))`, widened within the area
  tolerance until aspect ≤ amax (mirrors `realize`); constants come from
  `ale.geometry.blocks.Consts` and frames from `ale.geometry.junction` (as `greedy_plan` does).
- **T08**: `prepare_input` rejects P25 on site_rect_small (`E_NOT_FEASIBLE`), so the test swaps
  P8's site/footprint into the prepared P25. "Within budget" is asserted as
  `elapsed_s ≤ budget + 0.5 s` (one realisation can finish after the last budget check).
- **T09**: random plans = one piece, 1–3 bands, connector `start`, shuffled rooms, 20 % finger
  bays of 2–4 rooms, random cuts into blocks; first 50 valid (seeded `random.Random`).
- **unsatisfiable_required**: REQUIRED pairs in different blocks whose block regions (from the
  realised depths, else equal split) share < c modules of boundary.
- Determinism holds while the time budget is not exhausted (the restart loop and swap phase
  stop on time as a safety net).
- `networkx` ships no stubs and none are in the dev extra: imported with
  `# type: ignore[import-untyped]` (pyproject is outside this ticket's files).
