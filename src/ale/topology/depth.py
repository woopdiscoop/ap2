"""Depth-interval-aware assignment of rooms to blocks (Ticket Q.1 §4).

Realisation only emits compliant rooms (area rule, ``aspect <= amax``, ``wmin``), so the
room bays of one block must share a depth inside every one of their compliant depth
intervals. This module chooses target block depths first and fills the blocks second:

1. **Depth sets**: for every room, the block depths at which it can be a room bay (exact,
   with the :class:`ale.geometry.blocks.Solver` the realiser uses), and whether it can be a
   stack room at a depth.
2. **Depth groups**: rooms sorted by ``dmin``; a new group opens when the running
   intersection of intervals empties. Group depths become candidate block depths.
3. **Band splits**: band depths are the realiser's start (equal split of the piece); each
   band's ``D_A`` is chosen among the candidates by coordinate descent on the packing score
   ``(rooms without a compatible block, estimated overflow, path distance)``.
4. **Packing**: every room goes to the compatible block nearest to its position on the
   serpentine path (room bay if its interval holds the block depth, else a finger-bay
   stack), then rooms leave over-full blocks for the cheapest compatible block with room.
5. **Bays**: per block, zone runs in path order; stack rooms are packed into finger bays
   (stacks checked exactly); a last exact pass moves rooms out of blocks that still overflow.

All loops are bounded by the number of rooms, blocks and candidates.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import cast

from ale.contracts.corridor_plan import FingerBay, RoomBay
from ale.topology.repair import Bay, Ctx, Slot

__all__ = [
    "DEADLINE_KEY",
    "BandSpec",
    "depth_groups",
    "fill_blocks",
    "form_depth_bays",
    "room_depths",
]

_STACK_PENALTY_M = 3.0
"""Extra path distance (metres) charged for putting a room in a stack instead of a bay."""
_FACADE_PENALTY_M = 60.0
"""Extra path distance (metres) charged for a ``needs_facade`` room in an inner block."""
_DESCENT_PASSES = 3
_MEMO_MAX = 200_000
"""The assignment memo is cleared beyond this many entries (bounded memory)."""
_EXACT_FINALISTS = 4
_EXACT_DESCENT = True
"""Rank band splits by the exact overflow of the formed blocks (the estimate misleads)."""
"""Band splits finished with the exact pass (best packing keys first)."""
_MAX_STACK = 3
"""Rooms per stack (one side of a finger bay) tried by :func:`form_depth_bays`."""


@dataclass(frozen=True)
class BandSpec:
    """A band of piece ``p``: index ``k`` and inner depth ``inner = P_b - s``."""

    p: int
    k: int
    inner: int


def room_depths(ctx: Ctx, room: str, max_depth: int) -> tuple[int, ...]:
    """Depths in ``[1, max_depth]`` at which ``room`` is a compliant room bay."""
    key = ("depths", room, max_depth)
    memo = _memo(ctx)
    hit = memo.get(key)
    if hit is None:
        hit = tuple(d for d in range(1, max_depth + 1) if ctx.bay_ok(room, d))
        memo[key] = hit
    return hit  # type: ignore[return-value]


def depth_groups(ctx: Ctx, rooms: Sequence[str], max_depth: int) -> list[tuple[int, int]]:
    """Greedy clustering of the rooms' depth intervals (sorted by ``dmin``)."""
    spans = []
    for r in rooms:
        ds = room_depths(ctx, r, max_depth)
        if ds:
            spans.append((ds[0], ds[-1]))
    spans.sort()
    groups: list[tuple[int, int]] = []
    for lo, hi in spans:
        if groups and max(groups[-1][0], lo) <= min(groups[-1][1], hi):
            glo, ghi = groups[-1]
            groups[-1] = (max(glo, lo), min(ghi, hi))
        else:
            groups.append((lo, hi))
    return groups


def _memo(ctx: Ctx) -> dict[object, object]:
    return ctx.memo


DEADLINE_KEY = "deadline"
"""``ctx.memo[DEADLINE_KEY]``: ``time.monotonic()`` after which the assignment cuts its
searches short (set by :func:`ale.topology.seed.seed_plan` from its time budget)."""


def _late(ctx: Ctx) -> bool:
    deadline = ctx.memo.get(DEADLINE_KEY)
    return isinstance(deadline, float) and time.monotonic() > deadline


