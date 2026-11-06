# Ticket 1.2 — Structural Vectorization (CubiCasa5K) · Requirements Document

> **Worker brief.** This document is self-contained. Build exactly what is
> specified here. Your code is merged only if every gate in `eval.md` (same
> folder) passes. You will plug into an existing package `ale` that already
> contains `ale.ingest.orchestrator` (summarised in §3); do not modify that package.

## 1. Purpose

Run the pretrained **CubiCasa5K** floor-plan network locally on a single page
raster and convert its raw outputs into **exact structural vector geometry**:
walls, windows, doors, and enclosed space polygons, in the page's pixel
coordinate system.

This ticket deliberately **discards the model's native residential semantics**
(Kitchen, Bedroom, Bath, Sauna, …). The project processes commercial and public
buildings; the model's room labels are wrong for that domain. We use the model
only as a *structural* detector. Room meaning is assigned later by a separate
vision-language step that this ticket does not implement.

## 2. Scope

**In scope**

- Vendoring the minimal CubiCasa5K model definition and post-processing code.
- Weights loading with integrity check.
- Preprocessing, resize/pad (and optional tiling) with an exact inverse transform.
- Inference with optional 4-rotation test-time augmentation.
- Post-processing logits → walls (polygon + centreline), openings (door/window), spaces (unlabelled polygons).
- Geometry cleaning and validation with Shapely.
- Export: GeoJSON + metadata JSON + debug overlay PNG.
- A processor entry point compatible with the orchestrator.

**Out of scope**

- Any semantic room classification, VLM/API calls, scale calibration (pixels → metres), or adjacency graphs.
- Training or fine-tuning.
- Modifying `ale.ingest.orchestrator`.

## 3. Upstream contract (from Ticket 1.1 — already exists, read-only)

The orchestrator calls your processor in an isolated child process:

```python
# ale.ingest.orchestrator.models
@dataclass(frozen=True)
class JobSpec:
    job_id: str; doc_id: str; page_index: int
    raster_path: str          # PNG, RGB, 8-bit, original page resolution
    page_manifest_path: str   # manifest.json (has width_px, height_px, raster_dpi per page)
    out_dir: str              # empty directory you write all outputs into
    attempt: int

@dataclass(frozen=True)
class ProcessResult:
    ok: bool
    outputs: list[str]        # paths relative to out_dir
    metrics: dict[str, float | int | str]
    message: str | None = None

# ale.ingest.orchestrator.errors
class NonRetryableError(Exception): ...   # raise for permanent failures (bad weights, unreadable raster)
```

The orchestrator enforces a hard wall-clock timeout and kills the process on
overrun. Your code must therefore never loop unboundedly (see §11).

## 4. Environment & dependencies

- Python 3.11+. Runtime deps (add as an optional extra `ale[vectorize]` in `pyproject.toml`):
  - `torch>=2.2` (CPU build is sufficient; CUDA optional), `numpy>=1.26`, `opencv-python-headless>=4.9`,
    `shapely>=2.0`, `Pillow>=10`, `scipy>=1.11` (only if required by vendored post-processing),
    `jsonschema>=4.21`.
- **No network access** at runtime. Weights are a local file supplied by the operator; the code must never download anything.
- Do **not** commit model weights or CubiCasa5K dataset files to git.

## 5. Model (vendored)

- Vendor the minimal subset of the upstream repository `github.com/CubiCasa/CubiCasa5k`
  required for the `hg_furukawa_original` architecture and its post-processing
  into `src/ale/_vendor/cubicasa5k/`. Include the upstream `LICENSE` file and a
  `VENDORED.md` stating the upstream commit hash and listing every local modification
  (e.g. removed dead code, added loop bounds). Keep modifications minimal and marked with `# ALE:` comments.
- Network configuration as used by upstream for the released weights (verify against the pinned commit and record what you find in `VENDORED.md`):
  - backbone `hg_furukawa_original`, output head replaced to **44 channels**,
  - channel split **`[21, 12, 11]`** = junction heatmaps / room segmentation / icon segmentation,
  - room classes (12): `Background, Outdoor, Wall, Kitchen, Living Room, Bed Room, Bath, Entry, Railing, Storage, Garage, Undefined`,
  - icon classes (11): `No Icon, Window, Door, Closet, Electrical Appliance, Toilet, Sink, Sauna Bench, Fire Place, Bathtub, Chimney`,
  - input normalisation `x = 2 * (rgb / 255) - 1`, NCHW float32.
