# Ticket I.1 — Evaluation (all inputs generated in tests; reuse the builders from tests/pdfread, tests/raster, tests/cad)
| ID | Test | Pass condition |
|---|---|---|
| N1 | pdf_vector | Ingest a generated vector-PDF plan page + a text-only page → extract: plan page EXTRACTED with plan.json (rooms typed PDF_TEXT, scale TITLE_BLOCK); text page EXCLUDED `not a plan`. |
| N2 | scanned_and_raster | A scanned PDF page and a PNG plan → EXTRACTED; plan.json present; scale UNKNOWN → flag `scale_unknown` stored. |
| N3 | meta_scale | `plans_meta.csv` with `scale_1_to=100, dpi=150` for the PNG → scale META_CSV = 100·0.0254/150; `north_angle_deg` stored in meta_json. |
| N4 | cad_also_labelled | DXF plans now pass through resolve_scale/label_plan/review_flags (flags stored; plan.json unchanged except label/scale fields). |
| N5 | review_page | `ale review` writes `review/index.html`: valid HTML (parses with html.parser), one row + one inline `<svg>` per flagged plan; `--all` lists all; `--json` matches the DB. |
| N6 | migration | DB at user_version 1 → 2 on first run; re-running is a no-op; existing tables untouched. |
| N7 | idempotent | Second `ale extract --only-new` touches nothing. |
| N8 | stubs | No CLI stubs remain; the retargeted cp1252 test passes. |
| N9 | gates | Whole suite passes with `.[dev,excel,cad,pdf,raster]`; tests needing an extra skip cleanly without it; ruff, ruff format --check, mypy strict clean; coverage of `ale.corpus` ≥ 90 %; `python -m ale.contracts.lock --check` exits 0. |
