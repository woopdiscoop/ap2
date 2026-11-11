# Ticket M.1 · Evaluation (synthetic programme sized like the AREP-MS Région, ~3,000 m², R+3 bar with a receding top floor; no real files)
| ID | Test | Pass condition |
|---|---|---|
| M101 | building | `building.yaml` loads; French errors for: non-contiguous levels, upper outline not inside the lower, core outside an outline, zero or two cores. G.2's `parti_NN/building.yaml` loads. |
| M102 | groups | Default groups = room-id prefixes; explicit `groups` override; wet rooms excluded from groups; every non-wet instance in exactly one group. |
| M103 | stacking | Synthetic case: pins met (PRES, DAP, DGS on the top floor; entrance rooms on the ground floor); every floor load ≤ 110 %; groups split only over contiguous floors; result deterministic. |
| M104 | optimality | 10 random small cases (≤ 5 groups, ≤ 3 floors): local search objective equals brute force. |
| M105 | infeasible | Pinned groups larger than the top floor: hard miss reported with the shortfall in m², stacking still produced, exit code documented, no traceback. |
| M106 | skeleton | Core and wet-stack cells identical on every floor; wet stack adjacent to the core and inside the top outline; each wet room ≥ target; every occupied floor has ≥ 1 sanitary room. |
| M107 | diagrams | One cell diagram per floor, no room cell on core or wet-stack cells, 0 fragmented rooms after repair (repairs counted), metrics recomputed independently match. |
| M108 | outputs | `stacking.md` (French, all §7 items), `stack.svg` valid XML, `floor_NN/site.yaml` loads as `SiteSpec` with the two cores, `floor_NN/programme.xlsx` round-trips via `read_program`; two runs byte-identical. |
| M109 | stackability | Metric recomputed independently on a hand-made 2-floor case (known value). |
| M110 | gates | ruff, format, mypy strict; coverage of `ale.stack` ≥ 90 % (path-form `--cov=src/ale/stack`); lock --check unchanged; whole suite passes; synthetic case (4 floors) in ≤ 60 s. |
