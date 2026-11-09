# Ticket I.2 — Claude labelling in `ale extract` · Evaluation report

All tests mock the provider (`make_provider` patched in `ale.corpus.extract`, or the real
factory with the key unset). No network call is made and no API key is read or needed.

## Results
| ID | Test | Result |
|---|---|---|
| V201 | `tests/corpus_extract/test_extract_vlm.py::test_V201_default_off` | PASS. `[vlm] provider = ""` → `make_provider` returns None. A subprocess `run_extract` over a 5-unit generated corpus (untyped DXF, labelled DXF, raster PNG, vector PDF, scanned PDF) extracts 5 units with 0 VLM calls, and `'anthropic' not in sys.modules`. A copy of the same workspace extracted with the I.1 labelling step verbatim gives byte-equal `plan.json` (5 files). No `cache/vlm` entries. |
| V202 | `tests/labels_render/test_render_eval.py::test_V202_raster_extent` (+ `_from_source_file`) | PASS. `extent == (0, 0, W, H)`. The image decodes to exactly the traced bitmap. The mock VLM returns the room's pixel box, normalised; `label_plan` types that room only (`VLM`/`office`). R1/R3 share their x range and differ only in y, so a row flip would be caught. The box → native round trip is exact (1e-9). |
| V203 | `test_render_eval.py::test_V203_pdf_extent` (+ `_rotated_page`) | PASS. Page rendered at `raster_dpi` (2480×3509 px), `extent == (0, 0, 595, 842)` pt. Every wall centreline maps onto drawn ink in the prepared image. Each of the 2 rooms is labelled by its own mock box. A `/Rotate 90` page is rendered unrotated, matching the reader's coordinates. |
| V204 | `test_render_eval.py::test_V204_dxf_render` | PASS. Pillow drawing with long side 1568, so `prepare_image` is a no-op (same bytes). `extent = plan_extent + 2 %` per axis. Y_UP check: the top wall is drawn within the top 10 % of the rows. Top-right and bottom-right rooms (which differ only in y) are each labelled by their mock box. |
| V205 | `test_extract_vlm.py::test_V205_prepared_image` | PASS. 3000×2000 PNG through `run_extract`: the only `image` given to `label_plan` equals `prepare_image(plan_image(...)).png` (1568×1045). The provider received the same bytes. The cache file for `cache_key(..., image=those bytes)` exists. |
| V206 | `test_extract_vlm.py::test_V206_missing_key` | PASS. Provider `anthropic`, `ALE_VLM_API_KEY` unset: `ale extract` exits 0 and prints `avertissement : clé API absente : la VLM est désactivée` exactly once. 3 units extracted text-only; no VLM rooms and no cache files. |
| V207 | `test_extract_vlm.py::test_V207_provider_error` | PASS. The mock raises `VlmProviderError` for the DXF plan's image. Exit 0; summary `VLM : 3 plan(s) envoyé(s), 0 réponse(s) du cache, 1 erreur(s)`. The DXF plan carries the warning `VLM provider call failed: VlmProviderError: …` and stays text-labelled; the PNG and PDF plans are VLM-labelled. All units are EXTRACTED. |
| V208 | `test_extract_vlm.py::test_V208_cache` | PASS. Run 1: 3 provider calls. Units reselected (see Spec issues), then run 2 with a provider that would answer differently: 0 calls, summary `0 plan(s) envoyé(s), 3 réponse(s) du cache`, `plan.json` byte-identical. |
| V209 | `test_extract_vlm.py::test_V209_no_vlm_flag` | PASS. `--no-vlm` with a configured provider: `make_provider` is never called, 0 provider calls, no VLM summary line, rooms text-only. |
| V210 | `tests/labels_render/test_render_gates.py::test_V210_gates` | PASS. Covers `lock --check`, ruff, ruff format and mypy (strict) on the I.2 files. It also measures coverage of the I.2 tests in a subprocess: `ale.labels.render` ≥ 90 % and the VLM section of `extract.py` ≥ 90 %. Numbers below. |

