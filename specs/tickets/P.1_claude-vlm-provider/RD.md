# Ticket P.1 — Claude VLM provider for room labelling · Requirements

> **Worker brief.** Context = this file, `eval.md`, the `ale.labels` public API (`VlmProvider` protocol, `VlmResponse`,
> `VlmRoom`, `label_plan`, `VlmCache`, `PROMPT_VERSION`) and `ale.contracts.config` (`[vlm]` section).
> **Before writing any Anthropic SDK code, load the `claude-api` skill and follow it** (Python). Do not guess SDK usage.
> User decision (2026-11-09): the VLM provider is **Claude** (Anthropic API).

## 1. Files
```
src/ale/labels/providers/__init__.py
src/ale/labels/providers/anthropic_provider.py   # AnthropicVlmProvider
src/ale/labels/providers/factory.py               # make_provider(config) -> VlmProvider | None
pyproject.toml                                    # ONLY: extra `vlm = ["anthropic>=1.0"]` (and add it to `all`)
tests/labels_providers/**
specs/tickets/P.1_claude-vlm-provider/eval_report.md
```

## 2. Behaviour
- `make_provider(config)`: `vlm.provider == ""` → `None`; `"anthropic"` → `AnthropicVlmProvider(model_id=vlm.model_id or "claude-opus-5-5", api_key_env=vlm.api_key_env, timeout_s=vlm.timeout_s)`; anything else → `ValueError` naming the provider.
- The API key is read from the environment variable named by `vlm.api_key_env` (default `ALE_VLM_API_KEY`) and passed to the SDK client explicitly; missing → a clear error before any call. Never log or persist the key.
- `label_image(image_png, prompt, *, temperature)`:
  - one Messages API call: user content = image block (base64 PNG) followed by the text prompt;
  - **no sampling parameters** are sent (current models reject `temperature`); the `temperature` argument must be `0.0` (assert) and is otherwise ignored — determinism comes from `VlmCache`;
  - structured output: request JSON matching `VlmResponse` (`{"rooms":[{"label","bbox","confidence"}]}`) using the SDK's structured-output support as documented in the skill; return the JSON text;
  - `output_config.effort = "low"` (labelling is a perception task; keep cost down), adaptive thinking as the skill prescribes for the model;
  - check `stop_reason`: `refusal` / `max_tokens` → raise a provider error (label_plan already turns failures into untyped rooms + warning);
  - enable the server-side refusal fallback the skill recommends for the chosen model and say so in the report;
  - enforce `vlm.timeout_s` on the request; map SDK errors with a most-specific-first chain (rate limit, auth, bad request, connection, status).
- Images larger than the API limits are downscaled (keep aspect, long side ≤ 1568 px) before encoding; `label_plan`'s bbox conversion must use the size actually sent — expose it so `label_plan` gets consistent coordinates (if this needs a change in `ale.labels.label`, report it instead of editing that file).

## 3. Out of scope
Batch processing, other providers, CLI wiring (I.1 calls `make_provider` later).
