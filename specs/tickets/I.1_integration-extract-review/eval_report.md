# I.1 integration evaluation — Router-authorized revision

Rebased cleanly onto `origin/claude/new-session-2hmd3s` at `b48e39ea96e12f6106020de61f919961741b5e46`, retaining contracts 1.3.0, the upstream CI clock fix and P.1. Work remains on `codex/I.1-integration`; existing draft PR #1 targets the Router branch. No merge performed.

The Router's latest instruction and ticket notes authorize the three superseded legacy assertions below. No other existing test was weakened or deleted. Contracts, reader packages, pyproject.toml and the project board are unchanged relative to the new base.

## Exact legacy-test changes (authorized by Router)

| Existing test | Old assertion / setup → new assertion |
|---|---|
| `tests/corpus/test_corpus_ingest.py::test_C13_migration` | After ingest, `PRAGMA user_version == 1` → `2`; no-op `migrate(conn) == 1` → `2`. Initial version 0, ale_meta preservation, schema stability and required-table assertions remain unchanged. |
| `tests/corpus_extract/test_extract_eval.py::test_W07_other_kinds` | Two PDF/raster stubs reported; later kind filters each report one stub; units remain NEW and events unchanged → first run reports two exclusions for these generated **non-plan** fixtures, subsequent kind filters select zero, identities/kinds remain unchanged, both statuses are EXCLUDED with `not a plan (score …)` reasons, and exactly two exclusion events are added. Existing exit-code and no-plan-artifact assertions retained. N1/N2 independently assert successful extraction of actual generated plans. |
| `tests/rulebook/test_rulebook_eval.py::test_K10_cli` | `north_angle_deg` unknown-column warning required, followed by manual SQL injection → no north-column warning, and assert persisted CSV north values 0/90 directly. The obsolete manual write is removed, replaced with read-only SQL assertions. Only corresponding import cleanup (`execute` → `json`) is added. All later rulebook/output/idempotence assertions remain unchanged. |

Targeted rerun of these three tests: **3 passed in 0.76 s**.

## P.1 / I.2 boundary

The Router's subsequent ruling in `42de038` explicitly withdraws the prepare_image instruction: I.1 remains `image=None, provider=None`. Rendering, image preparation, configured provider wiring and opt-in API calls are deferred to I.2. The provisional optional-image API and its tests were removed before final delivery. No provider or renderer is enabled by this ticket.

## Evaluation IDs

| ID | Test | Outcome |
|---|---|---|
| N1 | `test_N1_pdf_vector` | PASS: generated vector plan extracted with PDF_TEXT rooms and TITLE_BLOCK scale; text/decorative-path page excluded. |
| N2 | `test_N2_scanned_and_raster` | PASS: scanned page and PNG extracted with UNKNOWN scale and persisted scale_unknown flags. |
| N3 | `test_N3_meta_scale` | PASS: page metadata overrides file values; scale 100 × 0.0254 / 150; north/DPI persisted. |
| N4 | `test_N4_cad_also_labelled` | PASS: CAD pipeline output matches scale+label APIs, geometry retained and flags stored. |
| N5 | `test_N5_review_page` | PASS: HTMLParser, one row/SVG per flagged plan, --all, DB/JSON consistency and unchanged HTML rewrite. |
| N6 | `test_N6_migration` | PASS: v1→v2, existing content preserved, rerun no-op. |
| N7 | `test_N7_idempotent` | PASS: --only-new leaves plan/DB bytes and mtime unchanged; flag replacement deduplicates. |
| N8 | `test_N8_stubs` | PASS: no review stub; authorized cp1252 status test retained. |
| N9 | `test_N9_gates` | PASS: whole suite has zero failures; static gates clean; corpus coverage 98.962%. |

Focused I.1 and corrected legacy tests: **16 passed in 2.66 s**. Generated fixtures only, reused builders, no copyrighted/binary plans committed. No network calls in this implementation or tests.

## Environment and gates

Python 3.11.17, isolated `.venv`; `python -m pip install -e ".[dev,excel,cad,pdf,raster,vlm]"` (vlm added for upstream P.1). Full-suite command: `python -m pytest --cov=ale.corpus --cov-report=term-missing --cov-report=json:/tmp/ale-i1-evidence/final-coverage.json`.

