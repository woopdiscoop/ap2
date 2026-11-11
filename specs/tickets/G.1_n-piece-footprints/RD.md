# Ticket G.1 — Exact plans in any orthogonal footprint (N pieces, several junctions) · Requirements Document

> Context = this file, `eval.md`, `specs/design/corridor_grammar.md` (§5 L shapes J1/J2, §8 bands),
> `specs/design/research_roadmap.md` (G.1, U-12), contracts (`footprint.py`: `FootprintPieces`, `decompose_footprint`;
> `corridor_plan.py`: junction bays), `ale.geometry` (`junction.py`, `realize.py`), `ale.topology` (`seed.py`),
> `ale.optimize` (moves). Includes a **contract amendment (1.6.0), backward compatible**: rectangles and L shapes must
> give byte-identical results.

## 1. Purpose
Phase 1 (G.3 form, G.2 parti) produces U, T, H, comb, Z and courtyard outlines; the exact-plan engine handles only
rectangles and L shapes. Generalise the L logic to a **tree of pieces**.

## 2. Contract amendment (1.6.0)
- `Junction(parent: int, child: int, kind: "J1" | "J2", cut: (ModulePoint, ModulePoint), facing_block: "A" | "B" | None)`.
- `FootprintPieces.junctions: tuple[Junction, ...] = ()`; for 1–2 pieces it holds 0 or 1 junction equal to today's
  `junction` / `cut` / `facing_block` fields, which stay (filled as today) so existing code and fixtures are unchanged.
- `decompose_footprint`: for > 2 pieces, cut the orthogonal polygon at reflex vertices into rectangles, choosing cuts
  that give wing-like pieces (minimise the number of pieces, then the larger aspect deviation from the wing depth —
  tie rules deterministic and documented); build the contact graph; spanning tree rooted at the largest piece
  (ties: lowest-leftmost); each tree edge classified J1 / J2 exactly as the L rule (cut parallel or perpendicular to the
  parent's spine). **Courtyards** (holes): the ring is decomposed into ≥ 4 pieces; the contact not in the tree is an
  *open contact* (rooms may meet there, no corridor link required). Polygons that cannot be decomposed into ≤ 12
  pieces → clear error.
- `CorridorPlan` junction bays: `junction: bool` gains an optional `junction_to: int | None = None` (child piece index)
  so a parent piece can host several junction fingers; validation: one junction bay per J1 child, in the parent's
  facing block for that child; `None` keeps the 1-child meaning.
- Schemas, `CONTRACTS.lock`, contract tests updated (follow A.3 / Q.4 / A.4).

## 3. Engine
- `geometry.junction`/`realize`: realise pieces in tree order (root first); each child's spine band follows its
  junction exactly as today's J1/J2 (offsets, connector on the cut side for multi-band parents); circulation of all
  pieces is one connected set; open contacts are checked only for overlap.
- `topology.seed`: band counts per piece as today; junction bays inserted for every J1 child; capacity estimate per
  piece; repair moves unchanged.
- `optimize.moves`: moves already piece-aware stay valid; G5 (move a zone run to another block/piece) works across all
  pieces.

## 4. Files (ownership)
`src/ale/contracts/**`, `src/ale/geometry/**`, `src/ale/topology/**`, `src/ale/optimize/moves.py`, `tests/contracts/**`,
`tests/geometry/**`, `tests/topology/**`, `tests/optimize/test_optimize_moves*.py`, `specs/tickets/G.1_n-piece-footprints/eval_report.md`.
Do not touch `src/ale/form/**` (G.3).
