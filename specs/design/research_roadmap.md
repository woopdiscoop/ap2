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

### Target pipeline (v2): where the cell method sits
| Phase | Question | Method | Tickets | Output (reviewed by the architect) |
|---|---|---|---|---|
| 0 Inputs | What is asked, where? | Annexe import, site + anchors, rulebook learned from built plans | P.2, A.4, R.8 | programme, site, rules |
| 1 Form (parti) | What shape, how many floors? | Cell growth with the outside as a connected type, then massing types | G.3, G.2 | building outline(s) per height option |
| 2 Stacking | Which entity on which floor? | Floor assignment, fixed cores and wet stacks | M.1 | stacking diagram |
| 3 Cell diagram | What goes where on each floor? | Whole-programme cell growth: anchors, façade shares, adjacencies | R.9 | cell diagram per floor |
| 4 Plan | Exact rooms and corridors | Corridor grammar + annealing (multi-start), depth rule | 3.3, Q.3, Q.4, R.1, G.1 | DXF/SVG plans, report |
| 5 Evaluate | Is it good, which variant? | Checks, space syntax, visual critique, variant set | R.2, R.3, R.6 | report, critique, comparison |
Loops: a failure in phase 4 (e.g. rooms without façade) is fixed upstream (phase 3 façade shares, phase 1 form);
each defect seen in phase 5 becomes a rule (AREP-MS method). The cell diagram (phases 1–3) replaces the current
abstract seeding and is a checkpoint the architect can edit (anchors, hard lines) before the exact plan.

### Building form (user decision U-12)
The footprint is a design output, not only an input. Three steps, v2:
- **G.1 any orthogonal footprint**, including courtyards (holes), U, T, H, combs: decompose into rectangular pieces
  (generalising the L-shape J1/J2 junctions to N pieces and ring corridors around a courtyard). Freeform outlines are
  approximated on the 60 cm grid with orthogonal rooms inside; curved façades stay out of scope.
- **G.2 parti generation** (user decision U-16: a good solution solves several problems at once). A parti = a few
  strong decisions generated together, as genes: massing type (bar, L, U, comb, courtyard, terraced), orientation of
  the long façades, core position, circulation figure (spine, loop, comb fingers), entrance/forecourt relation,
  terraces. The programme is placed *by* these decisions (phases 2–4), never patched after. Scoring:
  - **forcedness** = share of requirements met by the parti before any local repair + number of local exceptions
    the plan needed (end strips, fillers, odd room shapes, rooms moved to get a façade, dead ends) — lower is better;
  - **parti card** in the report: each major element and the problems it solves (e.g. the courtyard: daylight for
    the deep wing + forecourt + separation of the two institutions); an element that solves only one problem is
    flagged as a possible patch;
  - all jury criteria evaluated jointly (non-dominated set, R.2), never one after another.
- **G.2 massing typologies** (as the parti's form gene): a parametric family (bar, L, U, courtyard/ring, comb, T, hybrids) sized from the programme
  (wing depth from the room depths: about 2 × 7.2 m + corridor), placed on the buildable zone with setbacks; each
  candidate scored on capacity per floor, orientation of the long façades, compactness, prospects (courtyard ≥ H/2),
  site coverage. The AREP-MS method's "population of partis".
- **G.3 form-finding by cell growth, with the outside as a space type** (user proposal, 2026-11-11): the whole site is
  gridded; "outside" is one more type, seeded on the site boundary and the setbacks; rooms grow from their anchors;
  rule: **all outside cells stay connected to the site boundary** (no growth step may disconnect it: digital-topology
  "simple point" test). The building's shape is what remains. Consequences: *façade* becomes "touches outside" (no
  fixed façade edges); *depth* becomes the distance to the nearest outside cell (≤ 12 cells for 7.20 m); orientation
  = which side the outside is on. Extra rules so the form is architectural: a **courtyard** type (enclosed outside,
  allowed only if its short side ≥ H/2); minimum outside width (no slivers, ≥ setback / isolation distance); a
  compactness term against façade-hungry sprawl; optional "n buildings" (AREP-MS: 2). Raw shapes are ragged and are
  then snapped to G.2 typologies (wings of constant depth).

### Multi-storey requirements (user decision U-10)
Stackability first: (1) **vertical cores fixed across floors**: stairs, lifts, shafts, wet rooms (sanitary, cleaning,
technical) occupy the same grid cells on every floor; (2) **room stacking**: a room placed above another of the same
footprint is rewarded, and floors share one bay rhythm (same bay widths along each band where possible);
(3) floor outlines may recede upwards to make **terraces** (user, U-15): cores, wet stacks and the column grid stay
continuous, the floor plate above sits within the one below unless an overhang is a deliberate choice; (4) **structural regularity**: one column grid for all floors (multiple of the 60 cm module), partition lines
aligned to it where possible. Approach: lay out the most constrained floor first (or a "typical floor"), freeze its
cores and bay rhythm, then lay out the other floors inside that skeleton; scored by a stackability metric (share of
room area with an identical room above / below, core alignment = hard).

Not planned: learned generators, text-to-plan prompting, BIM/IFC, urban scale (see the review, §3).
