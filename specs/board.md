# ALE 2.2 — Board

Maintained by the Router only. Directive: `specs/DIRECTIVE.md` (v2.2, supersedes 2.0/2.1).

**Statuses:** `BLOCKED` · `READY` · `IN-PROGRESS` · `IN-REVIEW` · `DONE` · `FAILED` (with reason)

**Critical path:** Phase 0 → Phase 3 (on the seed rulebook) → Phase 1 → Phase 2 → rulebook swap.

## Tickets

| Ticket | Title | Status | Depends on | Spec | Notes |
|---|---|---|---|---|---|
| 0.1 | Scaffolding & CLI | **READY** | — | RD + eval | Owns `pyproject.toml`, CLI, `ale.toml` contract (`AleConfig`). Parallel-safe with 0.2 (disjoint files). |
| 0.2 | Data contracts | **READY** | — | RD + eval + taxonomy v1 | Frozen at 1.0.0 via `CONTRACTS.lock` once 0.1 and 0.2 are DONE. |
| 0.3 | Seed rulebook | **READY (user input)** | user values; validation needs 0.2 | template + RD + eval | Aspect pre-filled (U-2); remaining ≈ 196 entries: area + orientation per type, 30 pairs, core offset. Unused types can be deleted. |
| 0.4 | Guards & test harness | BLOCKED | 0.1, 0.2 | — | `ale.guards.bounded`, subprocess runner, shared fixtures (8/25/60 rooms; rectangle + L sites). |
| 3.1 | Program & site ingestion | BLOCKED | 0.2, 0.4 · (1.2 only for DWG sites) | — | Excel template, feasibility pre-check. |
| 3.2 | Topology & seeding | BLOCKED | 3.1, 0.3 | — | Adjacency graph, planarity diagnostic, seeded force layout → first slicing tree. |
| 3.3 | Slicing-tree realization | BLOCKED | 0.2, 0.3, 0.4 · decision O-2 | — | Can run in parallel with 3.2 (needs a tree, not 3.2's code). |
| 3.4 | SA optimizer | BLOCKED | 3.2, 3.3 | — | Metropolis over Wong–Liu moves. |
| 3.5 | Export & report | BLOCKED | 3.3 (3.4 for final metrics) | — | DXF / SVG / JSON / report.md. |
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
| U-3 | **Corridors can be narrow.** | `circulation.min_width_m` default 1.8 → 0.9 m. Exact minimum to confirm. |

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
| O-9 | Taxonomy v1 review | Check the 25 types, their default macro-zones/service-core flags, and synonyms (notably `OFFICE` → kitchenette). | 0.2 (spec uses the draft) |

## Corrections to the directive found while specifying

- (Moot since U-1, kept for the record) §3.B.5: the largest overshoot in the 1:1–1:2 band is **+1.217 m²** (at T ≈ 7.423 m²), not +1.14 m²; targets in **7.423–7.439 m²** have no valid rectangle under the +1.2 m² cap. For a 1:2.5 band the maximum is +1.04 m² (cap still never reached). Encoded as test A02 in 0.2.
- (Correction of the Router's own v2.0 board: `1.8 % 0.6` evaluates to `1.11e-16` in CPython, as the directive states — not `0.5999…`. The conclusion, integer modules, is unchanged.)

## History

- 2026-11-06 — v2.0 workspace initialised (tickets 1.1, 1.2 specified).
- 2026-11-07 — U-2 clarified (2:1 is a hard maximum → `shape.aspect_max`); U-4 academic non-commercial use resolves O-4 and O-8.
- 2026-11-07 — User decisions U-1 (0.10 m module), U-2 (aspect ≈ 1:1–1:2), U-3 (narrow corridors) applied to 0.1, 0.2, 0.3 specs. Spec bug fixed in 0.2: the area helper now rounds **up** (`best_buildable_rect`).
- 2026-11-07 — Directive v2.2 received; v2.0 tickets retired (kept in git history). `specs/` rebuilt: 0.1 and 0.2 specified and READY, 0.3 template issued (READY, user input), all other tickets BLOCKED.
