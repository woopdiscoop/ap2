"""Grammar moves G1-G7 on a :class:`CorridorPlan` (RD 3.4 §2).

Every move is a pure function ``move(plan, ctx, rng) -> CorridorPlan | None``: it draws its
choices from ``rng`` (a seeded ``random.Random``) and returns a new plan that passes the
contract validators and ``check_against``, or ``None`` when the move does not apply or its
result would be invalid. A result that adds macro-zone grammar violations
(``zone_violations``) or equals the input plan is also ``None``.

* ``G1`` swap two rooms of the same zone whose target areas are within 25 %.
* ``G2`` move a room between a room bay and a stack, or between stacks, within its zone
  (finger bays are created / removed as needed; a non-junction finger is never left empty).
  A quarter of the draws on a room bay instead fold it and its adjacent same-zone room bays
  into the stack of one new finger bay (see :func:`_fold`).
* ``G3`` swap two adjacent bays of one zone run of a block.
* ``G4`` swap two zone runs of a block.
* ``G5`` move a whole zone run to another block (any band / piece).
* ``G6`` swap the stacks of a finger bay, or reverse one of its stacks.
* ``G7`` split a band into two (fewer than 6 bands) or merge two adjacent bands of a piece,
  redistributing their bays in order; connectors are fixed per the contract rules.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise, product
from typing import Literal

from pydantic import ValidationError

from ale.contracts.corridor_plan import (
    MAX_BANDS,
    BandPlan,
    BlockPlan,
    CorridorPlan,
    FingerBay,
    PiecePlan,
    RoomBay,
)
from ale.contracts.enums import MacroZone
from ale.contracts.footprint import FootprintPieces, decompose_footprint
from ale.program.models import PreparedInput

__all__ = [
    "MOVES",
    "MOVE_WEIGHTS",
    "MoveContext",
    "g1_swap_rooms",
    "g2_move_room",
    "g3_swap_bays",
    "g4_swap_runs",
    "g5_move_run",
    "g6_flip_finger",
    "g7_split_merge",
    "propose",
]

Bay = RoomBay | FingerBay
Connector = Literal["none", "start", "end"]
_CONNECTORS: tuple[Connector, ...] = ("none", "start", "end")
_AREA_TOLERANCE = 0.25
_FOCUS_SHARE = 0.5
_FOLD_SHARE = 0.25
"""Share of G2 draws on a room bay that fold its same-zone run into one stack."""


@dataclass(frozen=True)
class MoveContext:
    """What the moves need besides the plan: instance ids, zones, areas and the footprint."""

    instance_ids: tuple[str, ...]
    zone_of: Mapping[str, MacroZone]
    area_of: Mapping[str, float]
    footprint: FootprintPieces
    focus: tuple[str, ...] = ()
    """Rooms the moves pick first half of the time (e.g. rooms with hard violations)."""

    def with_focus(self, rooms: Iterable[str]) -> MoveContext:
        """This context with ``focus`` = the sorted known ids of ``rooms``."""
        focus = tuple(sorted(set(rooms) & set(self.instance_ids)))
        return self if focus == self.focus else replace(self, focus=focus)

    @classmethod
    def from_prepared(cls, prepared: PreparedInput) -> MoveContext:
        """Context of ``prepared`` (``ValueError`` for an unsupported footprint)."""
        return cls(
            instance_ids=tuple(iid for iid, _ in prepared.instances),
            zone_of={iid: spec.macro_zone for iid, spec in prepared.instances},
            area_of={iid: float(spec.target_area_m2) for iid, spec in prepared.instances},
            footprint=decompose_footprint(prepared.footprint.polygon),
        )


# ---------------------------------------------------------------- mutable working copy
Block = list[Bay]
Band = list[Block]  # [block A, block B]


@dataclass
class _Piece:
    bands: list[Band]
    connector: Connector


def _unpack(plan: CorridorPlan) -> list[_Piece]:
    return [
        _Piece(
            bands=[[list(b.block_a.bays), list(b.block_b.bays)] for b in piece.bands],
            connector=piece.connector,
        )
        for piece in plan.pieces
    ]


def _pack(pieces: Sequence[_Piece]) -> CorridorPlan:
    """Build the plan; ``ValidationError`` propagates."""
    return CorridorPlan(
        pieces=tuple(
            PiecePlan(
                bands=tuple(
                    BandPlan(block_a=BlockPlan(bays=tuple(a)), block_b=BlockPlan(bays=tuple(b)))
                    for a, b in p.bands
                ),
                connector=p.connector,
            )
            for p in pieces
        )
    )


def _blocks(pieces: Sequence[_Piece]) -> list[Block]:
    return [block for p in pieces for band in p.bands for block in band]


def _bay_rooms(bay: Bay) -> tuple[str, ...]:
    if isinstance(bay, RoomBay):
        return (bay.room,)
    return (*bay.left, *bay.right)


def _is_junction(bay: Bay) -> bool:
    return isinstance(bay, FingerBay) and bay.junction


def _bay_zone(bay: Bay, ctx: MoveContext) -> str | None:
    """The single zone of a non-junction bay, else ``None`` (junction or mixed)."""
    if _is_junction(bay):
        return None
    zones = {ctx.zone_of.get(r, "?") for r in _bay_rooms(bay)}
    return zones.pop() if len(zones) == 1 else None


def _runs(block: Block, ctx: MoveContext) -> list[tuple[int, int]]:
    """Maximal ``[start, stop)`` index ranges of non-junction bays sharing one zone.

    A junction bay breaks a run and belongs to none; a mixed bay is a run of its own.
    """
    out: list[tuple[int, int]] = []
    i = 0
    n = len(block)
    while i < n:
        if _is_junction(block[i]):
            i += 1
            continue
        zone = _bay_zone(block[i], ctx)
        j = i + 1
        while (
            zone is not None
            and j < n
            and not _is_junction(block[j])
            and _bay_zone(block[j], ctx) == zone
        ):
            j += 1
        out.append((i, j))
        i = j
    return out


def _finish(plan: CorridorPlan, pieces: Sequence[_Piece], ctx: MoveContext) -> CorridorPlan | None:
    """The packed result if it is valid, new and adds no zone violation; else ``None``."""
    try:
        new = _pack(pieces)
    except (ValidationError, ValueError):
        return None
    if new == plan:
        return None
    if new.check_against(ctx.instance_ids, ctx.footprint):
        return None
    if len(new.zone_violations(ctx.zone_of)) > len(plan.zone_violations(ctx.zone_of)):
        return None
    return new


def _pick_room(rooms: Sequence[str], ctx: MoveContext, rng: random.Random) -> str:
    """A room of ``rooms``: half of the time one of ``ctx.focus`` (when any is present)."""
    if ctx.focus and rng.random() < _FOCUS_SHARE:
        present = set(rooms)
        focus = [r for r in ctx.focus if r in present]
        if focus:
            return rng.choice(focus)
    return rng.choice(rooms)


# ---------------------------------------------------------------------------- G1
def _rename(bay: Bay, mapping: Mapping[str, str]) -> Bay:
    if isinstance(bay, RoomBay):
        return RoomBay(room=mapping.get(bay.room, bay.room))
    return FingerBay(
        left=tuple(mapping.get(r, r) for r in bay.left),
        right=tuple(mapping.get(r, r) for r in bay.right),
        junction=bay.junction,
    )


def g1_swap_rooms(plan: CorridorPlan, ctx: MoveContext, rng: random.Random) -> CorridorPlan | None:
    """G1: swap two rooms of the same zone with target areas within 25 %."""
    rooms = plan.room_ids()
    if len(rooms) < 2:
        return None
    a = _pick_room(rooms, ctx, rng)
    area_a = ctx.area_of.get(a, 0.0)
    partners = [
        b
        for b in rooms
        if b != a
        and ctx.zone_of.get(b) == ctx.zone_of.get(a)
        and abs(ctx.area_of.get(b, 0.0) - area_a)
        <= _AREA_TOLERANCE * max(ctx.area_of.get(b, 0.0), area_a)
    ]
    if not partners:
        return None
    b = rng.choice(partners)
    mapping = {a: b, b: a}
    pieces = _unpack(plan)
    for block in _blocks(pieces):
        block[:] = [_rename(bay, mapping) for bay in block]
    return _finish(plan, pieces, ctx)


# ---------------------------------------------------------------------------- G2
def _remove_room(block: Block, b: int, room: str) -> None:
    """Remove ``room`` from bay ``b`` of ``block`` (dropping an emptied non-junction bay)."""
    bay = block[b]
    if isinstance(bay, RoomBay):
        del block[b]
        return
    left = tuple(r for r in bay.left if r != room)
    right = tuple(r for r in bay.right if r != room)
    if not left and not right and not bay.junction:
        del block[b]
    else:
        block[b] = FingerBay(left=left, right=right, junction=bay.junction)


def _insert_positions(
    blocks: Sequence[Block], zone: str, ctx: MoveContext
) -> list[tuple[int, int]]:
    """``(block, index)`` insertion points next to a bay of ``zone``."""
    out: list[tuple[int, int]] = []
    for k, block in enumerate(blocks):
        for i in range(len(block) + 1):
            before = block[i - 1] if i > 0 else None
            after = block[i] if i < len(block) else None
            if any(bay is not None and _bay_zone(bay, ctx) == zone for bay in (before, after)):
                out.append((k, i))
    return out


def g2_move_room(plan: CorridorPlan, ctx: MoveContext, rng: random.Random) -> CorridorPlan | None:
    """G2: move a room between a room bay and a stack, or between stacks, within its zone."""
    rooms = plan.room_ids()
    if not rooms:
        return None
    room = _pick_room(rooms, ctx, rng)
    zone = ctx.zone_of.get(room, "?")
    pos = plan.locate(room)
    pieces = _unpack(plan)
    blocks = _blocks(pieces)
    flat = [
        (p, k, name) for p, pc in enumerate(pieces) for k in range(len(pc.bands)) for name in "AB"
    ]
    src = flat.index((pos.piece, pos.band, pos.block))
    from_stack = pos.stack is not None
    if not from_stack and rng.random() < _FOLD_SHARE:
        return _fold(plan, pieces, blocks[src], pos.bay, ctx, rng)
    _remove_room(blocks[src], pos.bay, room)

    # Targets: ("stack", block, bay, side) of a same-zone finger, ("new", block, index, kind).
    targets: list[tuple[str, int, int, str]] = []
    for k, block in enumerate(blocks):
        for b, bay in enumerate(block):
            if not isinstance(bay, FingerBay):
                continue
            zones = {ctx.zone_of.get(r) for r in _bay_rooms(bay)}
            if zones <= {zone}:
                targets += [("stack", k, b, "left"), ("stack", k, b, "right")]
    points = _insert_positions(blocks, zone, ctx) or [(src, min(pos.bay, len(blocks[src])))]
    for k, i in points:
        targets += [("new", k, i, "left"), ("new", k, i, "right")]
        if from_stack:
            targets.append(("new", k, i, "room"))
    kind, k, i, side = rng.choice(targets)
    block = blocks[k]
    if kind == "new":
        new_bay: Bay
        if side == "room":
            new_bay = RoomBay(room=room)
        elif side == "left":
            new_bay = FingerBay(left=(room,))
        else:
            new_bay = FingerBay(right=(room,))
        block.insert(i, new_bay)
    else:
        bay = block[i]
        assert isinstance(bay, FingerBay)
        stack = list(bay.left if side == "left" else bay.right)
        stack.insert(rng.randint(0, len(stack)), room)
        if side == "left":
            block[i] = FingerBay(left=tuple(stack), right=bay.right, junction=bay.junction)
        else:
            block[i] = FingerBay(left=bay.left, right=tuple(stack), junction=bay.junction)
    return _finish(plan, pieces, ctx)


def _fold(
    plan: CorridorPlan,
    pieces: list[_Piece],
    block: Block,
    b: int,
    ctx: MoveContext,
    rng: random.Random,
) -> CorridorPlan | None:
    """G2 fold: the room bay ``b`` and its adjacent same-zone room bays become one stack.

    Moving these rooms into a new finger one at a time costs a finger width at the first
    step, which an otherwise full block cannot absorb; one stack of several rooms is as
    wide as their room bays together, so the fold can fit where single moves cannot.
    """
    zone = _bay_zone(block[b], ctx)
    lo, hi = b, b + 1
    while lo > 0 and isinstance(block[lo - 1], RoomBay) and _bay_zone(block[lo - 1], ctx) == zone:
        lo -= 1
    while hi < len(block) and isinstance(block[hi], RoomBay) and _bay_zone(block[hi], ctx) == zone:
        hi += 1
    if hi - lo < 2:
        return None
    rooms = tuple(r for bay in block[lo:hi] for r in _bay_rooms(bay))
    new_bay = FingerBay(left=rooms) if rng.random() < 0.5 else FingerBay(right=rooms)
    block[lo:hi] = [new_bay]
    return _finish(plan, pieces, ctx)


# ---------------------------------------------------------------------------- G3
def g3_swap_bays(plan: CorridorPlan, ctx: MoveContext, rng: random.Random) -> CorridorPlan | None:
    """G3: swap two adjacent bays inside one zone run of a block."""
    pieces = _unpack(plan)
    cands = [
        (k, i)
        for k, block in enumerate(_blocks(pieces))
        for start, stop in _runs(block, ctx)
        for i in range(start, stop - 1)
    ]
    if not cands:
        return None
    k, i = rng.choice(cands)
    block = _blocks(pieces)[k]
    block[i], block[i + 1] = block[i + 1], block[i]
    return _finish(plan, pieces, ctx)


# ---------------------------------------------------------------------------- G4
def _segments(block: Block, ctx: MoveContext) -> tuple[list[list[Bay]], list[int]]:
    """``block`` cut into segments (runs and single junction bays) and the run segment ids."""
    segs: list[list[Bay]] = []
    run_ids: list[int] = []
    runs = dict(_runs(block, ctx))
    i = 0
    while i < len(block):
        if i in runs:
            run_ids.append(len(segs))
            segs.append(block[i : runs[i]])
            i = runs[i]
        else:
            segs.append([block[i]])
            i += 1
    return segs, run_ids


def g4_swap_runs(plan: CorridorPlan, ctx: MoveContext, rng: random.Random) -> CorridorPlan | None:
    """G4: swap two zone runs inside a block."""
    pieces = _unpack(plan)
    blocks = _blocks(pieces)
    cands = [k for k, block in enumerate(blocks) if len(_runs(block, ctx)) >= 2]
    if not cands:
        return None
    k = rng.choice(cands)
    segs, run_ids = _segments(blocks[k], ctx)
    x, y = rng.sample(run_ids, 2)
    segs[x], segs[y] = segs[y], segs[x]
    blocks[k][:] = [bay for seg in segs for bay in seg]
    return _finish(plan, pieces, ctx)


# ---------------------------------------------------------------------------- G5
def g5_move_run(plan: CorridorPlan, ctx: MoveContext, rng: random.Random) -> CorridorPlan | None:
    """G5: move a whole zone run to another block (any band / piece)."""
    pieces = _unpack(plan)
    blocks = _blocks(pieces)
    if len(blocks) < 2:
        return None
    runs = [(k, r) for k, block in enumerate(blocks) for r in _runs(block, ctx)]
    if not runs:
        return None
    k, (start, stop) = rng.choice(runs)
    moved = blocks[k][start:stop]
    del blocks[k][start:stop]
    dest = rng.choice([j for j in range(len(blocks)) if j != k])
    segs, _ = _segments(blocks[dest], ctx)
    cut = rng.randint(0, len(segs))
    blocks[dest][:] = (
        [bay for seg in segs[:cut] for bay in seg]
        + moved
        + [bay for seg in segs[cut:] for bay in seg]
    )
    return _finish(plan, pieces, ctx)


# ---------------------------------------------------------------------------- G6
def g6_flip_finger(plan: CorridorPlan, ctx: MoveContext, rng: random.Random) -> CorridorPlan | None:
    """G6: swap a finger bay's stacks, or reverse the order inside one of its stacks."""
    pieces = _unpack(plan)
    blocks = _blocks(pieces)
    fingers = [
        (k, b)
        for k, block in enumerate(blocks)
        for b, bay in enumerate(block)
        if isinstance(bay, FingerBay)
    ]
    if not fingers:
        return None
    k, b = rng.choice(fingers)
    bay = blocks[k][b]
    assert isinstance(bay, FingerBay)
    options = ["flip"]
    options += [s for s, st in (("left", bay.left), ("right", bay.right)) if len(st) >= 2]
    choice = rng.choice(options)
    if choice == "flip":
        new = FingerBay(left=bay.right, right=bay.left, junction=bay.junction)
    elif choice == "left":
        new = FingerBay(left=bay.left[::-1], right=bay.right, junction=bay.junction)
    else:
        new = FingerBay(left=bay.left, right=bay.right[::-1], junction=bay.junction)
    blocks[k][b] = new
    return _finish(plan, pieces, ctx)


