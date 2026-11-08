# Design note — Corridor grammar (user decision U-6, 2026-11-07)

Normative for Tickets A.1 (contract amendment), 3.2, 3.3, 3.4. Replaces the directive's free slicing tree
(§3.B.1) and free Wong–Liu moves (§6, 3.4 M1–M3) with a constrained family of slicing layouts in which
**every room touches circulation by construction** and **circulation is always connected**.

## 1. Vocabulary

- **Piece**: an axis-aligned rectangle of the module footprint. A rectangular footprint has 1 piece; an
  L-shaped footprint is cut into 2 pieces (§5). Other footprints are out of scope in v1.
- **Spine**: a corridor strip running the full length of a piece along its **spine axis** (the piece's long
  axis; ties → x). Width `s` = `ceil(circulation.min_width_m / module)` modules (12 at 0.10 m).
- **Blocks**: the two parts of the piece on either side of the spine — block **A** (lower / left side of
  the spine) and block **B** (upper / right). A block may be empty (single-loaded spine). Block depths
  `D_A + s + D_B = piece depth` (depth = extent across the spine axis).
- **Bay**: a slice of a block, perpendicular to the spine, spanning the block's full depth. Bays are
  ordered along the spine from the piece's start (min coordinate). Two kinds:
  - **Room bay**: exactly one room, filling the bay. It touches the spine along its whole width and the
    exterior (or the far piece edge) along its far side.
  - **Finger bay**: `[left stack | finger | right stack]` along the spine direction. The **finger** is a
    corridor strip of width `s`, perpendicular to the spine, spanning the block depth and touching the
    spine. Each **stack** is a sequence of rooms ordered from the spine outward, each room spanning the
    stack's width and touching the finger along its full extent. A stack may be empty (single-loaded finger).
- **End strip**: when a block's bays do not fill the piece length, the leftover becomes a circulation
  strip at the block's far end (touching the spine), never a room.

```
   piece (spine axis = x)
   ┌──────┬──────┬────┬───┬────┬──────┬────────┐   ← exterior
   │ room │ room │ R3 │ F │ R6 │ room │  end   │   block B (depth D_B)
   │ bay  │ bay  ├────┤ i ├────┤ bay  │ strip  │
   │      │      │ R2 │ n │ R5 │      │ (circ) │
   │      │      ├────┤ g │    │      │        │
   │      │      │ R1 │ . │ R4 │      │        │
   ├──────┴──────┴────┴───┴────┴──────┴────────┤
   │                 spine (width s)           │
   ├──────────┬──────────┬─────────────────────┤
   │   ...    │   ...    │       ...           │   block A (depth D_A)
   └──────────┴──────────┴─────────────────────┘   ← exterior
```

## 2. Guarantees (checked by Ticket 3.3's eval)

1. Every room touches the spine or a finger. The contact length is the room's extent along that corridor,
   and it must be ≥ `ceil(min_door_edge_m / module)` modules (12). This is enforced as a minimum room dimension.
2. Circulation (spine + fingers + end strips + junction elements) is one connected set.
3. Room bays touch the exterior on their far side when the block is at the piece boundary; in a stack,
   only the outermost room does. `needs_facade` rooms must be in such positions (a hard constraint;
   violations are reported).
4. Rooms + circulation + reported residue tile the footprint exactly, with no overlap (integer modules).

## 3. Macro-zones

Each room's macro-zone comes from the program. Within one block, the bays (and stack rooms) of a zone are
**contiguous**: a block's bay sequence splits into zone runs, each zone appearing at most once per block.
A zone may have runs in several blocks or pieces. Finger stacks hold rooms of a single zone.

## 4. Dimensions (realisation, Ticket 3.3)

All integer modules. Given a plan, 3.3 chooses the block depths `D_A`, `D_B` (and, for L shapes, the
junction offset), then derives every width:
- Room bay: width `w = smallest integer ≥ s_min` such that `w × D` satisfies the area rule; aspect
  `max(w, D) / min(w, D) ≤ shape.aspect_max` (hard).
- Stack of a finger bay: one stack width `w_s` shared by its rooms; room heights `h_i` with `Σ h_i = D`;
  areas `w_s × h_i`. `w_s` and `h_i` are solved jointly (3.3 RD gives the algorithm).
- `Σ bay widths ≤ piece length`; the remainder becomes the end strip (circulation). Overflow means the
  plan is infeasible: 3.3 reports `PLAN_OVERFLOW`, and 3.4 must move rooms.

## 5. L-shaped footprints

Cut the L at its reflex vertex, horizontally or vertically, choosing the cut that minimises the larger
piece aspect ratio (tie → horizontal). The **primary** piece is the larger one (tie → the one containing
the lowest-leftmost vertex); the **secondary** attaches along the cut. The secondary's spine axis is
**perpendicular to the cut**.
- **J1** (cut parallel to the primary spine): the primary block on the cut side gets a forced
  **junction finger bay** whose finger is aligned with the secondary spine (same offset and width), so the
  corridor turns the corner.
- **J2** (cut perpendicular to the primary spine): the two spines are collinear (same offset), and the
  primary spine's end meets the cut.

## 6. Optimiser moves (Ticket 3.4), replacing directive M1–M3

- **G1** swap two rooms of the same zone whose areas are within 25 % (directive M4).
- **G2** move a room between a room bay and a stack, or between stacks, within its zone.
- **G3** reorder bays inside a zone run.
- **G4** reorder zone runs inside a block.
- **G5** move a whole zone run to the other block or piece.
- **G6** flip a stack side (left ↔ right) or the order inside a stack.

The geometry is rebuilt by 3.3 after every move. Metropolis acceptance, as in the directive.

## 7. What the directive's `PolishExpression` becomes

Every grammar plan is a slicing layout. 3.3 may emit the equivalent `PolishExpression` for the report,
but the optimiser state is the `CorridorPlan` (contract amendment A.1), not a free expression.

## 8. Bands — several parallel corridors per piece (user decision U-7, 2026-11-08)

A single spine cannot serve deep pieces: at 30 m depth each block is ~14 m deep while a 12 m² office within 2:1
is at most ~4.9 m deep. A piece is therefore divided, across its spine axis, into **bands** stacked from the
piece's min `v` upward. Each band = `block A | spine | block B` (the single-spine piece of §1 is a 1-band piece).
Band depths sum to the piece depth; 3.3 chooses them.

- **Connector**: when a piece has ≥ 2 bands, a corridor strip of width `s` spans the full piece depth at its
  `start` (u ∈ [0, s)) or `end` (u ∈ [L − s, L)); every band spine runs from the connector to the far end, so
  all spines are joined. 1-band pieces have no connector.
- **J2 (collinear)**: if both pieces have 1 band, spines stay collinear (§5). If the primary has ≥ 2 bands, its connector
  lies on the cut side and the secondary needs none; if only the secondary has ≥ 2 bands, the secondary's connector lies
  on its cut side and the primary's single spine meets it.
- **J1 (junction finger)**: v1 keeps the secondary at 1 band; the junction finger sits in the primary's band
  adjacent to the cut (band 0 if `facing_block = A`, last band if `B`), in that band's facing block.
- Guarantees of §2 are unchanged. New optimiser move **G7**: split a band / merge two adjacent bands (3.4).
