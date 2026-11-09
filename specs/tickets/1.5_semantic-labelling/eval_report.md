# Ticket 1.5 — Semantic labelling · Evaluation report

Platform of this run: Linux, Python 3.13, **without scipy** (the greedy fallback is the
default path; the scipy path is exercised through an injected `scipy.optimize` stand-in).
Only fake providers are used: no network, no API.

Ticket tests (`tests/labels`): **69 passed**. Coverage of `ale.labels`: **99 %**
(statements 100 %, one partial branch). Whole suite: 846 passed, 7 skipped, 2 xfailed.

## 1. Evaluation (`tests/labels/test_labels_eval.py`)

| ID | Test(s) | Result |
|---|---|---|
| L1 | `test_L1_text_first`, `test_L1_text_first_no_provider_calls_for_text_rooms`, `test_L1_already_typed_rooms_kept` | PASS: `BUREAU 3` → office, `WC H/F` → sanitary, `PDF_TEXT`, 0 calls; text-typed rooms never get a VLM label |
| L2 | `test_L2_vlm_fill`, `test_L2_vlm_fill_y_down` | PASS: room C typed `meeting_room` / `storage`, `label_source VLM`, 1 call, confidence = 0.9 × 1.0 |
| L3 | `test_L3_cache`, `test_L3_cache_location_in_workspace` | PASS: 2nd run 0 calls (same plan); new `model_id` → 1 call; `PROMPT_VERSION` "v2" → 1 call; cache in `<ws>/cache/vlm/` |
| L4 | `test_L4_invalid_json_then_valid`, `test_L4_invalid_json_twice` | PASS: garbage→valid = 2 calls, typed; garbage twice = 2 calls, untyped, warning, no exception; failures are not cached |
| L5 | `test_L5_bbox_roundtrip[...]` (7 image sizes × Y_DOWN/Y_UP), `test_L5_bbox_roundtrip_inexact_aspect`, `test_L5_letterbox_centred` | PASS: exact (`==`) on the 4 extent corners |
| L6 | `test_L6_hungarian`, `test_L6_assignment_maximises_total[scipy/greedy]`, `test_L6_scipy_path_used_when_available` | PASS |
| L7 | `test_L7_no_provider[...]`, `test_L7_provider_none_but_config_set` | PASS: untyped, 0 calls, no exception |
| L8 | `test_L8_temperature` | PASS: every call (incl. the retry) gets `float` 0.0 |
| L9 | gates | ruff, ruff format --check, mypy strict: clean; `python -m ale.contracts.lock --check`: OK; coverage 99 % ≥ 90 % |

Edge cases (`tests/labels/test_labels_robust.py`): non-PNG image, missing image, degenerate
extent, provider exception, non-`str` answer, retry count follows
`vlm.max_invalid_json_retries` (0/1/3), corrupt cache entry, cache write failure (warning,
temp file removed), bad cache keys, prompt-version mismatch warning, low-overlap and
zero-area boxes, taxonomy-key labels, unknown labels, invalid polygons, text in a hole,
total failure → input plan returned. All PASS.

## 2. Design notes, literal readings and ambiguities (for review)

1. **Native extent / rendering model.** The RD says the bbox conversion uses "the image size
   and the plan's native extent" but does not define either. Chosen: the extent is drawn
   with a uniform scale, centred (letterboxed if the aspect ratios differ); image rows go
   down (Y_UP: top row = `ymax`; Y_DOWN: top row = `ymin`). `label_plan` gets an extra
   **optional** keyword `extent=` (default `plan_extent(plan)` = bounds of room exteriors,
   walls and openings; texts excluded). The renderer of the integration ticket must use the
   same model, or pass `extent`.
2. **"Exact" round trip (L5).** Exact with `Fraction` arithmetic and one final float
   rounding. It is bit-exact on the 4 corners whenever the intermediate normalised values
   are representable (same aspect ratio, or a representable letterbox offset). For arbitrary
   aspect ratios the normalised floats are rounded, so the round trip is within ~1 ulp
   (tested separately with `rel=1e-12`).
3. **Greedy fallback is not optimal in general.** The RD asks for "a deterministic greedy
   fallback" when scipy is missing; implemented literally (highest overlap first, ties by
   index). L6's crosswise case is solved optimally by both paths, but adversarial matrices
   (e.g. `[[0.9, 0.8], [0.85, 0]]`) are only optimal with scipy; this is asserted in
   `test_L6_scipy_path_used_when_available`. scipy is not a declared dependency.
4. **Retry count.** RD: "one retry"; `config.vlm.max_invalid_json_retries` (default 1, 0..3)
   is honoured, so the default matches the RD.
5. **Prompt version / model id in the cache key.** The key uses the module constant
   `ale.labels.provider.PROMPT_VERSION` (the prompt text belongs to it) and
   `provider.model_id` (the model actually called). A different `vlm.prompt_version` in the
   config only produces a warning; `vlm.model_id` is not used.
6. **Text sources.** `TextItem.source` `CAD` → `CAD_TEXT`, `PDF` → `PDF_TEXT`; `OCR` has no
   `LabelSource` of its own and is mapped to `PDF_TEXT`. Text confidence mirrors the CAD
   reader: 1.0 exact match, 0.8 prefix match; the longest matched synonym wins.
7. **VLM labels.** The prompt asks for the exact French label (`label_fr` normalises to its
   key, `label_en` mostly does not). Extension: a label equal to a taxonomy key is taken as
   that key before `normalize_label` (otherwise `"office"` would normalise to
   `kitchenette`). Unmatched labels → `"unknown"`, `label_source VLM`.
8. **Kept rooms.** Every room that already has a type (any `label_source`) is kept as is.
9. **Warnings** are returned in `LabelResult.warnings`; `plan.warnings` is not modified.
   Invalid responses are not cached; only a valid raw response is stored.
10. **Timeout.** `vlm.timeout_s` is not enforced here (no threads/signals); it is the real
    provider's job (decision O-3).
11. Only key-shaped names (64 lowercase hex chars) are accepted by `VlmCache`, so cache paths
    cannot escape the directory. Writes are atomic (`mkstemp` + `Path.replace`, Windows-safe).

## 3. Whole suite

`pytest -q`: **846 passed, 7 skipped, 2 xfailed** (pre-existing skips/xfails) in ~203 s.