# ---------------------------------------------------------------------------- G7
def _cuts(n: int, parts: int, rng: random.Random) -> list[int]:
    """``parts - 1`` sorted cut indices in ``[0, n]``, near the even split, jittered by ±1."""
    out = []
    for j in range(1, parts):
        c = round(n * j / parts) + rng.randint(-1, 1)
        out.append(min(n, max(0, c)))
    return sorted(out)


def _chunks(seq: list[Bay], cuts: list[int]) -> list[list[Bay]]:
    bounds = [0, *cuts, len(seq)]
    return [seq[a:b] for a, b in pairwise(bounds)]


def _fix_connectors(pieces: list[_Piece], changed: int, ctx: MoveContext) -> bool:
    """Give each piece a connector that the contract accepts, preferring the current ones.

    The changed piece (and, on an L footprint, the other piece) may be re-assigned; ``False``
    when no assignment passes the piece rule and ``check_against``.
    """
    current = [p.connector for p in pieces]
    options: list[tuple[Connector, ...]] = []
    for p, piece in enumerate(pieces):
        free = p == changed or len(pieces) == 2
        if len(piece.bands) == 1:
            options.append(("none",))
        elif free:
            ordered = (current[p], *(c for c in _CONNECTORS if c != current[p]))
            options.append(ordered)
        else:
            options.append((current[p],))
    for combo in product(*options):
        if any(len(pc.bands) == 1 and c != "none" for pc, c in zip(pieces, combo, strict=True)):
            continue
        for pc, c in zip(pieces, combo, strict=True):
            pc.connector = c
        try:
            trial = _pack(pieces)
        except (ValidationError, ValueError):
            continue
        if not trial.check_against(ctx.instance_ids, ctx.footprint):
            return True
    for pc, c in zip(pieces, current, strict=True):
        pc.connector = c
    return False


