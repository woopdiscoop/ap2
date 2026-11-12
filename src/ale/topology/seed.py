"""Seeding: a bounded, seeded search for a first valid :class:`CorridorPlan` (RD 3.2 §5).

Per attempt ``k`` (seed ``seed`` for ``k = 0``, else ``seed·1000 + k``): seeded embedding of
the adjacency graph → band counts → capacity-aware assignment of rooms to blocks along a
serpentine path → :func:`ale.geometry.realize` → overflow repair. The first valid plan is
kept (else the least-overflow one) and then improved by swaps that lower the
``required_adjacency`` cost term without breaking validity (at most 25 % of the remaining
budget). Deterministic for a seed as long as the time budget is not exhausted; never raises.

Ticket Q.2: the assignment steers ``needs_facade`` rooms to the exterior blocks first; a
valid plan is then improved by a greedy façade pull (swaps with non-façade rooms that have a
façade contact, bays moved to a block end), and multi-band pieces without a cut-side
connector rule are also tried with an ``"inner"`` connector (kept if ``(n_hard, cost)``
improves).

Ticket Q.3 (deterministic budgets): ``seed_plan(..., max_attempts=N)`` bounds the restarts by
``N`` before time; every share of the budget (assignment deadline, repair, swaps, façade pull)
is then taken of the safety cap :data:`SAFETY_TIME_S` instead of ``time_budget_s``, so a run
that finishes well inside it gives the same plan on any machine, with or without coverage.

Ticket Q.3 (Q311, budget kept): the run works to a deadline ``t0 + time_budget_s - margin``
(margin ``min(1 s, 10 %)``). A new attempt, every repair / swap / façade-pull realisation and
every ``"inner"`` trial starts only while the time left exceeds the slowest step of its kind
seen so far, so ``elapsed_s <= time_budget_s`` holds on slow machines and under coverage.
"""

from __future__ import annotations

import itertools
import logging
import math
import time
from collections.abc import Sequence
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictFloat, StrictInt

from ale.contracts.config import AleConfig
from ale.contracts.corridor_plan import (
    MAX_BANDS,
    BandPlan,
    BlockPlan,
    ConnectorBay,
    CorridorPlan,
    FingerBay,
    PiecePlan,
    RoomBay,
)
from ale.contracts.footprint import FootprintPieces, Piece, decompose_footprint
from ale.contracts.geometry import ModuleRect
from ale.contracts.models import Rulebook
from ale.geometry import Realization, realize
from ale.geometry.checks import exterior_contacts
from ale.geometry.evaluate import FACADE_CODES, hard_codes_of
from ale.geometry.junction import across_origin, along_origin, cut_side, frame, to_abs
from ale.guards import Budget, bounded
from ale.program.models import PreparedInput
from ale.topology.cellgrow import grow
from ale.topology.depth import DEADLINE_KEY, BandSpec, fill_blocks
from ale.topology.embed import Positions, embed
from ale.topology.fromdiagram import diagram_positions
from ale.topology.graph import AVOID, REQUIRED, TopologyReport, build_graph, planarity
from ale.topology.repair import (
    Bay,
    Connector,
    Ctx,
    Draft,
    Slot,
    band_depths,
    bay_rooms,
    block_depths,
    move_room,
    repair_step,
    score,
    usable_length,
)

__all__ = ["SeedResult", "seed_plan"]

_LOG = logging.getLogger(__name__)
_MAX_ATTEMPTS = 10_000
SAFETY_TIME_S = 3600.0
"""Time cap of a run bound by ``max_attempts`` (a safety net only, Q.3)."""
_END_MARGIN_S = 1.0
_END_MARGIN_SHARE = 0.1
"""The run stops ``min(_END_MARGIN_S, _END_MARGIN_SHARE · budget)`` before its budget (Q311)."""
_STEP_SAFETY = 1.5
"""A step starts only when the time left exceeds this multiple of its estimated cost."""
_SWAP_SHARE = 0.25
_SWAP_TRIALS_PER_PROGRAM = 720
_SWAP_TRIALS_MIN = 10
_SWAP_TRIALS_MAX = 60
_SEED_STRIDE = 1000
_D_T_FACTOR = Fraction(7, 5)
_EXTRA_ATTEMPTS = 3
"""Attempts made after the first valid plan; the best ``(n_hard, cost)`` is kept (Q.2)."""
_EXTRA_SHARE = 0.4
"""The extra attempts stop once this share of the budget is spent (Q.2)."""
_FACADE_SHARE = 0.25
"""Share of the remaining budget the façade pull may use (Q.2)."""
_FACADE_TRIALS = 300
"""Realisations the façade pull may try (Q.2)."""
HARD_CODES: frozenset[str] = frozenset(
    {
        "AREA_UNDER",
        "AREA_OVER",
        "ASPECT",
        "MIN_WIDTH",
        "NO_FACADE",
        "FACADE_DEPTH",
        "REQUIRED_ADJ",
        "AVOID_ADJ",
        "NO_CIRCULATION_ACCESS",
        "SOLID_NO_ACCESS",
    }
)
"""The hard violation codes of RD 3.4 §3 (``n_hard``), used to rank seeded plans (Q.2)."""


