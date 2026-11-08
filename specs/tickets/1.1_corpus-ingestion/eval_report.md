# Ticket 1.1 — Corpus Ingestion · Evaluation report

Environment: Linux, Python 3.13. Two virtual environments outside the worktree:
`.[dev,excel,cad,pdf]` ("full") and `.[dev]` ("dev only").

## Results by eval ID

| ID | Test(s) (`tests/corpus/`) | Full | Dev only |
|---|---|---|---|
| C01 | `test_C01_read_only` | pass | pass |
| C02 | `test_C02_idempotent`, `test_C02_touched_file_is_unchanged` | pass | pass |
| C03 | `test_C03_rename_move` | pass | pass |
| C04 | `test_C04_modified` | pass | pass |
| C05 | `test_C05_kinds` | pass | pass (the `.png`-that-is-a-PDF is `NEEDS_TOOL`) |
| C06 | `test_C06_pdf_pages`, `test_C06_pdf_vector_only_via_path_rule`, `test_C06_pdf_without_extra` | pass | first two skip, third passes |
| C07 | `test_C07_dwg_needs_tool`, `test_C07_dwg_tool_on_path` | pass | pass |
| C08 | `test_C08_corrupt_never_fatal`, `test_C08_encrypted_pdf_report` | pass | first passes (no encrypted PDF), second skips |
| C09 | `test_C09_filters` | pass | pass |
| C10 | `test_C10_meta_csv`, `test_C10_meta_csv_per_page` | pass | first passes, second skips |
| C11 | `test_C11_workspace_inside_input` | pass | pass |
| C12 | `test_C12_unicode_paths` | pass | pass |
| C13 | `test_C13_migration`, `test_C13_newer_schema_refused` | pass | pass |
| C14 | `test_C14_cli`, `test_C14_status_bad_db` | pass | pass |
| C15 | `test_C15_real_corpus_smoke` | skipped (no `ALE_CORPUS_DIR`); run once manually, see below | skipped |
| C16 | `test_C16_gates` (lock --check, CI install line, ruff, ruff format, mypy on the corpus code) | pass | pass |

`test_corpus_units.py` adds edge-case tests: detection table, TIFF/BigTIFF/PNG checks,
PDF rules through a fake PyMuPDF, so they also run without the extra, meta CSV parsing,
scan errors, hash errors and the NEEDS_TOOL re-classification.

## Gates

* Whole suite, full venv: **589 passed, 6 skipped** (skips are pre-existing Windows-only/root ones, plus C15).
* Whole suite, dev-only venv: **549 passed, 17 skipped** (the PDF tests skip, as do pre-existing extra-dependent tests).
* `tests/corpus`: 52 passed / 1 skipped (full); 47 passed / 6 skipped (dev only).
* `ruff check .`, `ruff format --check .`, `mypy` (strict): clean in the full venv.
  In the dev-only venv, `mypy` reports 3 **pre-existing** `import-not-found` errors in
  `src/ale/program/site.py` (ezdxf, from the `cad` extra). They are not part of this ticket. CI installs `cad`.
* `python -m ale.contracts.lock --check`: exit 0, so the contracts are unchanged.
* Coverage of `ale.corpus` (full venv, `pytest --cov=ale`): 640 statements, 1 missed, so **99.8 % line**
  (classify 100 %, db 100 %, ingest 100 % line, meta 100 %, scan 98 %). `cli/commands/ingest.py` and `status.py` are both at 100 %.

## C15: real reference corpus (run once, `ALE_CORPUS_DIR` set, full venv)

The corpus was used read-only and nothing from it was copied into the repo. Ingest took about 80 s; a second ingest found everything unchanged.

| Count | Value |
|---|---|
| files_seen | 439 |
| files_new | 432 |
| duplicates | 7 |
| units_new | 1734 |
| units_by_kind | DWG 17 · PDF_VECTOR 879 · PDF_SCANNED 436 · RASTER 402 |
| units_by_status | NEW 1717 · NEEDS_TOOL 17 (the DWGs: no converter on this machine) |
| failed | 0 |
| skipped_archives | 3 (2 `.zip`, 1 `.rar`) |
| second run | units_new 0, files_unchanged = files_seen |

## Spec issues and the readings chosen

1. **Pre-existing tests conflicted with the ticket**, and both lie outside RD §2. To keep the
   suite green I made the smallest edit that would do it, and I am flagging both here:
   * `tests/cli/test_cli_surface.py::test_S04_stub_exit_code` expected `ingest` / `status` to
     exit 3 ("not implemented"). The two entries were removed from `STUB_TICKETS`. Their options
     are still checked by S03 and S05.
   * `tests/cli/test_portability.py::test_P05_ci_matrix` asserted the old install line. It was
     updated to `.[dev,excel,cad,pdf]`, as RD §2 requires for `ci.yml`.
2. **`kind` of a unit that could not be analysed.** `kind` is `NOT NULL`, but the content gives no answer.
   The extension decides as a tie-break: dwg→DWG, dxf→DXF, pdf→`PDF_SCANNED`, any other→RASTER.
   An encrypted or unreadable PDF and a PDF without the extra (`NEEDS_TOOL`) each get one unit,
   `page 0`, `PDF_SCANNED`.
3. **Corrupt raster detection** (C08 "truncated PNG"). Magic bytes alone cannot catch a truncated file,
   so light structural checks run without any library: PNG needs IHDR plus IEND in the tail, JPEG needs
   an EOI marker in the last 4 KiB, and a TIFF's IFD offset must fall inside the file. No decoding is done.
4. **`meta.page`** is 0-based, the same as `units.page`. Exclusion with `page` empty marks the file
   (`excluded = 1`) and all of its units `EXCLUDED`. Exclusion with `page` given excludes only that unit
   and leaves the file flag at 0. File-level fields go at the top level of `meta_json`; page fields go
   under `meta_json.pages["<page>"]`. A bare name that matches several paths of the *same* content is
   not ambiguous. Truthy values are those of the RD plus `y/o/vrai`. A value that is neither truthy nor
   falsy gives a warning and is read as "no".
5. **Report scope.** `units_by_kind`, `units_by_status` and `failed` describe the files seen in *this*
   run (after meta), not the whole corpus. `ale status` shows the whole corpus.
6. **Renames.** The old `file_paths` row is kept as history, since the RD does not say to delete it.
7. **NEEDS_TOOL re-classification** (an extension of the RD). When an unchanged file has only
   `NEEDS_TOOL` units and the tool or extra is now available, its units are re-classified (`event reclassified`).
   Without this, those files could never leave `NEEDS_TOOL`.
8. **Exit 4 before any write.** `ale ingest` checks workspace/input overlap *before* opening the
   workspace, because opening it attaches the log file, which would land inside the input folder.
   Overlap is tested on resolved paths with OS case rules.
9. **PyMuPDF import name.** `pymupdf` is tried first and the legacy `fitz` second, because importing
   `fitz` raises a FutureWarning in current PyMuPDF.
10. `ale.corpus` does not re-export `ingest`, because the function would shadow the `ale.corpus.ingest`
    submodule. Use `from ale.corpus.ingest import ingest`.
11. `ale status` reads the database read-only. A database not yet migrated (user_version 0) shows as an empty corpus.
