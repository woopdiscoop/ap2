# Ticket G.3 · Evaluation (synthetic plot and programme, the prototype's ground-floor case rebuilt in the tests)
| ID | Test | Pass condition |
|---|---|---|
| G301 | one_mass | Every candidate: one connected building; outside connected to the streets; no cell beyond the setbacks. |
| G302 | areas | Every room reaches its cell count (or the shortfall is reported); cores untouched. |
| G303 | anchors | The entrance room touches the main entrance; circulation touches every core. |
| G304 | courtyard | With `--courtyard`: courtyard present; reported open (U form) or enclosed with its size. |
| G305 | outline | Outline is orthogonal, closed, on the 0.60 m grid; notches < 2 cells removed; area within 1 % of the built cells; vertices reported. |
| G306 | yaml | `form_kk.yaml` loads as a `SiteSpec` (mode footprint) with cores and entrances carried over. |
| G307 | deterministic | Same inputs and K → identical files (two fresh processes); K candidates differ (at least 3 distinct outlines for K = 6). |
| G308 | ranking | `forms.md` ranks by the key of RD §5; metrics match recomputation. |
| G310 | contiguity (Router addition 2026-11-11) | Every room and the circulation zone is a single 4-connected region in every candidate (K = 6, with and without `--courtyard`); a room that cannot reach its count is reported short, never scattered. |
| G309 | gates | ruff, format, mypy strict; coverage of `ale.form` ≥ 90 % (path-form); lock --check; whole suite passes; a P25-size case runs in ≤ 10 s per candidate. |
