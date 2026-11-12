# Ticket M.2 · Evaluation (synthetic; reuse the M.1 4-floor case; no real files)
| ID | Test | Pass condition |
|---|---|---|
| M201 | contracts | `ModulePolygon.solids` and `Layout.fixed` validate (inside, CW, no touching/overlap; fixed rooms inside solids); empty → serialised form unchanged; lock bumped to 1.7.0 and `lock --check` OK. |
| M202 | intake | A site with one core gives one solid snapped outward; sites without cores give byte-identical prepared inputs and feasibility reports (hash vs base). |
| M203 | facade | A room along a solid has no façade contact from it; depth-from-façade unaffected; hand-built cases. |
| M204 | generate | P25 programme on a rectangle with a central core: layout passes `check_layout`, tiles footprint minus solid exactly, no room over the core, circulation touches the core. |
| M205 | access_rule | A layout where rooms enclose the solid is reported with the new hard code (French message). |
| M206 | unchanged | Existing P08/P25/P60 sample outputs (no cores) byte-identical to the base commit. |
| M207 | stack_plans | `ale stack --plans` on the M.1 case: one plan per floor, each passing `check_layout`; core and wet rooms in `Layout.fixed` with identical rectangles on all floors; `plans.md` in French with the vertical check. |
| M208 | exports | DXF/SVG show solids and fixed rooms (layer / class present); JSON round-trips. |
| M209 | failure | A floor that cannot be generated (programme too big) is reported in `plans.md`; other floors still produced; exit code documented. |
| M210 | gates | ruff, format, mypy strict; coverage of changed engine modules not lower than base, `ale.stack` ≥ 90 % (path-form); whole suite (`-m "not slow"`) passes; 4-floor `--plans` with 5 s per floor ≤ 60 s. |