def _option(ctx: Ctx, room: str, depth: int) -> tuple[float, bool] | None:
    """Estimated length share of ``room`` in a block of ``depth`` and whether it is a stack
    room; ``None`` when it fits neither way."""
    key = ("opt", room, depth)
    memo = _memo(ctx)
    if key in memo:
        return memo[key]  # type: ignore[return-value]
    out: tuple[float, bool] | None = None
    w = ctx.exact_room_width(room, depth)
    if w is not None:
        out = (float(w), False)
    else:
        w1 = ctx.exact_stack_width([room], depth)
        if w1 is not None:
            levels = 2 if ctx.exact_stack_width([room, room], depth) is not None else 1
            out = (w1 / levels + ctx.k.s / (2 * levels), True)
    memo[key] = out
    return out


@dataclass
class _Packing:
    members: dict[Slot, list[str]]
    stacked: set[str]
    key: tuple[int, int, float]
    formed: dict[Slot, list[Bay]]
    width: dict[Slot, int]
    alt: _Packing | None = None
    """The capacity-first packing of the same depths, when it was computed."""


def _sibling(sl: Slot) -> Slot:
    return (sl[0], sl[1], "B" if sl[2] == "A" else "A")


def _effective(depths: Mapping[Slot, int], members: Mapping[Slot, Sequence[str]], sl: Slot) -> int:
    """Depth the realiser gives ``sl``: 0 when empty, the whole band inner depth when its
    sibling block is empty, else the target."""
    sib = _sibling(sl)
    if not members[sl]:
        return 0
    if not members[sib]:
        return depths[sl] + depths[sib]
    return depths[sl]


def _form(
    ctx: Ctx,
    members: Mapping[Slot, Sequence[str]],
    stacked: set[str],
    depths: Mapping[Slot, int],
    ppos: Mapping[str, float],
    sl: Slot,
) -> tuple[list[Bay], int, int]:
    """``(bays, exact width, bays that cannot comply)`` of block ``sl``."""
    rs = sorted(members[sl], key=lambda r: (ppos[r], ctx.order[r]))
    if sl[2] == "B":
        rs = rs[::-1]
    depth = _effective(depths, members, sl)
    if not rs:
        return [], 0, 0
    key = ("form", tuple(rs), frozenset(r for r in rs if r in stacked), depth)
    memo = _memo(ctx)
    hit = memo.get(key)
    if hit is not None:
        cached = cast("tuple[tuple[Bay, ...], int, int]", hit)
        return list(cached[0]), cached[1], cached[2]
    bays = form_depth_bays(ctx, rs, stacked, depth)
    width = 0
    bad = 0
    for bay in bays:
        w = ctx.exact_bay_width(bay, depth)
        if w is None:
            bad += 1
            w = ctx.bay_width(bay, Fraction(max(1, depth)))
        width += w
    if len(memo) >= _MEMO_MAX:
        deadline = memo.get(DEADLINE_KEY)
        memo.clear()
        if deadline is not None:
            memo[DEADLINE_KEY] = deadline
    memo[key] = (tuple(bays), width, bad)
    return bays, width, bad


