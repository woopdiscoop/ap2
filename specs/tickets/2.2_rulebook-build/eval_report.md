# Ticket 2.2 — Rulebook build · Evaluation report

Branch `ticket-2.2-rulebook-build` (from `claude/new-session-2hmd3s` @ 48f1f9f).

## Results

| ID | Test | Result |
|---|---|---|
| K1 | `tests/rulebook/test_rulebook_eval.py::test_K1_adjacency_p` | pass — p = 0.7, n_support 4 |
| K2 | `::test_K2_fidelity_weights` | pass — support 3.5, hits 2.5 asserted, n_support = round(3.5) = 4 |
| K3 | `::test_K3_min_support` | pass — seed entry kept / pair omitted (with report note) |
| K4 | `::test_K4_quantiles` | pass — hand-computed weighted quantiles; RASTER room ignored; aspect p90 3.0 → 2.0 with note |
| K5 | `::test_K5_core_offset` | pass — exact dx/dy, fidelity-weighted mean, plan without core not used |
| K6 | `::test_K6_orientation` | pass — office S = 1.0; < 3 north plans → seed kept; 3 plans → blended |
| K7 | `::test_K7_blend` | pass — 0.8 / 0.4 / n = 10 / k = 10 → 0.6; quantile order preserved (200 random triples) |
| K8 | `::test_K8_output_valid` | pass — YAML round trip, kind, `mined-YYYY-MM-DD-<8 hex>`, source_mix |
| K9 | `::test_K9_deterministic` | pass — shuffled topologies and geometries → identical YAML and report bytes |
| K10 | `::test_K10_cli` | pass — DXF workspace, `--seed-rulebook`, 3 files written, exit 0, no-scale plan skipped and reported |
| K11 | `tests/rulebook/test_rulebook_gates.py::test_K11_gates` | pass — ruff, ruff format --check, mypy strict, lock --check |

Extra unit tests: `tests/rulebook/test_rulebook_units.py` (16 tests).

## Gates

- Whole suite: 980 passed, 7 skipped, 2 xfailed (one failure in a first run — `test_P02_no_absolute_paths`
  flagged the plan label format `sha/p0/0`; the label is now `sha p0 n0`, rerun green).
- `ruff check src/ale tests`, `ruff format --check`: clean. `mypy` (strict, `src/ale`): clean.
- `python -m ale.contracts.lock --check`: OK (no contract touched).
- Coverage `ale.rulebook`: blend 100 %, build 100 %, report 99 %, stats 98 %, `__init__` 100 %;
  CLI `rulebook.py` 100 %. Whole project 98 %.

## Spec issues, ambiguities and literal readings

1. **North in `plans_meta.csv` (K10).** RD §3 reads `north_angle_deg` from `files.meta_json`, but the Ticket 1.1
   meta parser only knows the columns `filename,page,scale_1_to,units,building_type,floor,exclude`: a
   `north_angle_deg` column is ignored with a warning and never reaches `meta_json`. `src/ale/corpus/` is outside
   this ticket, so K10 writes the CSV (asserting the warning) and then sets `meta_json.north_angle_deg` with SQL.
   The reader accepts the key at top level or under `pages.<page>` (same layout as `units`). **Follow-up:** add
   `north_angle_deg` to `ale.corpus.meta.COLUMNS` (numeric field).
2. **Inputs not on `Rulebook`.** `fidelity_weights`, `laplace_alpha`, `blend_k`, `min_support` are read from
   `AleConfig.rulebook` (RD writes `rulebook.…`); `shape.aspect_max` from `AleConfig.shape`.
3. **`build_rulebook` signature.** Extra keyword-only arguments: `min_support` (CLI override), `north`
   (`(sha, page) → degrees`, since `PlanGeometry` has no north), `skipped` (upstream skips for the report),
   `today` (UTC date for `version`/`date`, injectable for tests). Topologies and geometries are matched by
   `(sha, page, plan_index)`; a topology without a geometry is skipped (“géométrie absente”).
4. **Weighted quantile definition.** “Linear interpolation on the weighted CDF” is not unique. Chosen: plotting
   position `(S_i − w_i/2)/S` (Hazen for equal weights), clamped outside the first/last positions.
5. **Aspect clipping.** When the mined p90 exceeds `aspect_max`, every quantile is clipped with `min(q, max)` so
   that `p10 ≤ p50 ≤ p90` holds. Clipping is applied to the mined value before blending.
6. **Same-type pairs** `(a, a)`: a plan “contains both types” only with ≥ 2 rooms of type `a`.
7. **`n_support = round(support)`** uses Python `round` (half to even), literally.
8. **Blending.** An adjacency pair is “present in the seed” only when listed explicitly (unlisted pairs use
   `default_p`, already the Laplace `p0`), so the seed influences listed pairs twice (prior and blend) as RD §3/§4
   literally specify. `n` for adjacency = the weighted support (float). Blended quantiles carry the mined `n`.
   Seed types without mined rooms keep the seed values; mined data are blended whenever n ≥ 1 (no min_support gate
   for types already in the seed). A mined-only type with < 3 north-known plans gets orientation 0.0 everywhere.
9. **Core offset.** “Union of rooms' bbox” read as the bounding box of all rooms; `(fx, fy)` its centre. Service-core
   rooms = types with `service_core: true` (incl. VERTICAL stair/lift). Plans without one are not used. All
   fidelities count (RD restricts only aspect/area). Without data and seed: `(0, 0, n = 0)`.
10. **Orientation.** Façade edges = room exterior edges within 0.3 m of the outer boundary, using the Ticket 2.1
    geometry helpers (`ale.mining.topology` private functions, imported to stay consistent with
    `PlanTopology.exterior`); bearing = outward normal, `compass_bearing_deg` + `bearing_bin`, with the north angle
    applied in the metric Y-up frame. The type-independent share uses every room (typed or not). Lengths are
    fidelity-weighted. Types in VERTICAL are allowed (only SPECIAL/CIRCULATION/unknown are excluded).
11. **Version / date.** `version` = `mined-<UTC date>-<first 8 hex of SHA-256(inputs)>` also when `kind` is
    `blended` (RD literal); `date` = the same UTC date. Determinism is per day: the same inputs on another day
    change the date in `version`.
12. **Numbers** are rounded to 9 significant digits (the precision of `canonical_json`) so that YAML bytes do not
    depend on summation noise; sums are done in sorted plan order.
13. **CLI.** An unreadable/invalid seed file → usage error (exit 2, `--seed-rulebook`). Outputs are written
    atomically (temp file + replace); `rulebook.sqlite` is rebuilt each run with the used plans only (skipped plans
    are listed in the report).
