# Ticket 1.5 — Evaluation (fake providers only; no network)
| ID | Test | Pass condition |
|---|---|---|
| L1 | text_first | Plan with 3 rooms, 2 containing texts `BUREAU 3`, `WC H/F` → typed office/sanitary via PDF_TEXT; 0 provider calls for those. |
| L2 | vlm_fill | Remaining room labelled by a fake provider returning valid JSON with bbox over it → typed, label_source VLM, 1 call. |
| L3 | cache | Second run → 0 calls; changing PROMPT_VERSION or model_id → 1 call. |
| L4 | invalid_json | Fake returns garbage then valid → 2 calls, success; garbage twice → untyped + warning, no exception. |
| L5 | bbox_roundtrip | Normalised↔native conversion exact on 4 corners for Y_DOWN and Y_UP plans, several image sizes. |
| L6 | hungarian | Two VLM boxes overlapping two rooms crosswise → one-to-one assignment maximising total overlap. |
| L7 | no_provider | `vlm.provider = ""` → untyped rooms stay untyped, 0 calls, no exception. |
| L8 | temperature | Provider called with temperature 0.0 exactly. |
| L9 | gates | ruff, format, mypy strict; coverage ≥ 90 %; lock --check; whole suite. |
