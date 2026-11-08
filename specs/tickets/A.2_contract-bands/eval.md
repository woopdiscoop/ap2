# Ticket A.2 — Contract amendment: bands · Evaluation

| ID | Test | Pass condition |
|---|---|---|
| B01 | version_schema | `CONTRACTS_VERSION == "1.2.0"`; `CorridorPlan().schema_version` default `"ale.corridor_plan/2"`; `export_schemas --check` passes; `lock --check` passes. |
| B02 | footprint_unchanged | `git diff <base> -- src/ale/contracts/footprint.py src/ale/contracts/models.py src/ale/contracts/geometry.py` is empty; F01–F05 still pass. |
| B03 | roundtrip | A 2-piece plan with 3 bands in piece 0 (`connector "end"`), 1 band in piece 1, room and finger bays, one junction finger → canonical JSON and YAML round-trips equal. |
| B04 | validators | 0 bands → error; 7 bands → error; 1 band with `connector "start"` → error; duplicate id across two bands → error; junction finger in `pieces[1]` → error. |
| B05 | order_locate | Piece 0: band 0 = (A: [room R1], B: [room R2]); band 1 = (A: [finger left=(R3,R4)], B: []). → `room_ids() == ("R1","R2","R3","R4")`; `locate("R4") == RoomPosition(piece=0, band=1, block="A", bay=0, stack="left", index=1)`. |
| B06 | zones_per_band | Zone P in band 0 block A and again in band 1 block A → **no** violation (different band blocks); P, A, P inside band 1 block A → `("zone PUBLIC split in piece 0 band 1 block A",)`. |
| B07 | connector_rules | Rectangle footprint, 2 bands, `connector "none"` → `"piece 0 has 2+ bands but no connector"`; with `"start"` → `()`. |
| B08 | J2_rules | site_L footprint (J2, cut on the primary's max-x edge): both pieces 1 band, no connectors → `()`; primary 2 bands with `connector "start"` → message containing `cut side (end)`; with `"end"` and secondary 2 bands without connector → `()`; primary 1 band + secondary 2 bands with secondary `connector "end"` → message containing `secondary connector must be on the cut side (start)`; with `"start"` → `()`. |
| B09 | J1_rules | J1 example footprint (facing_block B): secondary with 2 bands → `secondary must have exactly one band…`; primary 3 bands, junction finger in band 0 → `junction finger must be in band 2 block B`; junction in band 2 block B → `()`. |
| B10 | gates | Whole suite passes **except** `tests/geometry` (Ticket 3.3, reworked separately — run with `--ignore=tests/geometry` and say so); ruff, mypy strict clean; coverage of `corridor_plan.py` ≥ 95 %. |