- If the pinned upstream differs from the list above, upstream wins; document the difference in `VENDORED.md` and in your `eval_report.md`.
- **Licence note (record, do not resolve):** the CubiCasa5K dataset and released weights are published under a non-commercial licence (verify the exact terms at the pinned commit). Copy the licence text into `VENDORED.md`. The Router will decide on commercial-use implications.

## 6. Configuration

A dataclass `VectorizeConfig` loaded from environment variables (the processor
runs in a child process with no other config channel), with these defaults:

| Env var | Default | Meaning |
|---|---|---|
| `ALE_CUBICASA_WEIGHTS` | *(required)* | Path to the `.pkl` / `.pth` checkpoint. |
| `ALE_CUBICASA_WEIGHTS_SHA256` | *(required)* | Expected lowercase hex SHA-256 of the weights file. |
| `ALE_VEC_DEVICE` | `cpu` | `cpu` or `cuda[:n]`. |
| `ALE_VEC_LONG_SIDE_PX` | `1024` | Long side of the inference image after resize. |
| `ALE_VEC_TILING` | `0` | `1` → tile the image instead of downscaling (see §7). |
| `ALE_VEC_TILE_PX` / `ALE_VEC_TILE_OVERLAP_PX` | `1024` / `128` | Tiling parameters. |
| `ALE_VEC_TTA` | `1` | `1` → average logits over 0°/90°/180°/270° rotations. |
| `ALE_VEC_HEATMAP_THRESHOLD` | `0.2` | Junction heatmap threshold for wall extraction. |
| `ALE_VEC_MIN_SPACE_AREA_PX` | `400` | Spaces smaller than this (in **source** px²) are dropped. |
| `ALE_VEC_SIMPLIFY_TOL_PX` | `1.0` | Douglas–Peucker tolerance (source px). |
| `ALE_VEC_SNAP_TOL_PX` | `4.0` | Wall endpoint snapping / opening-to-wall host distance (source px). |
| `ALE_VEC_DEBUG_OVERLAY` | `1` | Write `overlay.png`. |
| `ALE_VEC_THREADS` | `0` | `torch.set_num_threads`; `0` = leave default. |

Invalid values → `NonRetryableError` naming the variable.

## 7. Processing pipeline

Implement as separately testable stages. **Inference and post-processing must be
decoupled**: post-processing takes NumPy arrays only and never imports `torch`.

1. **Load** (`io.py`): read `raster_path` as RGB uint8 `H×W×3`. Read `width_px`/`height_px` for `page_index` from the manifest and assert they match the PNG (mismatch → `NonRetryableError`).
2. **Weights** (`weights.py`): stream-hash the weights file; mismatch with `ALE_CUBICASA_WEIGHTS_SHA256` → `NonRetryableError`. Load with `torch.load(..., map_location=device, weights_only=True)` where the checkpoint format permits; otherwise document why not in `VENDORED.md`. Model in `eval()` mode, `torch.inference_mode()`.
3. **Geometric transform** (`transform.py`): produce the inference tensor plus a `PixelTransform` object holding the exact affine mapping *inference px → source px*.
   - *Resize mode (default):* scale `s = ALE_VEC_LONG_SIDE_PX / max(H, W)` (never upscale beyond `s = 1.0` unless the long side < 256 px), area interpolation, then pad right/bottom with white to the next multiple of **32**. Inverse: `x_src = x_inf / s`, `y_src = y_inf / s`; padding region discarded.
   - *Tiling mode:* no resize; tiles of `TILE_PX` with `OVERLAP_PX` overlap, each padded to a multiple of 32; logits blended with a linear ramp in the overlap; full-resolution logit maps reassembled before post-processing.
   - Use pixel-**corner** convention: pixel `(i, j)` covers `[j, j+1) × [i, i+1)`. Document this in the module docstring.
