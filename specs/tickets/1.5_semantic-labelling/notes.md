# 1.5 — Router notes

Status: BLOCKED on 1.2, 1.3, 1.4 (needs PlanGeometry outputs) and decision O-3 (VLM provider).

Parked:
- Cache key = sha256(file) + page + prompt_version + model_id (directive §3.D); a second run must make 0 API calls.
- The bbox convention must be fixed per provider and converted in exactly one tested function.