def _pack(
    ctx: Ctx,
    depths: Mapping[Slot, int],
    slots: Sequence[Slot],
    caps: Mapping[Slot, int],
    ppos: Mapping[str, float],
    centers: Mapping[Slot, float],
    penalty: Mapping[tuple[str, Slot], float],
    exact: bool = True,
) -> _Packing:
    """Pack the rooms at ``depths`` (module docstring, step 4). With ``exact`` the blocks
    are formed and the key holds the exact overflow; without, the estimated one (fast)."""
    rooms = sorted(ppos, key=lambda r: (ppos[r], ctx.order[r]))
    opts: dict[str, dict[Slot, tuple[float, bool]]] = {}
    for r in rooms:
        opts[r] = {}
        for sl in slots:
            o = _option(ctx, r, depths[sl])
            if o is not None:
                opts[r][sl] = o

    def cost(r: str, sl: Slot) -> float:
        extra = _STACK_PENALTY_M if opts[r][sl][1] else 0.0
        return abs(centers[sl] - ppos[r]) + extra + penalty.get((r, sl), 0.0)

    where: dict[str, Slot] = {}
    load = {sl: 0.0 for sl in slots}
    bad = 0
    homeless: dict[str, Slot] = {}  # no compatible block: deepest block (realise reports it)
    for r in rooms:
        if not opts[r]:
            bad += 1
            homeless[r] = max(slots, key=lambda t: (depths[t], -slots.index(t)))
            continue
        sl = min(opts[r], key=lambda t: (cost(r, t), slots.index(t)))
        where[r] = sl
        load[sl] += opts[r][sl][0]
    for _ in range(len(rooms) * len(slots)):
        over = [sl for sl in slots if load[sl] > caps[sl]]
        if not over:
            break
        src = max(over, key=lambda t: (load[t] - caps[t], -slots.index(t)))
        best: tuple[float, str, Slot] | None = None
        for r in (r for r in rooms if where.get(r) == src):
            for t, (share, _) in opts[r].items():
                if t == src or load[t] + share > caps[t]:
                    continue
                delta = cost(r, t) - cost(r, src)
                if best is None or delta < best[0]:
                    best = (delta, r, t)
        if best is None:
            break
        _, r, t = best
        load[src] -= opts[r][src][0]
        load[t] += opts[r][t][0]
        where[r] = t

    def packing(where: Mapping[str, Slot]) -> _Packing:
        members: dict[Slot, list[str]] = {sl: [] for sl in slots}
        for r in rooms:
            if r in where:
                members[where[r]].append(r)
            elif r in homeless:
                members[homeless[r]].append(r)
        dist = sum(cost(r, sl) for r, sl in where.items())
        stacked = {r for r, sl in where.items() if opts[r][sl][1]}
        formed: dict[Slot, list[Bay]] = {}
        width: dict[Slot, int] = {}
        n_bad = bad
        if not exact:
            used = {sl: 0.0 for sl in slots}
            for r, sl in where.items():
                used[sl] += opts[r][sl][0]
            est = sum(max(0.0, used[sl] - caps[sl]) for sl in slots)
            return _Packing(members, stacked, (n_bad, math.ceil(est), dist), formed, width)
        for sl in slots:
            formed[sl], width[sl], b = _form(ctx, members, stacked, depths, ppos, sl)
            n_bad += b
        overflow = sum(max(0, width[sl] - caps[sl]) for sl in slots)
        return _Packing(members, stacked, (n_bad, overflow, dist), formed, width)

    near = packing(where)
    if near.key[1] == 0:
        return near
    # Capacity first: hardest rooms (fewest compatible blocks, widest) into the block with
    # the most room left, avoiding facade penalties when it fits.
    fill: dict[str, Slot] = {}
    left = {sl: float(caps[sl]) for sl in slots}
    order = sorted(
        (r for r in rooms if opts[r]),
        key=lambda r: (len(opts[r]), -max(o[0] for o in opts[r].values()), ctx.order[r]),
    )
    for r in order:
        sl = min(
            opts[r],
            key=lambda t: (
                left[t] < opts[r][t][0],
                penalty.get((r, t), 0.0),
                -(left[t] - opts[r][t][0]),
                slots.index(t),
            ),
        )
        fill[r] = sl
        left[sl] -= opts[r][sl][0]
    packed = packing(fill)
    first, second = (packed, near) if packed.key < near.key else (near, packed)
    first.alt = second
    return first


def form_depth_bays(ctx: Ctx, rooms: Sequence[str], stacked: set[str], depth: int) -> list[Bay]:
    """Bays of a block at ``depth``: zone runs (zones in order of first appearance); rooms
    in ``stacked`` (or that cannot be room bays) go into finger-bay stacks, each stack
    holding as many consecutive rooms as stay compliant (at most :data:`_MAX_STACK`)."""
    zones: list[str] = []
    for r in rooms:
        if ctx.zone[r] not in zones:
            zones.append(ctx.zone[r])
    out: list[Bay] = []
    for zone in zones:
        left: list[str] = []
        right: list[str] = []
        finger_at = -1
        for r in (r for r in rooms if ctx.zone[r] == zone):
            if r not in stacked and ctx.bay_ok(r, depth):
                out.append(RoomBay(room=r))
                continue
            if finger_at >= 0 and len(left) < _MAX_STACK and _stack_fits(ctx, [*left, r], depth):
                left.append(r)
            elif (
                finger_at >= 0 and len(right) < _MAX_STACK and _stack_fits(ctx, [*right, r], depth)
            ):
                right.append(r)
            else:
                if finger_at >= 0:
                    out[finger_at] = FingerBay(left=tuple(left), right=tuple(right))
                left, right = [r], []
                finger_at = len(out)
                out.append(FingerBay(left=(r,)))
        if finger_at >= 0:
            out[finger_at] = FingerBay(left=tuple(left), right=tuple(right))
    return out


def _stack_fits(ctx: Ctx, rooms: Sequence[str], depth: int) -> bool:
    return ctx.exact_stack_width(rooms, depth) is not None


