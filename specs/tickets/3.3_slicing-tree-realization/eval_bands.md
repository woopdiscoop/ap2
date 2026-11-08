# Ticket 3.3b — Evaluation (in addition to 3.3 `eval.md`, ported to the new model)

All 3.3 eval IDs must still exist and pass after porting (E01–E06, G01–G04, R01–R04, V01–V03).

| ID | Test | Pass condition |
|---|---|---|
| N01 | two_bands_exact | Footprint 60 × 116, spine axis X. Piece: 2 bands, connector `start`; band 0 = (A empty, B = [room 12 m²]); band 1 = (A empty, B = [room 12 m²]). → `check_layout == ()`; connector `(0,0,12,116)`; each band's spine starts at x = 12; both rooms 12.00 m² (w = 30, D = 40). |
| N02 | inverse_bands | Hypothesis (`max_examples=150`, derandomized): generate valid multi-band rectangular layouts first (1–4 bands, connector start or end), derive the program from the realised areas → `realize` succeeds, `check_layout == ()`, zero overshoot (as G01–G03). |
| N03 | inverse_bands_L | Same for L footprints covering: J2 both 1 band; J2 primary multi-band; J2 secondary-only multi-band; J1 primary multi-band. |
| N04 | connector_connectivity | In every N02/N03 success, circulation is one connected component and every band spine touches the connector (or the cut-side connector of the other piece). |
| N05 | greedy_bands | `greedy_plan` on P60/site_L produces ≥ 2 bands in the primary piece; `realize` never raises. Report (not gate) whether P8, P25, P60 realise without failures, with the overflow if any. |
| N06 | performance | P60 with the greedy plan ≤ 1.0 s. |
