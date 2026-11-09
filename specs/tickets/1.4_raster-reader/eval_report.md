# Ticket 1.4 — Raster reader (classical CV, v1) · Evaluation report

Branch: worker worktree for 1.4 (merged `claude/new-session-2hmd3s`). Library only: `src/ale/raster/{__init__,read,preprocess,walls,rooms,openings}.py`, tests in `tests/raster/`. No contract, CLI or other package touched.

## Results

| ID | Test(s) | Result | Measured |
|---|---|---|---|
| R1 | `test_R1_synthetic_plan` | PASS | 3 rooms; wall IoU 1.00; room IoU 0.995 / 0.996 / 0.995; 2 doors, widths 40.0 and 50.0 px (GT 40, 50); plan_score 1.00 |
| R2 | `test_R2_noise_and_skew` (+ `test_R2_skew_both_directions`: -2°, 2°, 5°) | PASS | skew found -1.97° (image rotated +2°); wall IoU 0.937 (0.933–0.939 over the other angles/seed); 3 rooms |
| R3 | `test_R3_scanned_pdf` | PASS | image placed full-page in a PDF, `rasterize_pdf_page(…, 150)` → 1200×800 grey; 3 rooms (same as R1) |
| R4 | `test_R4_not_a_plan[photo / white_noise / text]` | PASS | scores: blurred-noise "photo" with gradient 0.005, white noise 0.08, text page 0.00 (all < 0.3) |
| R5 | `test_R5_robustness`, `test_R5_huge_image_downscaled` | PASS | blank, all-black, 1×1 (black/white), 0×0 → `plans == ()` with a warning, ≤ 0.02 s each; 10 000×10 000 → downscaled to the 12 MP cap, ≈ 1 s, 3 rooms, door widths reported in native (input) pixels |
| R6 | `test_R6_contract` | PASS | JSON round-trip equal; `Y_DOWN`; `UNKNOWN` scale / `None`; unlabelled rooms; unique ids; deterministic |
| R7 | `test_R7_real_corpus_smoke` (optional, `ALE_CORPUS_DIR`) | RUN locally, skipped in CI | see below |
| R8 | `test_R8_gates` + commands | PASS | see Gates |

Unit tests (`tests/raster/test_raster_units.py`, 26 tests) cover argument validation, missing extras (`cv2`, `PIL`, `pymupdf` mocked away), file loading (non-ASCII paths, multi-page TIFF, corrupt/missing files, size cap, decoder fallback), `to_gray` dtypes/channels/alpha, skew sign, oblique-line warning, inverted and non-uniform backgrounds, thin-line rejection, collinear merge, gap deduplication, room caps/time budget, polygon repair, and the `plan_score` formula.

## Gates

- `pytest` (whole suite): 813 passed, 9 skipped (incl. R7 without `ALE_CORPUS_DIR`), 2 xfailed (pre-existing), total coverage 98 % (all pass; raster tests skip cleanly without the `raster` extra — verified by running `tests/raster` with `cv2` blocked: 2 module-level skips, no errors).
- `ruff check .`, `ruff format --check .`: clean.
- `mypy` (strict, `src/ale`): clean. OpenCV 5.0 ships `py.typed` stubs, so no ignores were needed for `cv2`; two `# type: ignore[no-untyped-call]` for `pymupdf.open` / `pymupdf.Matrix` (untyped constructors in PyMuPDF's stubs).
- Coverage of `ale.raster`: 99 % (branch coverage on); 2 defensive branches marked `pragma: no cover`.
- `python -m ale.contracts.lock --check`: OK (exit 0).

## R7 smoke (20 of 366 `floor_plan_images`, every 18th by sorted relative path)

All 20 read without exception, 0.0–0.4 s each. Per image (walls / rooms / doors / score): 61/0/11/0.12, 1/0/0/0.37, 99/1/10/0.26, 124/2/28/0.42, 31/0/7/0.17, 14/0/0/0.02, 355/12/151/0.42, 80/2/11/0.29, 257/7/60/0.43, 29/0/4/0.47, 43/2/5/0.18, 461/18/184/0.64, 21/0/3/0.00, 231/14/74/0.52, 334/8/121/0.37, 244/20/68/0.79, 397/41/173/0.39, 20/0/2/0.26, 138/3/39/0.41, 152/1/74/0.46.

Reading: the classical pipeline finds rooms on clean, solid-wall plans (hospital, museum, office plates: 8–41 rooms) but under-segments web renderings with coloured fills, hatching, double-line (outline) walls, or several plans per image. Door counts are inflated on real images (every bridged gap within the median band is a "door", including windows). This is consistent with the v1 scope; the ML variant (CubiCasa5K) remains the planned upgrade behind the same API.

## Literal readings and spec issues (for the router)

1. **Door gaps vs. "closing by the median wall thickness" (step 3/4).** A closing with a kernel of one wall thickness seals only gaps narrower than a wall; real door gaps are 4–9 × the wall thickness (R1's are 5–6 ×), so the literal closing cannot seal them and R1 would yield 1 room. Implemented: gaps are bridged explicitly first — a bounded ray is cast from each wall end along its centreline; if it meets another wall within `min(10 × median thickness, 15 % of the short side)` the free run is a gap and is drawn as wall — then the closing by the median thickness is applied as specified. Step 4 then classifies bridged gaps within 0.5–1.5 × the median gap as `DOOR` (`width_native` = gap px). The 10× / 15 % bound is my choice.
2. **"Crop to the largest dark-content bbox"**: read as the bbox of the largest 8-connected dark component (+ 2 % of its larger side, ≥ 2 px, padded with paper colour if it reaches the image edge). Detached parts of a drawing outside that bbox are lost; a text page crops to one word (used by `plan_score`, see 4).
3. **Thickness "from distance transform"**: the DT ridge value fixes the thickness only to ±1 px (a 7- and an 8-px bar both have ridge 4). Implemented as the median run length across each bar, which is exact; documented in `walls.py`.
4. **`plan_score` "wall pixels share, room count"** was not discriminative enough on R4 (noise images produce many short bars and small enclosures). Documented formula (module docstring of `read.py`): `s_ink · s_extent · (0.3 s_wall + 0.3 s_rooms + 0.2 s_straight + 0.2 s_long)` — it still uses the wall share and room count, plus ink share, crop extent, room-area share, straight-stroke share and long-wall share.
5. **Coordinates**: geometry is mapped back through crop, deskew rotation and memory-cap downscale to the *input* image's pixels (pixel centres on integer coordinates), so it overlays the caller's image; `units_label = "px"`.
6. **`rasterize_pdf_page` has no warnings channel**: on failure it logs a warning and returns an empty `(0, 0)` array (which `read_raster` reports as `empty image`); the DPI is lowered when the page would exceed 60 MP.
7. **Not-a-plan policy**: `plans == ()` when there is no dark content or no wall; otherwise the plan is returned with `plan_score` and a `low plan score` warning below 0.3 (R4 accepts either).
8. Other v1 choices: kernels forced odd (an even opening/closing shifts the mask by 1 px); room holes not traced; only `DOOR` openings; bars thinner than 0.4 × the area-weighted median thickness are dropped as drawing lines; inverted (light-on-dark) images are detected (median grey < 96) and inverted; `config` is accepted but unused (no raster tunable in `AleConfig` besides `extract.raster_dpi`, which the caller passes to `rasterize_pdf_page`).