def _candidates(groups: Sequence[tuple[int, int]], inner: int, c: int) -> list[int]:
    """``D_A`` candidates of a band of inner depth ``inner``: the even split and, for every
    depth group, its bounds and middle on either side."""
    half = inner // 2
    if inner < 2 * c:
        return [half]
    vals = {half}
    for lo, hi in groups:
        for d in (lo, hi, (lo + hi) // 2):
            vals.add(d)
            vals.add(inner - d)
    return sorted(v for v in vals if c <= v <= inner - c)


def fill_blocks(
    ctx: Ctx,
    bands: Sequence[BandSpec],
    slots: Sequence[Slot],
    caps: Mapping[Slot, int],
    ppos: Mapping[str, float],
    centers: Mapping[Slot, float],
    fixed: Mapping[tuple[int, int], int] | None = None,
    facade: Mapping[str, bool] | None = None,
    outer: frozenset[Slot] = frozenset(),
) -> tuple[dict[Slot, int], dict[Slot, list[Bay]], tuple[int, int]]:
    """Target depths and bays of every block (module docstring, steps 2-5).

    ``slots`` are the blocks in serpentine order, ``caps`` their usable lengths, ``ppos``
    the rooms' positions along the path and ``centers`` the blocks' (metres). ``fixed``
    forces ``D_A`` of the bands ``(piece, band)`` it names (repair move (g)). Rooms with
    ``facade[room]`` are steered to the ``outer`` blocks (those along the exterior).
    The third item is the estimate ``(rooms or bays that cannot comply, exact overflow)``.
    """
    fixed = fixed or {}
    penalty = {
        (r, sl): _FACADE_PENALTY_M
        for r, needs in (facade or {}).items()
        if needs
        for sl in slots
        if sl not in outer
    }
    c = ctx.k.c
    max_depth = max((b.inner for b in bands), default=1)
    groups = depth_groups(ctx, list(ppos), max_depth)
    split = {(b.p, b.k): fixed.get((b.p, b.k), b.inner // 2) for b in bands}

    def depths_of(sp: Mapping[tuple[int, int], int]) -> dict[Slot, int]:
        out: dict[Slot, int] = {}
        for b in bands:
            out[(b.p, b.k, "A")] = sp[(b.p, b.k)]
            out[(b.p, b.k, "B")] = b.inner - sp[(b.p, b.k)]
        return out

    best = _pack(ctx, depths_of(split), slots, caps, ppos, centers, penalty, exact=_EXACT_DESCENT)
    seen: dict[tuple[tuple[tuple[int, int], int], ...], _Packing] = {
        tuple(sorted(split.items())): best
    }
    for _ in range(_DESCENT_PASSES):
        improved = False
        for b in bands:
            if (b.p, b.k) in fixed or _late(ctx):
                continue
            for d_a in _candidates(groups, b.inner, c):
                if d_a == split[(b.p, b.k)]:
                    continue
                trial = dict(split)
                trial[(b.p, b.k)] = d_a
                key = tuple(sorted(trial.items()))
                got = seen.get(key)
                if got is None:
                    got = _pack(
                        ctx,
                        depths_of(trial),
                        slots,
                        caps,
                        ppos,
                        centers,
                        penalty,
                        exact=_EXACT_DESCENT,
                    )
                    seen[key] = got
                if got.key < best.key:
                    best, split, improved = got, trial, True
        if not improved:
            break
    # The packing keys are taken before the exact pass: finish the most promising splits
    # (both packings each) and keep the best expected result.
    ranked = sorted(seen.items(), key=lambda kv: kv[1].key)[:_EXACT_FINALISTS]
    final: tuple[tuple[int, int], float, dict[Slot, int], dict[Slot, list[Bay]]] | None = None
    for key, _ in ranked:
        depths = depths_of(dict(key))
        pack = _pack(ctx, depths, slots, caps, ppos, centers, penalty)
        for cand in (pack, pack.alt):
            if cand is None:
                continue
            blocks, estimate = _exact_bays(ctx, cand, depths, slots, caps, ppos, centers, penalty)
            score = (estimate, cand.key[2])
            if final is None or score < (final[0], final[1]):
                final = (estimate, cand.key[2], depths, blocks)
        if final is not None and (final[0] == (0, 0) or _late(ctx)):
            break
    assert final is not None
    return final[2], final[3], final[0]


def _exact_bays(
    ctx: Ctx,
    pack: _Packing,
    depths: Mapping[Slot, int],
    slots: Sequence[Slot],
    caps: Mapping[Slot, int],
    ppos: Mapping[str, float],
    centers: Mapping[Slot, float],
    penalty: Mapping[tuple[str, Slot], float],
) -> tuple[dict[Slot, list[Bay]], tuple[int, int]]:
    """Move rooms out of blocks whose exact width overflows (bounded, greedy); also return
    ``(bays that cannot comply, exact overflow)`` of the result."""
    members = {sl: list(rs) for sl, rs in pack.members.items()}
    formed: dict[Slot, list[Bay]] = {}
    width: dict[Slot, int] = {}
    bad: dict[Slot, int] = {}
    for sl in slots:
        formed[sl], width[sl], bad[sl] = _form(ctx, members, pack.stacked, depths, ppos, sl)
    n_rooms = sum(len(rs) for rs in members.values())
    for _ in range(2 * n_rooms):
        over = [sl for sl in slots if width[sl] > caps[sl]]
        if not over or _late(ctx):
            break
        src = max(over, key=lambda t: (width[t] - caps[t], -slots.index(t)))
        best: tuple[float, str, Slot, dict[Slot, tuple[list[Bay], int, int]]] | None = None
        for r in list(members[src]):
            for t in slots:
                if t == src or _option(ctx, r, depths[t]) is None:
                    continue
                members[src].remove(r)
                members[t].append(r)
                touched = {src, t, _sibling(src), _sibling(t)}
                new = {sl: _form(ctx, members, pack.stacked, depths, ppos, sl) for sl in touched}
                members[t].remove(r)
                members[src].append(r)
                if any(new[sl][2] > bad[sl] for sl in touched):
                    continue
                before = sum(max(0, width[sl] - caps[sl]) for sl in touched)
                after = sum(max(0, new[sl][1] - caps[sl]) for sl in touched)
                if after >= before:
                    continue
                dist = abs(centers[t] - ppos[r]) + penalty.get((r, t), 0.0)
                if best is None or dist < best[0]:
                    best = (dist, r, t, new)
        if best is None:
            swap = _best_swap(ctx, pack, members, depths, slots, caps, ppos, width, bad, src)
            if swap is None:
                break
            r, q, t, new = swap
            members[src].remove(r)
            members[t].remove(q)
            members[src].append(q)
            members[t].append(r)
        else:
            _, r, t, new = best
            members[src].remove(r)
            members[t].append(r)
        for sl, (bays, w, b) in new.items():
            formed[sl], width[sl], bad[sl] = bays, w, b
    homeless = pack.key[0] - sum(
        _form(ctx, pack.members, pack.stacked, depths, ppos, sl)[2] for sl in slots
    )
    estimate = (homeless + sum(bad.values()), sum(max(0, width[sl] - caps[sl]) for sl in slots))
    return formed, estimate


def _best_swap(
    ctx: Ctx,
    pack: _Packing,
    members: dict[Slot, list[str]],
    depths: Mapping[Slot, int],
    slots: Sequence[Slot],
    caps: Mapping[Slot, int],
    ppos: Mapping[str, float],
    width: Mapping[Slot, int],
    bad: Mapping[Slot, int],
    src: Slot,
) -> tuple[str, str, Slot, dict[Slot, tuple[list[Bay], int, int]]] | None:
    """The swap of a room of ``src`` with a room of another block that lowers the exact
    overflow the most without adding non-compliant bays (``None`` if there is none)."""
    best: tuple[int, str, str, Slot, dict[Slot, tuple[list[Bay], int, int]]] | None = None
    for t in slots:
        if t == src:
            continue
        touched = {src, t, _sibling(src), _sibling(t)}
        before = sum(max(0, width[sl] - caps[sl]) for sl in touched)
        for r in list(members[src]):
            if _option(ctx, r, depths[t]) is None:
                continue
            for q in list(members[t]):
                if _option(ctx, q, depths[src]) is None:
                    continue
                members[src].remove(r)
                members[t].remove(q)
                members[src].append(q)
                members[t].append(r)
                new = {sl: _form(ctx, members, pack.stacked, depths, ppos, sl) for sl in touched}
                members[src].remove(q)
                members[t].remove(r)
                members[src].append(r)
                members[t].append(q)
                if any(new[sl][2] > bad[sl] for sl in touched):
                    continue
                gain = before - sum(max(0, new[sl][1] - caps[sl]) for sl in touched)
                if gain > 0 and (best is None or gain > best[0]):
                    best = (gain, r, q, t, new)
    return None if best is None else best[1:]
