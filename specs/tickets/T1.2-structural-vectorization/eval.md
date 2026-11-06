# Ticket 1.2 — Structural Vectorization · Evaluation Metrics

Two tiers. **Tier A** runs anywhere, without model weights, and is a hard merge
gate. **Tier B** needs the CubiCasa5K weights (and optionally the dataset) and
is run by the Router on a machine that has them; its results are recorded, and
the listed floors are also merge gates.

Each test ID must exist as a named pytest test (e.g. `test_A03_openings_hosted`).

## 0. Harness rules (Watchdog)

- `pytest-timeout` default **30 s per test**; Tier B tests may set up to **300 s**.
- Tier A suite wall-clock **≤ 180 s** on 4 CPU cores.
- Tier B tests are skipped (not failed) unless `ALE_CUBICASA_WEIGHTS` is set and the file exists; marker `@pytest.mark.weights`.
- No network in either tier.

## 1. Synthetic fixture generator (`tests/ingest/vectorize/synth.py`)

Required so post-processing can be tested against **known ground truth** without the model:

- `make_plan(spec) -> (rgb: uint8[H,W,3], gt: GroundTruth)` draws a plan from a small declarative spec (rectangular exterior, interior partitions, doors, windows) with walls as filled black rectangles of a given thickness.
- `make_logits(gt, scale, noise_sigma, seed) -> Logits` produces heatmap/room/icon arrays **in the exact channel layout the real model emits** (21/12/11), rendered from the ground truth at inference resolution, with optional Gaussian noise and blur. Junction heatmap channels must follow the upstream junction-type encoding (document the mapping you used, citing upstream).
- Canonical fixtures (all must be used):
  - **F1 "two-room":** 600×400 px, exterior wall 12 px, one vertical partition at x=300, one door (48 px) in the partition, one window (100 px) on the top exterior wall, one window on the bottom wall.
  - **F2 "L-shape":** L-shaped exterior, 3 spaces, 2 doors, 3 windows.
  - **F3 "corridor":** 1 corridor + 6 rooms off it, 6 doors; source raster 3000×2000 (forces downscale at `LONG_SIDE_PX=1024`).
  - **F4 "blank":** 800×600 white image, all-background logits.

## 2. Tier A — functional (no weights; merge-blocking)

Matching rule used below: an output wall *matches* a ground-truth wall if both
centreline endpoints are within **3 px** (source px; for F3 within `3 / scale` px)
of the GT endpoints (either orientation) and the angle difference ≤ **2°**.

| ID | Name | Fixture | Pass condition |
|----|------|---------|----------------|
| A01 | walls_recovered | F1, F2, F3 (noise σ=0) | Bijective wall matching: every GT wall matched by exactly one output wall; no unmatched outputs. `thickness_px` within ±2 px of GT. |
| A02 | walls_noisy | F1, F2 (noise σ=0.1, blur 1 px, 5 seeds) | Wall recall ≥ 0.95 and precision ≥ 0.95 averaged over seeds. |
| A03 | openings_hosted | F1, F2, F3 | Door/window counts equal GT; each opening's `host_wall_id` is the wall matched to its GT host; `width_px` within ±3 px of GT; `axis_angle_deg` within ±2° of host wall angle (mod 180). |
| A04 | spaces_iou | F1, F2, F3 | Space count equals GT; Hungarian-matched IoU ≥ **0.95** for each space (source px). |
| A05 | spaces_disjoint | all | For every pair of spaces, `intersection.area ≤ 1e-6 × W × H`. `quality.space_overlap_area_px` equals the measured total. |
| A06 | spaces_vs_walls | F1, F2, F3 | For every space, area of `space ∩ union(walls)` ≤ **2 %** of space area. |
| A07 | geometry_validity | all | Every geometry `is_valid`, non-empty, `Polygon` (walls/openings/spaces); exterior rings oriented per RD §8.1; all coordinates within `[0, W] × [0, H]`; all coordinates have ≤ 2 decimals. |
| A08 | semantic_override | F1 with room logits whose argmax is set to `Kitchen`, `Bath`, `Bed Room`, `Garage` in different spaces, and icon logits containing `Toilet`, `Sink`, `Bathtub` blobs. | No room/non-structural-icon class string from RD §7.6 occurs anywhere in the bytes of `structure.geojson` (case-insensitive substring search). Every space has `"label": null`. Toilet/Sink/Bathtub blobs produce **no** features. Space count still equals GT. |
| A09 | transform_roundtrip | F3 at `LONG_SIDE_PX` ∈ {512, 1024}; plus a 1000×1000 image at 1024 (no upscale) | Output coordinates are in **source** px: wall endpoint error ≤ `1.5 / scale` px. `structure_meta.inference.scale` equals the applied scale. Padding never produces geometry. |
| A10 | tiling_equivalence | F3 with `ALE_VEC_TILING=1`, tile 512, overlap 128 (synthetic logits rendered per tile) | Same feature counts as resize mode on noise-free logits; matched wall endpoints within 3 px of GT. |
| A11 | tta_reindex | F1 logits rotated 90° and fed through the TTA de-rotation path | De-rotated logits equal the unrotated logits (max abs diff ≤ 1e-6), including junction-channel re-indexing. |
| A12 | blank_page | F4 | No exception; `counts` all 0; `quality.status == "EMPTY"`; `ProcessResult.ok is True`; GeoJSON validates with an empty `features` list. |
| A13 | min_area_and_simplify | F1 + 10 random speckle regions of 5–15 px² in room logits | Speckles produce no spaces; space vertex counts ≤ GT vertex count + 2. |
| A14 | schema_validation | all | Every `structure.geojson` and `structure_meta.json` validates against the shipped JSON Schema (`jsonschema` Draft 2020-12). A deliberately corrupted feature (`kind: "kitchen"`) fails validation. |
| A15 | stable_ids_determinism | F2, run twice in fresh processes | `structure.geojson` byte-identical; ids follow RD §8.1 ordering rule (verify by recomputing). |
| A16 | import_isolation | — | Importing `ale.ingest.vectorize.postprocess`, `.export`, `.transform` in a fresh interpreter does not put `torch` in `sys.modules`. |

