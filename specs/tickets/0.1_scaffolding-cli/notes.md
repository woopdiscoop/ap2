# 0.1 — Router notes

## Decisions taken while specifying
- `ale/contracts/config.py` (+ `config.schema.json`) is owned by **0.1**, not 0.2, so 0.1 and 0.2 touch disjoint files and can run in parallel. `ale/contracts/__init__.py` is created empty by both (identical content, no conflict).
- 0.1 owns `pyproject.toml`, including the pytest-timeout setting (60 s). Ticket 0.4 owns `tests/conftest.py`, fixtures and `ale.guards`.
- Values marked "Router-proposed" in the config defaults (`site.max_fill = 0.95`, `extract.pdf_vector_min_paths = 200`, `rulebook.blend_k = 10`, SA schedule) are placeholders; changing a default later does not change the schema.
- External-tool detection never executes the binary (the ODA converter opens a GUI with no arguments).
- Machine-specific tool paths: env vars `ALE_ODA_PATH` / `ALE_ACCORECONSOLE_PATH` override auto-detection so a copied workspace keeps working on another machine without editing `ale.toml`.
- A CI matrix (Windows/macOS/Linux × 3.11–3.13) is part of the deliverable: it is the only real evidence for "Windows first" from this Linux environment.

## 2026-11-07 user decisions
- `grid.module_mm` default 600 → **100** (U-1). `circulation.min_width_m` default 1.8 → **1.2 m** (U-3, confirmed by the user).

## Review log
- 2026-11-07 — Attempt 1 (commit 9af59a4): 123 pass / 3 skip. Accepted ambiguity resolutions: malformed-TOML message `ale.toml: line N, column M`, `generate --seed` default None (no workspace there), stub without workspace → exit 2, UTC log date, ruff `extend-exclude = ["specs"]`, bare `--version`. Follow-up requested: `vlm.timeout_s > 0`, `types-shapely`.
- 2026-11-07 — Attempt 2 (commit 2f196f4): Router re-run in a clean checkout + fresh venv: 124 pass / 3 skip (2 Windows-only, 1 root-only chmod), ruff/format/mypy clean, coverage 97 %, all 33 eval IDs present, ownership clean. Manual CLI checks passed (accented path + cp1252, idempotent init, doctor secret hygiene, stub exit 3, config error exit 4).
- Merged with 0.2: 327 pass / 3 skip, mypy strict clean on 33 modules. **DONE** (merge cafd493). Windows/macOS evidence pending first CI run (P05).