def g7_split_merge(plan: CorridorPlan, ctx: MoveContext, rng: random.Random) -> CorridorPlan | None:
    """G7: split a band into two (fewer than 6 bands) or merge two adjacent bands of a piece.

    The bays of the band(s), in order (block A then block B, lower band first), are cut into
    four (split: lower A, lower B, upper A, upper B) or two (merge: A, B) contiguous chunks.
    """
    pieces = _unpack(plan)
    ops: list[tuple[str, int, int]] = []
    for p, piece in enumerate(pieces):
        n = len(piece.bands)
        if n < MAX_BANDS:
            ops += [("split", p, k) for k in range(n)]
        ops += [("merge", p, k) for k in range(n - 1)]
    op, p, k = rng.choice(ops)
    bands = pieces[p].bands
    if op == "split":
        seq = [*bands[k][0], *bands[k][1]]
        a1, b1, a2, b2 = _chunks(seq, _cuts(len(seq), 4, rng))
        bands[k : k + 1] = [[a1, b1], [a2, b2]]
    else:
        seq = [*bands[k][0], *bands[k][1], *bands[k + 1][0], *bands[k + 1][1]]
        a, b = _chunks(seq, _cuts(len(seq), 2, rng))
        bands[k : k + 2] = [[a, b]]
    if not _fix_connectors(pieces, p, ctx):
        return None
    return _finish(plan, pieces, ctx)


