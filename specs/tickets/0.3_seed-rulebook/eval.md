# Ticket 0.3 — Seed Rulebook · Evaluation

Run by the Router once Ticket 0.2 is `DONE` and the user has committed `seed_rulebook.yaml`.

| ID | Check | Pass condition |
|---|---|---|
| R01 | validates | `python -m ale.contracts.validate rulebook specs/tickets/0.3_seed-rulebook/seed_rulebook.yaml` prints `OK`, exit 0 (no `null` left, all ranges respected, `kind: seed`, author and date present). |
| R02 | fixture_coverage | `Rulebook.missing_types(...)` over the 13 fixture types listed in RD §Constraints returns `()`. |
| R03 | roundtrip | `dump_yaml(load_yaml(Rulebook, text))` re-loads to an equal model; `content_sha256()` recorded in `notes.md` as the seed version hash. |
| R04 | feasibility_scan (informative) | For every type, `best_buildable_rect(T, GridSpec(), p10, p90, default tolerance)` over T from `area_m2.p10` to `area_m2.p90` in 0.01 m² steps; the share of T with no valid rectangle is reported per type in `notes.md`. Not a gate — shown to the architect, who may widen a band. |