## 3. Tier A — contract, robustness & Watchdog (merge-blocking)

| ID | Name | Pass condition |
|----|------|----------------|
| C01 | processor_contract | With a **fake model** injected (returns `make_logits(F1)`), run the job through the real orchestrator `drain` command on a workspace containing F1 as a JPEG. Job reaches `DONE`; `result/` contains `structure.geojson`, `structure_meta.json`, `result.json`; `ProcessResult.metrics` contains the 4 counts and `status`. |
| C02 | weights_missing | `ALE_CUBICASA_WEIGHTS` unset or nonexistent → `NonRetryableError`; through the orchestrator the job is `QUARANTINED` after **1** attempt. |
| C03 | weights_hash_mismatch | 1 KB dummy file with wrong SHA → `NonRetryableError` raised **before** any `torch.load` call (assert via mock). |
| C04 | manifest_mismatch | PNG dims ≠ manifest dims → `NonRetryableError`. |
| C05 | bad_config | Each env var set to an invalid value (negative, non-numeric, unknown device) → `NonRetryableError` naming the variable. |
| C06 | atomic_outputs | Kill the processor process (SIGKILL) during export (inject a sleep in export via monkeypatch in a child process). `out_dir` contains no `structure.geojson` or only a complete, schema-valid one — never a truncated file. |
| C07 | iteration_caps | Feed adversarial logits (heatmap = 0.99 everywhere, 2048×2048) to post-processing. Completes or raises the documented cap error within **30 s**; with junction cap, flag `junctions_capped` set. Never hangs. |
| C08 | postprocess_runtime | F3 at 1024 px, noise σ=0.1: post-processing ≤ **10 s** CPU. |
| C09 | no_network | Run C01 with sockets blocked (e.g. `pytest-socket` or monkeypatched `socket.socket`); passes. |
| C10 | vendored_provenance | `src/ale/_vendor/cubicasa5k/VENDORED.md` exists, contains a 40-hex commit hash, licence text, and lists every `# ALE:` edit; `grep -c "# ALE:"` in vendored code equals the number listed. |

## 4. Tier B — real model (requires weights)

| ID | Name | Pass condition |
|----|------|----------------|
| B01 | model_loads | Checkpoint loads; forward on a 1×3×512×512 input returns shape `1×44×512×512`; output finite. |
| B02 | determinism_real | Same page twice on CPU → byte-identical `structure.geojson`. |
| B03 | cubicasa_test_subset | *Only if the CubiCasa5K dataset is available locally.* On 20 fixed test-split samples (list the sample ids in `eval_report.md`): wall-pixel IoU (rasterised output wall polygons vs. GT wall mask) **≥ 0.60** mean, door+window instance recall at IoU 0.5 **≥ 0.60**. These floors are **provisional**; the first accepted run's numbers become the baseline in `specs/tickets/T1.2-structural-vectorization/baseline.json`, and later changes must not drop any metric by more than **0.02**. |
| B04 | real_page_runtime | One 300-dpi A3 page via the processor on 4 CPU cores, resize mode, TTA on: total ≤ **120 s**; peak RSS ≤ 4 GB. |
| B05 | commercial_smoke_set | 5 commercial/public-building plans chosen by the user. For each: job `DONE`, schema-valid output, `overlay.png` produced. The Router reviews overlays and records per plan in `eval_report.md`: walls visually plausible (Y/N), openings mostly on walls (Y/N), spaces mostly closed (Y/N). **Gate:** ≥ 3 of 5 plans pass all three. This measures out-of-domain transfer (the model is trained on residential plans) and is the key risk signal for Phase 1. |

## 5. Static & quality gates

| Gate | Command | Threshold |
|------|---------|-----------|
| Lint | `ruff check src/ale/ingest/vectorize tests/ingest/vectorize` | 0 findings (vendored dir excluded) |
| Format | `ruff format --check` (same paths) | clean |
| Types | `mypy --strict src/ale/ingest/vectorize` | 0 errors (vendored dir excluded) |
| Coverage | `pytest -m "not weights" --cov=ale.ingest.vectorize --cov-branch` | ≥ 85 % line, ≥ 70 % branch |
| No weights in git | `git ls-files | grep -Ei '\.(pkl|pth|pt|ckpt)$'` | empty |
| Orchestrator untouched | `git diff --stat <base> -- src/ale/ingest/orchestrator` | empty |

## 6. Merge procedure

1. Worker returns code + `eval_report.md` (Tier A + C results; Tier B marked SKIPPED if no weights).
2. Router re-runs Tier A + C independently; any discrepancy = reject.
3. Router (or user) runs Tier B where weights are available; B01, B02, B04, B05 must pass; B03 must pass if the dataset is available.
4. Router updates `board.md`.
