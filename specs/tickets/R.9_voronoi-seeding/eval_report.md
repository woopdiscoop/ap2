# R.9 eval report

Budgets: `seed_plan(seed=s, max_attempts=50)` then `anneal(seed=6, max_iter=1500)` (P60: 1100), seeds s = 1..5,
`seeder` the only difference. Resolution of the diagram: one cell = 6 x 6 modules at 100 mm (0.6 m).

## Per-ID results

| ID | Result |
|---|---|
| R9-01 | pass: exact cell counts on P25/P60/AREP, cores untouched, shortfall reported when the programme is tripled, identical in two fresh processes (different PYTHONHASHSEED) |
| R9-02 | pass on the anchor fixture (corner room on a corner, entrance room at the entrance, REQUIRED pairs adjacent, sanitary rooms next to the core) |
| R9-03 | pass: all façade rooms touch the façade on P25/P60/AREP; with 200 façade rooms on 140 perimeter cells the rooms without façade are named |
| R9-04 | pass: `plan_from_diagram` passes `check_against`; `seeder="cells"` realisations pass `check_layout` on P8/P25/P60 |
| R9-05 | pass: default and explicit `spring` give the pre-R.9 seed-3 start layouts (SHA-256 of Q.4 D02) |
| R9-06 | pass |
| R9-07 | pass (table below, written by the test) |
| R9-08 | FAIL, kept as written: AREP hard, `cells`, NO_FACADE = 3 (> 1), FACADE_DEPTH = 0 (start hard 4, final hard 4, REQUIRED_ADJ 1) |
| R9-09 | see "Gates" |

## Adoption verdict

Do not adopt: `cells` is worse on P25 (6.0 vs 4.0 mean hard) and P60 (15.0 vs 11.8) and on the AREP hard mode
(4.0 vs 3.0); only the AREP soft mode improves (3.0 vs 3.6). `spring` stays the default. The cells results are
identical across seeds: the diagram is the same and annealing converges to the same plan.


## Comparison table (R9-07)

<!-- R9-07:begin -->
| case | seeder | final hard (per seed 1-5) | mean hard | mean NO_FACADE | mean REQUIRED_ADJ | mean cost |
|---|---|---|---:|---:|---:|---:|
| P25 | spring | 5, 2, 5, 3, 5 | 4.0 | 1.8 | 2.2 | 2200.7 |
| P25 | cells | 6, 6, 6, 6, 6 | 6.0 | 4.0 | 2.0 | 2000.7 |
| P60 | spring | 14, 9, 9, 14, 13 | 11.8 | 8.2 | 3.6 | 3600.7 |
| P60 | cells | 15, 15, 15, 15, 15 | 15.0 | 11.0 | 4.0 | 4000.7 |
| AREP hard | spring | 3, 3, 3, 3, 3 | 3.0 | 2.8 | 0.2 | 200.8 |
| AREP hard | cells | 4, 4, 4, 4, 4 | 4.0 | 3.0 | 1.0 | 1000.9 |
| AREP soft | spring | 4, 3, 4, 3, 4 | 3.6 | 2.0 | 1.6 | 1600.8 |
| AREP soft | cells | 3, 3, 3, 3, 3 | 3.0 | 2.0 | 1.0 | 1000.8 |

Verdict: **DO NOT ADOPT (keep `spring`)** (P60 lower: False; AREP hard lower: False; AREP soft lower: True; P25 not higher: False).
<!-- R9-07:end -->


## Design notes

- The diagram feeds the existing seeder through room positions (cell centroids replace the spring embedding);
  the existing depth-aware assignment, capacity estimate and repair then run. If the cells attempt does not
  realise validly after repair, that attempt falls back to the spring embedding and an INFO record
  "spring fallback" is logged by `ale.topology.seed`.
- Attempt 0 uses the plain diagram; later attempts use a seeded jitter (0.5) on the growth score.
- A room enclosed by others is re-seeded (at most 3 times) or jumps to the free cell nearest its centroid.

## Spec issues

- RD §4 (assignment "to the block containing most of its cells") is realised through positions, because the
  capacity-aware block assignment of 3.2 needs a path position per room; cell centroids give the same ordering.
- RD §3.2: a room placed on the ribbon next to a REQUIRED partner already on the ribbon takes the free span
  next to it (otherwise R9-02 "REQUIRED pairs adjacent" is not met); zone/programme order applies otherwise.
- RD §5 "AREP floor": adoption was required in both depth modes (hard and soft).
- RD §3 does not say how the diagram resolves with a 100 mm module; 0.6 m cells were used (RD prototype grid).

## Gates

Whole suite once under `--cov=src/ale`: 1390 passed, 13 skipped, 3 xfailed (pre-existing), 1 failed
(R9-08, kept as written), 71 min. Total coverage 98 %; cellgrow.py 95 %, fromdiagram.py 100 %,
export/diagram.py 96 %, seed.py 99 %. ruff check, ruff format --check and mypy strict on src pass;
lock --check passes (no contract change).