4. **Inference** (`infer.py`): returns `Logits(heatmaps: float32[21,h,w], rooms: float32[12,h,w], icons: float32[11,h,w])` at inference resolution (sigmoid on heatmaps, softmax on rooms/icons, as upstream). With TTA: rotate input, infer, rotate logits back — heatmap channels whose meaning is orientation-specific (junction types) must be **re-indexed** on rotation exactly as upstream's evaluation code does; cite the upstream function in a comment.
5. **Post-processing** (`postprocess/`):
   - **Walls** (`walls.py`): use the vendored upstream junction-heatmap → wall-line procedure at `HEATMAP_THRESHOLD`. For each wall output: Shapely `Polygon` (wall body) and a 2-point `LineString` centreline; `thickness_px` = polygon area / centreline length. Snap centreline endpoints within `SNAP_TOL_PX` to shared junctions; merge collinear touching segments (angle diff ≤ 2°, perpendicular offset ≤ 1 px).
   - **Openings** (`openings.py`): from upstream opening extraction for icon classes **Window (1)** and **Door (2) only**. Each opening → `minimum_rotated_rectangle`; `width_px` = long side; `axis_angle_deg` in `[0, 180)`. Assign `host_wall_id` = id of the wall whose centreline is nearest to the opening centroid if within `max(SNAP_TOL_PX, thickness_px)`; else `null`.
   - **Spaces** (`spaces.py`): take upstream room polygons; **ignore their class labels entirely**. Exclude regions whose argmax class was `Background`, `Outdoor`, `Wall`, or `Railing`; every other class collapses to a single kind `space`. Then: `make_valid` → keep largest `Polygon` parts → remove parts < `MIN_SPACE_AREA_PX` → simplify (topology-preserving) → resolve pairwise overlaps by assigning the overlap to the space with higher mean room-probability mass (deterministic tie-break: lower id) → drop anything that became empty.
   - All stages operate in inference px; convert to source px via `PixelTransform` **before** area thresholds, simplification, and snapping (thresholds are specified in source px).
6. **Semantic override (hard rule):** the strings of the 12 room classes and the 9 non-structural icon classes (`Closet`, `Electrical Appliance`, `Toilet`, `Sink`, `Sauna Bench`, `Fire Place`, `Bathtub`, `Chimney`, `No Icon`) must **never appear** in `structure.geojson`. They may appear only in `debug/native_labels.json` (optional, for diagnostics), which downstream tickets are forbidden to read.

## 8. Output contract

All files written inside `JobSpec.out_dir`:

```
structure.geojson       # primary output (schema below)
structure_meta.json     # provenance + metrics
overlay.png             # optional debug overlay (walls red, doors green, windows blue, spaces translucent)
debug/native_labels.json  # optional
```

### 8.1 `structure.geojson`

A GeoJSON `FeatureCollection` used as a container format **in pixel space, not
WGS84**: origin top-left of the source raster, +x right, +y down, units = source
pixels, coordinates rounded to **2 decimals**. Polygon rings closed, exterior
counter-clockwise **in the y-down frame as rendered on screen** — i.e. apply
`shapely.geometry.polygon.orient(p, sign=1.0)` and document it.

```json
{
  "type": "FeatureCollection",
  "ale_schema": "ale.structure/1.0",
  "crs_local": {"frame": "raster_px", "origin": "top-left", "y_axis": "down",
                "width_px": 4961, "height_px": 3508},
  "features": [
    {"type": "Feature", "id": "wall-00000",
     "geometry": {"type": "Polygon", "coordinates": [[[x,y], ...]]},
     "properties": {"kind": "wall", "centerline": [[x0,y0],[x1,y1]],
                    "thickness_px": 11.8, "length_px": 412.3, "confidence": 0.91}},
    {"type": "Feature", "id": "door-00000",
     "geometry": {"type": "Polygon", "coordinates": [...]},
     "properties": {"kind": "door", "width_px": 52.4, "axis_angle_deg": 90.0,
                    "host_wall_id": "wall-00007", "confidence": 0.84}},
    {"type": "Feature", "id": "window-00000", "geometry": {...},
     "properties": {"kind": "window", "width_px": 118.0, "axis_angle_deg": 0.0,
                    "host_wall_id": "wall-00002", "confidence": 0.77}},
    {"type": "Feature", "id": "space-00000", "geometry": {...},
     "properties": {"kind": "space", "label": null, "area_px": 182340.5,
                    "confidence": 0.88}}
  ]
}
```

- `kind` ∈ `{"wall", "door", "window", "space"}` — nothing else.
- `confidence` ∈ `[0, 1]` = mean of the relevant probability channel inside the feature (heatmap/icon/room-mass respectively).
- **Stable ids:** within each kind, sort features by `(round(min_y), round(min_x), round(max_y), round(max_x), round(area, 2))` of their bounds and number from `00000`. Features listed in order wall → door → window → space.
- Ship a JSON Schema at `src/ale/ingest/vectorize/schema/structure-1.0.json` and validate every output against it before writing; schema failure is a bug (raise, retryable).

### 8.2 `structure_meta.json`

