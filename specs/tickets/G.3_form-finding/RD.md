# Ticket G.3 — Form-finding: the building's outline from the outside (cell growth on the plot) · Requirements

> Context = this file, `eval.md`, `specs/design/research_roadmap.md` (target pipeline phase 1; G.3 definition; U-12,
> U-15, U-16), the prototype (Part C of the grid-sizing page; algorithm in §3), contracts 1.5.0 (A.4: `SiteSpec.mode
> = "plot"`, `setbacks`, `party_edges`, `entrances`, `cores`; `RoomSpec.anchor`), `ale.topology.cellgrow` (R.9: reuse
> its grid/cell utilities where they fit), `ale.export.diagram`. No contract changes.

## 1. Files (ownership)
`src/ale/form/__init__.py`, `src/ale/form/grow.py`, `src/ale/form/outline.py`, `src/ale/form/metrics.py`,
`src/ale/cli/commands/form.py` (+ registration in `src/ale/cli/__init__.py`), `tests/form/**`,
`specs/tickets/G.3_form-finding/eval_report.md`.

## 2. Command
`ale form --program P.xlsx --site S.yaml --out DIR [--candidates 6] [--courtyard]` with `S.yaml` in mode `plot`.
For candidates k = 1..K (seed k; k = 1 keeps programme order, k > 1 shuffles the seeding order deterministically):
grow a form (§3), simplify its outline (§4), score it (§5). Writes per candidate `form_kk.svg` (cell diagram coloured
by type, outline, outside, setbacks, party wall, entrance, cores) and `form_kk.yaml` (the outline as a site in mode
`footprint`, cores and entrances carried over, ready for later phases), and `forms.md` ranking the candidates.

## 3. Growth (`grow.py`), deterministic, 0.60 m cells
Plot gridded; setbacks are outside; beyond a street edge = street (outside), beyond a party edge = building. Rooms:
programme instances + a circulation zone (16 % of programme cells) + an optional courtyard (enclosed outside type,
default 19 × 19 cells). The building grows as **one mass**: the hall (`anchor="entrance"` room, else the largest
PUBLIC room) at the main entrance, then circulation (compact, attracted to the cores until it touches each), then
each next room seeded on the edge of the mass (preferably on the circulation) once the previous one reached 60 % of
its count or is stuck. Growth scores as in the prototype (own compactness, façade = touches outside, partner and core
attraction, party-wall attraction for storage). **Rule: no claim may cut the outside off from the streets** (local
simple-point test; global flood-fill check when ambiguous); with `--courtyard` the courtyard cells count as outside.

## 4. Outline (`outline.py`)
Union of built cells → orthogonal polygon(s) in metres; remove notches narrower than 2 cells (fill or cut, whichever
changes less area, never cutting the outside connection); report the number of vertices before/after. One polygon
expected (one building); holes = enclosed courtyards.

## 5. Metrics (`metrics.py`) and ranking
Coverage of the buildable zone, footprint m², façade length m, compactness (perimeter / (4·√area)), outline vertices,
courtyard open/enclosed + size, share of façade rooms touching outside, share of rooms touching circulation, number
of rooms short of their area. Ranking key: (rooms short of area, façade rooms without façade, rooms off circulation,
vertices, compactness). `forms.md` lists all candidates with their metrics (French).
