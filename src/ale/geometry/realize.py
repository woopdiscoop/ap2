"""Corridor-plan realisation: ``CorridorPlan`` → exact integer-module ``Layout``.

RD 3.3 §5 as amended by RD 3.3b (bands): a piece is split across its spine axis into bands
(``block A | spine | block B``); with two or more bands a connector corridor spans the full
piece depth at the piece's start or end and every band spine starts at it. Each band runs
the 3.3 depth search inside its own depth; band depths are then tuned by coordinate descent
on the internal band boundaries.

Deterministic and exact (integer modules, ``Fraction`` targets); no randomness — ``seed``
is only recorded in the layout. Problems with a valid plan become :class:`Failure` entries,
never exceptions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictStr, model_validator

from ale.contracts.config import AleConfig
from ale.contracts.corridor_plan import BandPlan, CorridorPlan, FingerBay, RoomBay
from ale.contracts.footprint import FootprintPieces, Piece, decompose_footprint
from ale.contracts.models import Layout, LayoutMetrics, PlacedRoom, RoomSpec, Rulebook
from ale.geometry.blocks import BlockOut, Consts, Item, RoomReq, Solver
from ale.geometry.evaluate import evaluate
from ale.geometry.junction import (
    across_origin,
    band_fits,
    cut_side,
    frame,
    j1_secondary_depth,
    j2_secondary_depth,
    to_abs,
)
from ale.guards import bounded
from ale.program.models import PreparedInput

__all__ = ["Failure", "Realization", "realize", "shared_solver"]

_CONFIG = ConfigDict(extra="forbid", frozen=True)
_DEPTH_BUDGET_S = 5.0
_BAND_BUDGET_S = 5.0
_MAX_SHIFT = 24
_SHIFTS = tuple(d for k in range(1, _MAX_SHIFT + 1) for d in (k, -k))

Bays = tuple[RoomBay | FingerBay, ...]
Fail = tuple[str, str]
Score = tuple[int, Fraction]
_NO_SCORE: Score = (1 << 30, Fraction(0))


class Failure(BaseModel):
    """Why a plan could not be realised: ``code`` (e.g. ``PLAN_OVERFLOW``) and ``detail``."""

    model_config = _CONFIG

    code: StrictStr
    detail: StrictStr


class Realization(BaseModel):
    """Result of :func:`realize`; ``layout`` is ``None`` iff ``failures`` is non-empty.

    ``depths``: ``(D_A, D_B)`` per band, pieces in order (primary first), bands from the
    piece's min ``v`` upward; a band's depth is ``D_A + s + D_B``.
    """

    model_config = _CONFIG

    layout: Layout | None
    failures: tuple[Failure, ...]
    depths: tuple[tuple[int, int], ...]

    @model_validator(mode="after")
    def _exclusive(self) -> Realization:
        if (self.layout is None) == (not self.failures):
            raise ValueError("layout must be None if and only if failures is non-empty")
        return self


@dataclass
class _Link:
    """What a band candidate brings along: linked secondary pieces and extra failures."""

    pieces: list[_PieceOut] = field(default_factory=list)
    extra: list[Fail] = field(default_factory=list)


LinkFn = Callable[[int, BlockOut, BlockOut], _Link | None]
"""``(piece-local spine v, block A, block B)`` → link, or ``None`` to skip the candidate."""


@dataclass
class _BandOut:
    depth: int
    d_a: int
    a: BlockOut
    b: BlockOut
    b_depth: int
    link: _Link = field(default_factory=_Link)

    def own_failures(self) -> list[Fail]:
        return [*self.a.failures, *self.b.failures, *self.link.extra]

    def failures(self) -> list[Fail]:
        out = self.own_failures()
        for po in self.link.pieces:
            out += po.failures()
        return out

    def cost(self) -> Fraction:
        """RD 5.1 (amended): area deviation cells + stack-end strip cells (linked included)."""
        own = self.a.area_dev + self.b.area_dev + self.a.strip_cells + self.b.strip_cells
        return own + sum((po.cost() for po in self.link.pieces), Fraction(0))

    def key(self) -> tuple[int, Fraction, int, int]:
        return (len(self.failures()), self.cost(), abs(self.d_a - self.b_depth), self.d_a)


@dataclass
class _PieceOut:
    index: int
    piece: Piece
    connector: Literal["none", "start", "end"]
    bands: list[_BandOut]
    extra: list[Fail] = field(default_factory=list)

    def failures(self) -> list[Fail]:
        return [f for bo in self.bands for f in bo.failures()] + self.extra

    def own_failures(self) -> list[Fail]:
        return [f for bo in self.bands for f in bo.own_failures()] + self.extra

    def cost(self) -> Fraction:
        return sum((bo.cost() for bo in self.bands), Fraction(0))

    def score(self) -> Score:
        return (len(self.failures()), self.cost())

    def linked(self) -> list[_PieceOut]:
        return [po for bo in self.bands for po in bo.link.pieces]


_SOLVERS: dict[tuple[Consts, tuple[tuple[str, RoomReq], ...]], Solver] = {}
_MAX_SOLVERS = 8


def shared_solver(consts: Consts, reqs: dict[str, RoomReq]) -> Solver:
    """A :class:`Solver` reused across calls with the same constants and rooms (its memos
    are pure functions of them, so results are unchanged; Q.1 seeding speed)."""
    key = (consts, tuple(sorted(reqs.items())))
    hit = _SOLVERS.get(key)
    if hit is None:
        if len(_SOLVERS) >= _MAX_SOLVERS:
            _SOLVERS.clear()
        hit = _SOLVERS[key] = Solver(consts, reqs)
    return hit


class _Realizer:
    def __init__(
        self, prepared: PreparedInput, plan: CorridorPlan, fp: FootprintPieces, consts: Consts
    ) -> None:
        self.plan = plan
        self.fp = fp
        self.k = consts
        self.specs: dict[str, RoomSpec] = dict(prepared.instances)
        reqs = {iid: consts.req(spec) for iid, spec in self.specs.items()}
        self.solver = shared_solver(consts, reqs)
        self.timed_out = False
        self._blocks: dict[tuple[int, int, str, int], BlockOut] = {}
        self._fixed: dict[tuple[int, int], _PieceOut] = {}

    # ------------------------------------------------------------------ frames
    def region(self, p: int) -> tuple[int, int]:
        """``(u0, length)`` of the bands of piece ``p`` (after the connector, if any)."""
        length, _ = frame(self.fp.pieces[p])
        connector = self.plan.pieces[p].connector
        if connector == "none":
            return 0, length
        return (self.k.s if connector == "start" else 0), length - self.k.s

    def block(self, p: int, k: int, side: str, depth: int) -> BlockOut:
        key = (p, k, side, depth)
        hit = self._blocks.get(key)
        if hit is None:
            band = self.plan.pieces[p].bands[k]
            bays = band.block_a.bays if side == "A" else band.block_b.bays
            _, length = self.region(p)
            hit = self.solver.block(bays, depth, length, f"piece {p} band {k} block {side}")
            self._blocks[key] = hit
        return hit

    # ------------------------------------------------------------------ depths
    def min_depth(self, bays: Bays) -> int:
        """Smallest useful depth of a non-empty block: the smallest room ``wmin`` (RD 5.1),
        raised to ``k·c`` for a ``k``-room stack (shallower stacks cannot be realised)."""
        rooms = [r for bay in bays for r in _bay_rooms(bay)]
        if not rooms:  # a lone junction finger
            return 1
        low = min(self.solver.reqs[r].wmin for r in rooms)
        for bay in bays:
            if isinstance(bay, FingerBay):
                low = max(low, self.k.c * len(bay.left), self.k.c * len(bay.right))
        return low

    def depth_candidates(self, band: BandPlan, depth: int) -> range:
        """RD 5.1: forced depth for empty blocks, else ``[low_A, P - s - low_B]``."""
        if not band.block_a.bays:
            return range(0, 1)
        if not band.block_b.bays:
            return range(depth - self.k.s, depth - self.k.s + 1)
        lo = self.min_depth(band.block_a.bays)
        hi = depth - self.k.s - self.min_depth(band.block_b.bays)
        if lo > hi:  # band too shallow for both blocks: split evenly
            mid = (depth - self.k.s) // 2
            return range(mid, mid + 1)
        return range(lo, hi + 1)

    def fits(self, p: int, d_a: int) -> bool:
        """Whether both non-empty blocks of 1-band piece ``p`` reach their ``min_depth``."""
        band = self.plan.pieces[p].bands[0]
        d_b = frame(self.fp.pieces[p])[1] - self.k.s - d_a
        return all(
            not bays or d >= self.min_depth(bays)
            for bays, d in ((band.block_a.bays, d_a), (band.block_b.bays, d_b))
        )

    def band_at(self, p: int, k: int, depth: int, d_a: int) -> _BandOut:
        d_b = depth - self.k.s - d_a
        a = self.block(p, k, "A", d_a)
        b = self.block(p, k, "B", d_b)
        return _BandOut(depth=depth, d_a=d_a, a=a, b=b, b_depth=d_b)

    def band(self, p: int, k: int, v0: int, depth: int, link: LinkFn | None) -> _BandOut | None:
        """Best band of depth ``depth`` at ``v0`` (RD 5.1 search); ``None`` if every
        candidate is skipped by ``link``."""
        plan = self.plan.pieces[p].bands[k]
        best: _BandOut | None = None
        best_da: int | None = None
        best_key: tuple[int, Fraction, int, int] | None = None
        s = self.k.s
        with bounded(
            max_iter=depth + 1,
            time_budget_s=_DEPTH_BUDGET_S,
            label="depth-search",
            on_exhaust="stop",
        ) as budget:
            for d_a in self.depth_candidates(plan, depth):
                if not budget.tick():
                    self.timed_out = True
                    break
                if link is None:
                    d_b = depth - s - d_a
                    a, b = self.block(p, k, "A", d_a), self.block(p, k, "B", d_b)
                    key = (
                        len(a.failures) + len(b.failures),
                        a.dev() + b.dev(),
                        abs(d_a - d_b),
                        d_a,
                    )
                    if best_key is None or key < best_key:
                        best_da, best_key = d_a, key
                    continue
                cand = self.band_at(p, k, depth, d_a)
                got = link(v0 + d_a, cand.a, cand.b)
                if got is None:
                    continue
                cand.link = got
                key = cand.key()
                if best_key is None or key < best_key:
                    best, best_key = cand, key
        if best_da is not None:
            return self.band_at(p, k, depth, best_da)
        return best

    def fixed_piece(self, p: int, d_a: int) -> _PieceOut:
        """A 1-band piece at forced ``D_A`` (secondary aligned with the primary)."""
        key = (p, d_a)
        hit = self._fixed.get(key)
        if hit is None:
            depth = frame(self.fp.pieces[p])[1]
            band = self.band_at(p, 0, depth, d_a)
            hit = _PieceOut(p, self.fp.pieces[p], "none", [band])
            self._fixed[key] = hit
        return hit

    # ------------------------------------------------------------------ bands
    def piece(self, p: int, links: dict[int, LinkFn]) -> _PieceOut | None:
        """Piece ``p`` with band depths from equal split + coordinate descent (RD 3.3b §1.3).

        ``links[k]`` is applied to band ``k``'s candidates. ``None`` if no band arrangement
        has a candidate for every band.
        """
        pc = self.fp.pieces[p]
        plan = self.plan.pieces[p]
        n = len(plan.bands)
        _, depth = frame(pc)
        s = self.k.s
        if n * s > depth:
            detail = f"piece {p} depth {depth} cannot hold {n} spines of width {s}"
            return _PieceOut(p, pc, plan.connector, [], [("BANDS_TOO_SHALLOW", detail)])
        cache: dict[tuple[int, int, int], _BandOut | None] = {}

        def arrange(depths: list[int]) -> _PieceOut | None:
            outs: list[_BandOut] = []
            v0 = 0
            for k, d in enumerate(depths):
                link = links.get(k)
                key = (k, -1 if link is None else v0, d)  # unlinked bands ignore v0
                if key not in cache:
                    cache[key] = self.band(p, k, v0, d, link)
                bo = cache[key]
                if bo is None:
                    return None
                outs.append(bo)
                v0 += d
            return _PieceOut(p, pc, plan.connector, outs)

        def score(po: _PieceOut | None) -> Score:
            return _NO_SCORE if po is None else po.score()

        depths = [depth // n] * n
        depths[-1] += depth - n * (depth // n)
        current = arrange(depths)
        if n == 1:
            return current
        cur_score = score(current)
        with bounded(
            max_iter=40 * n * depth,
            time_budget_s=_BAND_BUDGET_S,
            label="band-search",
            on_exhaust="stop",
        ) as budget:
            improved = True
            while improved:
                improved = False
                for i in range(1, n):
                    best: tuple[Score, list[int], _PieceOut] | None = None
                    for delta in _SHIFTS:
                        if not budget.tick():
                            self.timed_out = True
                            return current
                        trial = list(depths)
                        trial[i - 1] += delta
                        trial[i] -= delta
                        if trial[i - 1] < s or trial[i] < s:
                            continue
                        po = arrange(trial)
                        sc = score(po)
                        if po is not None and sc < cur_score and (best is None or sc < best[0]):
                            best = (sc, trial, po)
                    if best is not None:
                        cur_score, depths, current = best
                        improved = True
        return current

    # ------------------------------------------------------------------ L shapes
    def search(self) -> list[_PieceOut] | None:
        fp = self.fp
        if fp.junction == "NONE":
            primary = self.piece(0, {})
            return None if primary is None else [primary]
        if fp.junction == "J1":
            return self._j1()
        return self._j2()

    def _j2(self) -> list[_PieceOut] | None:
        prim_piece, sec_piece = self.fp.pieces
        n_prim = len(self.plan.pieces[0].bands)
        n_sec = len(self.plan.pieces[1].bands)
        s = self.k.s
        if n_prim == 1 and n_sec == 1:  # 3.3: collinear spines, joint search

            def aligned(v: int, a: BlockOut, b: BlockOut) -> _Link | None:
                d_sec = j2_secondary_depth(prim_piece, sec_piece, v)
                if not band_fits(sec_piece, d_sec, s) or not self.fits(1, d_sec):
                    return None
                return _Link([self.fixed_piece(1, d_sec)])

            primary = self.piece(0, {0: aligned})
            return None if primary is None else [primary, *primary.linked()]
        if n_prim == 1:  # secondary connector on its cut side: primary spine must meet it
            sec_lo = across_origin(sec_piece)
            sec_hi = sec_lo + frame(sec_piece)[1]

            def meets(v: int, a: BlockOut, b: BlockOut) -> _Link | None:
                lo = across_origin(prim_piece) + v
                overlap = min(lo + s, sec_hi) - max(lo, sec_lo)
                return _Link() if overlap >= s else None

            secondary = self.piece(1, {})
            primary = self.piece(0, {0: meets})
            if primary is None or secondary is None:
                return None
            return [primary, secondary]
        # Primary connector on its cut side: secondary spines must end on it (unless the
        # secondary's own connector lies on the cut).
        primary = self.piece(0, {})
        links: dict[int, LinkFn] = {}
        if self.plan.pieces[1].connector != cut_side(self.fp, 1):
            prim_lo = across_origin(prim_piece)
            prim_hi = prim_lo + frame(prim_piece)[1]
            for k in range(n_sec):
                links[k] = self._meets_connector(k, prim_lo, prim_hi)
        secondary = self.piece(1, links)
        if primary is None or secondary is None:  # pragma: no cover - links never skip
            return None
        return [primary, secondary]

    def _meets_connector(self, k: int, lo: int, hi: int) -> LinkFn:
        s = self.k.s
        sec = self.fp.pieces[1]

        def link(v: int, a: BlockOut, b: BlockOut) -> _Link:
            start = across_origin(sec) + v
            if start >= lo and start + s <= hi:
                return _Link()
            detail = f"piece 1 band {k} spine at {start} does not meet the piece 0 connector"
            return _Link(extra=[("JUNCTION_MISALIGNED", detail)])

        return link

    def _j1(self) -> list[_PieceOut] | None:
        prim_piece, sec_piece = self.fp.pieces
        facing = self.fp.facing_block
        n = len(self.plan.pieces[0].bands)
        jb = 0 if facing == "A" else n - 1
        u0, _ = self.region(0)
        s = self.k.s

        def junction(v: int, a: BlockOut, b: BlockOut) -> _Link:
            block = a if facing == "A" else b
            if block.junction_u is None:  # pragma: no cover - facing block has depth >= 1
                return _Link(extra=[("JUNCTION_MISALIGNED", "junction finger not placed")])
            ju = u0 + block.junction_u
            d_sec = j1_secondary_depth(prim_piece, sec_piece, ju)
            if band_fits(sec_piece, d_sec, s):
                return _Link([self.fixed_piece(1, d_sec)])
            detail = (
                f"junction finger at u = {ju} puts the secondary spine at {d_sec}, outside piece 1"
            )
            return _Link(extra=[("JUNCTION_MISALIGNED", detail)])

        primary = self.piece(0, {jb: junction})
        if primary is None:  # pragma: no cover - the junction link never skips
            return None
        return [primary, *primary.linked()]


def _bay_rooms(bay: RoomBay | FingerBay) -> tuple[str, ...]:
    return (bay.room,) if isinstance(bay, RoomBay) else (*bay.left, *bay.right)


def _block_rects(
    spine_v: int, block: BlockOut, side: str, s: int
) -> tuple[list[tuple[Item, int]], list[tuple[Item, int]]]:
    """Rooms and circulation items of a block with their piece-local ``v``."""
    rooms: list[tuple[Item, int]] = []
    circ: list[tuple[Item, int]] = []
    for it in block.items:
        v = spine_v - it.t - it.dt if side == "A" else spine_v + s + it.t
        (rooms if it.kind == "room" else circ).append((it, v))
    circ.sort(key=lambda iv: (iv[0].u, iv[1]))
    return rooms, circ


def _build_layout(
    real: _Realizer, prepared: PreparedInput, outs: list[_PieceOut], seed: int
) -> Layout:
    s = real.k.s
    rooms: list[PlacedRoom] = []
    circulation: list[PlacedRoom] = []

    def add_circ(pc: Piece, u: int, v: int, du: int, dv: int) -> None:
        circulation.append(
            PlacedRoom(
                instance_id=f"circ-{len(circulation) + 1:03d}",
                spec_id=None,
                rect=to_abs(pc, u, v, du, dv),
                target_area_m2=None,
            )
        )

    for po in outs:
        pc = po.piece
        full, depth = frame(pc)
        u0, length = real.region(po.index)
        if po.connector != "none":
            add_circ(pc, 0 if po.connector == "start" else full - s, 0, s, depth)
        v0 = 0
        for bo in po.bands:
            spine_v = v0 + bo.d_a
            v0 += bo.depth
            add_circ(pc, u0, spine_v, length, s)
            for side, block in (("A", bo.a), ("B", bo.b)):
                block_rooms, block_circ = _block_rects(spine_v, block, side, s)
                for it, v in block_circ:
                    add_circ(pc, u0 + it.u, v, it.du, it.dt)
                for it, v in block_rooms:
                    assert it.room is not None
                    spec = real.specs[it.room]
                    rooms.append(
                        PlacedRoom(
                            instance_id=it.room,
                            spec_id=spec.id,
                            rect=to_abs(pc, u0 + it.u, v, it.du, it.dt),
                            target_area_m2=spec.target_area_m2,
                        )
                    )
    placeholder = LayoutMetrics(
        total_cost=0.0,
        cost_breakdown={},
        total_overshoot_m2=0.0,
        circulation_area_m2=0.0,
        residue_area_m2=0.0,
        violations=(),
    )
    return Layout(
        grid=prepared.grid,
        footprint=prepared.footprint.polygon,
        rooms=tuple(sorted(rooms, key=lambda p: p.instance_id)),
        circulation=tuple(sorted(circulation, key=lambda p: p.instance_id)),
        residue=(),
        seed=seed,
        rulebook_version=prepared.rulebook_version,
        metrics=placeholder,
    )


def _fail(code: str, detail: str) -> Realization:
    return Realization(layout=None, failures=(Failure(code=code, detail=detail),), depths=())


def realize(
    prepared: PreparedInput,
    plan: CorridorPlan,
    rulebook: Rulebook,
    config: AleConfig,
    *,
    seed: int = 0,
) -> Realization:
    """Realise ``plan`` on ``prepared``'s footprint and score it with :func:`evaluate`."""
    try:
        fp = decompose_footprint(prepared.footprint.polygon)
    except ValueError as exc:
        return _fail("FOOTPRINT_UNSUPPORTED", str(exc))
    problems = plan.check_against([iid for iid, _ in prepared.instances], fp)
    if problems:
        return _fail("PLAN_INVALID", "; ".join(problems))
    consts = Consts.from_config(config)
    for i, piece in enumerate(fp.pieces):
        if frame(piece)[1] < consts.s:
            return _fail("PIECE_TOO_SMALL", f"piece {i} is narrower than the spine width")
    real = _Realizer(prepared, plan, fp, consts)
    outs = real.search()
    if outs is None and real.timed_out:
        return _fail("DEPTH_SEARCH_TIMEOUT", "depth search budget exhausted")
    if outs is None:
        return _fail(
            "JUNCTION_MISALIGNED", "no primary depth puts its spine against the secondary's"
        )
    depths = tuple((bo.d_a, bo.b_depth) for po in outs for bo in po.bands)
    failures = [f for po in outs for f in po.own_failures()]
    if failures:
        return Realization(
            layout=None,
            failures=tuple(Failure(code=c, detail=d) for c, d in failures),
            depths=depths,
        )
    layout = _build_layout(real, prepared, outs, seed)
    metrics = evaluate(layout, prepared, rulebook, config, plan)
    return Realization(
        layout=layout.model_copy(update={"metrics": metrics}), failures=(), depths=depths
    )