```json
{"ale_schema": "ale.structure_meta/1.0",
 "job_id": "...", "doc_id": "...", "page_index": 0,
 "source": {"width_px": 4961, "height_px": 3508, "raster_dpi": 300},
 "model": {"name": "cubicasa5k/hg_furukawa_original", "upstream_commit": "...",
           "weights_sha256": "...", "n_classes": 44, "split": [21, 12, 11]},
 "inference": {"mode": "resize", "scale": 0.2064, "padded_hw": [736, 1024], "tta": true,
               "device": "cpu", "torch_version": "2.x", "threads": 4},
 "thresholds": {"heatmap": 0.2, "min_space_area_px": 400, "simplify_tol_px": 1.0, "snap_tol_px": 4.0},
 "counts": {"wall": 0, "door": 0, "window": 0, "space": 0},
 "quality": {"status": "OK", "flags": [], "unhosted_openings": 0,
             "space_overlap_area_px": 0.0, "invalid_geometries_repaired": 0},
 "timings_s": {"load": 0.0, "infer": 0.0, "postprocess": 0.0, "export": 0.0, "total": 0.0}}
```

- `quality.status`: `"OK"`; `"EMPTY"` if zero walls were found (not an error — downstream decides); `"DEGRADED"` if any flag is raised. Flags (strings): `no_spaces`, `many_unhosted_openings` (> 25 % of openings), `tiny_image` (long side < 256 px), `extreme_aspect` (> 6:1), `scale_clamped`.

### 8.3 Processor entry point

`ale.ingest.vectorize.processor:process(spec: JobSpec) -> ProcessResult`

- Returns `ok=True` for `OK`, `EMPTY`, and `DEGRADED` results; `metrics` = `counts` + `quality.status` + `timings_s.total`.
- Raises `NonRetryableError` for: missing/mismatched weights, unreadable raster, manifest mismatch, invalid config.
- Any other exception propagates (orchestrator retries).
- Write outputs to temp names then `os.replace`, so a killed process never leaves a half-written `structure.geojson`.
- The model is loaded lazily once per process (module-level cache) — the orchestrator uses a fresh process per attempt, so this is only an optimisation for batch tooling.

## 9. Package layout

```
src/ale/_vendor/cubicasa5k/          # vendored upstream subset + LICENSE + VENDORED.md
src/ale/ingest/vectorize/
    __init__.py
    config.py         # VectorizeConfig (env-driven)
    io.py             # raster + manifest loading
    weights.py        # hashing + model construction + loading
    transform.py      # PixelTransform, resize/pad, tiling
    infer.py          # torch-only code lives here (and weights.py)
    postprocess/
        __init__.py
        walls.py
        openings.py
        spaces.py
        geometry.py   # shared Shapely helpers: validity, orientation, rounding, ids
    export.py         # GeoJSON/meta writing, schema validation, overlay rendering
    processor.py      # entry point
    schema/structure-1.0.json
    cli.py            # `python -m ale.ingest.vectorize IMAGE.png --out DIR` (for manual runs)
tests/ingest/vectorize/
    synth.py          # synthetic plan + logits generator (see eval.md)
    ...
```

Import rule: nothing under `postprocess/`, `export.py`, `transform.py` may import `torch` (enforced by test).

## 10. Determinism & numerical policy

- `torch.manual_seed(0)`, `torch.use_deterministic_algorithms(True)`, `torch.backends.cudnn.benchmark = False`.
- Given identical inputs, config, device and library versions, `structure.geojson` must be **byte-identical** across runs. (`json.dumps(..., sort_keys=False, separators=(",", ":"), ensure_ascii=False)` with fixed key order.)
- CPU is the reference device. CUDA results need not be byte-identical to CPU.

## 11. Bounded computation (Watchdog compliance)

- Every iterative routine in your code **and in the vendored post-processing** has an explicit iteration cap (`max_iter` derived from input size) and raises `RuntimeError("iteration cap exceeded in <fn>")` if hit. Mark vendored edits with `# ALE: loop bound`.
- Junction count fed to the wall-pairing step is capped (default 5 000, highest-confidence first); exceeding it sets flag `junctions_capped` and continues.
- Peak RSS for a 1024-px inference + post-processing on CPU should stay below **4 GB**.

## 12. Deliverables

1. Code per §9; vendored upstream with `LICENSE` and `VENDORED.md`.
2. Tests implementing every case in `eval.md` (Tier A must run without weights).
3. `src/ale/ingest/vectorize/README.md` (≤ 1 page): obtaining weights (manual step), env vars, running via orchestrator and via `cli.py`.
4. `eval_report.md` in this ticket folder with PASS/FAIL per test ID and, if weights were available, Tier B numbers.
