# Ticket U.1 — Local web interface (Streamlit) · Requirements Document

> User decision (2026-11-11): build a small local UI now so the architect can test the tool (the GUI was a v2 item).
> Context = this file, `eval.md`, `examples/README.md`, the CLI commands (`ale program import|check`, `ale generate`,
> `ale score`, `ale critique`, `ale form` when present), `ale.workspace`, `ale.config`. **No engine changes**: the UI
> calls the same Python functions the CLI commands call. French interface.

## 1. Files (ownership)
`src/ale/ui/__init__.py`, `src/ale/ui/app.py`, `src/ale/ui/pages/*.py` (if multi-page), `src/ale/cli/commands/ui.py`
(+ its registration line in `src/ale/cli/__init__.py`), `pyproject.toml` (ONLY: extra `ui = ["streamlit>=1.30"]` and
add it to `all`), `.github/workflows/ci.yml` + `tests/corpus/test_corpus_gates.py` + `tests/cli/test_portability.py`
(ONLY: the install line gains `ui`), `tests/ui/**`, `examples/README.md` (ONLY: a « Interface » section),
`specs/tickets/U.1_local-ui/eval_report.md`.

## 2. Launch
`ale ui [--workspace W] [--port 8501]` starts `streamlit run` on the packaged app (opens the browser). Without the
`ui` extra: French message « installez l'extra ui : pip install -e ".[ui]" », exit 3. Sidebar: workspace folder
(created with `ale init` defaults if missing), module (0,10 / 0,60 m), area tolerance (−0 / +10 % preset for AREP-MS
« jamais en dessous du programme »), time budget per variant.

## 3. Pages
1. **Programme** — upload an Annexe (« programme physique ») or an ALE template; for an Annexe, choose the building;
   show the table (id, name, type, zone, façade, quantity, m²) and the totals; run `program check` against the site
   when one is loaded; download the ALE xlsx.
2. **Site** — upload `site.yaml`, or a simple form: rectangle (width × depth) or L (two rectangles), north angle,
   access edge, entrance point, cores (list of rectangles), mode footprint/plot with setbacks per edge; preview drawing;
   download the YAML.
3. **Forme** — only if `ale.form` is importable: candidates count, courtyard on/off → run, gallery of `form_kk.svg` with
   the metrics table from `forms.md`; « utiliser cette forme » loads that candidate's YAML as the current site.
   Otherwise a note « disponible après la fusion de G.3 ».
4. **Plans** — variants count, seed → run `generate`; gallery side by side (preview SVG, hard violations, cost,
   circulation %), the report of the selected variant (rendered Markdown), download DXF / SVG / report / all as zip.
5. **Évaluer un projet existant** — upload a PDF/DXF + programme (or Annexe + building) → `score`; show `score.md`.
6. **Critique** (optional) — if `[vlm] provider` is set and the key present: run `critique` on the selected variant.
Long runs show a spinner and a status line; errors are shown in French with the CLI's message; nothing blocks the UI
thread forever (respect the configured budgets).
