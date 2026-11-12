# Ticket R.8 — Depth, width and façade rules learned from built plans · Requirements

> Context = this file, `eval.md`, `specs/design/research_roadmap.md` (row R.8), user decision U-9 (7.20 m is not
> absolute; tune from built plans), Q.4 (`facade.max_depth_m`, `max_depth_hard`, `FACADE_DEPTH`), `ale.rulebook`
> (`build_rulebook`, `stats.py`, `blend.py`, `report.py`), `ale rulebook build`. Contracts 1.7.0 → **1.8.0**
> (additive, backward compatible).

## 1. Purpose
The realiser's depth limit is one number (7.20 m) for every room type. Built plans say more: a cellular office is
about 4.8–5.7 m deep and 2.4–3.6 m wide (one to one-and-a-half bays), a meeting room deeper, sanitary rooms need no
façade at all. R.8 learns per type, from the corpus, the **depth from the façade**, the **façade width** and the
façade length per m², stores them in the rulebook, and uses the depth p90 as the soft depth limit per type. The width
statistics also feed the bay-first planning that follows (M.4 proposal).

## 2. Contract (1.8.0, additive)
`TypeStats` gains optional `depth_m: Quantiles | None`, `facade_width_m: Quantiles | None`,
`facade_m_per_m2: float | None`, `n_facade_samples: int = 0`. Rulebooks written before 1.8.0 load unchanged;
schemas and `CONTRACTS.lock` regenerated; version tests moved to 1.8.0.

## 3. Learning (`ale.rulebook`)
- For each room of a corpus plan with scale: the façade edges (room edges on the plan's exterior outline); depth =
  room extent perpendicular to its longest façade edge; façade width = length of that edge. Rooms without a façade
  count for `facade_m_per_m2 = 0` and not for depth/width.
- Quantiles (p10/p50/p90) per type, fidelity-weighted as the existing stats; < 5 façade samples → fields left None and
  the report says « échantillon insuffisant ». Blending (`blend.py`) with the seed rulebook follows the existing rule.
- Report (`report.py`): per type, a table depth p50/p90, width p50/p90, façade m/m², n samples.

## 4. Use
- Realiser soft depth limit per type = `depth_m.p90` when present, else `facade.max_depth_m` (unchanged). With no
  learned depths every output is **byte-identical** (M206 digests).
- `max_depth_hard` keeps its meaning (applies to the config value only).
- Plan report: per type, « votre plan / plans construits » (depth p50 of the plan vs corpus p50/p90).

## 5. Files (ownership)
`src/ale/contracts/models.py` (TypeStats fields only), schemas, `CONTRACTS.lock`, contract version constant + version
tests, `src/ale/rulebook/**`, `src/ale/geometry/blocks.py` (per-type depth limit only), `src/ale/report/**` (the
comparison table only), `tests/rulebook/**`, `tests/contracts/**` (version bump only), `tests/geometry/test_geometry_r8.py`,
`specs/tickets/R.8_depth-rules/eval_report.md`. Test helpers not imported as `conftest`. Never weaken a test. Commit
early and often.
