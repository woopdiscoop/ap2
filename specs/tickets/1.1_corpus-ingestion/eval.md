# Ticket 1.1 — Corpus Ingestion · Evaluation

Fixtures are **generated in tests** (tiny PNG/JPEG/TIFF via Pillow if installed else hand-written bytes; DXF via
ezdxf; PDFs via PyMuPDF: one page with 300 line paths, one page that is a single full-page image, one blank page;
a fake DWG = `b"AC1032" + zeros`). Never commit the user's corpus.

| ID | Test | Pass condition |
|---|---|---|
| C01 | read_only | Snapshot (path, size, mtime_ns, sha256) of the input folder before/after two ingests → identical. |
| C02 | idempotent | Second `ingest` on the same folder adds 0 files, 0 units; report `files_unchanged == files_seen`. |
| C03 | rename_move | Renaming / moving a file inside the input → recognised by hash: 0 new units, new `file_paths` row. |
| C04 | modified | Modifying a file's bytes → a new `files` row and new `NEW` units; the old ones untouched. |
| C05 | kinds | PNG, JPEG, TIFF → RASTER; DXF → DXF; fake DWG → DWG; `.png` that is really a PDF → PDF kind + `kind_mismatch` event. |
| C06 | pdf_pages | The 3-page PDF → 3 units: page 0 `PDF_VECTOR`, page 1 `PDF_SCANNED`, page 2 `PDF_SCANNED`; with `pdf_vector_min_paths = 500`, page 0 becomes `PDF_VECTOR` only via the ≥ 1 path rule. |
| C07 | dwg_needs_tool | With no converter detected → DWG unit `NEEDS_TOOL` + reason; with `tools.oda_file_converter` pointing to a dummy file → `NEW`. |
| C08 | corrupt_never_fatal | Truncated PNG, empty file, encrypted PDF → `FAILED` with reasons; ingest still exits 0 and registers the good files. |
| C09 | filters | Hidden files/folders, `~$x.dwg`, extensions not in `--include`, `.zip`/`.rar` (reported as skipped archives) are not registered; `--no-recursive` ignores subfolders. |
| C10 | meta_csv | `;`-separated CSV with BOM: exclude one file (units → EXCLUDED), set `scale_1_to=100` on another (stored in meta_json); ambiguous bare name → warning, not applied. |
| C11 | workspace_inside_input | Workspace inside the input folder (and input inside workspace) → exit 4, nothing written. |
| C12 | unicode_paths | Input folder `Références/Plans 2024` with a file `Façade é.png` → registered, `rel_path` NFC with `/`. |
| C13 | migration | Fresh `ale init` DB (user_version 0) → migrated to 1 on first ingest; `ale_meta` rows preserved; re-opening is a no-op. |
| C14 | cli | `ale ingest` exit 0 with summary; `ale status --json` counts equal a direct SQL `GROUP BY kind, status`. |
| C15 | real_corpus_smoke (optional) | If env `ALE_CORPUS_DIR` points to a folder, ingest it into a tmp workspace and print the counts (skipped otherwise; never in CI). |
| C16 | gates | ruff, ruff format, mypy strict clean; coverage of `ale.corpus` ≥ 90 % line; `lock --check` 0; whole suite passes with `.[dev,excel,cad,pdf]` **and** with `.[dev]` (PDF tests skip). |
