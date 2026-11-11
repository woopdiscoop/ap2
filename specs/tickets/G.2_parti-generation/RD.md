# Ticket G.2 — Parti generation (strong decisions generated together, multi-problem scoring) · Requirements

> Context = this file, `eval.md`, `specs/design/research_roadmap.md` (target pipeline phase 1; G.2 definition; user
> decisions U-12, U-14, U-15, U-16 on the board), contracts 1.5.0 (site plot mode, setbacks, party edges, entrances,
> cores), `ale.form` (G.3), `ale.topology.cellgrow` (R.9: cell diagram inside a given footprint), `ale.export.diagram`.
> No contract changes. Do not touch `src/ale/geometry`, `src/ale/topology`, `src/ale/optimize`, `src/ale/contracts`
> (G.1 is changing them).

## 1. Purpose
The architect's criticism of the manual scheme: "forced, no strong parti, every issue solved independently; a good
solution solves several problems at once". A parti is a small set of strong decisions taken together; the programme
is placed by them. Generate many partis, evaluate every criterion jointly, explain each one.

## 2. Files (ownership)
`src/ale/parti/__init__.py`, `genes.py`, `massing.py`, `evaluate.py`, `card.py`, `src/ale/cli/commands/parti.py`
(+ registration in `src/ale/cli/__init__.py`), `tests/parti/**`, `specs/tickets/G.2_parti-generation/eval_report.md`.

## 3. Genes (`genes.py`)
`Parti(typology, orientation_deg, wing_depth_m, floors, core_position, circulation, entrance_side, courtyard)`:
- typology ∈ {bar, L, U, T, comb (2–4 fingers), courtyard (ring), H};
- orientation of the long façades (0/90° in the site frame, plus the site's main axis);
- wing depth ∈ {single-loaded ≈ 7.2 + corridor, double-loaded ≈ 2·7.2 + corridor} on the 0.60 m grid;
- floors ∈ the allowed range (from the CLI, e.g. 3–5); upper floors may recede (terraces) by whole wings;
- core position: one core (U-14: one stairwell, a core may hold several stairs) at a wing junction, a wing end, or
  the centre of the longest wing;
- circulation figure ∈ {spine, loop (courtyard/ring), comb fingers};
- entrance side = the main entrance's street; forecourt = open space between the entrance and the building, if any.

## 4. Massing (`massing.py`)
For each gene set, size the wings so that floors × usable floor area ≈ programme / (1 − circulation share) (within
±10 %), fit them inside the buildable zone with setbacks (party edges allowed to be built against), keep courtyard
short side ≥ H/2 (prospect rule, H = floors × 3.5 m), and output one outline per floor (terraces = receding outlines).
Invalid gene sets (do not fit) are dropped with the reason. Optional `--from-forms DIR`: G.3 candidates are matched
to the nearest typology (IoU of outlines) and their genes seeded from it.

## 5. Evaluation (`evaluate.py`): everything at once
Per parti: capacity per floor vs programme; façade length per orientation and share on good orientations (site
setting, e.g. NNO/SSE good, OSO/ENE exposed for AREP-MS); frontage capacity vs façade-room demand; compactness;
coverage; courtyard/prospect check; distance from the core to the farthest room (proxy for egress, reported only); a
**cell diagram of the typical floor** inside the outline (R.9 `cellgrow`) giving façade rooms without façade, rooms
off circulation, rooms short; and **forcedness** = (share of requirements met by the parti itself before any local
repair, number of local exceptions in the cell diagram). Ranking: non-dominated set over (hard misses, forcedness,
façade-orientation share, compactness), listed first.

## 6. Parti card (`card.py`)
For each parti, list its major elements (each wing, the courtyard, the core, the forecourt, the terraces) and, from a
documented rule table, the problems each solves: e.g. courtyard → daylight for a wing deeper than 2 × 7.2 m, quiet
side, prospect-compliant inner façade; core at the junction → serves all wings within the distance limit, one
stairwell; forecourt on the entrance street → arrival, no cars on the forecourt; wing on the good orientation → offices
on NNO/SSE. **An element that solves only one problem is flagged** « élément à fonction unique (rustine possible) ».

## 7. Command
`ale parti --program P.xlsx --site S.yaml(plot) --out DIR [--floors 3-5] [--count 40] [--from-forms DIR]` writes
`partis.md` (French ranking, non-dominated set first, each with its card), one SVG per parti (outlines per floor,
core, forecourt, orientation arrows, typical-floor cell diagram) and one `site.yaml` per parti (typical floor as a
footprint) for the plan phase.
