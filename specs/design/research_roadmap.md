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
| 8 | **M.1–M.3** multi-storey (v2) | Liggett's two stages: **stacking** (assign entities to floors under floor rules, e.g. Présidence/DAP/DGS top floor; balance floor areas) → **blocking** (existing per-floor engine) → stacked cores and wet rooms as fixed bays shared across floors. | AREP-MS Région programme on a given bar footprint, R+3: every floor realises; top-floor rule met; cores aligned. | Q.4, R.1; directive change | L |

Not planned: learned generators, text-to-plan prompting, BIM/IFC, urban scale (see the review, §3).
