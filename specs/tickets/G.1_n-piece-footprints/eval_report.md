# Ticket G.1 · Evaluation report

Contracts 1.5.0 → **1.6.0** (backward compatible). Base commit `bf798b6`.

## Results

| ID | Test | Result |
|---|---|---|
| N01 | `test_N01_*` (`tests/contracts/test_contracts_g1.py`) | pass. Contracts 1.6.0, lock and schemas checked. `decompose_footprint` of 3 rectangles and 32 L shapes (all 8 orientations of 4 L families, J1 and J2) has the same digest as at `bf798b6` (`284507e6…`, computed by running `tests/contracts/g1_compat.py` against a `git archive` of the base). P8 / P25 / P60 layouts (seed-3 start and annealed layout, Q.3 budgets) equal the base digests (the A.4 digests; verified by running A401 against the base source first). Pre-G.1 `CorridorPlan` JSON loads and re-dumps byte-equal (no `junction_to` key); a hole-free `ModulePolygon` dumps without `holes`. |
| N02 | `test_N02_decompose[U,T,H,comb,Z,ring]`, `test_N02_more_than_12_pieces`, `test_N02_holes_validation` | pass. Hand-checked fixtures (tiling, areas, aspect arguments in the test comments); deterministic, independent of the start vertex of the ring. 12 pieces accepted, 13 and 14 refused with `ValueError`. |
| N03 | `test_N03_realise[U,T,comb,ring,H]` | pass: P25 realises with `failures == ()` and `check_layout == ()` on U (3 pieces), T (2), comb (4, 3 fingers), courtyard ring (4 pieces, 1 open contact) and H (3 pieces, J1 + J2). `seed_plan(seed=3, max_attempts=40)`; wall time U 8 s, comb 8 s, ring 2 s, T 1 s, H 2 s (the run stops at the first valid plan plus extra attempts). A comb with a two-band root and an inner connector is covered by `test_two_band_root_with_fingers_and_inner_connector`. |
| N04 | `test_N04_circulation[U,comb,ring,H]` | pass: circulation is one connected set (independent flood fill), reaches every piece, every room touches it with contact ≥ c. |
| N05 | `test_N05_multi_junction`, `test_N05_u_chain_and_h_j2`, contract tests `test_N05_*` | pass: the comb root hosts three junction fingers (`junction_to` 1, 2, 3), each as wide as, in line with, and touching the cut next to the child's spine; U chain of two J1; H with collinear J2 spines. Contract validators and `check_against` messages covered. |
| N06 | `test_N06_anneal`, `test_N06_moves_keep_junction_targets_and_work_across_pieces` (`tests/optimize/test_optimize_moves_g1.py`) | pass: `anneal` (600 iterations, seed 6) on U keeps `check_layout == ()`, hard count not above the start's, deterministic; 400 proposals keep both `junction_to` fingers and G5 moves rooms between pieces. |
| N07 | gates | see below. |

## Gates

- `ruff check .`: clean. `ruff format --check .`: clean. `mypy` (strict, 133 source files): clean.
- `python -m ale.contracts.lock --check` and `export_schemas --check`: OK.
- Whole suite under `--cov=src/ale`: 1445 passed, 13 skipped, 3 xfailed (the pre-existing ones), 3 failed in 81 min. The 3 failures were existing tests that used a footprint that G.1 now supports (see below); they were changed and re-run green. Total coverage 97.9 %.
- Coverage of the touched modules (path form `src/ale/…`): `contracts/corridor_plan.py` 100 %, `contracts/footprint.py` 99.5 %, `contracts/geometry.py` 99.6 %, `geometry/blocks.py` 99.2 %, `geometry/checks.py` 98.4 %, `geometry/realize.py` 97.0 % (before the inner-connector test, which covers lines 673-684), `topology/seed.py` 97.9 %, `topology/repair.py` 99.0 %, `optimize/moves.py` 97.3 %, `optimize/polish.py` 100 %, `optimize/fastreal.py` 94.7 %.

## What changed

