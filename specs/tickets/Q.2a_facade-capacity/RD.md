# Ticket Q.2a — Grammar-aware façade capacity in feasibility · Requirements
> **Worker brief.** Context = this file, `eval.md`, 3.1 specs (`specs/tickets/3.1_program-site-ingestion/RD.md`),
> the contracts (incl. `footprint.decompose_footprint`), `ale.program` code. Ownership: `src/ale/program/feasibility.py`,
> `tests/program/test_program_feasibility.py` (add tests; keep existing ones), `specs/tickets/Q.2a_facade-capacity/eval_report.md`.
## Change
Add to `FeasibilityReport`: `facade_usable_m: float` and a **warning** `W_FACADE_TIGHT` (not an error) when the
façade demand `Σ max(min_facade_len, w_est) over needs_facade instances` exceeds `facade_usable_m`, where
`w_est` = the room's narrowest compliant width (area rule + 2:1) in metres.
`facade_usable_m` = Σ over pieces of the exterior edges **parallel to the spine axis** (only blocks along those edges
can face out; edges on the cut excluded) − one spine width `s` per exterior short edge per band (spine ends) — use
the band count estimate `n0` of 3.2 (`max(1, round((P − s) / (2·D_t + s)))`).
`E_FACADE_INSUFFICIENT` (raw perimeter check) is unchanged.