Extra tests:
- `test_extract_vlm.py`: one test per source kind end to end (DXF, PNG and vector PDF are each VLM-labelled, and the provider is built once per run); unknown provider name (warning, text-only); render failure (plan warning, no call); a fully text-labelled plan (not rendered, no call); scanned PDF (the traced bitmap is passed and sent).
- `tests/labels_render/test_render_robust.py`: tall/DWG/Y_DOWN CAD drawings (colours, door red, window not drawn, holes); missing source or bitmap; empty bitmap; unreadable image; scanned page reloaded at a given DPI; invalid DPI; page out of range; corrupt PDF; pixel cap.

## Gates
- Whole suite: **1172 passed, 12 skipped, 4 xfailed** (the xfails are pre-existing, none in I.2 files), 713 s.
- `ruff check .`, `ruff format --check .` (221 files) and `mypy` (strict, 115 source files): clean.
- `python -m ale.contracts.lock --check`: OK. No contract changes.
- Coverage, measured on the whole suite with path-form targets (`--cov=src/ale/labels --cov=src/ale/corpus --cov=src/ale/cli`; package-form `--cov` crashes on a numpy reload in this repo):
  - `ale.labels.render`: **99 %**. The only miss is line 121, the zero-size page-box guard.
  - `ale.corpus.extract`: **99 %**. Misses: 526->528, which is one branch of the per-plan counters (VLM section), and lines 586 and 679, which are pre-existing paths.
  - `ale.cli.commands.extract`: **100 %**.
  - On the I.2 tests alone (what V210 checks): render 99 %, extract VLM section ≥ 99 %.

## Design notes
- **Two-pass labelling**: `label_plan` first runs text-only. The image is rendered only when untyped rooms remain and a provider exists, then `label_plan` runs a second time with the image. Typed rooms are kept, and the warnings of both passes are merged in order and de-duplicated. Without a provider the code path and output are those of I.1 (V201).
- **Counting**: `label_plan` already turns any provider exception into a result warning, so errors are counted by a thin wrapper around the provider (calls and errors) and cache hits by a `VlmCache` subclass. Per plan: `vlm_plans` counts plans with at least one provider call; `vlm_cache_hits` counts plans answered from the cache with no call; `vlm_errors` counts plans whose call raised. `ExtractReport` also gains `vlm_enabled`, `vlm_calls` and `vlm_warning`, all present in `to_dict()`.
- **Other `make_provider` failures** (unknown provider name → `ValueError`; missing `anthropic` package → `VlmProviderError`) are not specified. They are handled like the missing key: one French warning `VLM indisponible (…) : la VLM est désactivée` and a text-only run, never a failed run.
- **CAD margin**: "2 % margin" is read as 2 % of each axis' extent on each side, which keeps the aspect ratio.
- **Doors**: only `OpeningKind.DOOR` is drawn (red). Windows are not drawn, because the RD lists walls, doors, rooms and texts.
- **Render failure** (e.g. source file unreadable at render time) adds the plan warning `VLM skipped: plan image not rendered (…)`; the plan stays text-labelled.

## Spec issues
1. **V208 `ale extract --force` does not exist.** The I.1 CLI has only `--only-new` and `--kind`. EXTRACTED units are never reselected, so a plain second run makes 0 calls trivially. The RD's file list (§2) adds only `--no-vlm`. Following the intent (re-extracting the same plans must hit the cache), the test resets the units to `NEW` between the runs (what a forced re-extraction would do) and checks 0 provider calls, 3 cache hits and byte-identical output. No `--force` flag was added.
2. **Raster extent is half a pixel off the reader's convention.** RD §3 says `extent = (0, 0, W, H)` for RASTER/PDF_SCANNED. The raster reader puts pixel centres on integer coordinates, so the exact rendering-model extent would be `(-0.5, -0.5, W - 0.5, H - 0.5)`. The RD was followed literally; the offset is 0.5 native px and has no effect on overlap matching.
3. **PDF page size rounding.** PyMuPDF rounds the pixmap size up (A4 at 300 dpi gives 2480×3509, not 2479.2×3508.3). The uniform-scale, centred model absorbs the difference (< 1 px). The page is rendered with `/Rotate` cleared, because the vector reader's coordinates are in unrotated page space; the extent is the unrotated page box.
