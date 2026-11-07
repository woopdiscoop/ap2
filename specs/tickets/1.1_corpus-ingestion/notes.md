# 1.1 — Router notes

Status: BLOCKED on 0.1, 0.2, 0.4 and the annotated test corpus (directive §7).

Parked for specification:
- Workspace portability: store the input root once plus relative paths, so a copied workspace can be re-pointed (`--input` on a new machine) without re-hashing.
- macOS returns NFD file names; normalise names to NFC for display/DB keys but always open files via the OS-provided path.
- Vector/scanned PDF page classification needs a fixture set (vector page, scanned page, mixed page with a raster logo).
- DWG detection: header `AC10xx`; DWG without converter → `NEEDS_TOOL`, never fatal.
