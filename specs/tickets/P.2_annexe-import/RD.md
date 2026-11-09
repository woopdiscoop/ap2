# Ticket P.2 — Import a "programme physique" (Annexe format) · Requirements Document

> Context = this file, `eval.md`, `ale.program` (`excel.py`, `template.py`), `ale.contracts` (taxonomy, `Program`),
> `ale.cli.commands.program`, and the test helpers in `tests/program/`. No contract changes.

## 1. Purpose
Public-tender programmes come as a "programme physique" spreadsheet, not ALE's template. ALE should convert one into a
valid ALE programme, as was done by hand for the AREP-MS Annexe 3 (see `specs/design/arep_ms_gaps.md`). The real file
is a competition document and must **not** be committed; tests use synthetic files of the same shape.

## 2. Files (ownership)
```
src/ale/program/annexe.py          # NEW: read_annexe(path, rules) → AnnexeResult
src/ale/program/data/annexe_rules.yaml   # NEW: default name → (type, zone, needs_facade) rules
src/ale/cli/commands/program.py    # ONLY: add `ale program import`
tests/program_annexe/**
specs/tickets/P.2_annexe-import/eval_report.md
```

## 3. Input format (detected, not hard-coded to one file)
One sheet; header rows are found by matching (case- and accent-insensitive) the columns **ESPACE**, **NOMBRE**,
**SURFACE UNITAIRE** (and optionally **ENTITE**, **SURFACE TOTALE**). A header row can repeat (several buildings).
- **Building sections**: a title row containing `PROGRAMME PHYSIQUE` (also tolerate the typo `PHYIQUE`) starts a new
  building. Its name is the rest of the title, and later rows belong to it.
- **Entity**: the ENTITE cell, carried down over merged/empty cells until the next non-empty one.
- **Data row**: ESPACE text + NOMBRE int ≥ 1 + SURFACE UNITAIRE number > 0. Rows whose surface is text (e.g. "Selon
  conception") or whose espace matches an `exclude` rule (default: parking) are skipped and reported.
- **Totals and notes** (`TOTAL`, `(+) Circulation`, `NB :`) are ignored. When present, the stated total is compared
  with the sum of the read rows, and a mismatch beyond 0.5 m² is a warning.

## 4. Mapping
`annexe_rules.yaml`: an ordered list of `{match: <regex on folded name>, type: <taxonomy key | null>, zone, facade}`
(first match wins; `type: null` = exclude). Shipped defaults equal the AREP-MS mapping: hall/accueil, loge gardien,
bureau d'ordre, archives, stockage, serveurs, nettoyage, régie, local technique, sanitaires/ablutions, buvette,
infirmerie, prière, conférence, salon, réunion, open space, chauffeurs, then bureau/chef/secrétariat/… → office. `--rules
FILE` overrides. Unmatched names → error listing them (French), no output.
- **IDs**: entity code (initials of the significant words, ≤ 4 letters; collisions get a digit suffix) + 2-digit
  counter, unique per building.
- **Names**: `<espace> — <entity, title case>`, ≤ 120 chars.

## 5. CLI
`ale program import --annexe FILE --out DIR [--rules FILE] [--building NAME]` writes one ALE template per building
(`<slug>_programme.xlsx`, written with the template writer so `ale program check` accepts it) plus
`<slug>_mapping.csv` (id, name, entity, type, zone, facade, quantity, area). French summary: buildings, lines, instances,
useful m² per building, skipped rows, total checks. Exit 0, or 2 on unmatched names or an unreadable file.

## 6. Out of scope
Floors (v1 programmes are single-storey: everything gets floor 0), adjacencies (not in the Annexe format).
