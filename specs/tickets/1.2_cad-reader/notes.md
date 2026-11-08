# 1.2 — Router notes

Status: BLOCKED on 1.1, test corpus, decision O-5 (ODA vs accoreconsole on the target workstation).

Parked:
- ODA File Converter is free but distributed under ODA's own terms and requires a download/registration; record version used.
- Unit inference from door blocks needs a fixture DWG without `$INSUNITS` (directive §7 already asks for one).
- "DWG and its exported DXF give identical PlanGeometry" — define identity tolerance (float noise after conversion).
- (2026-11-07, from CI) Windows tools write stdout in the ANSI/OEM code page, not UTF-8; `ale.proc` decodes UTF-8 with replacement, so non-ASCII in ODA/accoreconsole messages shows as U+FFFD. Fine for diagnostics; if 1.2 must *parse* tool output (e.g. file names in error lines), decode with `locale.getpreferredencoding()` on Windows or avoid depending on non-ASCII output.

## Review log
- 2026-11-08 — a3da38a: 15 IDs pass, 94.8 % coverage. Worker found substring matching flaw in layer proposal (MUR PORTEUR → DOOR; TEXTE LOCAUX → ZONE) — Router spec error; RD rewritten to whole-word matching with text roles before zones. Accepted: odafc command run via ale.proc (timeout), override precedence, lowercase LayerRole values, extra keyword args, pairing details. Rework requested.
- 2026-11-08 — Rework 1772eb3: whole-word matching, -AL→-AUX plural accepted, A-AREA-IDEN → area_label accepted. **DONE**.
