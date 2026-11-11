# Research-driven roadmap (2026-11-10)

From `literature_review_2026-11.md`. Each item names what it fixes, how we will know it worked, and what it depends on.
Order = value / cost. Items marked (v2) need the user's approval to widen the v1 scope of the directive.

| # | Ticket | What | Measurable target | Depends on | Size |
|---|---|---|---|---|---|
| 1 | **R.1** multi-start annealing | K short chains from different seeds instead of one long one, same total iteration budget; keep the best by (hard, cost). Deterministic. | P60 `NO_FACADE ≤ 6` and hard ≤ 10 at **every** total budget in {1000, 1100, 1200, 1300, 1500} (today: 6–10 / 9–13); P25 ≤ 5; P8 0. | Q.4 merged (same files) | S |
| 2 | **R.2** variant set + diversity | `ale generate --variants N` keeps the non-dominated variants over (hard, required-adjacency, façade/orientation, circulation %), reports a diversity score (share of rooms whose block differs), side-by-side table in `summary.md`. | N=6 on P25: ≥ 3 non-dominated variants, pairwise diversity ≥ 0.2, table present. | R.1 | S |
| 3 | **R.3** space-syntax measures | Depth from the entrance and integration per room on the generated layout (door graph = room–circulation contacts); section in `report.md`; public rooms shallow / management deep as an optional soft cost term (weight 0 by default). | Hand-computed values on a 6-room fixture match exactly; report section present. | — (export + evaluate) | S |
| 4 | **R.4** explain the variant | Plain-language paragraph per variant from the cost terms and violations (no LLM): what is good, what is broken, what to change in the programme/site to fix it. | Golden-text tests on 3 fixtures (FR). | R.3 | XS |
| 5 | **R.5** adjacencies from the functional programme | `ale program adjacency --text FILE`: Claude proposes `adjacent_to` / `avoid` pairs with a reason and a level (N1–N4) → a review table (xlsx); the architect edits it; `--apply` writes them into the programme. Opt-in, cached, mocked tests. | On a synthetic brief with 12 stated relations: all 12 recovered by the mock; table round-trips; nothing applied without `--apply`. | P.1, P.2 (done); needs the user's functional programme for a real trial | M |
| 6 | **R.6** visual critique | `ale critique --variant DIR`: Claude reads the rendered plan + report and returns structured defects (room, kind, why). Advisory file `critique.md`; never changes the layout. | Mocked: schema-valid output, defects mapped to existing room ids. Real trial on 3 variants reviewed by the user. | P.1 | S |
| 7 | **R.7** VLM geometry reader | Raster/scanned plans → room polygons by Claude (pixels → JSON), cross-checked with the classical reader; disagreements flagged for `ale review`. | On the synthetic raster fixtures: room count exact, IoU ≥ 0.9 (mock); on 10 real corpus plans: user review. | I.2, X.1 | M |
| 8 | **R.8** depth and shape rules from built plans | `ale rulebook build` also learns, per room type, the **depth from the façade** (p50 / p90) and façade length per m² from the corpus; the rulebook carries them; the realiser's soft depth limit per type = corpus p90 (fallback: `facade.max_depth_m`). Report shows "your plan vs built plans" per type. | On the synthetic corpus: learned p50/p90 equal the constructed values; a type with < 5 samples falls back to the config value and says so. | Q.4 (soft depth), corpus with scale | M |
| 9 | **R.9** Voronoi seeding (experiment) | Weighted L1 Voronoi in the footprint as the topology hint for the seeder (neighbours, façade rooms, band order); grammar unchanged. | Adopted only if mean final hard is lower on P60 and not higher on P25 / AREP floor, 5 seeds, same budget. | R.1 | S–M |
| 10 | **M.1–M.3** multi-storey (v2) | Liggett's two stages: **stacking** (assign entities to floors under floor rules, e.g. Présidence/DAP/DGS top floor; balance floor areas) → **blocking** (existing per-floor engine) → stacked cores and wet rooms as fixed bays shared across floors. | AREP-MS Région programme on a given bar footprint, R+3: every floor realises; top-floor rule met; cores aligned. | Q.4, R.1; directive change | L |

### Building form (user decision U-12)
The footprint is a design output, not only an input. Three steps, v2:
- **G.1 any orthogonal footprint**, including courtyards (holes), U, T, H, combs: decompose into rectangular pieces
  (generalising the L-shape J1/J2 junctions to N pieces and ring corridors around a courtyard). Freeform outlines are
  approximated on the 60 cm grid with orthogonal rooms inside; curved façades stay out of scope.
- **G.2 massing typologies**: a parametric family (bar, L, U, courtyard/ring, comb, T, hybrids) sized from the programme
  (wing depth from the room depths: about 2 × 7.2 m + corridor), placed on the buildable zone with setbacks; each
  candidate scored on capacity per floor, orientation of the long façades, compactness, prospects (courtyard ≥ H/2),
  site coverage. The AREP-MS method's "population of partis".
- **G.3 form-finding by cell growth**: grow the programme cells (R.9) on the whole buildable zone with no fixed outline;
  the mass that emerges is snapped to the nearest typologies of G.2.

### Multi-storey requirements (user decision U-10)
Stackability first: (1) **vertical cores fixed across floors**: stairs, lifts, shafts, wet rooms (sanitary, cleaning,
technical) occupy the same grid cells on every floor; (2) **room stacking**: a room placed above another of the same
footprint is rewarded, and floors share one bay rhythm (same bay widths along each band where possible);
(3) **structural regularity**: one column grid for all floors (multiple of the 60 cm module), partition lines
aligned to it where possible. Approach: lay out the most constrained floor first (or a "typical floor"), freeze its
cores and bay rhythm, then lay out the other floors inside that skeleton; scored by a stackability metric (share of
room area with an identical room above / below, core alignment = hard).

Not planned: learned generators, text-to-plan prompting, BIM/IFC, urban scale (see the review, §3).
