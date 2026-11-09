# Ticket P.1 — Claude VLM provider · Evaluation report

## Results
| ID | Test | Result |
|---|---|---|
| V1 | `test_V1_factory` | PASS — `""` → None; `"anthropic"` → `AnthropicVlmProvider` (`claude-opus-5-5` default, `api_key_env`/`timeout_s` from config, custom model id honoured); unknown → `ValueError` naming it. |
| V2 | `test_V2_request_shape` | PASS — one `client.beta.messages.create` call: model id; image block (base64, `image/png`) then text block; `output_config.format` = `json_schema` whose fields/required/`additionalProperties:false` match `VlmResponse`/`VlmRoom` (validated with jsonschema); `effort: "low"`; `thinking: {"type": "adaptive"}`; per-request `timeout = vlm.timeout_s`; no `temperature`/`top_p`/`top_k`. |
| V3 | `test_V3_json_roundtrip` | PASS — mocked structured answer parses into `VlmResponse`; through `label_plan` + real `VlmCache` both rooms typed with `LabelSource.VLM`; second run 0 client calls, identical plan. |
| V4 | `test_V4_errors[×5]` | PASS — refusal, max_tokens, 429, 401, connection error → `VlmProviderError` raised; `label_plan` leaves rooms untyped, warning contains `VlmProviderError`, nothing cached. |
| V5 | `test_V5_key_hygiene` | PASS — unset/blank env var → `MissingApiKeyError` naming the variable, SDK constructor never called; key passed explicitly as `api_key=`; key absent from `repr`, provider attributes, logs (DEBUG caplog), warnings, auth-error message and every cache file. |
| V6 | `test_V6_downscale` | PASS — 4000×3000 → sent 1568×1176 (aspect kept); `provider.last_image_size` and `prepare_image(...).size` equal the decoded sent size. |
| V7 | `test_V7_live_smoke` | SKIPPED (needs `ALE_LIVE_VLM=1`; not run, per instructions). |
| V8 | gates | PASS — see below. |

Extra edge tests: `tests/labels_providers/test_providers_robust.py` (full SDK error chain incl. 403/400/5xx/timeout/generic `APIError`, refusal category, unexpected stop reason, empty answer, text after a `fallback` switch point, temperature assert, constructor validation, small/tall/invalid images, real `anthropic.Anthropic` built with key/timeout/max_retries).

## Gates
- Whole suite: 1088 passed, 10 skipped, 2 xfailed (pre-existing).
- Provider tests `pytest.importorskip("anthropic")` → skip cleanly without the `vlm` extra; the package itself imports `anthropic` lazily (factory `""` path works without it).
- `ruff check`, `ruff format --check`, `mypy` (strict): clean.
- Coverage `ale.labels.providers`: **100 %** (statements and branches). Measured with `--cov=src/ale/labels/providers`: in this venv a dotted *sub-package* target (`--cov=ale.labels.providers`, also `--cov=ale.labels.label`) makes coverage import the parents before pytest and numpy fails with "cannot load module more than once per process" — an environment quirk unrelated to this ticket (`--cov=ale.labels` works).
- `python -m ale.contracts.lock --check`: OK (exit 0).

## Refusal fallback
Enabled the **server-side refusal fallback in `"default"` mode**: `client.beta.messages.create(..., betas=["server-side-fallback-2026-07-01"], fallbacks="default")`. A classifier decline is re-run inside the same call on the model Anthropic recommends for that refusal category. Only text after the last `fallback` content block is returned. If the final `stop_reason` is still `refusal` (whole chain declined), `VlmProviderError` is raised with the `stop_details.category`. Note: this works on the Claude API only (not Bedrock/Vertex/Foundry, where the SDK middleware would be needed).

## Design notes / literal readings
- **SDK usage** follows the `claude-api` skill (Python, anthropic 2.6.0 installed): model `claude-opus-5-5`, base64 image block before text, `output_config.format` json_schema (raw schema, since the beta endpoint is needed for `fallbacks`), `output_config.effort="low"`, `thinking={"type":"adaptive"}` (thinking cannot be disabled on Opus 5.5), `max_tokens=16000` non-streaming, error chain most-specific-first: RateLimit → Authentication → PermissionDenied → BadRequest → APIStatusError → APITimeoutError → APIConnectionError → APIError.
- **Schema**: hand-written JSON schema equivalent to `VlmResponse`; numeric ranges (0..1000, 0..1, min≤max) are not in the structured-output schema subset, so they stay enforced by `parse_response`.
- **Timeout**: `vlm.timeout_s` is set on the client and on each request. The SDK still retries 408/409/429/5xx/connection errors (`max_retries=2`, constructor arg), so worst-case wall clock is `timeout_s × 3`. If "per VLM call" must bound the whole call, construct with `max_retries=0` (not exposed in `[vlm]`, contracts frozen).
- **temperature**: `assert temperature == 0.0` as specified (asserts vanish under `python -O`; `VlmConfig` already rejects non-zero values).
- **Downscale needs Pillow** (extra `raster`); the RD only allows adding `anthropic` to `vlm`. Without Pillow an image > 1568 px raises `VlmProviderError` with an install hint. Images ≤ 1568 px are sent byte-for-byte.
- **bbox consistency (no `ale.labels.label` change needed, reported)**: the VLM bbox is normalised 0..1000 relative to the image, so it is invariant under an aspect-preserving resize; `label_plan` converting with the original PNG size only differs by sub-pixel rounding of the resized dimensions. For exact consistency (and a cache key on the image actually sent), I.1 should call `ale.labels.providers.prepare_image(png)` and pass `prepared.png` to `label_plan`; the provider then sends it unchanged. The sent size is exposed as `PreparedImage.size` and `AnthropicVlmProvider.last_image_size`.
