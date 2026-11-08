# ALE 2.2 — Board

Maintained by the Router only. Directive: `specs/DIRECTIVE.md` (v2.2, supersedes 2.0/2.1).

**Statuses:** `BLOCKED` · `READY` · `IN-PROGRESS` · `IN-REVIEW` · `DONE` · `FAILED` (with reason)

**Critical path:** Phase 0 → Phase 3 (on the seed rulebook) → Phase 1 → Phase 2 → rulebook swap.

## Tickets

| Ticket | Title | Status | Depends on | Spec | Notes |
|---|---|---|---|---|---|
| 0.1 | Scaffolding & CLI | **DONE** | — | RD + eval | Owns `pyproject.toml`, CLI, `ale.toml` contract (`AleConfig`). Parallel-safe with 0.2 (disjoint files). |
| 0.2 | Data contracts | **DONE** | — | RD + eval + taxonomy v1 | Frozen at 1.0.0 via `CONTRACTS.lock` once 0.1 and 0.2 are DONE. |
| 0.3 | Seed rulebook | **READY (user input)** | user values; validation needs 0.2 | template + RD + eval | Aspect pre-filled (U-2); remaining ≈ 196 entries: area + orientation per type, 30 pairs, core offset. Unused types can be deleted. |
| 0.4 | Guards & test harness | **DONE** | — | RD + eval + fixtures | `ale.guards.bounded`, `ale.proc.run_tool`, fixtures P8/P25/P60 + 3 sites (Router-verified). Dispatch right after 0.1/0.2 merge. |
| 3.1 | Program & site ingestion | **DONE** | — (0.2, 0.4 done) | RD + eval | Excel → Program with full French error report; site.yaml/DXF → module footprint; feasibility; template + `ale program check`. |
| 3.2 | Topology & seeding | **DONE** | — | RD + eval | Valid first plan at attempt 1 for P8 (0.07 s), P25 (0.49 s), P60 (1.55 s); adjacency far better than random. |
| 3.3 | Grammar realization (+3.3b bands) | **DONE** | — | RD + eval (+ bands) | Bands, connectors, J1/J2; 99 % coverage; P60 realisation 0.10 s. |
| 3.4 | SA optimizer + `ale generate` | **DONE** | — | RD + eval | Lexicographic (hard, cost) annealing, progress schedule, cached realisation (86 it/s P25). Hard breaks: P8 6→0, P25 13→7, P60 35→27 (15 s); P60 60 s run: 22 left. |
| 3.5 | Export & report | **DONE** | — | RD + eval | layout.json, layered DXF (audit clean), SVG preview, French report.md. `ale generate` wiring in 3.4. |
| A.1 | Contract amendment: CorridorPlan + footprint decomposition | **DONE** | — | RD + eval | Contracts 1.0.0 → 1.1.0; adds `corridor_plan.py`, `footprint.py`; regenerates lock. |
| A.2 | Contract amendment: bands | **DONE** | — | RD + eval | Contracts 1.2.0 (CorridorPlan /2). |
| Q.1 | Realisation never emits rule-breaking rooms | **IN-PROGRESS** | — | RD + eval | ROOM_INFEASIBLE / STACK_INFEASIBLE instead of fallbacks. |
| A.3 | Contract: inner connector | **IN-PROGRESS** | — | RD + eval | Contracts 1.3.0, backward compatible. |
| Q.2a | Façade capacity in feasibility | **DONE** | — | RD + eval | usable façade: site_rect 43.2 m, site_L 90.0 m; P60 demand 117.9 m → W_FACADE_TIGHT. |
| Q.2 | Façade-aware layouts | BLOCKED | Q.1, A.3 | — | Inner connectors in geometry/seeding/moves; façade-pull move; grammar façade capacity in feasibility. |
| Q.3 | Cache into geometry + P8 reliability | BLOCKED | Q.2 | — | |
| 1.1 | Corpus ingestion & classification | **DONE** | — | RD + eval | Real corpus: 439 files → 1734 units (DWG 17 NEEDS_TOOL, PDF_VECTOR 879, PDF_SCANNED 436, RASTER 402), 0 failed, idempotent. |
| 1.2 | CAD reader (DXF; DWG via converter) | **DONE** (library) | — | RD + eval | Layers (whole-word), units, walls, rooms, labels, openings, multi-plan, DWG→DXF via ODA/accoreconsole. Follow-up 1.2c: wire `ale layers` / `ale extract --kind dxf\|dwg` to the corpus DB. Real DWGs need ODA on the user's workstation. |
| 1.2c | CAD → corpus CLI (`ale layers`, `ale extract` dxf/dwg) | **DONE** | — | RD + eval | Empty layer map → in-memory proposal + warning; NEEDS_TOOL DWGs retried. |
| 1.3 | Vector-PDF reader (library) | **IN-PROGRESS** | — | RD + eval | Walls/doors/rooms from PDF paths, PDF_TEXT labels, title-block scale, plan-likeness score. |
| 1.4 | Raster reader (classical CV v1, library) | **IN-PROGRESS** | — | RD + eval | No model weights needed; CubiCasa can be added later behind the same API. |
| 1.5 | Semantic labelling (library) | **DONE** | — | RD + eval | Text-first; VLM interface + cache with fake providers. For integration: renderer must use the same extent model; real provider must enforce vlm.timeout_s. Real provider = O-3. |
| 1.6 | Scale reconciliation & review flags (library) | **DONE** | — | RD + eval | Dimension-text rule fixed (plausibility + notation tie-break). |
| 2.1 | Topology extraction (library) | **DONE** | — | RD + eval | Facing-edge shared length (formula fixed); DOOR contacts; façade lengths. |
| 2.2 | Rulebook build (library + `ale rulebook build`) | **IN-PROGRESS** | — | RD + eval | Fidelity-weighted adjacency, quantiles, core offset, orientation; blend with seed; report.md. |

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