- **Contracts** (`footprint.py`, `corridor_plan.py`, `geometry.py`, version, schemas, lock): `Junction`, `FootprintPieces.junctions` / `open_contacts` (+ `children`, `parent_junction`), `MAX_PIECES = 12`, `FingerBay.junction_to` (+ `with_rooms`), `CorridorPlan` of 1–12 pieces with the tree validators and `check_against` rules, `ModulePolygon.holes`. Optional fields are left out of the serialised form when empty.
- **Decomposition**: rectangles and 6-vertex L shapes use the unchanged code. Everything else (more vertices, or holes): every reflex vertex extended through one of its edges (all `2^r` choices, `r ≤ 12`), faces merged where their union is a rectangle, then the choice minimising (pieces, J2 junctions, largest aspect, sorted `(y, x, w, h)` tuples); BFS spanning tree from the largest piece (ties: lowest-leftmost), pieces numbered in pre-order, spine of a child perpendicular to its cut, each tree edge a J1 / J2 `Junction` as for the L, other contacts `open_contacts`.
- **Realisation** (`geometry/realize.py`, `blocks.py`): `_Realizer._tree` for more than two pieces (the one- and two-piece code is untouched). A parent's band search carries the links of all its children; a J1 child hangs on the finger that names it (`BlockOut.fingers`, `finger_at`), a J2 child takes the depth aligning its spine; the finger / spine band must lie inside the cut. A misaligned finger still realises the child at the nearest fitting depth, so the failure does not hide the child's problems (this is what lets the repair loop make progress). `ale.optimize.fastreal` reuses `_Realizer.search` and is unchanged.
- **Hole-aware checks** (`geometry/checks.py`): `rect_in_polygon_cells` subtracts courtyards, `exterior_contacts` includes courtyard edges (façade on the court).
- **Seeding** (`topology/seed.py`, `repair.py`): one band for every J1 child and every piece incident to a J2 junction; junction fingers inserted for every J1 child at a bay boundary inside the finger window nearest the child's spine mid-depth; `_shift_junction` moves the finger named by the failure.
- **Moves** (`optimize/moves.py`): only `FingerBay` copies now keep `junction_to` (`with_rooms`); the moves themselves were already piece-aware.
- `geometry/greedy.py`: `greedy_plan` raises a clear `ValueError` for more than two pieces.

## Existing tests changed

- `tests/contracts/test_contracts_a4.py`, `test_contracts_q4.py`, `test_serialization.py`, `test_corridor_plan.py` (I01, S03…): `CONTRACTS_VERSION == "1.6.0"`.
- `tests/contracts/test_corridor_plan.py`: `K02_existing_unchanged` (changed-file list gains `geometry.py`, `schemas/Layout.schema.json`); `K04_validators` (3 pieces are valid now: 13 pieces and 0 pieces are rejected, message "1 to 12"); `B02_footprint_unchanged` (the frozen A.1 files may now differ by the lines G.1 replaced, `G1_REPLACED_LINES`).
- `tests/contracts/test_models.py`: `Junction` added to the instance list of `M04`.
- `tests/contracts/test_footprint.py` (`F05_unsupported`), `tests/geometry/test_geometry_units.py`, `tests/optimize/test_optimize_fastreal_q3.py` (`cached_realize_early_failures`), `tests/topology/test_topology_units.py` (`unsupported_footprint`), `tests/program/test_program_feasibility.py` (`F3_non_grammar_footprint…`): they used a U / C footprint as the "unsupported footprint"; those decompose now, so they use a 14-step staircase (14 pieces) instead. Same assertions otherwise.

## Spec issues

1. **Courtyards cannot be expressed**: `ModulePolygon` has no holes and the site intake (`program/site.py`, outside this ticket's files) rejects them (`E_SITE_INVALID`). Following the intent, `ModulePolygon` gained an optional `holes` field (part of the 1.6.0 amendment, hidden when empty); engine, checks and tests handle it, and the ring test swaps the module footprint into a prepared input. A workbook / `site.yaml` with a courtyard is still refused at intake: lifting that is a follow-up in `ale.program`.
2. **"Larger aspect deviation from the wing depth"** is not defined. Implemented as: fewest pieces, then fewest J2 junctions (wings hang off the spine they grow from; without it a U splits into columns with a J2 and a spine along the short side), then the smallest largest aspect ratio (the L rule), then the sorted piece tuples.
3. **Restriction not in the RD**: in a plan of more than two pieces, every J1 child and every piece incident to a J2 junction has exactly one band (the L rule for the J1 secondary, extended); only the root (and pieces with no junction constraint) may have several bands, with the usual connector.
4. `program/feasibility.facade_usable_mm` (outside the files of this ticket) still uses the single legacy `fp.cut`; for more than two pieces `cut` is `None`, so the façade estimate ignores the inner cuts (an over-estimate). `optimize/polish.py` needed a one-line change (`FingerBay.with_rooms`, so a rebuilt junction finger keeps `junction_to`).
5. The RD's "spanning tree rooted at the largest piece" leaves the tree choice open for rings; BFS in `(y, x)` order was chosen (documented in `decompose_footprint`).
