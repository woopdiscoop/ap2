# Ticket A.2 — Contract amendment: bands (parallel corridors) · Requirements Document

> **Worker brief.** Context = this file, `eval.md`, and `src/ale/contracts/` (read the docstring of
> `corridor_plan.py` first). This amendment **intentionally changes** `corridor_plan.py` (a breaking change of
> the plan model, still unused outside Ticket 3.3). Everything else in the contracts must stay unchanged.

## 1. Why

User decision U-7: a piece may contain several parallel corridors (**bands**), joined by a **connector**
corridor. Text to add to the `corridor_plan.py` module docstring (verbatim, after the existing grammar text):

> Bands: a piece is divided across its spine axis into bands stacked from min v upward; each band is
> `block A | spine | block B`; band depths sum to the piece depth. With ≥ 2 bands the piece has a connector:
> a corridor of width s spanning the full piece depth at its start (u ∈ [0, s)) or end (u ∈ [L − s, L)); band
> spines run from the connector to the far end. 1-band pieces have no connector. J2: if both pieces have one
> band, spines are collinear; otherwise the primary's connector lies on the cut side and the secondary needs
> none. J1: the secondary has exactly one band; the junction finger is in the primary's band adjacent to the
> cut (band 0 if facing_block is A, else the last band), in that band's facing block.

## 2. Files

```
src/ale/contracts/corridor_plan.py      # changed as below
src/ale/contracts/version.py            # "1.2.0"
src/ale/contracts/schemas/CorridorPlan.schema.json   # regenerated
src/ale/contracts/CONTRACTS.lock        # regenerated LAST
tests/contracts/test_corridor_plan.py   # updated + new tests
tests/contracts/test_footprint.py, tests/contracts/test_serialization.py   # only if a literal (e.g. version) must change
tests/contracts/test_models.py          # only the M04 instance list, if needed
specs/tickets/A.2_contract-bands/eval_report.md
```
`footprint.py` is unchanged. Do **not** touch `src/ale/geometry/` (Ticket 3.3 is reworked separately).

## 3. Model changes (`corridor_plan.py`)

```python
class BandPlan(BaseModel):
    block_a: BlockPlan
    block_b: BlockPlan

class PiecePlan(BaseModel):                       # REPLACES the old (block_a, block_b) shape
    bands: tuple[BandPlan, ...]                   # 1..6, ordered from the piece's min v upward
    connector: Literal["none", "start", "end"] = "none"

class RoomPosition(BaseModel):                    # gains `band`
    piece: int; band: int; block: Literal["A","B"]; bay: int
    stack: Literal["left","right"] | None; index: int | None

class CorridorPlan(BaseModel):
    schema_version: Literal["ale.corridor_plan/2"] = "ale.corridor_plan/2"
    pieces: tuple[PiecePlan, ...]
```
Unchanged: `RoomBay`, `FingerBay`, `BlockPlan`, method names and signatures.

**Model validators** (in addition to the existing ones, which now range over all bands):
- `1 ≤ len(bands) ≤ 6`.
- Junction finger: at most one; only with 2 pieces; only in `pieces[0]` (any band — the band rule is checked in `check_against`).
- A piece with 1 band and `connector != "none"` → error.

**Plan order** (`room_ids`, `locate`): piece → band (ascending) → block A then B → bay → left stack → right stack.

**`zone_violations`**: contiguity is checked **per band block**; message format
`"zone ADMINISTRATIVE split in piece 0 band 1 block A"`; finger-mix message
`"finger bay 3 of piece 0 band 1 block B mixes zones"`.

**`check_against`** — add footprint rules (messages sorted, as before):
- `piece p has 2+ bands but no connector` — unless p is the secondary of a J2 footprint.
- J2 with any piece having ≥ 2 bands: the primary's connector must be on the cut side → otherwise
  `primary connector must be on the cut side (start|end)`. The cut side is `"end"` if the cut lies on the
  primary's max-u edge (axis X: max x; axis Y: max y), else `"start"`.
- J1: secondary must have 1 band → `secondary must have exactly one band in a J1 footprint`; the junction finger
  must be in band 0 when `facing_block == "A"` / in the last band when `"B"`, inside that band's block of the
  same letter → otherwise `junction finger must be in band k block X`.
- Existing rules (missing/unknown rooms, piece count, junction presence) unchanged.

## 4. Out of scope
Geometry (3.3 rework), plan construction (3.2), moves (3.4).
