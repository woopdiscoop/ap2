# Ticket A.1 — Contract amendment · Evaluation

Expected values computed by the Router.

| ID | Test | Pass condition |
|---|---|---|
| K01 | version | `CONTRACTS_VERSION == "1.1.0"`. |
| K02 | existing_unchanged | `git diff <base> --stat` shows no change to existing contract `.py` files other than `version.py` and `export_schemas.py` (list update only), and no change to existing schema files; the whole pre-existing suite still passes. |
| K03 | roundtrip | A plan with 2 pieces, room bays, finger bays (one stack empty), a junction finger in piece 0 → `canonical_json` round-trip equal; YAML round-trip equal; discriminated union restores `RoomBay`/`FingerBay` types. |
| K04 | validators | Duplicate id → error; 3 pieces → error; empty non-junction finger → error; junction finger with 1 piece → error; junction in piece 1 → error; two junction fingers → error. |
| K05 | room_ids_locate | For plan `pieces[0]: A = [room R1, finger(left=(R2,R3), right=(R4,))], B = [room R5]` → `room_ids() == ("R1","R2","R3","R4","R5")`; `locate("R3") == RoomPosition(piece=0, block="A", bay=1, stack="left", index=1)`; `locate("R5").stack is None`; `locate("X")` → KeyError. |
| K06 | zone_violations | Block A rooms in plan order with zones P, A, P → `("zone PUBLIC split in piece 0 block A",)`; finger with left=(admin), right=(services) → contains `"finger bay 1 of piece 0 block A mixes zones"`; a clean plan → `()`. |
| K07 | check_against | Missing / unknown ids reported; J1 footprint without junction finger → message; junction finger in the wrong block → message; correct plan → `()`. |
| F01 | rect | `decompose_footprint([(0,0),(240,0),(240,180),(0,180)])` → one piece `rect (0,0,240,180)`, axis `X`, `junction "NONE"`; a 100 × 300 rectangle → axis `Y`; 200 × 200 → `X`. |
| F02 | site_L_J2 | `[(0,0),(480,0),(480,180),(300,180),(300,300),(0,300)]` → cut **vertical** (max aspect 1.000 vs 2.667 horizontal); primary `(0,0,300,300)` axis `X`; secondary `(300,0,180,180)` axis `X`; `junction "J2"`; `cut ((300,0),(300,180))`; `facing_block None`. |
| F03 | J1 | `[(0,0),(600,0),(600,120),(200,120),(200,300),(0,300)]` → cut vertical (3.333 vs 5.000); primary `(0,0,200,300)` axis `Y`; secondary `(200,0,400,120)` axis `X`; `junction "J1"`; `cut ((200,0),(200,120))`; `facing_block "B"`. |
| F04 | rotations | The site_L shape in all 8 orientations (identity, 90°, 180°, 270° rotations, and their mirrors): always 2 pieces of 90 000 and 32 400 cells whose union area equals the polygon area, and **junction J2 in every orientation** (square primary → spine perpendicular to the cut). |
| F05 | unsupported | An 8-vertex U shape → `ValueError` with the v1 message. |
| S01 | schemas | `export_schemas --check` passes and includes `CorridorPlan.schema.json`, `FootprintPieces.schema.json`. |
| S02 | lock | `python -m ale.contracts.lock --check` exits 0 on the committed tree. |
| S03 | gates | ruff, ruff format, mypy strict clean; coverage of the two new modules ≥ 95 % line. |