class SeedResult(BaseModel):
    """Outcome of :func:`seed_plan`: the plan, its realisation, the topology report, the
    number of attempts (restarts + 1) and the wall-clock time spent (seconds)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan: CorridorPlan
    realization: Realization
    report: TopologyReport
    attempts: StrictInt
    elapsed_s: StrictFloat


# ---------------------------------------------------------------------- band counts
def _ceil_sqrt(x: Fraction) -> int:
    d = math.isqrt(math.floor(x))
    while d * d < x:
        d += 1
    return d


def _n0(ctx: Ctx, p: int) -> int:
    """RD 5.2: ``max(1, round((P - s) / (2·D_t + s)))`` (as in the 3.3b greedy plan)."""
    targets = sorted(r.target for r in ctx.reqs.values())
    if not targets:
        return 1
    mid = len(targets) // 2
    median = targets[mid] if len(targets) % 2 else (targets[mid - 1] + targets[mid]) / 2
    d_t = _ceil_sqrt(median * _D_T_FACTOR)
    depth = frame(ctx.fp.pieces[p])[1]
    return max(1, min(MAX_BANDS, round(Fraction(depth - ctx.k.s, 2 * d_t + ctx.k.s))))


def _single_band(fp: FootprintPieces, p: int) -> bool:
    """G.1: in a footprint of more than two pieces, a J1 child and every piece incident to a
    J2 junction has exactly one band."""
    if len(fp.pieces) <= 2:
        return False
    return any(
        (j.kind == "J1" and j.child == p) or (j.kind == "J2" and p in (j.parent, j.child))
        for j in fp.junctions
    )


def _allowed(ctx: Ctx) -> list[list[int]]:
    """Band-count candidates per piece: ``{n0-1, n0, n0+1} ∩ [1, 6]`` (J1 secondary: 1),
    dropping counts whose spines alone exceed the piece depth."""
    out: list[list[int]] = []
    for p, piece in enumerate(ctx.fp.pieces):
        if (ctx.fp.junction == "J1" and p == 1) or _single_band(ctx.fp, p):
            out.append([1])
            continue
        n0 = _n0(ctx, p)
        depth = frame(piece)[1]
        cands = [n for n in (n0, n0 - 1, n0 + 1) if 1 <= n <= MAX_BANDS and n * ctx.k.s <= depth]
        out.append(cands or [1])
    return out


def _access_point(prepared: PreparedInput) -> tuple[float, float]:
    a, b = prepared.footprint.polygon.edges()[prepared.footprint.access_edge]
    return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2


def _connectors(ctx: Ctx, counts: Sequence[int]) -> list[Connector]:
    """Contract connectors: the cut side where required (J2), else the end of the piece
    nearer the access edge; a J2 secondary whose spines reach the primary connector gets
    none (its spines run the full length)."""
    fp = ctx.fp
    ax, ay = _access_point(ctx.prepared)
    out: list[Connector] = []
    for p, n in enumerate(counts):
        if n == 1:
            out.append("none")
            continue
        piece = fp.pieces[p]
        length, depth = frame(piece)
        u0, v0 = along_origin(piece), across_origin(piece)
        mid = v0 + depth / 2

        axis_x = piece.spine_axis == "X"

        def dist(u: float, mid: float = mid, axis_x: bool = axis_x) -> float:
            if axis_x:
                return math.hypot(u - ax, mid - ay)
            return math.hypot(mid - ax, u - ay)

        near: Connector = "start" if dist(u0) <= dist(u0 + length) else "end"
        out.append(near)
    if fp.junction == "J2" and any(n >= 2 for n in counts):
        carrier = 0 if counts[0] >= 2 else 1
        side = cut_side(fp, carrier)
        out[carrier] = "start" if side == "none" else side
        if carrier == 0 and counts[1] >= 2:
            out[1] = "none"
    return out


# ---------------------------------------------------------------------- assignment
def _segments(
    ctx: Ctx, draft: Draft, depths: dict[Slot, Fraction]
) -> list[tuple[Slot, tuple[float, float], tuple[float, float]]]:
    """Serpentine path (metres): piece by piece, band by band, block A forward (min u →
    max u) then block B backward, along each block's centre line."""
    m = ctx.prepared.grid.module_mm / 1000
    s = ctx.k.s
    out: list[tuple[Slot, tuple[float, float], tuple[float, float]]] = []
    for p, n in enumerate(draft.counts):
        piece = ctx.fp.pieces[p]
        u0 = s if draft.connectors[p] == "start" else 0
        u1 = u0 + usable_length(ctx, draft, p)
        v = Fraction(0)
        for k in range(n):
            d_a, d_b = depths[(p, k, "A")], depths[(p, k, "B")]
            for side, vm, a, b in (
                ("A", v + d_a / 2, u0, u1),
                ("B", v + d_a + s + d_b / 2, u1, u0),
            ):
                out.append(((p, k, side), _point(piece, a, vm, m), _point(piece, b, vm, m)))
            v += d_a + s + d_b
    return out


def _point(piece: Piece, u: float, v: Fraction, m: float) -> tuple[float, float]:
    """Piece-local ``(u, v)`` (modules) → footprint metres."""
    along = (along_origin(piece) + u) * m
    across = float(across_origin(piece) + v) * m
    return (along, across) if piece.spine_axis == "X" else (across, along)