- Ruff check: PASS.
- Ruff format --check: PASS, 215 files formatted.
- Strict mypy: PASS, 114 source files.
- `python -m ale.contracts.lock --check`: PASS, exit 0.
- `git diff --check`: PASS.
- Whole suite: **1142 passed, 12 skipped, 4 xfailed, zero failures**, exit 0, 620.12 s (10m20s), 1158 collected.
- `ale.corpus` coverage: **98.962%** combined statements/branches (1040/1047 statements; 295/302 branches); statement coverage **99.331%**.
- Separate `.[dev]` environment, focused I.1 tests without reader extras: **2 passed, 11 skipped in 0.32 s**.

The full run tested the code at base `42de038`; the final rebase includes only upstream documentation changes in `b48e39e` (board and I.2 specifications), with no source/test/config difference. All four expected failures are existing geometry/optimizer cases on the new base, not introduced or changed here. The 12 existing skips include platform-only, optional corpus/live-provider, throughput-under-coverage and missing-history cases; they are not claimed as passes. An earlier run containing the now-withdrawn optional-image work was terminated and is not used as final evidence.

## Literal readings and ambiguities

- Selection remains exactly NEW, plus FAILED and DWG NEEDS_TOOL on default runs. Already EXTRACTED units are not automatically reprocessed or backfilled during migration. Existing v1 extracted plans have no new review flags until explicitly reset/re-extracted; --all still displays their plan files.
- Page-specific metadata overlays file-level fields; unspecified fields inherit. `north_angle_deg` accepts any finite float (no angle range specified). DPI accepts positive integral numeric values, including `150.0`; invalid fields warn and are omitted, consistent with the existing CSV parser.
- Scanned PDFs use page/file DPI or configured raster DPI for rendering, then the raster reader and its <0.3 exclusion threshold. The threshold is applied consistently to both raster routes. The renderer's bounded-resolution API returns no effective DPI; no reader change was made to recover it if rendering internally reduces resolution.
- PDF_VECTOR uses is_plan_likely; raster routes use score <0.3. A reader returning score zero on decode/missing-extra failure is therefore EXCLUDED under the literal score rule, with reader warnings preserved in the exclusion event. Exceptions still mark a unit FAILED. No hidden substitute reader or VLM call is used.
- UNKNOWN in N2 requires absence of scale anchors. Its generated raster closes the existing builder's two door gaps; otherwise the existing scale API may legitimately infer scale from door widths. N1's text page has one decorative line so ingestion classifies it as PDF_VECTOR and actually exercises the specified vector exclusion branch.
- Every successful plan runs scale → text-only labels → flags. Label warnings are retained on the plan. Flags are replaced per unit on extraction; the unique four-column key prevents duplicates.
- Per-kind summary counts mean successfully extracted units, alongside overall failed/excluded/needs-tool counts. The existing report's not_implemented field remains for API compatibility at zero but is no longer shown as a stub in the CLI.
- Review uses EXTRACTED units plus their plan.json files; default selection is stored flags, --all includes unflagged extracted plans. Deduplicated sources display the lexicographically first rel_path. Missing/corrupt/identity-mismatched plans fail explicitly rather than vanish from review.
- `--json` writes the same HTML and prints row data (including inline SVG strings) to stdout; the human path summary goes to stderr so stdout remains valid JSON. “Open the file path in the summary line” is interpreted as displaying the path to open, not automatically launching a browser.
- SVG coordinates are normalized to y-up from the plan's declared frame, then SVG's display axis is flipped. No physical rescaling or north rotation is specified/applied. Type colors are deterministic, untyped rooms grey, holes preserved, walls black, doors red. Source text is HTML-escaped. One data row and one inline SVG per plan; the table header is separate. Rendering is fully offline.

## Changed files and delivery

Original scope: corpus extract/meta/db/new review, CLI extract/review, corpus_extract fixtures/integration tests, new review tests, the two narrowly authorized CLI-test edits, and this report. Revision adds only the three Router-authorized legacy test corrections listed above. No other files changed relative to the rebased main branch.

The first delivery's HTTP 403 and three legacy failures are historical, resolved by restored access and the Router ruling. Existing PR: https://github.com/woopdiscoop/ap2/pull/1. Publication after rebase uses an explicit force-with-lease on **only** codex/I.1-integration; base/main are never pushed or merged.
