# Ticket A.4 — Contract amendment: site anchors and room anchors (contracts 1.5.0) · Requirements Document

> Context = this file, `eval.md`, `specs/design/research_roadmap.md` (target pipeline, phases 0 and 3), how A.3 and
> Q.4 amended the contracts (git log "Ticket A.3", "Q.4"), `ale.contracts` (`SiteSpec`, `RoomSpec`, `Program`),
> `ale.program` (`site.py`, `excel.py`, `template.py`, `prepare.py`) and their tests. **Backward compatible**: every
> new field is optional with a default that reproduces today's behaviour; layouts are byte-identical when unused.

## 1. Purpose
The cell-diagram phase (R.9) and the form phase (G.3) need the architect's hard lines as data: where the main entrance
is, where the stairs/cores are, which room takes a corner, which room is at the entrance; for multi-storey (M.1) a
room's level. This ticket only adds and validates the data; no engine uses it yet.

## 2. Files (ownership)
`src/ale/contracts/**` (models, version, schemas, lock), `src/ale/program/{site,excel,template,prepare}.py`,
`src/ale/program/data/*` (template), `tests/contracts/**`, `tests/program/**`, `tests/fixtures/**` (only if new optional
fields need a fixture), `specs/tickets/A.4_anchors/eval_report.md`.

## 3. Contract changes
- `SiteSpec.entrances: tuple[Entrance, ...] = ()` with `Entrance(point: Point2, label: str = "", main: bool = False)`;
  each point must lie on the footprint boundary (tolerance one module) when the footprint is the building outline,
  or inside the site when `SiteSpec.mode == "plot"` (see below). At most one `main`.
- `SiteSpec.cores: tuple[CoreSpec, ...] = ()` with `CoreSpec(id: str, rect: (x, y, w, h) metres, kind: "stair" | "lift" | "shaft" | "core")`;
  rectangles inside the site, non-overlapping. Supersedes nothing: `core_hint` stays (deprecated in the docstring).
- `SiteSpec.mode: Literal["footprint", "plot"] = "footprint"` — "footprint" = today (the polygon is the building
  outline); "plot" = the polygon is the plot and `setbacks` apply (for G.3).
- `SiteSpec.setbacks: tuple[float, ...] | None = None` — one value per exterior edge (metres), only with mode "plot".
- `SiteSpec.party_edges: tuple[int, ...] = ()` — exterior edge indices on a party wall (no outside beyond them).
- `RoomSpec.anchor: Literal["corner", "entrance"] | None = None`.
- `RoomSpec.floor`: allow `>= 0` (today the validator forces 0); keep default 0. Levels are not used by v1 engines;
  `prepare_input` must reject programmes with rooms on several floors when the engine is single-floor (clear French
  error), so nothing silently changes.
- Contracts version 1.5.0; schemas regenerated; `CONTRACTS.lock`; contract tests updated (follow A.3 / Q.4).

## 4. Inputs
- `site.yaml`: keys `entrances`, `cores`, `mode`, `setbacks`, `party_edges` (validated, French errors with the key).
- Programme Excel: new optional column **« Ancrage »** with values « coin » / « entrée » (accent/case-insensitive),
  template updated (drop-down list); column « Niveau » now accepts integers ≥ 0.
- `ale program check` prints the anchors found and validates them against the site (e.g. two `corner` rooms but a
  rectangular footprint has 4 corners: fine; an `entrance` room but no entrance in the site: warning).