def _path_position(
    pt: tuple[float, float],
    segs: Sequence[tuple[Slot, tuple[float, float], tuple[float, float]]],
) -> float:
    best: tuple[float, float] | None = None
    offset = 0.0
    for _, a, b in segs:
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        t = 0.0
        if length > 0:
            t = max(0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / length**2))
        d = math.hypot(pt[0] - a[0] - t * dx, pt[1] - a[1] - t * dy)
        if best is None or d < best[0]:
            best = (d, offset + t * length)
        offset += length
    return 0.0 if best is None else best[1]


def _junction_slots(ctx: Ctx, counts: Sequence[int]) -> list[tuple[Slot, int | None, int]]:
    """``(block, child, child piece)`` of every junction finger to place: the L's single one
    (``child`` ``None``, as before G.1) or one per J1 child of a tree of pieces."""
    fp = ctx.fp
    if len(fp.pieces) > 2:
        return [
            (
                (
                    j.parent,
                    0 if j.facing_block == "A" else counts[j.parent] - 1,
                    j.facing_block or "A",
                ),
                j.child,
                j.child,
            )
            for j in fp.junctions
            if j.kind == "J1"
        ]
    if fp.junction != "J1":
        return []
    facing = fp.facing_block or "A"
    return [((0, 0 if facing == "A" else counts[0] - 1, facing), None, 1)]


def assign(
    ctx: Ctx,
    counts: Sequence[int],
    pos: Positions,
    fixed: dict[tuple[int, int], int] | None = None,
) -> Draft:
    """RD 3.2 §5 step 3 as replaced by Q.1 §4: target block depths from the rooms' compliant
    depth intervals, then rooms packed into compatible blocks near their position on the
    serpentine path (see :mod:`ale.topology.depth`). ``fixed`` forces the ``D_A`` of some
    bands ``(piece, band)``."""
    draft = Draft(list(counts), _connectors(ctx, counts))
    depths0 = block_depths(ctx, draft)
    segs = _segments(ctx, draft, depths0)
    slots = [seg[0] for seg in segs]
    jslots = _junction_slots(ctx, counts)
    caps = {
        sl: usable_length(ctx, draft, sl[0]) - ctx.k.s * sum(1 for j in jslots if j[0] == sl)
        for sl in slots
    }
    centers: dict[Slot, float] = {}
    offset = 0.0
    for sl, a, b in segs:
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        centers[sl] = offset + length / 2
        offset += length
    ppos = {r: _path_position(pos[r], segs) for r in ctx.reqs}
    bands = [
        BandSpec(p, k, d - ctx.k.s)
        for p, n in enumerate(counts)
        for k, d in enumerate(band_depths(ctx, p, n))
    ]
    facade = {iid: spec.needs_facade for iid, spec in ctx.prepared.instances}
    outer = _outer_slots(ctx, draft)
    draft.depths, draft.blocks, draft.estimate = fill_blocks(
        ctx, bands, slots, caps, ppos, centers, fixed, facade, outer
    )
    for jslot, child, piece in sorted(jslots, key=lambda j: _junction_target(ctx, draft, j)):
        _place_junction(ctx, draft, jslot, Fraction(max(1, draft.depths[jslot])), child, piece)
    return draft


def _outer_slots(ctx: Ctx, draft: Draft) -> frozenset[Slot]:
    """Blocks whose outer long side lies on the footprint exterior (at least half of it)."""
    poly = ctx.prepared.footprint.polygon
    out: set[Slot] = set()
    for p, n in enumerate(draft.counts):
        piece = ctx.fp.pieces[p]
        _, depth = frame(piece)
        u0 = ctx.k.s if draft.connectors[p] == "start" else 0
        length = usable_length(ctx, draft, p)
        for slot, v in (((p, 0, "A"), 0), ((p, n - 1, "B"), depth - 1)):
            rect = to_abs(piece, u0, v, length, 1)
            if 2 * sum(ln for ln, _ in exterior_contacts(rect, poly)) >= length:
                out.add(slot)
    return frozenset(out)


def _repack(ctx: Ctx, draft: Draft, real: Realization, pos: Positions) -> Draft | None:
    """(g) re-assign ``draft``'s band counts with every band split fixed to the realised one
    (the realiser may pick other depths than the assignment's targets)."""
    if len(real.depths) != sum(draft.counts):
        return None
    fixed: dict[tuple[int, int], int] = {}
    i = 0
    for p, n in enumerate(draft.counts):
        for k, band_depth in enumerate(band_depths(ctx, p, n)):
            d_a, d_b = real.depths[i]
            i += 1
            inner = band_depth - ctx.k.s
            if d_a > 0 and d_b > 0 and ctx.k.c <= d_a <= inner - ctx.k.c:
                fixed[(p, k)] = d_a
    out = assign(ctx, draft.counts, pos, fixed=fixed)
    return None if out.blocks == draft.blocks else out


