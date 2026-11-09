# X.1 evaluation report

Base: `origin/claude/new-session-2hmd3s` at `a4dd777` (later than `bb5be3e`).
Branch: `codex/X.1-extract-followups`.

## Acceptance results

| ID | Named test | Result | Evidence |
|---|---|---|---|
| X01 | `tests/corpus_extract/test_extract_force.py::test_X01_force_all` | PASS | Five generated units selected after normal extraction: four plans extracted and one non-plan re-excluded; identical output bytes and flags; exactly one forced event per unit. |
| X02 | `tests/corpus_extract/test_extract_force.py::test_X02_force_kind` | PASS | Only the vector and scanned PDF units selected; non-PDF rows unchanged, and new events belong only to PDFs. |
| X03 | `tests/corpus_extract/test_extract_force.py::test_X03_exclusive` | PASS | CLI exit 2 with French message; API also rejects the combination; workspace file bytes and modification times unchanged. |
| X04 | `tests/corpus_extract/test_extract_force.py::test_X04_force_cache` | PASS | Mock provider: three initial calls, zero forced calls, three cache hits, zero errors; output, flags, and cache bytes unchanged. |
| X05 | `tests/labels_render/test_extract_followups.py::test_X05_extent` | PASS | Ten cases: both source kinds, interior/edge pixels, singleton image, several sizes. Exact outer extent, unchanged PNG bitmap, and independent normalized boxes mapping exactly to one-pixel edges. |
| X06 | `tests/labels_render/test_extract_followups.py::test_X06_gates` | PASS | Static gates, nondecreasing coverage, and full suite all pass; results below. |

Seven additional force cases cover every status (five cases), replacement of corrupted output and stale flags, and a forced attempt failing because its source disappeared. There are 22 new test cases overall. All inputs are generated using existing builders or synthetic arrays; VLM calls are mocked. No network calls or binary plan fixtures were added.

## Validation

Environment: Python 3.11.17, editable install with `[dev,excel,cad,pdf,raster,vlm]`.

| Gate | Result |
|---|---|
| `ruff check .` | PASS: all checks passed |
| `ruff format --check .` | PASS: 230 files already formatted |
| `mypy src` (repository strict configuration) | PASS: no issues in 116 source files |
| `python -m ale.contracts.lock --check` | PASS: OK; no contract changes |
| `git diff --check` | PASS |
| Focused suite before changes | 233 passed, 4 skipped in 47.40 s |
| Same focused suite after changes | 255 passed, 4 skipped in 39.14 s |
| Whole suite | 1214 passed, 12 skipped, 4 existing xfailed; zero failures in 650.57 s |

Focused suite command, before and after (only report paths differ):

```sh
python -m pytest tests/corpus tests/corpus_extract tests/labels_render tests/cli \
  --cov=src/ale/labels --cov=src/ale/corpus --cov=src/ale/cli \
  --cov-report=json:/tmp/ale-x1-evidence/after.json --cov-report=term
```

Whole suite command:

```sh
python -m pytest --cov=src/ale/labels --cov=src/ale/corpus --cov=src/ale/cli \
  --cov-report=json:/tmp/ale-x1-evidence/full-coverage.json --cov-report=term
```

Coverage uses path form throughout, including the CLI module, to avoid the known package-form NumPy reload issue. Percentages below are coverage.py combined statement/branch coverage, compared using the same test directories and configuration.

| Touched module | Before | After | Change |
|---|---:|---:|---:|
| `src/ale/corpus/extract.py` | 98.9796% | 99.4036% | +0.4240 percentage points |
| `src/ale/labels/render.py` | 98.7500% | 98.7500% | unchanged |
| `src/ale/cli/commands/extract.py` | 100.0000% | 100.0000% | unchanged |

Full-suite coverage:

- `src/ale/corpus/extract.py`: 99.4036% (398/399 statements, 102/104 branches).
- `src/ale/labels/render.py`: 98.7500% (117/118 statements, 41/42 branches).
- `src/ale/cli/commands/extract.py`: 100.0000% (36/36 statements, 10/10 branches).

The 12 skips are existing platform, optional corpus/live-provider, coverage-throughput, empty-parameter, and shallow-history checks. The four existing xfails are three geometry cases and one optimizer case; none were added or modified by X.1. All 22 new cases ran and passed.

## Existing test changes

Only exact extent expectations changed; no assertions were removed or relaxed:

- `tests/labels_render/test_render_eval.py::test_V202_raster_extent`: `(0, 0, float(w), float(h))` → `(-0.5, -0.5, w - 0.5, h - 0.5)`. Bitmap preservation and geometry/box checks remain.
- `tests/labels_render/test_render_robust.py::test_scanned_pdf_reloaded_at_dpi`: `(0, 0, 600, 400)` → `(-0.5, -0.5, 599.5, 399.5)`. Rendered image dimensions remain unchanged.

No test was weakened, deleted, or newly marked xfail.

## Spec issues and interpretations

1. RD §1 annotates corpus extraction ownership as “ONLY: selection for force”, while §2 also requires a new event. Followed §2's explicit intent with minimal force argument, exclusivity validation, selection, and event plumbing in the owned file. Existing readers, writer, flag replacement, provider selection, and cache remain unchanged.
2. “Whatever their status” includes explicitly EXCLUDED units. Their source metadata is retained. A genuine non-plan can be re-excluded on the new attempt; forcing does not make a non-plan into a plan. Five parameterized cases independently prove selection of NEW, FAILED, NEEDS_TOOL, EXTRACTED, and EXCLUDED.
3. `extract_forced` records each selected forced attempt, including failures and re-exclusions; existing terminal events remain. Its detail records previous status and source kind.
4. “Overwrites ... atomically” uses the existing atomic writer: changed output is atomically replaced; identical bytes avoid a redundant physical rewrite. A separate test corrupts stored output and inserts a stale review flag, then proves forced extraction restores both through that existing path. No new writer implementation was introduced.
5. Pixel centres are integers and outer pixel edges are half-integers. Vector PDF and CAD extents are unaffected. X05 uses image dimensions dividing 1000 so its mock normalized boxes are exact, rather than introducing unrelated normalized-coordinate quantization changes. Boxes are constructed independently from image pixel positions, not by round-tripping the inverse conversion.
6. X06 executes bounded static-gate subprocesses as a named test. The complete suite and before/after coverage are measured externally to avoid recursive pytest execution; their measured results are reported here.

No other spec disagreements identified. Only RD-owned files changed; no contracts, reader packages, dependencies, or project configuration changed.
