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
| 3.2 | Topology & seeding | BLOCKED | 3.1, A.1, 0.3 | — | Adjacency graph, planarity diagnostic, seeded force layout → initial **CorridorPlan** (grammar). |
| 3.3 | Grammar realization | **DONE** | — | RD + eval | CorridorPlan → Layout, cost, violations, invariant checks, greedy baseline (P25 fits; P8/P60 overflow). |
| 3.4 | SA optimizer | BLOCKED | 3.2, 3.3 | — | Metropolis over grammar moves G1–G6 (U-6). |
| 3.5 | Export & report | BLOCKED | 3.3 (3.4 for final metrics) | — | DXF / SVG / JSON / report.md. |
| A.1 | Contract amendment: CorridorPlan + footprint decomposition | **DONE** | — | RD + eval | Contracts 1.0.0 → 1.1.0; adds `corridor_plan.py`, `footprint.py`; regenerates lock. |
| A.2 | Contract amendment: bands | **IN-PROGRESS** | — | RD + eval | Merged together with the 3.3 rework (breaking plan change). |
| 1.1 | Corpus ingestion & classification | BLOCKED | 0.1, 0.2, 0.4 · **test corpus** | — | `ale ingest`; vector/scanned PDF per page. |
| 1.2 | CAD reader (DWG + DXF) | BLOCKED | 1.1 · test corpus · decision O-5 | — | ODA File Converter / accoreconsole. |
| 1.3 | Vector-PDF reader | BLOCKED | 1.1 · test corpus | — | PyMuPDF. |
| 1.4 | Raster reader | BLOCKED | 1.1 · test corpus | — | CubiCasa5K (v2.0 spec in git history reusable). |
| 1.5 | Semantic labelling | BLOCKED | 1.2, 1.3, 1.4 · decision O-3 | — | CAD text → PDF text → VLM → manual. |
| 1.6 | Geometry join & scale | BLOCKED | 1.5 | — | Scale hierarchy, Hungarian label matching. |
| 2.1 | Topology extraction | BLOCKED | 1.6 | — | |
| 2.2 | Rulebook build | BLOCKED | 2.1, 0.3 | — | Fidelity-weighted, blended with seed. |

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
