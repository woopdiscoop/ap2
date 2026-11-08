# 1.1 — Router notes

Status: BLOCKED on 0.1, 0.2, 0.4 and the annotated test corpus (directive §7).

Parked for specification:
- Workspace portability: store the input root once plus relative paths, so a copied workspace can be re-pointed (`--input` on a new machine) without re-hashing.
- macOS returns NFD file names; normalise names to NFC for display/DB keys but always open files via the OS-provided path.
- Vector/scanned PDF page classification needs a fixture set (vector page, scanned page, mixed page with a raster logo).
- DWG detection: header `AC10xx`; DWG without converter → `NEEDS_TOOL`, never fatal.

## Review log
- 2026-11-08 — 4984565: 52 tests, 99.8 % coverage; accepted edits to tests/cli S04 (stubs list) and P05 (CI line); accepted re-classification of NEEDS_TOOL units when a tool appears. Merged: 614 pass, gates clean. **DONE**.
- Real corpus C15: 439 files, 1734 units, 0 failed. Most PDF_VECTOR pages are report/book pages, not plans → Phase 1 needs a 'is this a floor plan?' filter before extraction (candidate for 1.5/1.6 or a small ticket).
