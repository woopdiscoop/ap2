# Ticket R.9 — Voronoi seeding experiment · Requirements Document

> **Starts after R.1 merges** (same seeding/optimiser files). Context = this file, `eval.md`, `ale.topology`
> (`embed.py`, `seed.py`, `depth.py`), `ale.optimize` (multi-start of R.1, deterministic budgets of Q.3), the grammar
> note. No contract changes. **An experiment**: it is adopted as default only if it beats the current seeder (§4).

## 1. Purpose
The current seeder orders rooms from a spring layout of the adjacency graph, which ignores the footprint's shape,
the target areas and where the façade is. A **weighted Voronoi (power) diagram in the Manhattan (L1) metric**
computed inside the footprint gives area-proportional, axis-aligned cells. They are read as a *topology hint*: which
rooms neighbour which, which reach the façade, and the order along each band. The grammar still produces the
geometry, so every by-construction guarantee is unchanged.

## 2. Files (ownership)
`src/ale/topology/voronoi.py` (NEW), `src/ale/topology/seed.py` (ONLY: a `seeder` option), `src/ale/config` is a
contract, so no new config key: the choice is a keyword argument `seeder: Literal["spring", "voronoi"] = "spring"`
on `seed_plan` and `generate`, `tests/topology/test_voronoi*.py`, `specs/tickets/R.9_voronoi-seeding/eval_report.md`
(with the comparison tables).

## 3. Method
1. Seeds: one per room instance, initial positions from the existing embedding; `needs_facade` rooms start on the
   exterior edge nearest to their orientation preference; weights from target areas.
2. Lloyd-style iterations (bounded, deterministic): compute the L1 power diagram on the module grid (raster at the
   module size is acceptable), move each seed to its cell centroid, adjust its weight towards its target area; stop at
   a mean area error ≤ 5 % or N iterations.
3. Read the result: façade rooms = cells with exterior contact ≥ f; neighbour pairs = cells sharing ≥ c; projection
   of the cell centroids on the band serpentine of 3.2 §5.3 gives the assignment order. Feed these to the existing
   assignment, capacity and repair steps instead of the spring ordering.

## 4. Adoption rule (measured, deterministic budgets)
Compare `spring` and `voronoi` on P25 and P60 (and the AREP top-floor demo of Q.4 D05), 5 seeds each, the same total
budget: final hard count, `NO_FACADE`, `REQUIRED_ADJ`, cost, seeding time. **Adopt** (default `voronoi`) only if the
mean final hard count is lower on P60 and not higher on P25 and the AREP floor, and the seeding time stays within the
budget. Otherwise keep `spring` as default, keep `voronoi` as an option, and record the result.
