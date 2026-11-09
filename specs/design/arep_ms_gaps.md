# ALE vs AREP-MS project needs (2026-11-09)

Input: Annexe 3 "Programme physique" (Région Marrakech-Safi + AREP headquarters), plus the project's design
rules. The source file is **not committed** (competition document); the conversion script and outputs live
outside the repository.

## What already works (configuration only)
| Project rule | ALE setting |
|---|---|
| 60 cm room grid | `[grid] module_mm = 600` |
| Never below the programme area, ±10 % tolerated → effectively 0 / +10 % | `[area] tol_down_pct = 0`, `tol_up_pct = 10`, `tol_up_abs_m2 = 0` |
| Proportions ≤ 2 | `[shape] aspect_max = 2.0` (default) |
| Offices, meeting rooms, management and reception rooms have a window | `needs_facade = Oui` per room |
| Room types | All Annexe 3 spaces map to existing taxonomy types (office, open_office, meeting_room, archive, sanitary, cleaning_room, technical_room, it_room, auditorium, control_room, bar, quiet_room, first_aid_room, waiting_area, security_room, mail_room, staff_room, entrance_hall). |

Conversion: 66 Région + 75 AREP program lines (173 room instances). Useful area: 2 943 m² Région (3 193 − 250 m²
of underground car park, which is out of scope) and 3 843 m² AREP, matching the Annexe totals.

## Gaps (v2 candidates, by impact)
1. **Multi-storey** (out of scope in v1): R+3/R+4, two buildings, floor constraints (Présidence/DAP/DGS on the
   Région top floor, Direction AREP on the AREP top floor), stacked cores and wet rooms. v1 can lay out one floor
   at a time from a hand-made floor programme.
2. **Depth from the façade ≤ 7.20 m** for rooms with a window: not modelled. Only façade contact is checked.
   Large open spaces (150–500 m²) at aspect ≤ 2 are deeper than 7.20 m. Needs either a max-depth rule
   or splitting open spaces into façade-deep bays.
3. **Two grid steps**: 60 cm for rooms with 30 cm tolerated for shafts, cleaning rooms, WC and control rooms. v1 has a single module.
4. **Egress / fire safety** (distances 40/50 m, dead ends ≤ 10 m, two protected stairs > 5 m apart): out of scope
   (v1 outputs are design studies, not code-checked).
5. **Arbitrary footprints** (trapezoidal buildable zone, setbacks 10 m on three streets): v1 handles rectangles
   and L shapes only.
6. **Organigram adjacency levels** (N1–N4 in the functional programme) → would map to graded adjacency weights
   instead of the binary `adjacent_to`.
7. **Annexe-format import**: the conversion is a script today; a supported `ale program import` (entity →
   department, name → type rules, façade rule by type) would make it reusable.
