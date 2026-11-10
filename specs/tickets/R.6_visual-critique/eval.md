# Ticket R.6 · Evaluation (client mocked)
| ID | Test | Pass condition |
|---|---|---|
| C601 | request | One call: image block (PNG, long side ≤ 1568) before the text; structured-output schema as RD; no temperature/top_p/top_k; model from config or the P.1 default. |
| C602 | outputs | Mock answer with 3 defects → `critique.md` (French, one section per defect, rooms named) and `critique.json` schema-valid. |
| C603 | unknown_ids | A defect naming a non-existent room id: id dropped, warning counted; a defect left with no id is kept under "général". |
| C604 | advisory | `layout.json`, `report.md`, DXF, SVG byte-identical before/after. |
| C605 | cache | Second run: 0 calls, identical files. |
| C606 | no_provider | `[vlm] provider = ""` or key unset → exit 3, French message, nothing written. |
| C607 | refusal_error | Mock `refusal` / API error → exit 1, French message, nothing written. |
| C608 | render | PNG contains every room id label position inside its room rectangle (checked through the render function's returned label boxes); deterministic bytes. |
| C609 | gates | ruff, format, mypy strict; coverage `ale.critique` ≥ 90 % (path-form); lock --check; whole suite passes. |
