"""Deterministic local polish of the annealer's best plan (Ticket Q.3).

Random proposals rarely hit the one swap or insertion that removes a given hard violation,
so :func:`ale.optimize.anneal` finishes with a first-improvement descent over targeted
neighbourhoods of the current best plan, in this order:

1. ``REQUIRED_ADJ`` room ``a`` lacking spec ``B``: each instance ``b`` of ``B`` swapped with
   each room touching ``a``, and ``a`` swapped with each room touching ``b``; the bays of
   ``a`` and ``b`` moved to every other index of their blocks.
2. ``NO_FACADE`` room ``a``: ``a`` made the outermost room of a same-zone stack (its own,
   or one of an exterior block); ``a`` moved as a room bay into an exterior block (band 0 block
   A or the last band's block B, every insertion point next to its zone or at a block end;
   the realiser then deepens the block, Q.3 narrow façade bays); ``a`` swapped with each
   room without ``needs_facade`` that has a façade contact (similar areas first).
3. ``AVOID_ADJ`` pair: each of the two rooms swapped with each same-zone room.
4. Every hard-violation room swapped with every other room of its zone.

A candidate is accepted when it is valid (contract, ``check_against``), adds no macro-zone
violation and lowers ``(n_hard, cost)``; the descent then restarts from it. The number of
evaluated candidates is bounded (``max_evals``) and so is the time (a safety net), so the
result is deterministic whenever the count binds.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping

from ale.contracts.corridor_plan import CorridorPlan, FingerBay, RoomBay
from ale.contracts.geometry import ModuleRect
from ale.contracts.models import Layout, RoomSpec
from ale.geometry.checks import exterior_contacts
from ale.optimize.moves import (
    Block,
    MoveContext,
    _bay_rooms,
    _blocks,
    _exterior,
    _finish,
    _Piece,
    _remove_room,
    _rename,
    _unpack,
)

__all__ = ["polish"]

Evaluate = Callable[[CorridorPlan], tuple[int, float, Layout | None]]
"""``plan`` → ``(n_hard, cost, layout or None)`` (the annealer's memoised scorer)."""


def _share(a: ModuleRect, b: ModuleRect) -> int:
    """Length of the common boundary of two disjoint rectangles (modules)."""
    if a.x2() == b.x or b.x2() == a.x:
        return max(0, min(a.y2(), b.y2()) - max(a.y, b.y))
    if a.y2() == b.y or b.y2() == a.y:
        return max(0, min(a.x2(), b.x2()) - max(a.x, b.x))
    return 0


def _swap(plan: CorridorPlan, a: str, b: str, ctx: MoveContext) -> CorridorPlan | None:
    mapping = {a: b, b: a}
    pieces = _unpack(plan)
    for block in _blocks(pieces):
        block[:] = [_rename(bay, mapping) for bay in block]
    return _finish(plan, pieces, ctx)


def _inserts(plan: CorridorPlan, room: str, ctx: MoveContext) -> Iterator[CorridorPlan]:
    """``room`` as a room bay at every insertion point of every other exterior block that
    lies next to a bay of its zone or at a block end."""
    zone = ctx.zone_of.get(room)
    pos = plan.locate(room)

    def cut() -> tuple[list[_Piece], list[Block], int | None]:
        pieces = _unpack(plan)
        src = pieces[pos.piece].bands[pos.band][0 if pos.block == "A" else 1]
        _remove_room(src, pos.bay, room)
        ext = _exterior(pieces)
        own = next((e for e, blk in enumerate(ext) if blk is src), None)
        return pieces, ext, own

    _, ext, own = cut()
    for e, dst in enumerate(ext):
        if e == own:
            continue
        for i in range(len(dst) + 1):
            near = [dst[j] for j in (i - 1, i) if 0 <= j < len(dst)]
            zones = {ctx.zone_of.get(r) for bay in near for r in _bay_rooms(bay)}
            if i not in (0, len(dst)) and zone not in zones:
                continue
            trial, trial_ext, _ = cut()
            trial_ext[e].insert(i, RoomBay(room=room))
            got = _finish(plan, trial, ctx)
            if got is not None:
                yield got


def _shift(plan: CorridorPlan, room: str, ctx: MoveContext) -> Iterator[CorridorPlan]:
    """The bay holding ``room`` moved to every other index of its block."""
    pos = plan.locate(room)
    n = len(_unpack(plan)[pos.piece].bands[pos.band][0 if pos.block == "A" else 1])
    for i in range(n):
        if i == pos.bay:
            continue
        pieces = _unpack(plan)
        block = pieces[pos.piece].bands[pos.band][0 if pos.block == "A" else 1]
        block.insert(i, block.pop(pos.bay))
        got = _finish(plan, pieces, ctx)
        if got is not None:
            yield got


def _outermost(plan: CorridorPlan, room: str, ctx: MoveContext) -> Iterator[CorridorPlan]:
    """``room`` as the outermost room of a same-zone stack (its own first, then those of the
    exterior blocks): the outermost room of a stack in an exterior block touches the
    façade."""
    zone = ctx.zone_of.get(room)
    pos = plan.locate(room)
    n_ext = len(_exterior(_unpack(plan)))
    targets: list[tuple[int | None, int, str]] = []  # (exterior block or None = own, bay, side)
    if pos.stack is not None:
        targets.append((None, pos.bay, pos.stack))
    for e in range(n_ext):
        for b, bay in enumerate(_exterior(_unpack(plan))[e]):
            if not isinstance(bay, FingerBay):
                continue
            if {ctx.zone_of.get(r) for r in _bay_rooms(bay)} <= {zone}:
                targets += [(e, b, "left"), (e, b, "right")]
    for where, b, side in targets:
        pieces = _unpack(plan)
        src = pieces[pos.piece].bands[pos.band][0 if pos.block == "A" else 1]
        dst = src if where is None else _exterior(pieces)[where]
        bay = dst[b]
        if not isinstance(bay, FingerBay):  # pragma: no cover - targets are finger bays
            continue
        left = tuple(r for r in bay.left if r != room)
        right = tuple(r for r in bay.right if r != room)
        if side == "left":
            left = (*left, room)
        else:
            right = (*right, room)
        dst[b] = FingerBay(left=left, right=right, junction=bay.junction)
        if not (dst is src and b == pos.bay):
            _remove_room(src, pos.bay, room)
        got = _finish(plan, pieces, ctx)
        if got is not None:
            yield got


def _candidates(
    plan: CorridorPlan,
    layout: Layout,
    specs: Mapping[str, RoomSpec],
    ctx: MoveContext,
    min_facade: int,
    hard: frozenset[str],
) -> Iterator[CorridorPlan]:
    rects = {p.instance_id: p.rect for p in layout.rooms}
    ids = sorted(rects)
    touching: dict[str, list[str]] = {r: [] for r in ids}
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if _share(rects[a], rects[b]) >= 1:
                touching[a].append(b)
                touching[b].append(a)
    by_spec: dict[str, list[str]] = {}
    for iid in ids:
        by_spec.setdefault(specs[iid].id, []).append(iid)
    seen: set[tuple[str, str]] = set()

    def swap(a: str, b: str) -> Iterator[CorridorPlan]:
        key = (a, b) if a <= b else (b, a)
        if a == b or key in seen:
            return
        seen.add(key)
        got = _swap(plan, a, b, ctx)
        if got is not None:
            yield got

    viol = [v for v in layout.metrics.violations if v.code in hard]
    for v in viol:  # 1. required adjacency
        if v.code != "REQUIRED_ADJ" or len(v.instance_ids) != 1:
            continue
        a = v.instance_ids[0]
        for other in specs[a].adjacent_to:
            for b in by_spec.get(other, []):
                for x in touching[a]:
                    yield from swap(b, x)
                for y in touching[b]:
                    yield from swap(a, y)
                yield from _shift(plan, a, ctx)
                yield from _shift(plan, b, ctx)
    lacking = sorted(
        {r for v in viol if v.code == "NO_FACADE" for r in v.instance_ids if r in rects}
    )
    spare = [
        p.instance_id
        for p in layout.rooms
        if not specs[p.instance_id].needs_facade
        and sum(n for n, _ in exterior_contacts(p.rect, layout.footprint)) >= min_facade
    ]
    for a in lacking:  # 2. façade
        yield from _outermost(plan, a, ctx)
        yield from _inserts(plan, a, ctx)
        area = float(specs[a].target_area_m2)
        for b in sorted(spare, key=lambda r: (abs(float(specs[r].target_area_m2) - area), r)):
            yield from swap(a, b)
    for v in viol:  # 3. avoided adjacency
        if v.code != "AVOID_ADJ":
            continue
        for a in v.instance_ids:
            for b in ids:
                if ctx.zone_of.get(b) == ctx.zone_of.get(a):
                    yield from swap(a, b)
    for a in sorted({r for v in viol for r in v.instance_ids if r in rects}):  # 4.
        for b in ids:
            if ctx.zone_of.get(b) == ctx.zone_of.get(a):
                yield from swap(a, b)


def polish(
    plan: CorridorPlan,
    score: tuple[int, float],
    layout: Layout,
    evaluate: Evaluate,
    specs: Mapping[str, RoomSpec],
    ctx: MoveContext,
    *,
    min_facade: int,
    hard: frozenset[str],
    max_evals: int,
    deadline: float,
) -> tuple[CorridorPlan, tuple[int, float], Layout, int]:
    """First-improvement descent from ``plan`` (module docstring); returns the best plan,
    its ``(n_hard, cost)``, its layout and the number of candidates evaluated.

    Stops after ``max_evals`` evaluations, at ``deadline`` (``time.monotonic()``), or when
    no candidate improves.
    """
    evals = 0
    improved = True
    while improved:
        improved = False
        for cand in _candidates(plan, layout, specs, ctx, min_facade, hard):
            if evals >= max_evals or time.monotonic() > deadline:
                return plan, score, layout, evals
            evals += 1
            n_hard, cost, got = evaluate(cand)
            if got is None or (n_hard, cost) >= score:
                continue
            plan, score, layout = cand, (n_hard, cost), got
            improved = True
            break
    return plan, score, layout, evals