# ------------------------------------------------------------------------ selection
Move = Callable[[CorridorPlan, MoveContext, random.Random], CorridorPlan | None]

MOVES: dict[str, Move] = {
    "G1": g1_swap_rooms,
    "G2": g2_move_room,
    "G3": g3_swap_bays,
    "G4": g4_swap_runs,
    "G5": g5_move_run,
    "G6": g6_flip_finger,
    "G7": g7_split_merge,
}
"""The moves by name."""

MOVE_WEIGHTS: dict[str, float] = {
    "G1": 0.25,
    "G2": 0.20,
    "G3": 0.15,
    "G4": 0.10,
    "G5": 0.10,
    "G6": 0.10,
    "G7": 0.10,
}
"""Selection probabilities (RD §2)."""

_NAMES = tuple(MOVES)
_WEIGHTS = tuple(MOVE_WEIGHTS[n] for n in _NAMES)


def propose(
    plan: CorridorPlan, ctx: MoveContext, rng: random.Random
) -> tuple[str, CorridorPlan | None]:
    """Draw a move by :data:`MOVE_WEIGHTS` and apply it: ``(name, new plan or None)``."""
    name = rng.choices(_NAMES, weights=_WEIGHTS)[0]
    return name, MOVES[name](plan, ctx, rng)
