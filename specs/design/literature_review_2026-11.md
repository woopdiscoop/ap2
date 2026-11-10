# Literature check — "Master Research Database: Program-to-Diagram Generation" (2026-11-10)

Source: the user's research database (PDF, 4 pages, ~45 links). Read: 13 arXiv abstracts; full text of the 2025
survey, the RLVR paper, the Utrecht SA thesis, Liggett 2000; and (second pass, 2026-11-10) Designing with Space
Syntax (eCAADe 2013), the GNN floor-plan system (eCAADe 2025), Shopgenerator v2 (TU Wien), the Liège thesis on AI in
design, the Nanjing LLM graph paper, the structural-schema GAN paper, and the abstract of the multi-storey GNN
preprint. **Not readable** (the publishers refuse automated access, HTTP 403): MDPI (urban blocks, NSGA-II, POE,
human–AI education), ScienceDirect, Cambridge repository. Not examined: ethics/copyright sources (outside ALE's
technical scope).

## 1. Where ALE sits
ALE = programme (Excel) + site → slicing-type corridor grammar → simulated annealing with hard rules → DXF/SVG.
This is the **optimisation lineage** (Liggett 2000: quadratic assignment, graph-theoretic methods, improvement procedures and simulated annealing), not the
deep-learning lineage. The database confirms that this is a defensible position for our use case:

| Finding in the literature | Consequence for ALE |
|---|---|
| Learning methods (House-GAN++, HouseDiffusion, ChatHouseDiffusion, HouseMind, RLVR) are trained and tested on **RPLAN-type single-floor Asian housing**, 4–8 rooms. The survey names "single dataset, poor generalisation" as the shared limitation; it does not mention offices or corridors at all. | No dataset exists for 60–170-room public office programmes. Training a generator is not an option; our rule/optimisation approach is the realistic one. Our corpus stays a source of *statistics* (rulebook), not of training data. |
| RLVR (2026) is the first LLM work to respect **numerical** constraints, and only total area + connectivity; overlaps still occur at higher room counts; circulation, egress, daylight, codes are explicitly "not modelled". | ALE already guarantees exact tiling, per-room areas, corridor access and façade contact by construction. These are our differentiators and should be stated as such in the academic write-up. |
| Utrecht thesis (2021): SA with 3 move types on a grid, residential, corridors as a penalised room; reports "diverse but slow, quality slightly reduced". | Same family as ALE, at a smaller scale and without access guarantees. Supports our corridor-grammar decision (U-6). A useful baseline to cite and compare with. |
| Liggett (2000): three objective families (adjacency/communication cost, area/shape, constraints); improvement procedures get stuck in local optima; multi-floor handled as "stacking" (assign activities to floors) then "blocking" (lay out each floor). | Matches the budget sensitivity observed in Q.3 (P60 result varies 6–10 with iteration count). Suggests the **two-stage multi-storey** approach for v2: stack/zoning first, then per-floor layout. |
| Boundary-constrained diffusion (2026): optimising realism collapses diversity; proposes a Diversity Score. | ALE has no diversity measure for variants. Cheap to add. |
| VLM vectorisation (FloorplanVLM 2026, "pixels-to-JSON") beats classical CV on rasters; "VLMs can parse floor plan maps" but degrade on large open areas. | Our raster reader (classical CV) under-segments rendered plans; I.2 only uses Claude for *labels*. A VLM *geometry* reader is the natural next corpus step. |
| Hybrid loop in the database (§3): LLM parses program → generate → VLM evaluates → evolutionary optimisation → human review. | ALE has the middle; P.2 covers program parsing by rules. Missing: a visual critique step and multi-objective (Pareto) output. |

### Second pass — additional findings
| Finding | Consequence for ALE |
|---|---|
| **Designing with Space Syntax** (Nourian et al., 2013): bubble diagram → planar embedding → real-time depth / integration / control / choice measures; explicitly a "see-move-see" designer loop, not an automatic solver. | ALE already builds the adjacency graph (3.2). Computing **depth from the entrance and integration** per room on the *generated* layout is cheap and gives the architect the "organisation et distribution" reading (public rooms shallow, management deep). Report-only at first. |
| **Shopgenerator v2** (TU Wien, 2015), the only non-residential generator in the list: force-based circle packing for topology, then a k-d tree (slicing) for geometry, for early-stage store drafts. | Same two-step structure as ALE (force embedding → slicing realisation), reached independently. Confirms the architecture; nothing to change. |
| **GNN floor plans with exterior constraints** (Osaka, eCAADe 2025): accuracy 0.74, still residential; **multi-storey GNN** (same group): floor plans derived from a volumetric design. | Learning methods are not yet reliable enough to replace rules; the multi-storey work starts from a *given volume*, which matches the AREP-MS method (massing first). |
| **LLM → functional graph** (Nanjing, 2025): chain-of-thought + injected architectural knowledge to turn a text brief into a room/relationship graph. | The right place for an LLM in ALE is **before** the solver: derive adjacency requirements (the Annexe has none) from the functional programme text. Output is reviewed by the architect, then feeds `adjacent_to`. |
| **Liège thesis** (2025, literature + architect interviews): consensus that AI belongs in the **early phases**, the architect keeps the "premier coup de crayon"; marginal role in detailed phases. | Matches ALE's positioning (design studies for refinement, not final plans). Worth citing in the academic framing. |
| Structural-schema GAN (64 % success), BIM generation (2016). | Out of scope for v1 (structure, BIM). |

## 2. Ideas worth adopting (ranked by value / cost)
1. **Restarts / population instead of one annealing chain** (Liggett; GA literature). Run K short chains from
   different seeds and keep the best; removes the budget sensitivity seen in Q.3 at equal total cost.
2. **Pareto set of variants** (NSGA-II idea, without changing the optimiser): keep non-dominated variants over
   (hard violations, adjacency, façade quality, circulation %) and show them side by side in `summary.md`.
3. **Diversity score between variants** (plan edit distance on room positions), reported and optionally enforced.
4. **VLM critique of a rendered variant** (database §3; "each visual defect becomes an evaluator rule" in the
   AREP-MS method): Claude reads `preview.svg` + the report and returns structured defects. Advisory only.
5. **VLM geometry reader** for raster/scanned plans (pixels → room polygons JSON), validated against the classical
   reader; feeds the corpus.
6. **Two-stage multi-storey** (stacking then per-floor), the main v2 item already in `arep_ms_gaps.md`.
7. **Adjacencies from the functional programme by LLM** (Nanjing paper): Claude proposes `adjacent_to` / `avoid`
   pairs with a reason each, from the detailed functional programme; the architect validates the table.
8. **Space-syntax measures in the report**: depth from the entrance and integration per room.
9. **Explainability** (gap named in the database): the report already lists violations and cost terms; add a
   plain-language "why this variant" paragraph generated from them (no LLM needed).

## 3. Not recommended for this project
- Fine-tuning an LLM/diffusion generator (no data for our building type; cannot guarantee hard rules).
- Text-to-plan prompting as the generator (Architext, Text-to-Layout: residential, no numerical guarantees).
- BIM/IFC export and Revit/Dynamo agents — out of scope in the directive (IFC is a v2 candidate).
- Urban-block NSGA-II studies — a different scale.