def _resplit(ctx: Ctx, draft: Draft, slot: Slot, room: str, pos: Positions) -> Draft | None:
    """(g) re-assign ``draft``'s band counts with the split of ``slot``'s band moved to the
    compliant depth of ``room`` nearest to the block's target depth."""
    p, k, side = slot
    inner = band_depths(ctx, p, draft.counts[p])[k] - ctx.k.s
    current = draft.depths.get(slot, inner // 2)
    c = ctx.k.c
    ok = [d for d in range(c, inner - c + 1) if ctx.bay_ok(room, d)]
    if not ok:
        return None
    d = min(ok, key=lambda x: (abs(x - current), x))
    d_a = d if side == "A" else inner - d
    out = assign(ctx, draft.counts, pos, fixed={(p, k): d_a})
    return None if out.blocks == draft.blocks else out


def _junction_window(
    ctx: Ctx, draft: Draft, jslot: tuple[Slot, int | None, int]
) -> tuple[int, int]:
    """Block-local ``u`` range ``[lo, hi]`` where a finger to a child piece may start: inside
    the cut and putting the child's spine inside the child."""
    slot, child, piece = jslot
    parent = ctx.fp.pieces[slot[0]]
    secondary = ctx.fp.pieces[piece]
    s = ctx.k.s
    u0 = s if draft.connectors[slot[0]] == "start" else 0
    base = along_origin(parent) + u0
    lo_c = across_origin(secondary)
    lo, hi = lo_c, lo_c + frame(secondary)[1] - s
    if child is not None:
        junction = ctx.fp.parent_junction(child)
        assert junction is not None
        (x0, y0), (x1, y1) = junction.cut
        cut_lo, cut_hi = (x0, x1) if y0 == y1 else (y0, y1)
        lo, hi = max(lo, cut_lo), min(hi, cut_hi - s)
    return lo - base, hi - base


def _junction_target(ctx: Ctx, draft: Draft, jslot: tuple[Slot, int | None, int]) -> int:
    """Block-local ``u`` where the finger to a child piece should start: the child's spine
    mid-depth, kept inside the window of a tree of pieces."""
    slot, child, piece = jslot
    parent = ctx.fp.pieces[slot[0]]
    secondary = ctx.fp.pieces[piece]
    s = ctx.k.s
    u0 = s if draft.connectors[slot[0]] == "start" else 0
    sec_depth = frame(secondary)[1]
    target = across_origin(secondary) + (sec_depth - s) // 2 - along_origin(parent) - u0
    if child is not None:
        lo, hi = _junction_window(ctx, draft, jslot)
        target = max(lo, min(target, hi))
    return target


def _place_junction(
    ctx: Ctx,
    draft: Draft,
    slot: Slot,
    depth: Fraction,
    child: int | None = None,
    piece: int = 1,
) -> None:
    """Insert the J1 junction finger where the child's spine falls mid-depth (a tree of
    pieces: at a bay boundary inside the finger window when there is one)."""
    jslot = (slot, child, piece)
    target = _junction_target(ctx, draft, jslot)
    bays = draft.blocks[slot]
    cands = [(abs(target), 0)]
    cum = 0
    for i, bay in enumerate(bays):
        cum += ctx.bay_width(bay, depth)
        cands.append((abs(target - cum), i + 1))
    if child is not None:
        lo, hi = _junction_window(ctx, draft, jslot)
        ends = [0]
        cum = 0
        for bay in bays:
            cum += ctx.bay_width(bay, depth)
            ends.append(cum)
        inside = [c for c, end in zip(cands, ends, strict=True) if lo <= end <= hi]
        cands = inside or cands
    bays.insert(min(cands)[1], FingerBay(junction=True, junction_to=child))


# ---------------------------------------------------------------------- search
class _Search:
    def __init__(
        self,
        prepared: PreparedInput,
        rulebook: Rulebook,
        config: AleConfig,
        fp: FootprintPieces,
        seed: int,
    ) -> None:
        self.ctx = Ctx.build(prepared, rulebook, config, fp)
        self.seed = seed
        self.allowed = _allowed(self.ctx)
        self.graph = build_graph(prepared, rulebook)
        self._cache: dict[str, Realization] = {}
        self.deadline = math.inf
        """``time.monotonic()`` by which the run must be done (Q311)."""
        self.slowest = 0.0
        """Longest realisation seen so far (seconds)."""

    def left(self) -> float:
        """Seconds left before :attr:`deadline`."""
        return self.deadline - time.monotonic()

    def affords(self, cost: float | None = None) -> bool:
        """Whether a step of ``cost`` seconds (default: the slowest realisation) still fits,
        with :data:`_STEP_SAFETY` headroom for timing noise."""
        return self.left() > _STEP_SAFETY * (self.slowest if cost is None else cost)

    def realise(self, draft: Draft) -> Realization:
        plan = draft.to_plan()
        key = plan.model_dump_json()
        hit = self._cache.get(key)
        if hit is None:
            hit = self.realise_plan(plan)
            self._cache[key] = hit
        return hit

    def realise_plan(self, plan: CorridorPlan) -> Realization:
        """``realize`` of ``plan``, timing it (:attr:`slowest`)."""
        ctx = self.ctx
        start = time.monotonic()
        out = realize(ctx.prepared, plan, ctx.rulebook, ctx.config, seed=self.seed)
        self.slowest = max(self.slowest, time.monotonic() - start)
        return out

    def combos(self) -> list[list[int]]:
        """Band-count combinations, ``n0`` first (closest to ``n0`` first, then lower)."""
        n0 = [a[0] for a in self.allowed]
        combos = [list(c) for c in itertools.product(*self.allowed)]
        combos.sort(key=lambda c: (sum(abs(x - y) for x, y in zip(c, n0, strict=True)), c))
        return combos


def _cells_positions(search: _Search, k: int) -> Positions:
    """Room positions of the cell diagram of attempt ``k`` (R.9): the plain diagram for
    ``k = 0``, a seeded variant afterwards."""
    ctx = search.ctx
    diagram = grow(
        ctx.prepared,
        ctx.rulebook,
        ctx.config,
        seed=_attempt_seed(search.seed, k),
        jitter=0.0 if k == 0 else 0.5,
    )
    return diagram_positions(diagram)


def _attempt_seed(seed: int, k: int) -> int:
    return seed if k == 0 else seed * _SEED_STRIDE + k


def _fallback(prepared: PreparedInput) -> CorridorPlan:
    """A one-piece, one-band plan holding every room as a room bay (unsupported footprint)."""
    bays = tuple(RoomBay(room=iid) for iid, _ in prepared.instances)
    band = BandPlan(block_a=BlockPlan(bays=bays), block_b=BlockPlan())
    return CorridorPlan(pieces=(PiecePlan(bands=(band,)),))


def _report(search: _Search | None, prepared: PreparedInput, rulebook: Rulebook) -> TopologyReport:
    graph = build_graph(prepared, rulebook) if search is None else search.graph
    planar, conflicts = planarity(graph)
    kinds = [k for _, _, k in graph.edges(data="kind")]
    return TopologyReport(
        n_nodes=graph.number_of_nodes(),
        n_required=kinds.count(REQUIRED),
        n_avoid=kinds.count(AVOID),
        planar=planar,
        conflicts=conflicts,
    )


def seed_plan(
    prepared: PreparedInput,
    rulebook: Rulebook,
    config: AleConfig,
    *,
    seed: int,
    time_budget_s: float = 20.0,
    max_attempts: int | None = None,
    seeder: Literal["spring", "cells"] = "spring",
) -> SeedResult:
    """A first valid corridor plan for ``prepared`` (RD 3.2 §5); never raises.

    Without a valid plan inside ``time_budget_s`` the least-overflow plan is returned with
    its failing realisation. ``max_attempts`` (Q.3): when given (``>= 1``), at most this
    many attempts are made and time is only a safety net (:data:`SAFETY_TIME_S`), so the
    result does not depend on the machine's speed.
    """
    t0 = time.monotonic()
    choices = ("cells", "spring") if seeder == "cells" else ("spring",)
    budget_s = max(float(time_budget_s), 1e-3)
    n_attempts = _MAX_ATTEMPTS
    if max_attempts is not None:
        n_attempts = max(1, min(int(max_attempts), _MAX_ATTEMPTS))
        budget_s = max(budget_s, SAFETY_TIME_S)
    try:
        fp = decompose_footprint(prepared.footprint.polygon)
    except ValueError:
        plan = _fallback(prepared)
        real = realize(prepared, plan, rulebook, config, seed=seed)
        return SeedResult(
            plan=plan,
            realization=real,
            report=_report(None, prepared, rulebook),
            attempts=1,
            elapsed_s=time.monotonic() - t0,
        )
    search = _Search(prepared, rulebook, config, fp, seed)
    ctx = search.ctx
    margin = min(_END_MARGIN_S, _END_MARGIN_SHARE * budget_s)
    search.deadline = t0 + budget_s - margin
    ctx.memo[DEADLINE_KEY] = search.deadline
    combos = search.combos()
    best: tuple[tuple[tuple[int, int], tuple[int, float]], Draft, Realization] | None = None
    attempts = 0
    extra = -1  # Q.2: attempts left after the first valid plan (-1: none found yet)
    slowest_attempt = 0.0
    slowest_assign = 0.0
    with bounded(
        max_iter=n_attempts, time_budget_s=budget_s, label="seed-restarts", on_exhaust="stop"
    ) as restarts:
        for k in range(n_attempts):
            # Q311: once a valid plan exists, a new attempt must fit whole; before that,
            # it only needs room for its realisation (its assignment and repair are guarded).
            room = slowest_attempt if extra >= 0 else None
            if attempts and (not restarts.tick() or not search.affords(room)):
                break
            attempts += 1
            t_attempt = time.monotonic()
            for which in choices:
                if which == "cells":
                    pos = _cells_positions(search, k)
                else:
                    pos = embed(search.graph, prepared, rulebook, seed=_attempt_seed(seed, k))
                counts = combos[k % len(combos)]
                # Q311: the assignment cuts its searches short early enough for the realisation.
                ctx.memo[DEADLINE_KEY] = search.deadline - _STEP_SAFETY * search.slowest
                t_assign = time.monotonic()
                draft = assign(ctx, counts, pos)
                slowest_assign = max(slowest_assign, time.monotonic() - t_assign)
                # Q.1: when the assignment expects problems, try the other band counts on the
                # same embedding and keep the best expectation (no realisation needed).
                for other in combos:
                    if draft.estimate == (0, 0) or time.monotonic() - t0 > budget_s / 2:
                        break
                    if not search.affords(slowest_assign + search.slowest):  # Q311
                        break
                    if other != counts:
                        t_assign = time.monotonic()
                        alt = assign(ctx, other, pos)
                        slowest_assign = max(slowest_assign, time.monotonic() - t_assign)
                        if alt.estimate < draft.estimate:
                            draft = alt
                real = search.realise(draft)

                def reassign(new_counts: list[int], pos: Positions = pos) -> Draft | None:
                    return assign(ctx, new_counts, pos)

                def resplit(
                    current: Draft, slot: Slot, room: str, pos: Positions = pos
                ) -> Draft | None:
                    return _resplit(ctx, current, slot, room, pos)

                def repack(current: Draft, got: Realization, pos: Positions = pos) -> Draft | None:
                    return _repack(ctx, current, got, pos)

                remaining = search.left() - search.slowest
                if score(real) != (0, 0) and remaining > 0:
                    with bounded(
                        max_iter=4 * len(ctx.reqs) + 40,
                        time_budget_s=remaining,
                        label="seed-repair",
                        on_exhaust="stop",
                    ) as rep:

                        def tick(rep: Budget = rep) -> bool:
                            return rep.tick() and search.affords()

                        for _ in range(4 * len(ctx.reqs) + 40):
                            step = repair_step(
                                ctx,
                                draft,
                                real,
                                search.realise,
                                reassign,
                                search.allowed,
                                tick,
                                resplit,
                                repack,
                            )
                            if step is None:
                                break
                            draft, real = step
                            if score(real) == (0, 0):
                                break
                if which == "spring" or score(real) == (0, 0):
                    break
                _LOG.info("cells seeding attempt %d unrealisable: spring fallback", k)
            slowest_attempt = max(slowest_attempt, time.monotonic() - t_attempt)
            sc = score(real)
            key = (sc, _rank(real) if sc == (0, 0) else (0, 0.0))
            if best is None or key < best[0]:
                best = (key, draft, real)
            if sc == (0, 0) and extra < 0:
                extra = _EXTRA_ATTEMPTS
            elif extra > 0:
                extra -= 1
            # Q.2: a few more attempts after the first valid plan, keeping the best
            # (n_hard, cost) — valid plans differ widely in façade contacts.
            if extra == 0 or (extra > 0 and time.monotonic() - t0 > _EXTRA_SHARE * budget_s):
                break
    assert best is not None  # at least one attempt always runs
    _, draft, real = best
    if not real.failures:
        draft, real = _improve_adjacency(search, draft, real, t0, budget_s)
        draft, real = _improve_facade(search, draft, real, t0, budget_s)
    report = _report(search, prepared, rulebook).model_copy(
        update={"unsatisfiable_required": unsatisfiable(search, draft, real)}
    )
    plan = draft.to_plan()
    if not real.failures:
        plan, real = _try_inner(search, plan, real)
    return SeedResult(
        plan=plan,
        realization=real,
        report=report,
        attempts=attempts,
        elapsed_s=time.monotonic() - t0,
    )


# ---------------------------------------------------------------------- adjacency swaps
def _share_len(a: ModuleRect, b: ModuleRect) -> int:
    """Length of the common boundary of two disjoint rectangles (modules)."""
    if a.x2() == b.x or b.x2() == a.x:
        return max(0, min(a.y2(), b.y2()) - max(a.y, b.y))
    if a.y2() == b.y or b.y2() == a.y:
        return max(0, min(a.x2(), b.x2()) - max(a.x, b.x))
    return 0


def _swap(draft: Draft, a: str, b: str) -> Draft:
    def rename(r: str) -> str:
        return b if r == a else a if r == b else r

    out = draft.copy()
    for slot, bays in out.blocks.items():
        new: list[RoomBay | FingerBay] = []
        for bay in bays:
            if isinstance(bay, RoomBay):
                new.append(RoomBay(room=rename(bay.room)))
            else:
                new.append(
                    bay.with_rooms(
                        tuple(rename(r) for r in bay.left), tuple(rename(r) for r in bay.right)
                    )
                )
        out.blocks[slot] = new
    return out


def _required_cost(real: Realization) -> float:
    assert real.layout is not None
    return real.layout.metrics.cost_breakdown.get("required_adjacency", 0.0)


def _swap_candidates(search: _Search, real: Realization) -> list[tuple[str, str]]:
    """Swaps that bring a missing required partner next to its room: for a violation of
    room ``a`` towards spec ``B``, each instance ``b`` of ``B`` swapped with each room
    touching ``a`` (and ``a`` with each room touching ``b``)."""
    layout = real.layout
    assert layout is not None
    c = search.ctx.k.c
    rects = {p.instance_id: p.rect for p in layout.rooms}
    ids = sorted(rects)
    touching: dict[str, list[str]] = {r: [] for r in ids}
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if _share_len(rects[a], rects[b]) >= c:
                touching[a].append(b)
                touching[b].append(a)
    specs = dict(search.ctx.prepared.instances)
    by_spec: dict[str, list[str]] = {}
    for iid, spec in search.ctx.prepared.instances:
        by_spec.setdefault(spec.id, []).append(iid)
    out: list[tuple[str, str]] = []
    for v in layout.metrics.violations:
        if v.code != "REQUIRED_ADJ" or len(v.instance_ids) != 1:
            continue
        a = v.instance_ids[0]
        for other in specs[a].adjacent_to:
            partners = by_spec.get(other, [])
            if any(p in touching.get(a, []) for p in partners):
                continue
            for b in partners:
                out += [(b, x) for x in touching.get(a, []) if x != b]
                out += [(a, y) for y in touching.get(b, []) if y != a]
    seen: set[tuple[str, str]] = set()
    uniq: list[tuple[str, str]] = []
    for a, b in out:
        key = (a, b) if a <= b else (b, a)
        if key not in seen:
            seen.add(key)
            uniq.append(key)
    reqs = search.ctx.reqs
    # Rooms of similar size first: their swap is the most likely to stay valid.
    uniq.sort(key=lambda ab: abs(reqs[ab[0]].target - reqs[ab[1]].target))
    return uniq


def _improve_adjacency(
    search: _Search, draft: Draft, real: Realization, t0: float, budget_s: float
) -> tuple[Draft, Realization]:
    """RD 5.6: swaps lowering ``required_adjacency`` while staying valid, with no new zone
    split; at most 25 % of the remaining budget."""
    remaining = min(budget_s - (time.monotonic() - t0), search.left())
    if remaining <= 0:
        return draft, real
    zones = {iid: spec.macro_zone for iid, spec in search.ctx.prepared.instances}

    def splits(d: Draft) -> int:
        return len(d.to_plan().zone_violations(zones))

    cost = _required_cost(real)
    n_split = splits(draft)
    trials = _SWAP_TRIALS_PER_PROGRAM // max(1, len(zones))
    trials = max(_SWAP_TRIALS_MIN, min(_SWAP_TRIALS_MAX, trials))
    with bounded(
        max_iter=trials,
        time_budget_s=_SWAP_SHARE * remaining,
        label="seed-adjacency-swaps",
        on_exhaust="stop",
    ) as budget:
        improved = True
        while improved and cost > 0:
            improved = False
            for a, b in _swap_candidates(search, real):
                if not budget.tick() or not search.affords():
                    return draft, real
                cand = _swap(draft, a, b)
                got = search.realise(cand)
                if got.failures or _required_cost(got) >= cost:
                    continue
                cand_split = splits(cand)
                if cand_split > n_split:
                    continue
                draft, real, cost, n_split = cand, got, _required_cost(got), cand_split
                improved = True
                break
    return draft, real


# ---------------------------------------------------------------------- façade (Q.2)
def _hard(real: Realization) -> int:
    """Hard violations of a valid realisation (the annealer's ``n_hard``, RD 3.4 §3)."""
    assert real.layout is not None
    hard = hard_codes_of(real.layout.metrics, HARD_CODES)
    return sum(1 for v in real.layout.metrics.violations if v.code in hard)


def _rank(real: Realization) -> tuple[int, float]:
    """``(n_hard, total_cost)`` of a valid realisation."""
    assert real.layout is not None
    return _hard(real), real.layout.metrics.total_cost


def _facade_candidates(search: _Search, draft: Draft, real: Realization) -> list[Draft]:
    """Drafts that may give a ``NO_FACADE`` (Q.4: or ``FACADE_DEPTH``) room a façade: first,
    its bay moved to an end of its block whose bay has a façade contact (an end wall); then
    swaps with rooms without ``needs_facade`` that have a façade contact (similar sizes
    first)."""
    layout = real.layout
    assert layout is not None
    ctx = search.ctx
    lacking = sorted(
        r for v in layout.metrics.violations if v.code in FACADE_CODES for r in v.instance_ids
    )
    facade = {iid: spec.needs_facade for iid, spec in ctx.prepared.instances}
    contact = {
        p.instance_id
        for p in layout.rooms
        if sum(n for n, _ in exterior_contacts(p.rect, layout.footprint)) >= ctx.k.f
    }
    spare = sorted(r for r in contact if not facade.get(r, False))
    moves: list[Draft] = []
    swaps: list[Draft] = []
    inserts: list[Draft] = []
    outer = sorted(_outer_slots(ctx, draft))
    depths = block_depths(ctx, draft, real)
    for a in lacking:
        here, _ = draft.find(a)
        # Q.3: the room joins an exterior block; the realiser deepens it (narrower bays).
        inserts += [move_room(ctx, draft, a, sl, depths[sl]) for sl in outer if sl != here]
        slot, i = draft.find(a)
        bays = draft.blocks[slot]
        for j in (0, len(bays) - 1):
            if j != i and set(bay_rooms(bays[j])) & contact:
                moved = draft.copy()
                bay = moved.blocks[slot].pop(i)
                moved.blocks[slot].insert(j, bay)
                moves.append(moved)
        t = ctx.reqs[a].target
        partners = sorted(
            spare,
            key=lambda b: (abs(t - ctx.reqs[b].target), b),
        )
        swaps += [_swap(draft, a, b) for b in partners]
    return moves + inserts + swaps


def _improve_facade(
    search: _Search, draft: Draft, real: Realization, t0: float, budget_s: float
) -> tuple[Draft, Realization]:
    """Q.2: greedy façade pull — accept a candidate of :func:`_facade_candidates` when it
    stays valid, adds no zone split and lowers ``(n_hard, cost)``; at most
    :data:`_FACADE_SHARE` of the remaining budget."""
    remaining = min(budget_s - (time.monotonic() - t0), search.left())
    if remaining <= 0:
        return draft, real
    zones = {iid: spec.macro_zone for iid, spec in search.ctx.prepared.instances}

    def splits(d: Draft) -> int:
        return len(d.to_plan().zone_violations(zones))

    best = _rank(real)
    n_split = splits(draft)
    with bounded(
        max_iter=_FACADE_TRIALS,
        time_budget_s=_FACADE_SHARE * remaining,
        label="seed-facade-pull",
        on_exhaust="stop",
    ) as budget:
        improved = True
        while improved:
            improved = False
            for cand in _facade_candidates(search, draft, real):
                if not search.affords():
                    return draft, real
                cand_split = splits(cand)
                if cand_split > n_split:
                    continue
                if not budget.tick():
                    return draft, real
                got = search.realise(cand)
                if got.failures or _rank(got) >= best:
                    continue
                draft, real, best, n_split = cand, got, _rank(got), cand_split
                improved = True
                break
    return draft, real


def _marker_at(bays: Sequence[Bay], ctx: Ctx) -> int:
    """Index of a connector marker at the block's capacity midpoint (estimated widths)."""
    widths = [
        Fraction(sum((ctx.reqs[r].target for r in bay_rooms(bay)), Fraction(0))) for bay in bays
    ]
    total = sum(widths, Fraction(0))
    best = (total, 0)
    cum = Fraction(0)
    for i, w in enumerate(widths):
        cum += w
        best = min(best, (abs(2 * cum - total), i + 1))
    return best[1]


def with_inner(plan: CorridorPlan, pieces: Sequence[int], ctx: Ctx) -> CorridorPlan:
    """``plan`` with the connector of ``pieces`` set to ``"inner"`` and one marker per block
    at its capacity midpoint (RD Q.2 §2.2); ``ValueError`` if the contract rejects it."""
    out: list[PiecePlan] = []
    for p, piece in enumerate(plan.pieces):
        if p not in pieces:
            out.append(piece)
            continue
        bands = []
        for band in piece.bands:
            blocks = []
            for block in (band.block_a, band.block_b):
                plain = [bay for bay in block.bays if not isinstance(bay, ConnectorBay)]
                bays: list[RoomBay | FingerBay | ConnectorBay] = list(plain)
                bays.insert(_marker_at(plain, ctx), ConnectorBay())
                blocks.append(BlockPlan(bays=tuple(bays)))
            bands.append(BandPlan(block_a=blocks[0], block_b=blocks[1]))
        out.append(PiecePlan(bands=tuple(bands), connector="inner"))
    return CorridorPlan(pieces=tuple(out))


def _try_inner(
    search: _Search, plan: CorridorPlan, real: Realization
) -> tuple[CorridorPlan, Realization]:
    """Q.2 §2.2: for the multi-band pieces without a cut-side connector rule, also realise
    the plan with an ``"inner"`` connector; keep the best ``(n_hard, cost)`` (ties: the
    plan as seeded)."""
    ctx = search.ctx
    eligible = [
        p
        for p, piece in enumerate(plan.pieces)
        if len(piece.bands) >= 2 and not _cut_side_required(ctx.fp, plan, p)
    ]
    best = (_rank(real), plan, real)
    for k in range(1, len(eligible) + 1):
        for subset in itertools.combinations(eligible, k):
            if not search.affords():
                return best[1], best[2]
            try:
                cand = with_inner(plan, subset, ctx)
            except ValueError:  # pragma: no cover - markers are always valid here
                continue
            got = search.realise_plan(cand)
            if got.layout is not None and _rank(got) < best[0]:
                best = (_rank(got), cand, got)
    return best[1], best[2]


def _cut_side_required(fp: FootprintPieces, plan: CorridorPlan, p: int) -> bool:
    """Whether the contract requires piece ``p``'s connector on the cut side (J2)."""
    if fp.junction != "J2" or not any(len(pc.bands) >= 2 for pc in plan.pieces):
        return False
    carrier = 0 if len(plan.pieces[0].bands) >= 2 else 1
    return p == carrier


# ---------------------------------------------------------------------- report
def _block_rects(search: _Search, draft: Draft, real: Realization) -> dict[Slot, ModuleRect]:
    """Footprint rectangles of every non-degenerate block region."""
    ctx = search.ctx
    s = ctx.k.s
    out: dict[Slot, ModuleRect] = {}
    n_bands = sum(draft.counts)
    i = 0
    for p, n in enumerate(draft.counts):
        piece = ctx.fp.pieces[p]
        u0 = s if draft.connectors[p] == "start" else 0
        length = usable_length(ctx, draft, p)
        v = 0
        equal = band_depths(ctx, p, n)
        for k in range(n):
            if len(real.depths) == n_bands:
                d_a, d_b = real.depths[i]
            else:
                d_a = (equal[k] - s) // 2
                d_b = equal[k] - s - d_a
            i += 1
            if d_a > 0 and length > 0:
                out[(p, k, "A")] = to_abs(piece, u0, v, length, d_a)
            if d_b > 0 and length > 0:
                out[(p, k, "B")] = to_abs(piece, u0, v + d_a + s, length, d_b)
            v += d_a + s + d_b
    return out


def unsatisfiable(search: _Search, draft: Draft, real: Realization) -> tuple[tuple[str, str], ...]:
    """REQUIRED pairs seeded into different blocks whose regions share less than a door
    length (``c``) of boundary, sorted."""
    rects = _block_rects(search, draft, real)
    where: dict[str, Slot] = {}
    for slot, bays in draft.blocks.items():
        for bay in bays:
            for r in bay_rooms(bay):
                where[r] = slot
    out: list[tuple[str, str]] = []
    c = search.ctx.k.c
    for a, b, kind in search.graph.edges(data="kind"):
        if kind != REQUIRED:
            continue
        sa, sb = where.get(a), where.get(b)
        if sa is None or sb is None or sa == sb:
            continue
        ra, rb = rects.get(sa), rects.get(sb)
        if ra is None or rb is None or _share_len(ra, rb) < c:
            out.append((a, b) if a <= b else (b, a))
    return tuple(sorted(out))
