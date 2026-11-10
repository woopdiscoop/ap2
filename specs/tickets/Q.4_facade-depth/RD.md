# Ticket Q.4 — Maximum depth from the façade · Requirements Document

> **Starts after Q.3 merges** (same geometry files). Context = this file, `eval.md`, contracts, `ale.geometry`,
> `ale.topology`, `ale.optimize`, `specs/design/arep_ms_gaps.md` (gap 2). Includes a **contract amendment** (§2).

## 1. Purpose
AREP-MS rule: offices, meeting rooms, management rooms and reception rooms get a window **and a depth ≤ 7.20 m from the façade**.
ALE checks façade contact only, so the test floor had a 9.60 m-deep President's office.

## 2. Contract amendment (contracts 1.4.0, backward compatible)
`FacadeConfig.max_depth_m: float | None = None` (None = rule off, the default). Taxonomy unchanged. New violation code
`FACADE_DEPTH` (hard: counted in `n_hard` like `NO_FACADE`). Regenerate schemas, `CONTRACTS.lock`, contract tests.

## 3. Rule
For a `needs_facade` room with façade contact: its **depth** is its extent perpendicular to its longest exterior
contact. With exterior contact on two opposite sides (a through room), the limit is `2 × max_depth_m`. Violation when
depth > limit, with no tolerance. In modules the limit is `floor(max_depth_m · 1000 / module_mm)` (doubled for a through room).

## 4. Geometry consequences
- **Realiser**: for exterior blocks, the depth search (3.3 §5.1 / Q.3 key) treats `D > floor(max_depth/module)` as one
  `FACADE_DEPTH` per affected room (same key position as the Q.3 façade count).
- **Aspect vs depth**: a room with `T > 2 · Dmax²` cannot satisfy both depth ≤ Dmax and aspect ≤ amax. For such
  rooms, **depth wins**: their `ASPECT` violation becomes soft (not counted in `n_hard`, still reported). Document it
  in the report, which lists those rooms under "proportion > 2 imposed by the depth rule".
- **Seeding/moves**: a room that cannot fit a block's depth is preferred in an exterior block whose depth fits
  (seed assignment and G9 façade pull consider `FACADE_DEPTH` like `NO_FACADE`).

## 5. Out of scope
Splitting open spaces into several rooms (the programme defines rooms; we never add spaces). Two-façade "through"
blocks are allowed only where the grammar already produces them (1-block bands at the piece boundary).

## 6. Scope change (user, 2026-11-10)
The 7.20 m depth is not absolute: rooms may be deeper, and the limit is to be tuned from the corpus of built plans
(ticket R.8). New `FacadeConfig.max_depth_hard: bool = False`. Default behaviour of the rule = **soft**: `FACADE_DEPTH`
reported but not hard, cost term `facade_depth` (weight in `[optimizer.weights]`, default 1.0) =
Σ max(0, depth − limit)/limit over `needs_facade` rooms ÷ number of rooms; ASPECT stays hard. With
`max_depth_hard = true` the rule behaves as §2–§4 (hard depth, soft aspect for deep rooms). D03–D05 run in hard mode;
new D08 checks the soft mode.
