# Ticket P.1 — Evaluation (no network in CI: the SDK client is mocked)
| ID | Test | Pass condition |
|---|---|---|
| V1 | factory | `""` → None; `"anthropic"` → AnthropicVlmProvider with model `claude-opus-5-5` by default; unknown → ValueError. |
| V2 | request_shape | Mocked client receives one request: model id, an image block (base64 PNG, media type image/png) before the text block, structured-output format matching VlmResponse, effort low, **no `temperature`/`top_p`/`top_k`**. |
| V3 | json_roundtrip | Mocked structured response → `label_image` returns text that parses into `VlmResponse`; through `label_plan` with a real `VlmCache` the room gets typed (`VLM`), second run makes 0 client calls. |
| V4 | errors | Mocked refusal, max_tokens, rate-limit, auth and connection errors → provider error raised (not swallowed); `label_plan` then leaves the room untyped with a warning. |
| V5 | key_hygiene | Missing env var → clear error, no client created; the key value never appears in logs or the cache directory. |
| V6 | downscale | 4000×3000 PNG → sent image long side ≤ 1568, aspect preserved; reported size equals the sent size. |
| V7 | live_smoke (optional) | Only if `ALE_LIVE_VLM=1`: label one generated 2-room plan image; assert ≥ 1 room typed. Never in CI. |
| V8 | gates | Whole suite (tests skip cleanly without the `vlm` extra); ruff, format, mypy strict; coverage of `ale.labels.providers` ≥ 90 %; lock --check. |
