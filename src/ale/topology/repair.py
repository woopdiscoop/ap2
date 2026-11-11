"""Draft plans, capacity estimates and overflow repair moves (RD 3.2 sections 5.3-5.4).

A :class:`Draft` is a mutable corridor plan: band counts, connectors and the bays of every
block (``slot = (piece, band, block)``). Widths are *estimates* in modules at a block depth
``D``: a room bay is ``ceil(T / D)`` clipped to ``[wmin, …]`` and widened (within the area
tolerance) to reach ``aspect ≤ amax``; a finger bay is ``s`` plus, per non-empty stack,
``max(wmin, ceil(ΣT / D))``. :func:`repair_step` applies the first improving move of RD 5.4
to the block with the largest overflow; :func:`score` ranks realisations (fewer non-overflow
failures, then less overflow).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal

from ale.contracts.config import AleConfig
from ale.contracts.corridor_plan import (
    MAX_BANDS,
    BandPlan,
    BlockPlan,
    CorridorPlan,
    FingerBay,
    PiecePlan,
    RoomBay,
)
from ale.contracts.footprint import FootprintPieces
from ale.contracts.models import Rulebook
from ale.geometry import Realization
from ale.geometry.blocks import Consts, RoomReq, Solver, aspect_ok
from ale.geometry.junction import frame
from ale.geometry.realize import shared_solver
from ale.program.models import PreparedInput

__all__ = [
    "FINGER_FACTOR",
    "Bay",
    "Connector",
    "Ctx",
    "Draft",
    "Slot",
    "block_overflows",
    "form_bays",
    "repair_step",
    "score",
]

Bay = RoomBay | FingerBay
Slot = tuple[int, int, str]
Connector = Literal["none", "start", "end"]
Score = tuple[int, int]

FINGER_FACTOR = Fraction(3, 5)
"""Rooms with ``T < 0.6·D²`` go into finger-bay stacks (RD 5.3)."""

_WHERE = re.compile(r"piece (\d+) band (\d+) block ([AB])")
_OVER = re.compile(r"over by (\d+) modules")
_ROOM_INFEASIBLE = re.compile(r"^(\S+) in piece (\d+) band (\d+) block ([AB]):")
_STACK_ROOMS = re.compile(r"no compliant stack width for (.+) at depth -?\d+$")
_JUNCTION_CHILD = re.compile(r"spine of piece (\d+)")
_OTHER_FAILURE_WEIGHT = 1


@dataclass(frozen=True)
class Ctx:
    """Everything the draft operations need, computed once per :func:`seed_plan` call."""

    prepared: PreparedInput
    rulebook: Rulebook
    config: AleConfig
    k: Consts
    fp: FootprintPieces
    reqs: dict[str, RoomReq]
    zone: dict[str, str]
    order: dict[str, int]
    solver: Solver = field(compare=False, repr=False, default=None)  # type: ignore[assignment]
    """Exact room-bay / stack solver of :mod:`ale.geometry` (Q.1: depth compatibility)."""
    memo: dict[object, object] = field(default_factory=dict, compare=False, repr=False)
    """Cache of the depth-aware assignment (:mod:`ale.topology.depth`)."""

    def __post_init__(self) -> None:
        if self.solver is None:  # the realiser's shared solver: warm memos across calls
            object.__setattr__(self, "solver", shared_solver(self.k, self.reqs))

    @classmethod
    def build(
        cls, prepared: PreparedInput, rulebook: Rulebook, config: AleConfig, fp: FootprintPieces
    ) -> Ctx:
        k = Consts.from_config(config)
        return cls(
            prepared=prepared,
            rulebook=rulebook,
            config=config,
            k=k,
            fp=fp,
            reqs={iid: k.req(spec) for iid, spec in prepared.instances},
            zone={iid: str(spec.macro_zone) for iid, spec in prepared.instances},
            order={iid: i for i, (iid, _) in enumerate(prepared.instances)},
        )

    # ------------------------------------------------------------------ depth rules (Q.1)
    def bay_ok(self, room: str, depth: int) -> bool:
        """Whether ``room`` can be a compliant room bay at block depth ``depth``."""
        return depth > 0 and self.solver.room_bay_width(self.reqs[room], depth) is not None

    def exact_room_width(self, room: str, depth: int) -> int | None:
        """Compliant room-bay width of ``room`` at ``depth`` (``None``: infeasible)."""
        if depth <= 0:
            return None
        return self.solver.room_bay_width(self.reqs[room], depth)

    def exact_stack_width(self, rooms: Sequence[str], depth: int) -> int | None:
        """Compliant stack width of ``rooms`` (spine outward) at ``depth`` (``None``:
        infeasible); ``0`` for an empty stack."""
        if not rooms:
            return 0
        if depth <= 0:
            return None
        sol = self.solver.stack(tuple(self.reqs[r] for r in rooms), depth)
        return None if sol is None else sol.w

    def exact_bay_width(self, bay: Bay, depth: int) -> int | None:
        """Compliant width of ``bay`` at ``depth`` (``None`` when a room cannot comply)."""
        if isinstance(bay, RoomBay):
            return self.exact_room_width(bay.room, depth)
        left = self.exact_stack_width(bay.left, depth)
        right = self.exact_stack_width(bay.right, depth)
        if left is None or right is None:
            return None
        return left + self.k.s + right

    # ------------------------------------------------------------------ widths
    def small(self, room: str, depth: Fraction) -> bool:
        """Whether ``room`` belongs in a finger stack at block depth ``depth``."""
        return self.reqs[room].target < FINGER_FACTOR * depth * depth

    def room_width(self, room: str, depth: Fraction) -> int:
        req = self.reqs[room]
        d = max(1, math.floor(depth))
        w_up = max(req.wmin, math.ceil(req.target / d))
        for w in range(w_up, max(w_up, req.hi // d) + 1):
            if aspect_ok(w, d, self.k.amax):
                return w
        return w_up

    def stack_width(self, rooms: Sequence[str], depth: Fraction) -> int:
        if not rooms:
            return 0
        d = max(Fraction(1), depth)
        total = sum((self.reqs[r].target for r in rooms), Fraction(0))
        return max(max(self.reqs[r].wmin for r in rooms), math.ceil(total / d))

    def bay_width(self, bay: Bay, depth: Fraction) -> int:
        if isinstance(bay, RoomBay):
            return self.room_width(bay.room, depth)
        return self.stack_width(bay.left, depth) + self.k.s + self.stack_width(bay.right, depth)

    def block_width(self, bays: Sequence[Bay], depth: Fraction) -> int:
        return sum(self.bay_width(b, depth) for b in bays)


def bay_rooms(bay: Bay) -> tuple[str, ...]:
    return (bay.room,) if isinstance(bay, RoomBay) else (*bay.left, *bay.right)


def form_bays(ctx: Ctx, rooms: Sequence[str], depth: Fraction) -> list[Bay]:
    """Bays of a block holding ``rooms`` (in order) at estimated depth ``depth``.

    Rooms are grouped by zone (zones in order of first appearance, so each zone is one
    run); big rooms become room bays; small rooms of a zone are grouped four at a time into
    finger bays (two per stack, left first) placed at their first room's position.
    """
    zones: list[str] = []
    for r in rooms:
        if ctx.zone[r] not in zones:
            zones.append(ctx.zone[r])
    out: list[Bay] = []
    for zone in zones:
        groups: list[list[str]] = []
        seq: list[str | int] = []  # room id → room bay; int → finger group index
        for r in (r for r in rooms if ctx.zone[r] == zone):
            if not ctx.small(r, depth):
                seq.append(r)
                continue
            if not groups or len(groups[-1]) >= 4:
                groups.append([])
                seq.append(len(groups) - 1)
            groups[-1].append(r)
        for item in seq:
            if isinstance(item, str):
                out.append(RoomBay(room=item))
                continue
            g = groups[item]
            if len(g) == 1:
                out.append(RoomBay(room=g[0]))
            else:
                half = (len(g) + 1) // 2
                out.append(FingerBay(left=tuple(g[:half]), right=tuple(g[half:])))
    return out


@dataclass
class Draft:
    """A mutable corridor plan."""

    counts: list[int]
    connectors: list[Connector]
    blocks: dict[Slot, list[Bay]] = field(default_factory=dict)
    depths: dict[Slot, int] = field(default_factory=dict)
    """Target block depths chosen by the depth-aware assignment (Q.1 §4); empty = unknown."""
    estimate: tuple[int, int] = (0, 0)
    """``(non-compliant rooms, overflow)`` the assignment expects at its target depths."""

    def copy(self) -> Draft:
        return Draft(
            list(self.counts),
            list(self.connectors),
            {slot: list(bays) for slot, bays in self.blocks.items()},
            dict(self.depths),
            self.estimate,
        )

    def slots(self) -> list[Slot]:
        return [
            (p, k, side) for p, n in enumerate(self.counts) for k in range(n) for side in ("A", "B")
        ]

    def to_plan(self) -> CorridorPlan:
        def block(p: int, k: int, side: str) -> BlockPlan:
            return BlockPlan(bays=tuple(self.blocks.get((p, k, side), [])))

        return CorridorPlan(
            pieces=tuple(
                PiecePlan(
                    bands=tuple(
                        BandPlan(block_a=block(p, k, "A"), block_b=block(p, k, "B"))
                        for k in range(n)
                    ),
                    connector=self.connectors[p],
                )
                for p, n in enumerate(self.counts)
            )
        )

    def find(self, room: str) -> tuple[Slot, int]:
        """``(slot, bay index)`` of ``room``; ``KeyError`` if absent."""
        for slot, bays in self.blocks.items():
            for i, bay in enumerate(bays):
                if room in bay_rooms(bay):
                    return slot, i
        raise KeyError(room)


# ---------------------------------------------------------------------- geometry estimates
def band_depths(ctx: Ctx, p: int, n: int) -> list[int]:
    """Equal split of piece ``p``'s depth into ``n`` bands (remainder to the last)."""
    depth = frame(ctx.fp.pieces[p])[1]
    out = [depth // n] * n
    out[-1] += depth - n * (depth // n)
    return out


def usable_length(ctx: Ctx, draft: Draft, p: int) -> int:
    length = frame(ctx.fp.pieces[p])[0]
    return length if draft.connectors[p] == "none" else length - ctx.k.s


def block_depths(ctx: Ctx, draft: Draft, real: Realization | None = None) -> dict[Slot, Fraction]:
    """Block depths: the realised ones when ``real`` reports one per band, else equal split."""
    s = ctx.k.s
    out: dict[Slot, Fraction] = {}
    n_bands = sum(draft.counts)
    if real is not None and len(real.depths) == n_bands:
        i = 0
        for p, n in enumerate(draft.counts):
            for k in range(n):
                d_a, d_b = real.depths[i]
                i += 1
                out[(p, k, "A")] = Fraction(max(1, d_a))
                out[(p, k, "B")] = Fraction(max(1, d_b))
        return out
    if draft.depths and all(slot in draft.depths for slot in draft.slots()):
        return {slot: Fraction(max(1, draft.depths[slot])) for slot in draft.slots()}
    for p, n in enumerate(draft.counts):
        for k, d in enumerate(band_depths(ctx, p, n)):
            half = Fraction(max(1, d - s), 2)
            out[(p, k, "A")] = half
            out[(p, k, "B")] = half
    return out


def slack(ctx: Ctx, draft: Draft, depths: dict[Slot, Fraction]) -> dict[Slot, int]:
    """Estimated free length per block (negative = estimated overflow)."""
    return {
        slot: usable_length(ctx, draft, slot[0])
        - ctx.block_width(draft.blocks.get(slot, []), depths[slot])
        for slot in draft.slots()
    }


# ---------------------------------------------------------------------- failures
def score(real: Realization) -> Score:
    """``(non-overflow failures, total overflow modules)``; ``(0, 0)`` = valid."""
    over = 0
    other = 0
    for f in real.failures:
        m = _OVER.search(f.detail) if f.code == "PLAN_OVERFLOW" else None
        if m is None:
            other += _OTHER_FAILURE_WEIGHT
        else:
            over += int(m.group(1))
    return other, over


def block_overflows(real: Realization) -> dict[Slot, int]:
    """Overflow modules per block (``PLAN_OVERFLOW``); other block-located failures count as
    overflow 0 so that they still name a block to repair."""
    out: dict[Slot, int] = {}
    for f in real.failures:
        w = _WHERE.search(f.detail)
        if w is None:
            continue
        slot: Slot = (int(w.group(1)), int(w.group(2)), w.group(3))
        m = _OVER.search(f.detail) if f.code == "PLAN_OVERFLOW" else None
        out[slot] = out.get(slot, 0) + (int(m.group(1)) if m else 0)
    return out


# ---------------------------------------------------------------------- moves
def _remove(bays: list[Bay], room: str) -> None:
    for i, bay in enumerate(bays):
        if isinstance(bay, RoomBay):
            if bay.room == room:
                del bays[i]
                return
            continue
        if room in bay.left or room in bay.right:
            left = tuple(r for r in bay.left if r != room)
            right = tuple(r for r in bay.right if r != room)
            if not left and not right and not bay.junction:
                del bays[i]
            elif not bay.junction and len(left) + len(right) == 1:
                bays[i] = RoomBay(room=(*left, *right)[0])
            else:
                bays[i] = bay.with_rooms(left, right)
            return


def _insert(ctx: Ctx, bays: list[Bay], room: str, depth: Fraction) -> None:
    """Insert ``room`` beside its zone in ``bays`` (into a same-zone finger stack with room
    for it when the room is small, else as a room bay after the zone's last bay)."""
    zone = ctx.zone[room]
    if ctx.small(room, depth):
        for i, bay in enumerate(bays):
            if isinstance(bay, FingerBay) and not bay.junction:
                if ctx.zone[bay_rooms(bay)[0]] != zone:
                    continue
                if len(bay.left) <= len(bay.right) and len(bay.left) < 2:
                    bays[i] = FingerBay(left=(*bay.left, room), right=bay.right)
                    return
                if len(bay.right) < 2:
                    bays[i] = FingerBay(left=bay.left, right=(*bay.right, room))
                    return
    last = -1
    for i, bay in enumerate(bays):
        rooms = bay_rooms(bay)
        if rooms and ctx.zone[rooms[0]] == zone:
            last = i
    bays.insert(last + 1 if last >= 0 else len(bays), RoomBay(room=room))


def move_room(ctx: Ctx, draft: Draft, room: str, dst: Slot, depth: Fraction) -> Draft:
    out = draft.copy()
    src, _ = out.find(room)
    _remove(out.blocks[src], room)
    _insert(ctx, out.blocks.setdefault(dst, []), room, depth)
    return out


def _move_smallest(
    ctx: Ctx, draft: Draft, slot: Slot, depths: dict[Slot, Fraction]
) -> Draft | None:
    """(a) the block's smallest room → the block with the most slack (same zone first)."""
    rooms = [r for b in draft.blocks.get(slot, []) for r in bay_rooms(b)]
    if not rooms:
        return None
    room = min(rooms, key=lambda r: (ctx.reqs[r].target, ctx.order[r]))
    free = slack(ctx, draft, depths)
    zone = ctx.zone[room]

    def has_zone(s: Slot) -> bool:
        return any(ctx.zone[r] == zone for b in draft.blocks.get(s, []) for r in bay_rooms(b))

    candidates = [s for s in draft.slots() if s != slot and depths[s] >= ctx.k.c]
    if not candidates:
        return None
    need = {s: ctx.room_width(room, depths[s]) for s in candidates}
    dst = max(
        candidates,
        key=lambda s: (free[s] >= need[s], has_zone(s), free[s], [-x for x in _key(s)]),
    )
    return move_room(ctx, draft, room, dst, depths[dst])


def _key(slot: Slot) -> tuple[int, int, int]:
    return slot[0], slot[1], 0 if slot[2] == "A" else 1


def _merge_small(ctx: Ctx, draft: Draft, slot: Slot, depth: Fraction) -> Draft | None:
    """(b) the two smallest room bays of one zone → one finger bay (one stack if deep
    enough for two rooms, else one room per stack)."""
    bays = draft.blocks.get(slot, [])
    singles = [(i, b.room) for i, b in enumerate(bays) if isinstance(b, RoomBay)]
    best: tuple[Fraction, int, int] | None = None
    for x in range(len(singles)):
        for y in range(x + 1, len(singles)):
            (i, a), (j, b) = singles[x], singles[y]
            if ctx.zone[a] != ctx.zone[b]:
                continue
            total = ctx.reqs[a].target + ctx.reqs[b].target
            if best is None or total < best[0]:
                best = (total, i, j)
    if best is None:
        return None
    _, i, j = best
    a, b = bays[i].room, bays[j].room  # type: ignore[union-attr]
    pair = (a, b)
    merged = FingerBay(left=pair) if depth >= 2 * ctx.k.c else FingerBay(left=(a,), right=(b,))
    out = draft.copy()
    new = out.blocks[slot]
    new[i] = merged
    del new[j]
    return out


def _rebalance_stack(draft: Draft, slot: Slot) -> Draft | None:
    """(c) in the finger bay with the most unequal stacks, move the outermost room of the
    longer stack to the other stack."""
    bays = draft.blocks.get(slot, [])
    best: tuple[int, int] | None = None
    for i, bay in enumerate(bays):
        if isinstance(bay, FingerBay) and not bay.junction:
            gap = abs(len(bay.left) - len(bay.right))
            if gap >= 1 and len(bay.left) + len(bay.right) >= 2 and (best is None or gap > best[0]):
                best = (gap, i)
    if best is None:
        return None
    bay = bays[best[1]]
    assert isinstance(bay, FingerBay)
    if len(bay.left) > len(bay.right):
        new = FingerBay(left=bay.left[:-1], right=(*bay.right, bay.left[-1]))
    else:
        new = FingerBay(left=(*bay.left, bay.right[-1]), right=bay.right[:-1])
    out = draft.copy()
    out.blocks[slot][best[1]] = new
    return out


def _shift_junction(draft: Draft, step: int, child: int | None = None) -> Draft | None:
    """Move the J1 junction finger (to ``child`` when given) ``step`` bays along its block."""
    for slot, bays in draft.blocks.items():
        for i, bay in enumerate(bays):
            if isinstance(bay, FingerBay) and bay.junction:
                if child is not None and bay.junction_to != child:
                    continue
                j = i + step
                if not 0 <= j < len(bays):
                    return None
                out = draft.copy()
                new = out.blocks[slot]
                new.insert(j, new.pop(i))
                return out
    return None


# ---------------------------------------------------------------------- Q.1 moves
def infeasible_rooms(real: Realization) -> list[str]:
    """Rooms named by ``ROOM_INFEASIBLE`` failures, then the outermost room of every
    ``STACK_INFEASIBLE`` stack (in failure order, without duplicates)."""
    out: list[str] = []
    for f in real.failures:
        room: str | None = None
        if f.code == "ROOM_INFEASIBLE":
            m = _ROOM_INFEASIBLE.search(f.detail)
            room = m.group(1) if m else None
        elif f.code == "STACK_INFEASIBLE":
            m = _STACK_ROOMS.search(f.detail)
            room = m.group(1).split(", ")[-1] if m else None
        if room is not None and room not in out:
            out.append(room)
    return out


def _insert_bay(ctx: Ctx, bays: list[Bay], bay: Bay, zone: str) -> None:
    """Insert ``bay`` after the last bay of ``zone`` (or at the end)."""
    last = -1
    for i, b in enumerate(bays):
        rooms = bay_rooms(b)
        if rooms and ctx.zone[rooms[0]] == zone:
            last = i
    bays.insert(last + 1 if last >= 0 else len(bays), bay)


def move_to_compatible(
    ctx: Ctx, draft: Draft, room: str, depths: dict[Slot, Fraction]
) -> Draft | None:
    """(e) move ``room`` as a room bay to the block with the most slack whose depth lies in
    its compliant depth interval."""
    try:
        src, _ = draft.find(room)
    except KeyError:
        return None
    free = slack(ctx, draft, depths)
    cands = [sl for sl in draft.slots() if sl != src and ctx.bay_ok(room, math.floor(depths[sl]))]
    if not cands:
        return None
    dst = max(cands, key=lambda sl: (free[sl], [-x for x in _key(sl)]))
    out = draft.copy()
    _remove(out.blocks[src], room)
    _insert_bay(ctx, out.blocks.setdefault(dst, []), RoomBay(room=room), ctx.zone[room])
    return out


def move_to_stack(ctx: Ctx, draft: Draft, room: str, depths: dict[Slot, Fraction]) -> Draft | None:
    """(f) put ``room`` into a compliant stack: a same-zone finger of its own block (or, if
    none fits, of the block with the most slack where it can be stacked), else a new finger
    bay holding it alone."""
    try:
        src, _ = draft.find(room)
    except KeyError:
        return None
    free = slack(ctx, draft, depths)
    others = sorted((sl for sl in draft.slots() if sl != src), key=lambda sl: (-free[sl], _key(sl)))
    order = [src, *others]
    zone = ctx.zone[room]
    for sl in order:
        d = math.floor(depths[sl])
        if ctx.exact_stack_width([room], d) is None:
            continue
        out = draft.copy()
        _remove(out.blocks[src], room)
        bays = out.blocks.setdefault(sl, [])
        for i, bay in enumerate(bays):
            if not isinstance(bay, FingerBay) or bay.junction:
                continue
            rooms = bay_rooms(bay)
            if not rooms or ctx.zone[rooms[0]] != zone:
                continue
            if ctx.exact_stack_width([*bay.left, room], d) is not None:
                bays[i] = FingerBay(left=(*bay.left, room), right=bay.right)
                return out
            if ctx.exact_stack_width([*bay.right, room], d) is not None:
                bays[i] = FingerBay(left=bay.left, right=(*bay.right, room))
                return out
        _insert_bay(ctx, bays, FingerBay(left=(room,)), zone)
        return out
    return None


Resplit = Callable[[Draft, Slot, str], Draft | None]
"""(g) re-assign with the depth split of a band changed so that a room fits its block."""

Repack = Callable[[Draft, Realization], Draft | None]
"""Re-assign the rooms with every band's split fixed to the realised one (Q.1 (g))."""

Realise = Callable[[Draft], Realization]
Reassign = Callable[[list[int]], Draft | None]


def band_moves(draft: Draft, p: int, allowed: Sequence[int]) -> list[list[int]]:
    """(d) band counts of piece ``p`` changed by -1 then +1, within ``allowed``."""
    out: list[list[int]] = []
    for delta in (-1, 1):
        n = draft.counts[p] + delta
        if 1 <= n <= MAX_BANDS and n in allowed:
            counts = list(draft.counts)
            counts[p] = n
            out.append(counts)
    return out


def repair_step(
    ctx: Ctx,
    draft: Draft,
    real: Realization,
    realise: Realise,
    reassign: Reassign,
    allowed: Sequence[Sequence[int]],
    tick: Callable[[], bool],
    resplit: Resplit | None = None,
    repack: Repack | None = None,
) -> tuple[Draft, Realization] | None:
    """One repair step (RD 5.4 + Q.1 §4): the first move that lowers :func:`score`, or
    ``None``. Rooms of ``ROOM_INFEASIBLE`` / ``STACK_INFEASIBLE`` failures are tried first
    with (e) :func:`move_to_compatible`, (f) :func:`move_to_stack` and (g) ``resplit``.

    ``realise`` realises a draft, ``reassign`` rebuilds a draft for new band counts,
    ``allowed[p]`` lists the band counts piece ``p`` may take, ``tick`` is the budget (one
    call per realisation; ``False`` stops).
    """
    current = score(real)
    over = block_overflows(real)
    depths = block_depths(ctx, draft, real)
    junction_failure = any(f.code == "JUNCTION_MISALIGNED" for f in real.failures)
    candidates: list[Callable[[], Draft | None]] = []
    if junction_failure:
        found = sorted(
            {int(m.group(1)) for f in real.failures if (m := _JUNCTION_CHILD.search(f.detail))}
        )
        kids: list[int | None] = [*found] if found else [None]
        for c in kids:
            candidates += [
                lambda c=c: _shift_junction(draft, 1, c),  # type: ignore[misc]
                lambda c=c: _shift_junction(draft, -1, c),  # type: ignore[misc]
            ]
    if repack is not None:
        candidates.append(lambda: repack(draft, real))
    for room in infeasible_rooms(real)[:3]:  # Q.1 moves (e) (f) (g)
        candidates += [
            lambda r=room: move_to_compatible(ctx, draft, r, depths),  # type: ignore[misc]
            lambda r=room: move_to_stack(ctx, draft, r, depths),  # type: ignore[misc]
        ]
        if resplit is not None:
            try:
                slot, _ = draft.find(room)
            except KeyError:  # pragma: no cover - realised rooms are in the draft
                continue
            candidates.append(lambda sl=slot, r=room: resplit(draft, sl, r))  # type: ignore[misc]
    worst: Slot | None = None
    if over:
        worst = max(over, key=lambda s: (over[s], [-x for x in _key(s)]))
    if worst is not None and worst in depths:
        w = worst
        candidates += [
            lambda: _move_smallest(ctx, draft, w, depths),
            lambda: _merge_small(ctx, draft, w, depths[w]),
            lambda: _rebalance_stack(draft, w),
        ]
    pieces = [worst[0]] if worst is not None else list(range(len(draft.counts)))
    for p in pieces:
        for counts in band_moves(draft, p, allowed[p]):
            candidates.append(lambda c=counts: reassign(c))  # type: ignore[misc]
    for make in candidates:
        cand = make()
        if cand is None:
            continue
        if not tick():
            return None
        got = realise(cand)
        if score(got) < current:
            return cand, got
    return None
