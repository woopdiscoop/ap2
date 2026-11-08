# 1.5 — Router notes

Status: BLOCKED on 1.2, 1.3, 1.4 (needs PlanGeometry outputs) and decision O-3 (VLM provider).

Parked:
- Cache key = sha256(file) + page + prompt_version + model_id (directive §3.D); a second run must make 0 API calls.
- The bbox convention must be fixed per provider and converted in exactly one tested function.

## Review log
- 2026-11-08 — 7e26c26: accepted. Readings: extent model (uniform scale, centred; optional `extent=`), L5 exact up to 1 ulp when aspect differs, greedy fallback, OCR→PDF_TEXT, exact taxonomy keys taken as-is, cache key uses module PROMPT_VERSION. Carry to integration: renderer/extent consistency, timeout in real provider. **DONE**.
