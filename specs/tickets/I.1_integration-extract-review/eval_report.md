# I.1 integration evaluation

**Status: BLOCKED for merge — N9 whole-suite acceptance fails on three conflicting legacy assertions.** Implementation and new acceptance tests are complete within ownership; no existing test was weakened or deleted. Router action is required to reconcile the legacy expectations with I.1. No reader, contract, dependency declaration, or global plan files were modified.

Base: `origin/claude/new-session-2hmd3s` at `1d08396`, isolated worktree, branch `codex/I.1-integration`. Python 3.11.17 on Linux. Installation: `python -m pip install -e ".[dev,excel,cad,pdf,raster]"` in a separate `.venv`. Test fixtures are generated at runtime from existing CAD/PDF/raster builders; no reference drawings or binary plan files are committed. Implementation/tests make no network calls.

## Evaluation IDs

| ID | Named test | Result | Evidence |
|---|---|---|---|
| N1 | `test_N1_pdf_vector` | PASS | Generated mixed PDF: vector plan extracted, two PDF_TEXT rooms and TITLE_BLOCK scale; non-plan text/decorative-line page excluded with score. |
| N2 | `test_N2_scanned_and_raster` | PASS | Generated scanned page and PNG extracted; UNKNOWN scale and stored scale_unknown flags. |
| N3 | `test_N3_meta_scale` | PASS | Page metadata overrides file metadata; PNG scale = 100 × 0.0254 / 150; file/page north and DPI persisted. |
| N4 | `test_N4_cad_also_labelled` | PASS | Persisted CAD plan equals public scale+label pipeline output; geometry retained and flags match review_flags. |
| N5 | `test_N5_review_page` | PASS | HTMLParser reads one row/SVG per flagged plan, --all adds clean plans, JSON flags match DB, repeated HTML bytes/mtime unchanged. |
| N6 | `test_N6_migration` | PASS | v1 table set/content migrated to v2 without changing existing table rows; second migration makes no changes. |
| N7 | `test_N7_idempotent` | PASS | --only-new preserves plan and database bytes/mtime; explicit re-extraction replaces flags without duplicates. |
| N8 | `test_N8_stubs` | PASS | Review executes with empty valid JSON; last stub entry removed. Authorized cp1252 status test also passes. |
| N9 | `test_N9_gates` | **FAIL overall** | Named executable static-gate test passes; full-suite gate fails on the three legacy assertions below. Corpus coverage exceeds 90%. |

Focused command: `python -m pytest tests/corpus_extract/test_integration_eval.py tests/review -q` → **13 passed in 3.03 s**. The five additional review checks cover markup escaping, missing/corrupt/mismatched plan files, and Y_DOWN-to-Y_UP previews. A prior focused run including the authorized portability tests passed those tests too.

Optional-extra check: a separate Python 3.11 environment with only `.[dev]`, same focused command → **2 passed, 11 skipped in 0.28 s**. Reader tests importorskip their extras; the N9 static gate requires the full requested extras because existing strict typing imports reader libraries. The initial minimal-environment run exposed that missing gate prerequisite; adding importorskip to the new N9 test corrected it without changing existing tests. This is not a claim that the repository's entire historical suite works without extras.

## Gates and measured coverage

| Command | Outcome |
|---|---|
| `python -m pytest --cov=ale.corpus --cov-report=term-missing --cov-report=json:/tmp/ale-i1-evidence/coverage.json` | **FAIL**, 3 failed, 1070 passed, 11 skipped, 2 xfailed in 411.64 s (1086 collected). |
| `ruff check .` | PASS, all checks passed. |
| `ruff format --check .` | PASS, 206 files already formatted. |
| `mypy` | PASS, no issues in 111 source files. |
| `python -m ale.contracts.lock --check` | PASS, exit 0, OK. |
| `git diff --check` | PASS. |

`ale.corpus` combined statement/branch coverage: **98.962%** (1040/1047 statements, 295/302 branches); statement coverage 99.331%. Module rounded totals: db 100%, extract 98%, meta 99%, review 97%, ingest 99%, scan 98%, classify 100%. Full-suite evidence predates only the new N9 optional-extra skip guard; that guard was independently rerun with and without extras and does not change full-extra behavior. Production code is identical to the full-suite run.

Existing skips include platform-only cases, optional real-corpus tests, throughput under coverage, and missing historical commits in the shallow checkout. The two existing geometry xfails remain unchanged. They are not claimed as passes.

## Blocking legacy assertions — no out-of-ownership edits

1. `tests/corpus/test_corpus_ingest.py::test_C13_migration` (line 445) expects `PRAGMA user_version == 1`; I.1 N6 requires 2. Measured actual is 2. This file is **outside ownership**; stopped short of changing it.
2. `tests/corpus_extract/test_extract_eval.py::test_W07_other_kinds` expects PDF/raster to remain NEW, untouched, and reported as unimplemented. I.1 §2 requires processing/exclusion. Kept the test unchanged despite ownership because the user explicitly prohibits weakening/deleting existing tests.
3. `tests/rulebook/test_rulebook_eval.py::test_K10_cli` (line 316) expects an unknown-column warning for `north_angle_deg`; I.1 §4 requires accepting/storing it. No warning is now emitted. This file is **outside ownership**; stopped short of changing it.

The Router needs to authorize/reconcile these obsolete expectations. Emitting misleading compatibility warnings, falsely reporting schema 1, or bypassing extraction to satisfy them would violate I.1. The branch is not ready to merge under the stated Done definition.

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

## Files changed

- Corpus: `extract.py`, `meta.py`, `db.py`, new `review.py`.
- CLI commands: `extract.py`, `review.py`.
- Tests: `tests/corpus_extract/conftest.py`, new `test_integration_eval.py`; new `tests/review/conftest.py` and `test_review.py`.
- Authorized narrow edits: remove review from `tests/cli/test_cli_surface.py` stub mapping; retarget only the cp1252 stub test in `test_portability.py` to status on `Łódź ws`.
- This report. No other files changed.
