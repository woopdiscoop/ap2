# Ticket A.1 — Contract amendment: CorridorPlan & footprint decomposition · Requirements Document

> **Worker brief.** This file and `eval.md` are your context, plus the existing contracts in
> `src/ale/contracts/`. This is a **contract amendment**: you are allowed to add files to
> `src/ale/contracts/`, bump the contracts version, regenerate schemas and `CONTRACTS.lock`.
> You must **not change the behaviour or signature of any existing contract**.

## 1. Purpose

User decision U-6 replaced free slicing trees with a **corridor grammar**: in each rectangular *piece* of
the footprint, a spine corridor runs along the piece's long axis; on each side of the spine, a *block* is a
sequence of *bays*, perpendicular to the spine. A **room bay** holds one room touching the spine. A
**finger bay** holds a corridor *finger*, perpendicular to the spine, with two *stacks* of rooms on its
sides, each room touching the finger. Every room thus touches circulation by construction. Tickets 3.2
(builds plans), 3.3 (realises geometry) and 3.4 (optimises plans) share the plan model and the footprint
decomposition defined here.

## 2. Files

```
src/ale/contracts/corridor_plan.py      # NEW: models + validators + helpers (§3, §4)
src/ale/contracts/footprint.py          # NEW: decompose_footprint (§5)
src/ale/contracts/version.py            # CONTRACTS_VERSION = "1.1.0"
src/ale/contracts/export_schemas.py     # add CorridorPlan and FootprintPieces to the exported list
src/ale/contracts/schemas/CorridorPlan.schema.json, FootprintPieces.schema.json   # generated
src/ale/contracts/CONTRACTS.lock        # regenerated (python -m ale.contracts.lock)
tests/contracts/test_corridor_plan.py, tests/contracts/test_footprint.py          # NEW
tests/contracts/test_models.py          # only: add instances of the new models to the M04 coverage list
specs/tickets/A.1_contract-corridor-plan/eval_report.md
```
Same global rules as the existing contracts: `extra="forbid"`, `frozen=True`, `StrictInt`/`StrictStr`
fields, tuples for collections, no shapely objects stored.

## 3. `corridor_plan.py`

```python
InstanceId = StrictStr          # an id from Program.instances() ("R1", "R1#03", …)

class RoomBay(BaseModel):
    kind: Literal["room"] = "room"
    room: InstanceId

class FingerBay(BaseModel):
    kind: Literal["finger"] = "finger"
    left: tuple[InstanceId, ...] = ()     # stack before the finger along the spine, ordered from the spine outward
    right: tuple[InstanceId, ...] = ()    # stack after the finger, ordered from the spine outward
    junction: bool = False                # True only for the L-shape J1 junction finger (§5)

Bay = Annotated[RoomBay | FingerBay, Field(discriminator="kind")]

class BlockPlan(BaseModel):
    bays: tuple[Bay, ...] = ()            # ordered along the spine from the piece's min coordinate

class PiecePlan(BaseModel):
    block_a: BlockPlan                    # lower (spine axis X) / left (spine axis Y) side of the spine
    block_b: BlockPlan                    # upper / right side

class RoomPosition(BaseModel):
    piece: int; block: Literal["A", "B"]; bay: int
    stack: Literal["left", "right"] | None        # None for a room bay
    index: int | None                             # position in the stack from the spine (0-based); None for a room bay

class CorridorPlan(BaseModel):
    schema_version: Literal["ale.corridor_plan/1"] = "ale.corridor_plan/1"
    pieces: tuple[PiecePlan, ...]                 # 1 or 2; same order as FootprintPieces.pieces
    def room_ids(self) -> tuple[str, ...]         # every room, in plan order (piece, block A then B, bay, left stack, right stack)
    def locate(self, instance_id: str) -> RoomPosition      # KeyError if absent
    def zone_violations(self, zone_of: Mapping[str, MacroZone]) -> tuple[str, ...]
    def check_against(self, instance_ids: Iterable[str], footprint: "FootprintPieces") -> tuple[str, ...]
```

