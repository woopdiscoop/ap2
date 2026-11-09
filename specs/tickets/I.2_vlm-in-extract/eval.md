# Ticket I.2 · Evaluation (all tests mock the provider; no network)

| ID | Test | Pass condition |
|---|---|---|
| V201 | default_off | `[vlm] provider = ""` → `make_provider` returns None, no `anthropic` import, results identical to I.1 (byte-equal plan.json on the fixture corpus). |
| V202 | raster_extent | A synthetic raster plan with a known room: the mock VLM returns that room's pixel box normalised; `label_plan` assigns the label to that room (box → native round trip exact). |
| V203 | pdf_extent | Same for a vector PDF fixture (page render + extent). |
| V204 | dxf_render | Same for a DXF fixture rendered by `render.py`; image long side 1568; Y_UP mapping correct. |
| V205 | prepared_image | A 3000 px raster: the bytes given to `label_plan` equal `prepare_image(...).png` (one downscale, consistent cache key). |
| V206 | missing_key | Provider configured, key unset → one French warning, run completes text-only, exit 0. |
| V207 | provider_error | Mock raises `VlmProviderError` on one plan → warning on that plan, other plans labelled, exit 0. |
| V208 | cache | Second `ale extract --force` run: 0 provider calls (all cache hits), identical output. |
| V209 | no_vlm_flag | `--no-vlm` with a configured provider → 0 provider calls. |
| V210 | gates | ruff, format, mypy strict; coverage of `ale.labels.render` and the new extract paths ≥ 90 %; lock --check; whole suite passes. |
