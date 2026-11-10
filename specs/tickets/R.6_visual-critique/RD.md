# Ticket R.6 — Visual critique of a variant (advisory) · Requirements Document

> Context = this file, `eval.md`, `ale.labels.providers` (Anthropic client pattern of P.1: lazy import, key from
> `[vlm] api_key_env`, structured output, no sampling parameters, refusal fallback, cache), `ale.export` (outputs of
> a variant), `ale.cli`. No contract changes. Tests mock the client; no network; never require a real key.

## 1. Files (ownership)
`src/ale/critique/__init__.py`, `src/ale/critique/critic.py`, `src/ale/critique/render.py` (NEW),
`src/ale/cli/commands/critique.py` (NEW) + its registration line in `src/ale/cli/__init__.py`,
`tests/critique/**`, `specs/tickets/R.6_visual-critique/eval_report.md`.

## 2. Command
`ale critique --variant DIR [--workspace W] [--json]` reads `DIR/layout.json` and `DIR/report.md`, renders a PNG of
the layout (Pillow: rooms filled by zone, circulation light grey, room ids as labels, north arrow; long side 1568),
and sends image + a compact text table (id, name, type, zone, area, dimensions, façade yes/no, violations) to
Claude with a fixed French prompt asking for defects an architect would see. Output (structured): list of
`{room_ids: [...], kind: one of [circulation, lumiere, proportion, adjacence, acces, residuel, autre], severity: 1–3,
observation: str, suggestion: str}` plus `summary`. Writes `DIR/critique.md` (French) and `DIR/critique.json`.
**Advisory only**: never modifies the layout, the report or any cost.
- Unknown `room_ids` in the answer are dropped and counted in a warning.
- Provider missing / key missing → exit 3 with a French message explaining how to configure `[vlm]`.
- Cached by (layout hash, prompt version, model id) in `cache/critique`; second run makes no call.
