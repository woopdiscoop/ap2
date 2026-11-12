# Ticket R.8 — Evaluation report

Contracts 1.7.0 -> **1.8.0** (additive). Branch `worktree-agent-ad4987c9143f2d401` (from `8c65473`).

## Results

| ID | Check | Result | Figures / evidence |
|---|---|---|---|
| R801 | Constructed depths / widths per type | PASS | Offices of depth 4.8 / 5.1 / 5.4 / 5.7 / 6.0 m, width 3.0 m: learned depth p10 / p50 / p90 = 4.8 / 5.4 / 6.0, width p50 = p90 = 3.0, `facade_m_per_m2` = 0.185 (1 / 5.4). Meeting rooms 6.0 x 6.6: depth p50 6.6, width p50 6.0. Rooms with no façade count for the m/m² ratio only (5 façade offices 3 x 5 m + 5 enclosed 3 x 4 m: 15 m of façade over 135 m²). Tests `tests/rulebook/test_rulebook_r8.py::test_R801_*` |
| R802 | < 5 façade samples | PASS | 4 samples: `depth_m`, `facade_width_m`, `facade_m_per_m2` None, `n_facade_samples` 0, report row « échantillon insuffisant », fields absent from the YAML / canonical JSON. A seed's values are kept when the sample is insufficient; blend with the seed above 5 samples. Realiser: `Consts.type_dmax == ()` and output byte-identical to the base rulebook (`test_geometry_r8.py::test_R802_*`) |
| R803 | Contract 1.8.0 | PASS | The three YAML rulebooks of the repository (seed, `examples/rulebook_test.yaml`, `tests/program/data/rulebook_test.yaml`) load unchanged with the same `content_sha256` after a round trip; `Rulebook.schema.json` and `CONTRACTS.lock` regenerated; `lock --check` and `export_schemas --check` OK |
| R804 | Realiser per-type limit | PASS | Rulebook office `depth_m.p90` = 5.4 m on a plate where the config says 7.2 m (soft): `type_dmax = (("office", 9),)`; the 10-module-deep office gets one `FACADE_DEPTH` ("depth 10 > 9 modules"), cost term `facade_depth` = 0.5 x (10-9)/9; the meeting room (12-module limit) is not flagged. Symmetric test for a learned meeting-room limit; learned 7.2 m over a configured 5.4 m relaxes the office only. `RealizeCache` with the rulebook is identical to `realize`; a cache built for another rulebook's depth limits raises |
| R805 | Byte identity with no learned depths | PASS | M206 (P08 / P25 / P60 digests, `test_geometry_m2.py`) passes unchanged; realiser outputs equal for 4 configs x 3 plate heights; the serialised rulebook carries none of the new keys |
| R806 | French reports | PASS | Rulebook report: section « Profondeur et largeur de façade » (depth p50 / p90, width p50 / p90, façade m/m², n, source). Plan report: section « Profondeur : votre plan / plans construits » (plan median vs corpus p50 / p90, « plus profond / moins profond / dans la plage »); absent when the rulebook has no learned depth, so reports are unchanged |
| R807 | Real corpus run | NOT RUN | No scaled corpus exists in the workspace (only pytest temporary workspaces); no figure for the number of types with >= 5 samples or the office depth p50 / p90 is claimed |
| R808 | Gates | PASS | see below |

## Gates

| Gate | Result |
|---|---|
| `ruff check .` | All checks passed |
| `ruff format --check .` | 335 files already formatted |
| `mypy` | Success: no issues found in 163 source files |
| `python -m ale.contracts.lock --check` | OK (`export_schemas --check` OK too) |
| `pytest -m "not slow" -q` | **1626 passed, 11 skipped, 54 deselected, 4 xfailed** in 896 s (the 4 xfails and the skips are pre-existing) |

New tests: `tests/rulebook/test_rulebook_r8.py` (8), `tests/geometry/test_geometry_r8.py` (9); helper `tests/rulebook/r8_helpers.py`.

## Design decisions (readings of the RD)

- Façade edge of a room: a ring edge with at least 0.6 m (`MIN_FACADE_EDGE_M`, the minimum shared contact) lying on the exterior outline within `EXTERIOR_TOL_M` (0.3 m), as the existing `room_facades`. Width = façade length of the longest such edge; depth = extent of the room perpendicular to it. `facade_m_per_m2` = weighted total façade length / weighted total area over **all** rooms of the type.
- Only CAD and PDF_VECTOR plans feed the statistics (same fidelities as aspect / area).
- Quantile weights, 9-digit rounding and seed blending (`blend_k`) are those of aspect / area; the sample threshold is 5 (`MIN_FACADE_SAMPLES`), independent of `min_support`.
- `TypeStats` omits `depth_m`, `facade_width_m`, `facade_m_per_m2` (when None) and `n_facade_samples` (when 0) from its serialised form (wrap serialiser, same pattern as `Layout.fixed`), so old rulebooks and their hashes are unchanged.
- Learned soft limit = `floor(depth_m.p90 / module)` modules (at least 1), applied to `needs_facade` rooms of that type through `RoomReq.dmax`; `Consts.type_dmax` is built from `Consts.from_config(config, rulebook)`.
- `max_depth_hard`: the learned limits are ignored when the configured rule is hard ("config value only").
- When `facade.max_depth_m` is unset but a type has a learned depth, the learned limit applies to that type (the rule is then on for it only).
- The soft-depth section of the plan report still quotes the configured limit; the violation detail lines give the actual limit in modules.

## Spec issues

- RD §4 does not say what happens to `max_depth_hard` combined with learned depths, nor with `max_depth_m` unset; the choices above are mine.
- RD §3 says "fidelity-weighted as the existing stats" but does not say whether raster plans count; I followed aspect / area (vector only).
- Existing signature changes outside the stated file list (needed to carry the rulebook to the limit): `Consts.from_config(config, rulebook=None)`, `RealizeCache(..., rulebook=None)`, `export_run(..., rulebook=None)` / `render_report(..., rulebook=None)`, and one-line call updates in `geometry/{evaluate,realize,greedy}.py`, `stack/{snap,plans}.py`, `topology/{repair,depth}.py`, `optimize/{anneal,fastreal,generate}.py`. All defaults keep today's behaviour.
- `tests/contracts/test_corridor_plan.py::test_K02_existing_unchanged` lists the contract files changed since 1.0.0; `schemas/Rulebook.schema.json` was added to that list (a required consequence of the bump).
