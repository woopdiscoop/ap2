# Ticket 1.1 — Corpus Ingestion & Classification (`ale ingest`, `ale status`) · Requirements Document

> **Worker brief.** Context = this file, `eval.md`, the contracts (`SourceKind`, `FileStatus`), and the public
> interfaces of `ale.workspace`, `ale.config`, `ale.paths`, the CLI stubs in `src/ale/cli/commands/ingest.py` and
> `status.py`, and the test helpers in `tests/conftest.py`. Do not modify contracts.

## 1. Purpose
Scan a user-chosen **read-only** input folder of reference plans, register every file and every PDF page in
`corpus.sqlite`, classify each unit's `SourceKind`, and queue it for extraction. Idempotent.

## 2. Files
```
src/ale/corpus/__init__.py
src/ale/corpus/db.py          # schema + migrations of corpus.sqlite (user_version 0 → 1)
src/ale/corpus/scan.py        # walk, filter, hash
src/ale/corpus/classify.py    # SourceKind detection (magic bytes, DWG header, PDF page analysis)
src/ale/corpus/meta.py        # plans_meta.csv
src/ale/corpus/ingest.py      # ingest(...) → IngestReport
src/ale/cli/commands/ingest.py, src/ale/cli/commands/status.py   # replace the stub bodies (keep options)
.github/workflows/ci.yml      # ONLY: install line becomes `pip install -e ".[dev,excel,cad,pdf]"`
tests/corpus/**
specs/tickets/1.1_corpus-ingestion/eval_report.md
```
Dependencies: PyMuPDF (`fitz`, extra `pdf`) for PDF page analysis, imported lazily; without it PDFs are
registered with status `NEEDS_TOOL` (`reason = "pdf extra not installed"`).

## 3. Database (`corpus.sqlite`, migrate `user_version` 0 → 1; keep `ale_meta`)
```sql
inputs(id INTEGER PRIMARY KEY, root TEXT NOT NULL UNIQUE, added_at TEXT NOT NULL)   -- absolute input root as given, NFC
files(sha256 TEXT PRIMARY KEY, size INTEGER NOT NULL, ext TEXT NOT NULL, first_seen TEXT NOT NULL,
      excluded INTEGER NOT NULL DEFAULT 0, meta_json TEXT)
file_paths(sha256 TEXT NOT NULL REFERENCES files, input_id INTEGER NOT NULL REFERENCES inputs,
      rel_path TEXT NOT NULL, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL, seen_at TEXT NOT NULL,
      PRIMARY KEY (input_id, rel_path))
units(id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL REFERENCES files, page INTEGER NOT NULL,
      kind TEXT NOT NULL, status TEXT NOT NULL, reason TEXT, updated_at TEXT NOT NULL,
      UNIQUE(sha256, page))
events(id INTEGER PRIMARY KEY, ts TEXT NOT NULL, sha256 TEXT, page INTEGER, event TEXT NOT NULL, detail TEXT)
```
`kind` ∈ `SourceKind` values; `status` ∈ `FileStatus` values. Timestamps UTC ISO-8601 with `Z`. `rel_path` uses
`/` separators and NFC. A unit = (file, page); non-PDF files have one unit with `page = 0`.

## 4. Scan & classification
- Walk `--input` (recursive by default), only extensions in `--include` (case-insensitive), skip hidden files
  and folders (name starts with `.`) and `~$*` lock files. Symlinks are not followed.
- **Read-only**: open files `rb` only; never write, rename, delete or touch anything under the input folder;
  refuse (exit 4) if the workspace lies inside the input folder or vice versa.
- Skip re-hashing when `(input_id, rel_path, size, mtime_ns)` is unchanged. SHA-256 in 1 MiB chunks.
- Same content under another path → new `file_paths` row, no new unit (`event duplicate`). Content changed at
  a path → new `files` row, new units `NEW`; the old file keeps its units.
- **Kind detection** (by content, extension only as a tie-break):
  - DWG: first 6 bytes `AC10` + 2 digits → `DWG`; if no ODA File Converter and no accoreconsole is detected
    (reuse `ale.doctor`'s tool detection) → status `NEEDS_TOOL`, reason `"DWG needs ODA File Converter or accoreconsole"`; else `NEW`.
  - DXF: text file whose first non-empty lines are `0` / `SECTION` (or binary DXF sentinel `AutoCAD Binary DXF`) → `DXF`.
  - Raster: PNG/JPEG/TIFF magic bytes → `RASTER`.
  - PDF (`%PDF-`): one unit per page; page is `PDF_VECTOR` if it has `≥ extract.pdf_vector_min_paths` drawing
    paths (`len(page.get_drawings())`), else `PDF_SCANNED` if images cover ≥ 50 % of the page area, else
    `PDF_VECTOR` when it has ≥ 1 path, else `PDF_SCANNED`. Encrypted / unreadable → `FAILED` with reason.
  - Extension says one thing, content another → content wins, `event kind_mismatch`.
  - Anything else / corrupt → unit `FAILED` with reason; never fatal.
- Archives (`.zip`, `.rar`) are not opened in v1: logged as `skipped_archive`, not registered.

## 5. `plans_meta.csv` (`--meta`)
UTF-8 (BOM accepted), `,` or `;` separator auto-detected, header `filename,page,scale_1_to,units,
building_type,floor,exclude`. `filename` matches `rel_path` or bare file name (ambiguous bare name → error row
reported, not applied). `exclude` truthy (`1/oui/yes/x/true`) → file `excluded = 1` and its units `EXCLUDED`.
Other fields stored in `files.meta_json` (per page when `page` given). Invalid rows → warnings in the report.

## 6. `ingest(...)` / CLI
`ingest(workspace, input_dir, include, recursive, meta) -> IngestReport` with counts: files_seen, files_new,
files_unchanged, duplicates, units_new, units_by_kind, units_by_status, failed (list of (rel_path, reason)),
skipped_archives, meta_warnings. CLI `ale ingest` prints a French summary (and `--json` is not required);
exit 0 even with FAILED units; exit 4 for workspace/input errors.
`ale status --workspace W [--json]`: counts of units by kind × status, number of inputs, last ingest time.

## 7. Out of scope
Extraction (1.2–1.4), archives, network.
