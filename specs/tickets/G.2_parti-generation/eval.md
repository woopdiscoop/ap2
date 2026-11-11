# Ticket G.2 · Evaluation (synthetic plot + programme sized like the AREP-MS Région, ~3,000 m²; no real files)
| ID | Test | Pass condition |
|---|---|---|
| P201 | genes | Every typology produces valid gene sets on a large plot; invalid ones are dropped with a reason. |
| P202 | massing | Outlines fit the buildable zone (setbacks, party edge), courtyard short side ≥ H/2, floors × area within ±10 % of the need, terraces recede (upper ⊆ lower). |
| P203 | one_core | Every parti has exactly one core (U-14), placed per its gene. |
| P204 | evaluate | Metrics recomputed independently match; the typical-floor cell diagram has 0 fragmented rooms. |
| P205 | forcedness | Synthetic case: a bar too thin for its façade rooms scores higher forcedness than a comb that holds them; ranking reflects it. |
| P206 | card | Parti card lists every major element with ≥ 1 problem; a deliberately useless element (forecourt on a non-entrance street) is flagged « fonction unique ». |
| P207 | ranking | Non-dominated set computed correctly (hand-checked on 6 synthetic partis); French `partis.md` with cards. |
| P208 | from_forms | `--from-forms` with G.3 outputs maps each form to a typology (IoU reported). |
| P209 | outputs | SVG per parti + `site.yaml` loading as a footprint `SiteSpec`; deterministic (two runs identical). |
| P210 | gates | ruff, format, mypy strict; coverage of `ale.parti` ≥ 90 % (path-form); lock --check; whole suite passes; 40 partis in ≤ 60 s. |
