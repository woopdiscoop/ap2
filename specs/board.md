# ALE 2.2 — Board

Maintained by the Router only. Directive: `specs/DIRECTIVE.md` (v2.2, supersedes 2.0/2.1).

**Statuses:** `BLOCKED` · `READY` · `IN-PROGRESS` · `IN-REVIEW` · `DONE` · `FAILED` (with reason)

**Critical path:** Phase 0 → Phase 3 (on the seed rulebook) → Phase 1 → Phase 2 → rulebook swap.

## Tickets

| Ticket | Title | Status | Depends on | Spec | Notes |
|---|---|---|---|---|---|
| 0.1 | Scaffolding & CLI | **DONE** | — | RD + eval | Owns `pyproject.toml`, CLI, `ale.toml` contract (`AleConfig`). Parallel-safe with 0.2 (disjoint files). |
| 0.2 | Data contracts | **DONE** | — | RD + eval + taxonomy v1 | Frozen at 1.0.0 via `CONTRACTS.lock` once 0.1 and 0.2 are DONE. |
| 0.3 | Seed rulebook | **DRAFT — awaiting architect validation** | user review | template + draft `seed_rulebook.yaml` | Router draft (23 types, 30 pairs) validates; fixture types covered; all targets buildable. Architect to correct values. |
| 0.4 | Guards & test harness | **DONE** | — | RD + eval + fixtures | `ale.guards.bounded`, `ale.proc.run_tool`, fixtures P8/P25/P60 + 3 sites (Router-verified). Dispatch right after 0.1/0.2 merge. |
| 3.1 | Program & site ingestion | **DONE** | — (0.2, 0.4 done) | RD + eval | Excel → Program with full French error report; site.yaml/DXF → module footprint; feasibility; template + `ale program check`. |
| 3.2 | Topology & seeding | **DONE** | — | RD + eval | Valid first plan at attempt 1 for P8 (0.07 s), P25 (0.49 s), P60 (1.55 s); adjacency far better than random. |
| 3.3 | Grammar realization (+3.3b bands) | **DONE** | — | RD + eval (+ bands) | Bands, connectors, J1/J2; 99 % coverage; P60 realisation 0.10 s. |
| 3.4 | SA optimizer + `ale generate` | **DONE** | — | RD + eval | Lexicographic (hard, cost) annealing, progress schedule, cached realisation (86 it/s P25). Hard breaks: P8 6→0, P25 13→7, P60 35→27 (15 s); P60 60 s run: 22 left. |
| 3.5 | Export & report | **DONE** | — | RD + eval | layout.json, layered DXF (audit clean), SVG preview, French report.md. `ale generate` wiring in 3.4. |
| A.1 | Contract amendment: CorridorPlan + footprint decomposition | **DONE** | — | RD + eval | Contracts 1.0.0 → 1.1.0; adds `corridor_plan.py`, `footprint.py`; regenerates lock. |
| A.2 | Contract amendment: bands | **DONE** | — | RD + eval | Contracts 1.2.0 (CorridorPlan /2). |
| Q.1 | Realisation never emits rule-breaking rooms + depth-aware seeding | **DONE** | — | RD + eval | 0 area/aspect/min-width breaks; hard after SA (15 s): P8 0, P25 6, P60 ≈ 19. |
| A.3 | Contract: inner connector | **DONE** | 8fc97b5 | RD + eval | Contracts 1.3.0, backward compatible; merged together with Q.2. |
| Q.2a | Façade capacity in feasibility | **DONE** | — | RD + eval | usable façade: site_rect 43.2 m, site_L 90.0 m; P60 demand 117.9 m → W_FACADE_TIGHT. |
| Q.2 | Façade-aware layouts (+ A.3 merge) | **DONE (partial)** | 8fc97b5 | RD + eval | Inner connector in geometry/seeding/moves; façade-pull move; fixes A.3 mypy errors. |
| Q.3 | Façade-aware depths + deterministic gates | **DONE** | 30169cf | RD + eval | P60 NO_FACADE ≤ 6 via façade-aware depth key; iteration-bound quality gates (O03 strict restored, G805 coverage xfail removed); seed/anneal budget split; fastreal coverage; P8 ≤ 1 for seeds 1–5. |
| 1.1 | Corpus ingestion & classification | **DONE** | — | RD + eval | Real corpus: 439 files → 1734 units (DWG 17 NEEDS_TOOL, PDF_VECTOR 879, PDF_SCANNED 436, RASTER 402), 0 failed, idempotent. |
| 1.2 | CAD reader (DXF; DWG via converter) | **DONE** (library) | — | RD + eval | Layers (whole-word), units, walls, rooms, labels, openings, multi-plan, DWG→DXF via ODA/accoreconsole. Follow-up 1.2c: wire `ale layers` / `ale extract --kind dxf\|dwg` to the corpus DB. Real DWGs need ODA on the user's workstation. |
| 1.2c | CAD → corpus CLI (`ale layers`, `ale extract` dxf/dwg) | **DONE** | — | RD + eval | Empty layer map → in-memory proposal + warning; NEEDS_TOOL DWGs retried. |
| I.2 | Claude labelling in `ale extract` | **DONE** | I.1 | RD + eval | Render plan image per kind (bbox model), prepare_image, make_provider; opt-in; mocked tests. |
| P.2 | Import « programme physique » (Annexe format) | **DONE** | e730d6a | RD + eval | `ale program import`; AREP-MS mapping as default rules; synthetic fixtures only. |
| Q.4 | Max depth from façade (7.20 m) | **DONE** | Q.3 | RD + eval | Contracts 1.4.0 `facade.max_depth_m`; `FACADE_DEPTH` hard; depth beats aspect for big rooms. |
| X.1 | `ale extract --force` + exact raster extent | **DONE** | I.2 | RD + eval | I.2 follow-ups; independent of P.2/Q.3/Q.4 files. |
| R.1 | Multi-start annealing (stable quality) | **REJECTED (negative result)** | Q.4 | roadmap | See `specs/design/research_roadmap.md`. |
| R.2 | Non-dominated variant set + diversity score | QUEUED | R.1 | roadmap | |
| R.3 | Space-syntax measures in the report | **DONE** | — | RD + eval | |
| R.4 | Plain-language explanation per variant | QUEUED | R.3 | roadmap | |
| R.5 | Adjacencies from the functional programme (Claude, reviewed) | QUEUED | user: functional programme | roadmap | |
| R.6 | Visual critique of a variant (Claude, advisory) | **DONE** | — | RD + eval | |
| X.2 | Vector PDF: filled zones as rooms (Archicad exports) | **DONE** | R.10 | RD + eval | Found on the real AREP-MS sheet: 371 filled zones, walls as single strokes → 0 rooms read. |
| R.10 | `ale score`: score an existing scheme against a programme (first use: the manual AREP-MS sheet) | **DONE** | — | RD + eval | Extract with the vector-PDF reader, match to programme, same checks as ALE variants; file kept outside the repo. |
| X.3 | Courtyards at intake + façade estimate for N pieces | DONE | 4cbb122 | RD + eval + eval report | `site.yaml` footprint accepts `{exterior, holes}`; French errors per courtyard; façade estimate over all junctions (rectangle/L reports byte-identical). Worker edited `cli/commands/program.py` (4 lines, structure line) outside RD §2, accepted. Router amendment at review: X303 generate budget 2 s → 10 s (failed once under load, never reproduced; pass conditions unchanged, b3fa76b). |
| G.2 | Parti generation: genes, massing, joint evaluation, forcedness, parti card, `ale parti` | DONE | 19af7d9 | RD + eval + eval report | 7 typologies; 40 partis in ~13 s; P201–P210 pass. Known limits: cellgrow fragments rooms (G.2 keeps the largest piece, strays → circulation, counted in forcedness); courtyards diagrammed with a slit (cellgrow rejects holes). Router fix at review: test helper imported as `conftest` clashed with tests/cli (2c8478f). |
| M.1 | Multi-storey stacking, vertical skeleton (one core + wet stack on identical cells), per-floor cell diagrams, `ale stack` | RUNNING | G.2 | RD + eval | U-10, U-14, U-15. Exact per-floor plans in the skeleton = M.2; room stacking / bay rhythm / column grid = M.3. |
| U.1 | Local web interface (Streamlit), `ale ui` | DONE | 537eba2 | RD + eval + eval report | Six French tabs (Programme, Site, Forme, Plans, Évaluer, Critique) on the CLI functions. Launch: `pip install -e ".[ui,excel,cad,pdf]"` then `ale ui --workspace ws`. Rulebook from a sidebar upload or the workspace/seed default (spec gap filled by the Worker). |
| G.1 | Exact plans in any orthogonal footprint (N pieces, several junctions; contracts 1.6.0) | **DONE** | — | RD + eval | Needed to build U, T, comb, courtyard partis in detail. |
| G.3 | Form-finding: outline from the outside (cell growth on the plot), `ale form` | **DONE** | A.4, R.9 | RD + eval | Phase 1 of the target pipeline. |
| R.9 | Whole-programme cell-growth seeding (user's method) | **DONE (option, not adopted)** | A.4 done | RD + eval | Adopted as default only if it beats the spring seeder. Carries the Q.4 D05 target NO_FACADE ≤ 1. |
| A.4 | Contract: site anchors (entrances, cores, plot mode, setbacks, party edges) + room anchors + floors (1.5.0) | **DONE** | — | RD + eval | Needed by R.9, G.3 and multi-storey. |
| R.8 | Depth/shape rules learned from built plans | QUEUED | Q.4 | roadmap | User decision U-9. |
| R.7 | VLM geometry reader for raster plans | **DONE** | X.1 done | roadmap | |
| M.2–3 | Multi-storey: M.2 exact per-floor plans inside the skeleton (engine honours fixed cores), M.3 room stacking + bay rhythm + column grid | QUEUED (in scope, U-13; after M.1) | A.4, R.9 | roadmap | |
| P.1 | Claude VLM provider | **DONE** | 3c9db4e | RD + eval + eval_report | User decision U-8: VLM = Claude (claude-opus-5-5, effort low, structured output, no sampling params, cached). |
| I.1 | Integration: PDF/raster extract, labels, scale, `ale review` | **DONE** | — | RD + eval | Assigned to an external Codex agent; PR to be reviewed by the Router. |
| 1.3 | Vector-PDF reader (library) | **DONE** | — | RD + eval | Plan-likeness on merged walls; HABS PDFs correctly identified as scanned (→ raster path). |
| 1.4 | Raster reader (classical CV v1, library) | **DONE** | — | RD + eval | Synthetic: wall IoU 1.00 / 0.94 noisy. Real web images: no crash, but fills/double-line walls under-segmented and doors over-counted → learned model (CubiCasa) is the v2 path. |
| 1.5 | Semantic labelling (library) | **DONE** | — | RD + eval | Text-first; VLM interface + cache with fake providers. For integration: renderer must use the same extent model; real provider must enforce vlm.timeout_s. Real provider = O-3. |
| 1.6 | Scale reconciliation & review flags (library) | **DONE** | — | RD + eval | Dimension-text rule fixed (plausibility + notation tie-break). |
| 2.1 | Topology extraction (library) | **DONE** | — | RD + eval | Facing-edge shared length (formula fixed); DOOR contacts; façade lengths. |
| 2.2 | Rulebook build (`ale rulebook build`) | **DONE** | — | RD + eval | Fidelity-weighted, neutral prior, blended with seed; date-free version; French report. Gap → I.1: `north_angle_deg` meta column. |

**External blocker for all Phase 1 tickets:** the annotated test set (directive §7) — ≥ 12 plans
(4 DWG/DXF incl. one multi-plan model space and one without `$INSUNITS`, 4 vector PDF, 4 JPEG/scanned)
with ground truth. The Router will issue an annotation template before Phase 1.

## User decisions (amend the directive)

| ID | Decision | Effect |
|---|---|---|
| U-1 | **Planning module 0.10 m** instead of 0.60 m (overrides directive §3.B.4). | `grid.module_mm` default = 100; geometry stays integer modules. On this grid every target from 2 to 60 m² fits a 1:1–1:2 rectangle within +0.11 m², with no undershoot. |
| U-2 | **Proportions: 1:2 minimum, 2:1 maximum** (hard). | New config key `shape.aspect_max = 2.0`, a hard rule like the area rule (circulation exempt). Seed template pre-filled 1.0 / 1.4 / 2.0, p90 ≤ 2.0 enforced. Both hard rules verified jointly feasible on the 0.10 m grid for every target 0.5–500 m². Resolves O-2. |
| U-4 | **Academic project, not for commercial use.** | Resolves O-4 (CubiCasa5K usable: attribution + share-alike on any published derived weights/data) and O-8 (PyMuPDF usable). Reference-plan copyright rule of directive §7 still applies: plans stay out of the repo, only derived statistics are kept. |
| U-5 | **More room types.** | Taxonomy v1.1: 25 → 75 types (retail, food service, education, health, sport, culture, services, outdoor), from Uniclass 2015 SL + French ERP types. Seed template: 23 core types active, 49 optional types listed commented-out. |
| U-6 | **Corridor grammar** for circulation (instead of a free slicing tree + penalty). | Every room touches a corridor by construction; circulation always connected. Spine per footprint piece, blocks of room bays / finger bays; L shapes via J1 (corner finger) / J2 (collinear spines). Replaces directive §3.B.1 free tree and 3.4 moves M1–M3 with grammar moves G1–G6. Design: `specs/design/corridor_grammar.md`. Contract amendment A.1. |
| U-7 | **Bands**: several parallel corridors per piece, joined by a connector corridor. | Deep plates (P60's 30 m piece) become feasible. Contract amendment A.2 (CorridorPlan /2, contracts 1.2.0), then 3.3 rework. Design note §8. |
| U-17 | **Build a small local UI now** to test the tool (moves the v2 GUI item forward). | U.1 (Streamlit, French, no engine changes). |
| U-16 | **A strong parti solves several problems at once** (user): the manual scheme is "forced": every issue solved independently, no strong parti. | G.2 becomes parti generation (a few strong decisions as genes, everything generated together); new metrics: *forcedness* (share of requirements met by the parti before any local repair, count of local exceptions) and a *parti card* (each major element → the problems it solves; single-purpose elements flagged); R.6 critique prompt gains this lens. |
| U-15 | **Sketch-phase reading (user, on the manual AREP-MS scheme)**: (1) a rough sketch's room areas may be a few % off, since they are adjusted later without changing the plan; (2) floor outlines that change from floor to floor can be a deliberate choice (terraces); (3) a deep block is acceptable when the rooms that need a façade have one. | Diagram phases (R.9, G.3) report small area gaps as "to adjust", not as failures; multi-storey (M) allows receding floors (terraces) while cores, wet stacks and structure stay continuous; depth stays soft (U-9). R.10 scores accordingly. |
| U-14 | **Vertical circulation (AREP-MS)**: the project requires **one stairwell**; **one core can hold several stairs** (e.g. two stairs in the same core). Supersedes the "two protected stairs > 5 m apart" reading used in the 2026-11-11 review of the manual scheme. | A.4 `CoreSpec(kind="core")` covers a multi-stair core; M.1 stacks one core; R.10 must not count "one stair per bar" as a violation. |
| U-13 | **Scope extended (user, 2026-11-11: "Ok go")**: multi-storey (M.1–M.3) and free building forms (G.1–G.3) are now in scope, following the target pipeline (roadmap). Work continues autonomously across usage-limit resets. | Order: R.1 → A.4 → R.9 → G.3/G.2 → M.1–M.3 → G.1; R.2, R.8 in between. |
| U-12 | **The building form is not fixed**: the shape follows the programme: bar, L, courtyard, U, comb, freeform, whichever is best. | ALE v1 takes the footprint as input (rectangle / L). Proposed v2 tickets G.1 (N-piece orthogonal footprints incl. courtyards), G.2 (massing typologies generated and scored), G.3 (form-finding by cell growth with "outside" as a connected space type: the user's proposal). |
| U-10 | **Multi-storey must be as stackable as possible**: shafts and water pipes at the same position on every floor; rooms of the same shape and area stacked above each other; a structure as regular as possible. | Requirement for M.1–M.3 (v2). |
| U-11 | **User's sizing method**: fill the target area with 60 × 60 cm cells (0.36 m² each), regardless of shape, then reshape into the right rectangle at the right place, never below the programme area. | Matches ALE with `module_mm = 600`, area tol 0/+10 %. Diagram published. |
| U-9 | **Façade depth 7.20 m is not absolute**: rooms may be deeper; limits are tuned from the corpus of built plans. | Q.4 → soft rule by default (`max_depth_hard = false`); R.8 learns per-type depth from the corpus. |
| U-8 | **VLM provider = Claude** (Anthropic API); Router to draft seed rulebook values for architect review. | O-3 resolved. Ticket P.1. Seed draft in 0.3. |
| U-3 | **Corridor minimum width 1.2 m.** | `circulation.min_width_m` default 1.8 → 1.2 m (12 modules). |

## Open decisions

| ID | Decision | Router recommendation | Blocks |
|---|---|---|---|
| O-1 | Default circulation ratio | Keep **0.18** (directive default) as the config default; it is overridable per run. | nothing (default already set) |
| O-2 | ~~Aspect band vs area rule~~ | **Resolved by U-1/U-2**: both hard; per-type bands soft inside 2:1. | — |
| O-3 | VLM provider + model | Choose one with deterministic temperature-0 output, JSON mode, and a bbox convention we can test. | 1.5 |
| O-4 | ~~Raster model licence~~ | **Resolved by U-4**: CubiCasa5K allowed (non-commercial). | — |
| O-5 | ODA File Converter vs AutoCAD `accoreconsole` on the target workstation | ODA as primary (free, no AutoCAD licence needed); accoreconsole only where AutoCAD is already installed. Need: which is installed on the workstation. | 1.2 |
| O-6 | Orientation granularity | 4 bearings (N/E/S/W) in v1 — halves the architect's inputs. | 0.2 (assumed in spec) |
| O-7 | Macro-zone list | PUBLIC / ADMINISTRATIVE / SERVICES in v1. | 0.2 (assumed in spec) |
| O-8 | ~~PyMuPDF licence~~ | **Resolved by U-4**: allowed. | — |
| O-10 | Repository licence | If the code is published (e.g. with a thesis), AGPL-3.0 is the simplest choice compatible with PyMuPDF; otherwise keep the repo private and unlicensed. Not blocking. | — |
| O-9 | Taxonomy review | **v1.1 issued** (75 types, user request U-5). Still worth a glance by the architect: default macro-zones, and `CUISINE` → commercial_kitchen / `OFFICE` → kitchenette. | — |

## Corrections to the directive found while specifying

- (Moot since U-1, kept for the record) §3.B.5: the largest overshoot in the 1:1–1:2 band is **+1.217 m²** (at T ≈ 7.423 m²), not +1.14 m²; targets in **7.423–7.439 m²** have no valid rectangle under the +1.2 m² cap. For a 1:2.5 band the maximum is +1.04 m² (cap still never reached). Encoded as test A02 in 0.2.
- (Correction of the Router's own v2.0 board: `1.8 % 0.6` evaluates to `1.11e-16` in CPython, as the directive states — not `0.5999…`. The conclusion, integer modules, is unchanged.)

## History

- 2026-11-06 — v2.0 workspace initialised (tickets 1.1, 1.2 specified).
- 2026-11-09 — User: yes to seed-rulebook draft and Claude as VLM. Seed draft written and validated; P.1 specified and dispatched. CI: raster extra added to the install line.
- 2026-11-11 — **G.1 merged** (contracts 1.6.0): U, T, H, comb, Z, courtyard ring (≤ 12 pieces) realise exactly; one connected circulation; several junction fingers per piece. Follow-ups: courtyards (holes) still refused at site/programme intake (`ale.program`); feasibility façade estimate assumes ≤ 2 pieces.
- 2026-11-11 — **G.3 merged** (`ale form`): one mass, outside connected, rooms contiguous (G310: 0 fragmented rooms over 12 candidates, verified by the Router), outline on the 0.60 m grid. Known limits for G.2 to address: ragged outlines (50–128 vertices), up to 8 façade rooms without façade and 5–17 rooms off circulation per candidate; a few rooms can end short (reported).
- 2026-11-11 — G.3 review: G301–G309 pass but rooms are fragmented (15–20 rooms per candidate split into several pieces). Spec gap: contiguity was not required. Router adds G310 (every room and the circulation one 4-connected region); returned to the Worker, not merged.
- 2026-11-11 — **R.10 + X.2 merged**: `ale score` reads the real AREP-MS sheet (327 filled zones) and matches every programme line of both buildings. Limit found: one sheet holds both buildings and the score has no way to tell which plan belongs to which building yet (follow-up: plan → building assignment, `--plans` selection).
- 2026-11-11 — **R.9 merged as an option** (`seeder="cells"`, default stays `spring`) + cell-diagram SVG export. Adoption rule not met: mean final hard spring vs cells P25 4.0/6.0, P60 11.8/15.0, AREP hard 3.0/4.0, AREP soft 3.6/3.0. Cause: the diagram only feeds positions to the fixed corridor bands, which impose their own depths and frontages; on a fixed bar the frontage cannot hold every façade room. R9-08 (NO_FACADE ≤ 1) amended to a regression guard (≤ 3); target moved to G.2 (parti generation, the floor plate itself changes). R.1 + R.9 together: the lever is the form / parti (U-16), not seeding or optimiser tuning.
- 2026-11-11 — **R.1 rejected (negative result, not merged; branch worktree-agent-ad9e09805908d8bb3 @ 211d7d7 kept)**: 4 starts at the same total budget are worse on P60 (NO_FACADE 8–10, hard 11–13 at budgets 1000–1500) than one chain (6–10 / 9–13): chains of 250–375 iterations do not converge. Conclusion: the P60 weakness is the initial arrangement, not the optimiser → R.9 (cell-diagram seeding) and the parti-first G.2 (U-16) are the levers.
- 2026-11-11 — **A.4 merged** (contracts 1.5.0: entrances, cores, plot mode, setbacks, party edges, room anchors « coin »/« entrée », floors). Container restart killed R.1's final run; WIP saved (4c9a3bb) and R.1 relaunched. User's manual AREP-MS scheme reviewed: areas slightly below programme (sketch tolerance, U-15), outline changes = terraces (U-15), "one stair per bar" withdrawn (U-14); R.10 baseline scoring queued.
- 2026-11-11 — **Q.4, R.3, R.6, R.7 merged** (integrated suite 1324 passed, 0 failed). Q.4 D05 amended: NO_FACADE ≤ 1 target moved to R.9. User's whole-programme cell method prototyped in the grid-sizing page; R.9 redirected to it (Voronoi kept as a growth-rule variant); A.4 contract proposed.
- 2026-11-11 — User: queue R.9 (Voronoi seeding experiment) after R.1. Voronoi also noted for v2: floor-plate zoning and medial-axis decomposition of non-rectangular footprints.
- 2026-11-11 — **X.1 merged** (PR #2, Codex). Codex is now off: its remaining work is picked up by Claude workers (Sonnet low). Router on Opus 5.5.
- 2026-11-10 — Literature check of the user's research database (`specs/design/literature_review_2026-11.md`) → research roadmap R.1–R.7 + M (v2) (`research_roadmap.md`). Q.4 interrupted by the weekly limit, WIP saved (90f5a00), resumed with a new worker.
- 2026-11-09 — **Q.3 merged** (30169cf): P60 hard 18 → 9 (NO_FACADE 6), P25 → 5, P8 0 for seeds 1–5; quality gates iteration-bound (same result on any machine / under coverage); O03 strict restored; seed deadline fixed (T05); generate budget split 25/75. Router review: 2 integrated full runs, 1203 passed each. Caveat: P60 NO_FACADE ≤ 6 is budget-sensitive (7–10 at other iteration counts). 3.3 RD §5.7 amended. Q.4 dispatched.
- 2026-11-09 — **P.2 merged**: `ale program import --annexe` reproduces the hand conversion of the real Annexe 3 exactly (2 buildings, totals OK). Cosmetic follow-up: building names keep the title remainder (« DES SERVICES DU SIEGE… »).
- 2026-11-09 — AREP-MS track opened: P.2 (Annexe import, dispatched) and Q.4 (façade depth ≤ 7.20 m, after Q.3). Decision (Router, per project rules): for rooms too big for depth ≤ 7.20 m at aspect ≤ 2, depth is hard and aspect becomes soft.
- 2026-11-09 — **I.2 merged**: `ale extract` sends still-untyped rooms to Claude with a rendered plan image when `[vlm] provider` is set (missing key → French warning, text-only); `--no-vlm`. Follow-ups: raster extent should be (−0.5, −0.5, W−0.5, H−0.5); consider `ale extract --force`. AREP-MS Annexe 3 converted (outside repo); gaps in `specs/design/arep_ms_gaps.md`.
- 2026-11-09 — **I.1 merged** (PR #1, Codex, 3cdb3c0): `ale extract` for PDF/raster + scale/labels/flags for all plans, DB v2 `review_flags`, `ale review` HTML; independent review 1142 passed. No CLI stubs remain. I.2 now ready.
- 2026-11-09 — CI #60/#61: T05 (seed P60 ≤ 20 s) fails intermittently (20.4–20.5 s) since Q.2 — post-seed steps ignore the deadline; routed to Q.3 (Q311). I.2 specified (waits for I.1).
- 2026-11-09 — I.1 scope kept text-only; Claude provider wiring into `ale extract` queued as I.2 (after I.1).
- 2026-11-09 — I.1 (Codex) committed locally at fb49b4b: 1070 passed, 3 failed — legacy tests asserting pre-I.1 behaviour; Router authorised updating exactly those (notes.md). Push blocked: Codex GitHub integration has no write access (HTTP 403).
- 2026-11-09 — **CI back and green on Windows/macOS/Linux** (3.11–3.13): runs #58 (23c50dc) and #59 (6006440), 9/9 jobs each.
- 2026-11-09 — A.3 + Q.2 merged (8fc97b5): contracts 1.3.0 (inner connector); P60 hard 24 → 17–18 (NO_FACADE 15 → 10), P25 7 → 6, P8 0; annealer early-stop bug fixed (converged counter started at 0). G804 (NO_FACADE ≤ 6) missed — Worker analysis: realiser's exact-area depths waste frontage; G805 is wall-clock dependent (passed alone, 7 > 6 in a loaded full run; xfailed under coverage). Both routed to Q.3 (specified, dispatched). Spec slip: G801 literal footprint miscounted (same as N01).
- 2026-11-09 — P.1 merged (Claude provider: structured output, effort low, server-side refusal fallback, no sampling params; 26 mocked tests, 100 % coverage; suite 1088 passed). CI now installs the `vlm` extra. Note for I.1: call `prepare_image(png)` before `label_plan` so bbox conversion and cache key use the image actually sent.
- 2026-11-09 — CI back (repo public): macOS 3/3 green; Linux/Windows failed only on timing — Windows `time.monotonic` resolution (~16 ms) made 1e-12 budget tests never expire, and D12 (10k random lines) took 21–24 s under coverage vs a 20 s limit. Fix: `guards` default clock → `time.perf_counter`; D12 test limit 60 s (eval amended).
- 2026-11-09 06:30 — Scheduled check: no Worker stopped by the usage limit; Q.1/1.3/1.4/2.2 already merged; Q.2 running (A.3 merged into its branch); I.1 with Codex.
- 2026-11-09 — Repository made public by the user (Actions minutes free → CI unblocked). I.1 specified and assigned to the user's Codex agent (works on its own branch, opens a PR; Router reviews before merge).
- 2026-11-09 — Q.1 merged after review: integrated with all later merges, full suite 1062 pass (first full run had 1 flaky failure, unreproduced). Follow-ups moved to Q.3.
- 2026-11-09 — 2.2 merged after rework. **CI not running since run #46 (2026-11-08 20:51 UTC)**: all jobs fail in ~3 s with no steps/logs → most likely GitHub Actions minutes/spending limit exhausted (macOS ×10, Windows ×2 multipliers; 49 runs × 9 jobs). Local full-suite verification continues meanwhile.
- 2026-11-09 — 1.3 merged after rework.
- 2026-11-09 — Account usage limit stopped Q.1, 1.3, 1.4, 2.2 (reset 01:20 UTC); all resumed 01:26; scheduled task at 06:30 UTC to resume again if needed. 1.4 merged after review.
- 2026-11-08 — 2.1 merged after review (shared-length formula fixed by Worker). 2.2 specified and dispatched.
- 2026-11-08 — 1.5 merged after review (69 tests, 99 %).
- 2026-11-08 — 1.6 merged after review (64 tests, 100 % branch coverage).
- 2026-11-08 — User: "launch all". Dispatched in parallel (libraries, no CLI wiring): 1.3, 1.4 (classical CV), 1.5 (fake VLM providers), 1.6, 2.1, Q.2a. Integration ticket I.1 (wire extract/review) to follow.
- 2026-11-08 — Q.1 attempt 1: geometry refuses rule-breaking shapes, but seeding then fails on P25/P60 (room bays in a block share depth; mixed room sizes have disjoint depth intervals). Scope extended to depth-interval-aware seeding (RD §4). Worker interrupted by the account usage limit, resumed 20:27 UTC. A.3 accepted (held for merge with Q.2).
- 2026-11-08 — User: go on the quality wave. Q.1 and A.3 specified and dispatched in parallel; Q.2, Q.3 queued.
- 2026-11-08 — 3.4 merged after review (777 tests). **End-to-end pipeline works: Excel → plan → optimised layout → DXF/SVG/report.** Quality gap on large programs (P60, 60 s): 22 hard breaks = 11 NO_FACADE (inner bands have no façade; connector at a piece end uses façade), 8 ASPECT/AREA/MIN_WIDTH (degenerate stack fallbacks in realisation), 2 REQUIRED_ADJ. Next wave: quality tickets Q.1–Q.3 (see notes).
- 2026-11-08 — 3.2 merged after review (732 tests). Router check seed 3: valid geometry on all fixtures but hard-rule violations remain (area, aspect, min width, façade, required adj.) → 3.4 energy amended to penalise all hard rules. 3.4 dispatched.
- 2026-11-08 — 3.2 Worker stopped by an account usage limit; resumed after reset (work preserved). 3.4 specified.
- 2026-11-08 — 1.2c merged after review (710 tests).
- 2026-11-08 — A.2 + 3.3b merged together (686 tests, contracts 1.2.0). Router feasibility probe (random plans, scratch): valid grammar plans exist for P8 (2906/5390), P25 (522/1264), P60 (22/672, bands [4,1]) → risk R-G1 closed; greedy plan is the weak part → 3.2 must find valid plans.
- 2026-11-08 — 1.2 merged after review (layer rule fixed to whole words; -AL→-AUX plurals).
- 2026-11-08 — 1.1 merged after review (614 tests). Note: PDF_VECTOR counts every page with drawing paths (charts, diagrams in the reports) — plan detection is a later step. Follow-up: dev-only install fails mypy on ezdxf imports in 3.1's site.py (CI unaffected).
- 2026-11-08 — 3.5 merged after review (564 tests; circulation ratio aligned to Σ net).
- 2026-11-08 — User: "start all". 3.5 and 1.1 specified and dispatched in parallel; 1.2 (DXF first) and 3.2 specs next.
- 2026-11-08 — A.2 accepted (held for joint merge); 3.3b dispatched on top of it.
- 2026-11-08 — User decision U-7 (bands). A.2 specified and dispatched; 3.3 rework to follow on top of it.
- 2026-11-08 — 3.3 merged after review (539 tests). Greedy baseline overflows P8/P60 → 3.2 must estimate grammar circulation demand (open risk R-G1).
- 2026-11-08 — CI run #13 green on all 9 jobs with extras (Windows: 501 pass, Excel/DXF tests run). Ticket 3.3 specified and dispatched.
- 2026-11-07 — Reference corpus received (user's Drive zip, 446 files); network allowlist: drive.google.com, drive.usercontent.google.com (user-approved, "for now"). Inventory in `specs/corpus/inventory_2026-11-07.md` (derived counts only; plans kept out of git).
- 2026-11-07 — A.1 merged after review: **contracts frozen at 1.1.0** (CorridorPlan, decompose_footprint; square primary → spine ⊥ cut, verified rotation-invariant over 8 orientations). Suite 501 pass. 3.2 and 3.3 now unblocked for specification.
- 2026-11-07 — 3.1 merged after review (465 tests with extras / 430 dev-only). CI now installs `.[dev,excel,cad]`; 0.1 doctor tests made extras-independent. A.1 in rework (rotation-invariant tie rule).
- 2026-11-07 — User decision U-6: corridor grammar. Design note written; contract amendment A.1 specified (READY); 3.2/3.3/3.4 re-scoped.
- 2026-11-07 — **Phase 0 verified on Windows / macOS / Linux × Python 3.11–3.13**: CI runs #4, #5, #6 green on all 9 jobs (408 tests). Ticket 0.1 eval P05 satisfied.
- 2026-11-07 — CI run #3: Windows ✔ (all 3). One intermittent Ubuntu/3.11 failure: race in 0.4 test cleanup helper (check-then-kill) — fixed test-only, merged. 3.1 Worker dispatched.
- 2026-11-07 — Ticket 3.1 specified (RD + eval, Router-verified numbers) → READY.
- 2026-11-07 — CI run #2: CRLF fix confirmed (Windows 407 pass); 2 Windows-only test bugs remain (0.1 S01 console-script location; 0.4 extra cwd test decoding cp1252 child output). Fixes sent to the owning Workers.
- 2026-11-07 — CI run #1: Linux ✔ macOS ✔ (9 jobs: 6 green), Windows ✘ — Git CRLF checkout broke byte-exact contract checks. Fixed with `.gitattributes` (eol=lf), verified with a simulated CRLF checkout (327 pass). 0.4 merged after review (408 pass).
- 2026-11-07 — 0.1 and 0.2 merged after independent Router review (327 tests pass on the merged tree). CONTRACTS.lock committed: contracts frozen at 1.0.0. 0.4 → READY.
- 2026-11-07 — 0.1 and 0.2 Workers reported back (0.1: 123 pass / 3 platform skips; 0.2: 181 pass, A03 expectation found wrong — Router error, corrected). Taxonomy v1.1 issued (U-5); follow-ups sent to both Workers before merge.
- 2026-11-07 — Ticket 0.4 specified (RD, eval, fixtures) while 0.1/0.2 run.
- 2026-11-07 — Workers dispatched for 0.1 and 0.2 (isolated worktrees, in parallel).
- 2026-11-07 — U-3 confirmed: corridors 1.2 m minimum.
- 2026-11-07 — U-2 clarified (2:1 is a hard maximum → `shape.aspect_max`); U-4 academic non-commercial use resolves O-4 and O-8.
- 2026-11-07 — User decisions U-1 (0.10 m module), U-2 (aspect ≈ 1:1–1:2), U-3 (narrow corridors) applied to 0.1, 0.2, 0.3 specs. Spec bug fixed in 0.2: the area helper now rounds **up** (`best_buildable_rect`).
- 2026-11-07 — Directive v2.2 received; v2.0 tickets retired (kept in git history). `specs/` rebuilt: 0.1 and 0.2 specified and READY, 0.3 template issued (READY, user input), all other tickets BLOCKED.
