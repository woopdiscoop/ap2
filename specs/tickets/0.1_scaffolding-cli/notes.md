# 0.1 — Router notes

## Decisions taken while specifying
- `ale/contracts/config.py` (+ `config.schema.json`) is owned by **0.1**, not 0.2, so 0.1 and 0.2 touch disjoint files and can run in parallel. `ale/contracts/__init__.py` is created empty by both (identical content, no conflict).
- 0.1 owns `pyproject.toml`, including the pytest-timeout setting (60 s). Ticket 0.4 owns `tests/conftest.py`, fixtures and `ale.guards`.
- Values marked "Router-proposed" in the config defaults (`circulation.min_width_m = 1.8`, `site.max_fill = 0.95`, `extract.pdf_vector_min_paths = 200`, `rulebook.blend_k = 10`, SA schedule) are placeholders; changing a default later does not change the schema.
- External-tool detection never executes the binary (the ODA converter opens a GUI with no arguments).
- Machine-specific tool paths: env vars `ALE_ODA_PATH` / `ALE_ACCORECONSOLE_PATH` override auto-detection so a copied workspace keeps working on another machine without editing `ale.toml`.
- A CI matrix (Windows/macOS/Linux × 3.11–3.13) is part of the deliverable: it is the only real evidence for "Windows first" from this Linux environment.

## Review log
_(empty)_
