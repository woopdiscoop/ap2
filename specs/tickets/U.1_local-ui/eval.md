# Ticket U.1 · Evaluation (Streamlit `AppTest`, small budgets, no network)
| ID | Test | Pass condition |
|---|---|---|
| U101 | launch | `ale ui --help` works; without streamlit installed (simulated) → French message, exit 3; with it, the command builds the right `streamlit run` invocation (mocked subprocess). |
| U102 | programme | AppTest: uploading a synthetic Annexe → building selector → table with the right totals; ALE xlsx download offered. |
| U103 | site | AppTest: rectangle form → valid `SiteSpec` YAML; plot mode with setbacks accepted; preview rendered. |
| U104 | plans | AppTest with P8 example inputs and a 2 s budget: generate 2 variants → 2 previews, summary table, zip download non-empty. |
| U105 | score | AppTest: synthetic zone PDF (X.2 helpers) + programme → score table shown. |
| U106 | form_guard | When `ale.form` is absent (monkeypatched), the Forme page shows the note and no error; when present, a run lists candidates. |
| U107 | errors | Invalid upload (corrupt xlsx) → French error message, app keeps running. |
| U108 | gates | ruff, format, mypy strict (src/ale/ui included); coverage of `ale.ui` ≥ 80 % (path-form); lock --check; whole suite passes; CI install line includes `ui`. |
