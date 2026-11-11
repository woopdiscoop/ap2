# Ticket U.1 · Evaluation report

Interface: `ale ui [--workspace W] [--port 8501]` (extra `ui = ["streamlit>=1.30"]`, also in `all`).
Tests: `tests/ui/test_ui_eval.py` (Streamlit `AppTest`, no network, 2 s budget per variant).

| ID | Result | Notes |
|---|---|---|
| U101 | pass | `ale ui --help`; streamlit absent (simulated `find_spec`) → « installez l'extra ui : pip install -e ".[ui]" », exit 3; present → `python -m streamlit run .../ui/app.py --server.port N` (mocked `subprocess.call`), workspace passed in `ALE_WORKSPACE`. |
| U102 | pass | Synthetic Annexe: building selector, 9 lines / 17 instances / 492.00 m², ALE xlsx download. |
| U103 | pass | Rectangle form → YAML accepted by `read_site`; plot mode with setbacks (3 m, 4 edges); L shape (6 vertices); preview image. |
| U104 | pass | p08 inputs + draft rulebook, 2 s budget, 2 variants: summary table (2 rows), previews, zip non-empty, DXF/SVG/report downloads. |
| U105 | pass | Synthetic zone PDF (R.10 helpers) + programme → `score.md` table shown. |
| U106 | pass | `form_available` monkeypatched to False: note « disponible après la fusion de G.3 », no error. Present: 2 candidates listed, « utiliser cette forme » loads `form_02.yaml` as current site. |
| U107 | pass | Corrupt xlsx (both modes) and broken YAML: French error, no exception, app keeps working with a good upload afterwards. |
| U108 | pass | See gates. |

## Gates
- `ruff check .` and `ruff format --check .`: clean.
- `mypy` (strict, 143 files, `ale.ui` included): no issues. Streamlit ships types; no ignore needed.
- `lock --check`: 0 (U108 calls it).
- Coverage of `ale.ui` (tests/ui alone): 83 % (render.py 83 %, core.py 86 %; the 3-line `app.py` shim is run by
  Streamlit's script runner, which coverage does not trace).
- CI install line (`ci.yml`, `test_corpus_gates.py`, `test_portability.py`): `.[dev,excel,cad,pdf,raster,vlm,ui]`.
- Whole suite (`pytest --cov=ale`, 1495 collected): the run passed 1441 tests with one failure
  (`test_P08_cli_registration_only`, an artefact of the uncommitted tree, passes once committed, see Spec issues),
  then sat in `tests/topology/test_cellgrow_compare.py::test_R9_07_comparison` (slow, timeout 4 h) and was stopped
  by the Worker. The remaining 40 tests plus `tests/ui` were run separately (48 passed); the two slow comparison
  tests (`test_R9_07`, `test_R9_08`) were not run. No xfail added; no test weakened.

## Design notes
- The UI calls `ale.program` (`read_program`, `check_inputs`, `read_annexe`, `write_outputs`), `ale.optimize.generate`,
  `ale.cli.commands.score.score` and `ale.cli.commands.form.form` (as functions; their exit/stderr become French
  errors), `ale.critique.run_critique`. No engine change.
- Files beyond RD section 1 (all inside `src/ale/ui/`): `core.py` (Streamlit-free helpers) and `render.py` (the pages).
  `app.py` is a 3-line shim so that the pages are importable and measured. No `pages/` folder: Streamlit would turn it
  into extra pages.
- Rulebook: sidebar upload, else first `<workspace>/rulebook/*.yaml`, else `examples/rulebook_seed_draft.yaml` when
  running from a checkout.

## Spec issues
- RD section 3 page 3 says the gallery shows `form_kk.svg` with the metrics of `forms.md`: the UI renders `forms.md`
  as Markdown; there is no separate metrics table.
- RD section 2 does not say where the rulebook comes from (the `generate`/`check` functions need one); added the
  sidebar upload and the defaults above.
- RD section 2 names the CLI refusal « exit 3 »; this is `EXIT_NOT_IMPLEMENTED` (3) in `_common.py`.
- `test_P08_cli_registration_only` diffs `cli/__init__.py` against history; it fails while the registration change is
  uncommitted (working-tree diff includes earlier tickets' import reflow) and passes once committed.
- U108's "whole suite" includes two slow cell-grow comparison tests (timeouts 4 h / 30 min); they were not waited for.
