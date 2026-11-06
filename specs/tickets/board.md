# ALE 2.0 — Ticket Board

Maintained by the Router only. Source of truth for project state.

**Status legend:** `TO-DO` (not yet specified) · `SPECIFIED` (RD + eval written, waiting on dependencies) · `READY` (can be dispatched now) · `IN-PROGRESS` (Worker dispatched) · `IN-REVIEW` (Router re-running eval) · `DONE` (merged) · `BLOCKED` (needs a decision; see below)

## Tickets

| Ticket | Title | Phase | Status | Depends on | Worker | Merge commit | Notes |
|---|---|---|---|---|---|---|---|
| 1.1 | Orchestrator Daemon | 1 – Extraction | **READY** | — | — | — | Defines the `JobSpec`/`ProcessResult`/`NonRetryableError` contract used by 1.2 and 1.3. |
| 1.2 | Structural Vectorization (CubiCasa5K) | 1 – Extraction | SPECIFIED | 1.1 | — | — | Tier A runs without weights. Tier B needs weights on a local machine (see D3, R1, R2). |
| 1.3 | Semantic Vision Engine (VLM) | 1 – Extraction | TO-DO | 1.1 | — | — | Needs D4 (which Vision API / model, bbox coordinate convention). |
| 1.4 | Spatial Geometry Join (scale calibration) | 1 – Extraction | TO-DO | 1.2, 1.3 | — | — | Consumes `structure.geojson` (pixel space) + VLM JSON; door `width_px` from 1.2 cross-checks VLM doors. |
| 2.1 | Topology Extraction | 2 – Rulebook | TO-DO | 1.4 | — | — | |
| 2.2 | SQLite Rulebook & Analytics | 2 – Rulebook | TO-DO | 2.1 | — | — | |
| 3.1 | Program & Site Ingestion | 3 – Generation | TO-DO | — | — | — | Independent of Phase 1–2; can run in parallel once D1 is decided. |
| 3.2 | Force-Directed Topology | 3 – Generation | TO-DO | 2.2, 3.1 | — | — | |
| 3.3 | Grid-Snapped Treemap | 3 – Generation | TO-DO | 3.2 | — | — | Needs D1. |
| 3.4 | Heuristic Optimizer (Simulated Annealing) | 3 – Generation | TO-DO | 3.3 | — | — | |

## Decisions log

| ID | Decision | Status |
|---|---|---|
| D1 | **0.6 m module in integer units.** `value % 0.6 == 0` is unreliable in floating point (`1.8 % 0.6 → 0.5999…`). Proposal: all generative geometry (Phase 3) is stored as integer millimetres or integer module counts (1 module = 600 mm); the grid check becomes `mm % 600 == 0` on `int`. Metres are produced only at export. | PROPOSED — needs user approval before 3.1/3.3 are specified |
| D2 | PDF rasterization uses `pypdfium2`, not PyMuPDF, because PyMuPDF is AGPL-licensed. | ADOPTED in 1.1 RD |
| D3 | CubiCasa5K weights are supplied manually by the operator and verified by SHA-256; never downloaded by code, never committed. | ADOPTED in 1.2 RD |
| D4 | Vision API for Ticket 1.3: provider/model, and whether `[ymin, xmin, ymax, xmax]` is in pixels or normalized (e.g. 0–1000). | OPEN — needed before 1.3 is specified |
| D5 | The directive's "Watchdog" agent is implemented as code, not as a prompt: the 1.1 runner enforces per-job hard timeouts (SIGTERM → SIGKILL), and every eval enforces `pytest-timeout` plus explicit iteration caps in geometric loops. | ADOPTED |
| D6 | One global board at `specs/tickets/board.md` (rather than one per ticket folder). | ADOPTED |

## Risk register

| ID | Risk | Mitigation |
|---|---|---|
| R1 | CubiCasa5K dataset/weights are published under a non-commercial licence; using them in a commercial pipeline may not be permitted. | Recorded in 1.2 `VENDORED.md`; user to confirm licence position before production use. |
| R2 | CubiCasa5K is trained on residential (mostly Finnish) plans; commercial plans are out of domain. Wall/opening quality may degrade. | Tier B gate B05 (commercial smoke set) measures this early. Fallback options if it fails: fine-tuning ticket, or classical CV wall extraction. |
| R3 | Filesystem events from SMB/NFS shares are not delivered by inotify. | 1.1 defaults to `PollingObserver` + periodic reconciliation scans. |
| R4 | Unbounded loops in geometric post-processing / treemap subdivision. | D5: hard timeouts + mandatory iteration caps tested in every eval. |

## Open inputs needed from the user

1. NAS mount path and expected volume (files/day) — sets 1.1 defaults; not blocking.
2. Whether a CUDA GPU is available on the inference machine — affects 1.2 Tier B runtime only.
3. D1 approval (integer-mm module).
4. D4 (Vision API choice) — before 1.3.
5. 5 representative commercial plans for gate B05.

## History

- 2026-11-06 — Workspace initialized. Tickets 1.1 and 1.2 specified. 1.1 marked READY.