**Validators (model-level, raise `ValidationError`):**
- `len(pieces)` ∈ {1, 2}.
- Every instance id appears **exactly once** across the plan.
- A non-junction finger bay has at least one room (in `left` or `right`).
- Junction fingers: at most one in the plan; only allowed when `len(pieces) == 2`; only in `pieces[0]`.

**Helpers (return messages; never raise for a valid model):**
- `zone_violations`: a zone appears in more than one **contiguous run** of rooms in a block (rooms read in
  plan order within the block, junction finger ignored) → `"zone ADMINISTRATIVE split in piece 0 block A"`;
  a finger bay whose two stacks contain more than one zone → `"finger bay 3 of piece 0 block B mixes zones"`.
  Returned sorted. An id missing from `zone_of` → `KeyError`.
- `check_against`: compares to the program and footprint: ids missing from the plan / unknown ids
  (`"missing room R7"`, `"unknown room X1"`), piece count ≠ footprint piece count, junction finger present
  iff `footprint.junction == "J1"` and placed in the primary's block that faces the cut (`facing_block`).
  Returned sorted.

## 4. Grammar invariants documented in the module docstring

Copy the "Vocabulary", "Guarantees" and "L-shaped footprints" sections of the design summary below into
the module docstring of `corridor_plan.py` (they are the reference text for Tickets 3.2–3.4):

> Piece = axis-aligned rectangle of the module footprint. Spine = corridor strip along the piece's spine
> axis, full length, width `s = ceil(circulation.min_width_m / module)`. Blocks A and B on each side
> (possibly empty). Bays ordered along the spine. Room bay = one room touching the spine along its full
> width and spanning the block depth. Finger bay = `[left stack | finger | right stack]`; finger = corridor
> strip of width `s` perpendicular to the spine, spanning the block depth; stack rooms ordered from the
> spine outward, each spanning the stack width and touching the finger along its full extent. Leftover
> length at a block's far end = circulation end strip. Guarantees: every room touches spine or finger with
> contact ≥ `ceil(min_door_edge_m / module)`; circulation connected; exact tiling. Macro-zones contiguous
> per block; one zone per finger bay. L shapes: see `footprint.decompose_footprint`; J1 = corridor turns
> the corner through a junction finger in the primary's facing block; J2 = collinear spines.

## 5. `footprint.py`

```python
class Piece(BaseModel):
    rect: ModuleRect
    spine_axis: Literal["X", "Y"]

class FootprintPieces(BaseModel):
    pieces: tuple[Piece, ...]                                   # primary first
    junction: Literal["NONE", "J1", "J2"]
    cut: tuple[tuple[int, int], tuple[int, int]] | None         # cut segment endpoints (lower/left first), on the secondary's side
    facing_block: Literal["A", "B"] | None                      # J1 only: block of the primary that faces the cut

def decompose_footprint(fp: ModulePolygon) -> FootprintPieces
```
- **Rectangle** (4 vertices): one piece = the rectangle; `spine_axis` = `"X"` if width ≥ height else `"Y"`;
  `junction "NONE"`, `cut None`, `facing_block None`.
- **L** (6 vertices, one reflex vertex r): candidate cuts through r, horizontal (y = r.y) and vertical
  (x = r.x), each giving two rectangles. Choose the cut minimising the larger of the two pieces' aspect
  ratios (long/short); tie → horizontal. **Primary** = larger area (tie → the piece whose rect has the
  smaller (y, x) origin). Primary `spine_axis` = its long axis (tie → `"X"`). **Secondary** `spine_axis`
  = perpendicular to the cut line (a vertical cut line → `"X"`; a horizontal one → `"Y"`).
  `junction` = `"J1"` if the cut line is parallel to the primary's spine axis, else `"J2"`.
  `facing_block` (J1): primary axis X → `"B"` if the cut lies on the primary's top edge, else `"A"`;
  axis Y → `"B"` if on its right edge, else `"A"`.
- Any other vertex count → `ValueError("v1 supports rectangular and L-shaped footprints only")`.
- Pure integer arithmetic; no shapely needed (allowed for validation only).

## 6. Out of scope

Realisation (3.3), plan construction (3.2), moves (3.4). No change to existing contract files other than
those listed in §2.
