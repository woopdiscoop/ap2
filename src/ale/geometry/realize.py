"""Corridor-plan realisation: ``CorridorPlan`` → exact integer-module ``Layout``.

RD 3.3 §5 as amended by RD 3.3b (bands): a piece is split across its spine axis into bands
(``block A | spine | block B``); with two or more bands a connector corridor spans the full
piece depth at the piece's start or end and every band spine starts at it. Each band runs
the 3.3 depth search inside its own depth; band depths are then tuned by coordinate descent
on the internal band boundaries.

Ticket Q.2 (contracts 1.3.0): with an ``"inner"`` connector the connector strip
``[u_c, u_c + s) x P`` lies inside the piece, ``u_c`` = the largest width of the bays before
the marker over all blocks; every band spine runs the full length (split in two by the
connector); a block whose bays before the marker end before ``u_c`` gets a circulation filler
strip up to ``u_c``; bays after the marker start at ``u_c + s``.

Ticket Q.3 (façade-aware depths): the band depth search key (RD 3.3 §5.1, amended) is
``(n_failures, n_no_facade, cost, |D_A - D_B|, D_A)`` and the band-depth descent (3.3b) ranks
arrangements by ``(n_failures, n_no_facade, cost)``. ``n_no_facade`` counts the
``needs_facade`` rooms predicted to end with façade ``< f`` from the candidate geometry
(:attr:`ale.geometry.blocks.BlockOut.no_facade`: a room bay in an exterior block has façade
= its width, a stack room only when outermost in an exterior block; linked pieces
included). A block is *exterior* when its outer long side (band 0 block A, last band block
B) lies on the footprint exterior along at least half of the band region; there, room bays
of ``needs_facade`` rooms take the smallest compliant width (RD 3.3 §5.2, amended).

Ticket G.1 (contracts 1.6.0): a footprint of more than two pieces is a tree of pieces
(:attr:`FootprintPieces.junctions`). Pieces are realised parent before child: a piece with
children brings the links of all its junctions to the band search of its (adjacent) band; a
J1 child hangs on the junction finger that names it (``junction_to``) and takes the depth
that aligns its spine with that finger; a J2 child takes the depth that puts its spine in the
same absolute band as its (single-band) parent's. Every non-root piece of such a plan has one
band. The finger (J1) or the spine band (J2) must lie inside the cut; open contacts need no
link. Plans of one or two pieces run the unchanged L code.

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
from ale.contracts.corridor_plan import BandPlan, ConnectorBay, CorridorPlan, FingerBay, RoomBay
from ale.contracts.footprint import FootprintPieces, Junction, Piece, decompose_footprint
from ale.contracts.models import Layout, LayoutMetrics, PlacedRoom, RoomSpec, Rulebook
from ale.geometry.bay import (
    WALL_MM,
    BayHint,
    BlockLattice,
    axis_lattice,
    count_lines,
    current_bay_hint,
)
from ale.geometry.blocks import AnyBay, BlockOut, Consts, Item, RoomReq, Solver
from ale.geometry.checks import exterior_contacts
from ale.geometry.evaluate import evaluate
from ale.geometry.junction import (
    across_origin,
    along_origin,
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

Bays = tuple[AnyBay, ...]
Connector = Literal["none", "start", "end", "inner"]
Fail = tuple[str, str]
Score = tuple[int, int, Fraction]
"""``(n_failures, n_no_facade, cost)`` (Q.3)."""
_NO_SCORE: Score = (1 << 30, 0, Fraction(0))


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

    def no_facade(self) -> int:
        """Q.3: predicted ``needs_facade`` rooms without façade (linked pieces included)."""
        return self.a.no_facade + self.b.no_facade + sum(po.no_facade() for po in self.link.pieces)

    def key(self) -> tuple[int, int, Fraction, int, int]:
        return (
            len(self.failures()),
            self.no_facade(),
            self.cost(),
            abs(self.d_a - self.b_depth),
            self.d_a,
        )


@dataclass
class _PieceOut:
    index: int
    piece: Piece
    connector: Connector
    bands: list[_BandOut]
    extra: list[Fail] = field(default_factory=list)
    u_c: int | None = None
    """Inner connector position (``connector == "inner"``), else ``None``."""

    def failures(self) -> list[Fail]:
        return [f for bo in self.bands for f in bo.failures()] + self.extra

    def own_failures(self) -> list[Fail]:
        return [f for bo in self.bands for f in bo.own_failures()] + self.extra

    def cost(self) -> Fraction:
        return sum((bo.cost() for bo in self.bands), Fraction(0))

    def no_facade(self) -> int:
        return sum(bo.no_facade() for bo in self.bands)

    def score(self) -> Score:
        return (len(self.failures()), self.no_facade(), self.cost())

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
        self,
        prepared: PreparedInput,
        plan: CorridorPlan,
        fp: FootprintPieces,
        consts: Consts,
        solver: Solver | None = None,
    ) -> None:
        self.plan = plan
        self.fp = fp
        self.k = consts
        self.specs: dict[str, RoomSpec] = dict(prepared.instances)
        if solver is None:
            reqs = {iid: consts.req(spec) for iid, spec in self.specs.items()}
            solver = shared_solver(consts, reqs)
        self.solver = solver
        self.timed_out = False
        self._blocks: dict[tuple[int, int, str, int], BlockOut] = {}
        self._fixed: dict[tuple[int, int], _PieceOut] = {}
        self._exterior: dict[tuple[int, int, str], bool] = {}
        self._poly = prepared.footprint.polygon

    # ------------------------------------------------------------------ frames
    def region(self, p: int) -> tuple[int, int]:
        """``(u0, length)`` of the bands of piece ``p`` (after the connector, if any)."""
        length, _ = frame(self.fp.pieces[p])
        connector = self.plan.pieces[p].connector
        if connector in ("none", "inner"):
            return 0, length
        return (self.k.s if connector == "start" else 0), length - self.k.s

    def exterior(self, p: int, k: int, side: str) -> bool:
        """Q.3: whether block ``side`` of band ``k`` of piece ``p`` is exterior — band 0
        block A or the last band's block B, whose outer long side lies on the footprint
        exterior along at least half of the band region."""
        key = (p, k, side)
        hit = self._exterior.get(key)
        if hit is None:
            n = len(self.plan.pieces[p].bands)
            hit = False
            if (side == "A" and k == 0) or (side == "B" and k == n - 1):
                piece = self.fp.pieces[p]
                u0, length = self.region(p)
                v = 0 if side == "A" else frame(piece)[1] - 1
                if length > 0:
                    rect = to_abs(piece, u0, v, length, 1)
                    contact = sum(ln for ln, _ in exterior_contacts(rect, self._poly))
                    hit = 2 * contact >= length
            self._exterior[key] = hit
        return hit

    def block(self, p: int, k: int, side: str, depth: int) -> BlockOut:
        key = (p, k, side, depth)
        hit = self._blocks.get(key)
        if hit is None:
            band = self.plan.pieces[p].bands[k]
            bays = band.block_a.bays if side == "A" else band.block_b.bays
            _, length = self.region(p)
            where = f"piece {p} band {k} block {side}"
            hit = self.solver.block(bays, depth, length, where, self.exterior(p, k, side))
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
        if not _occupied(band.block_a.bays):
            return range(0, 1)
        if not _occupied(band.block_b.bays):
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
            not _occupied(bays) or d >= self.min_depth(bays)
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
        best_key: tuple[int, int, Fraction, int, int] | None = None
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
                        a.no_facade + b.no_facade,
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
            if len(self.fp.pieces) > 2:  # G.1: the piece may carry children
                link = self._band_link(p, 0, None)
                if link is not None:
                    got = link(d_a, band.a, band.b)
                    band.link = got if got is not None else _Link(extra=[_NO_FIT])
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
            po = _PieceOut(p, pc, plan.connector, outs)
            if plan.connector == "inner":
                self.place_connector(po)
            return po

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

    def place_connector(self, po: _PieceOut) -> None:
        """Q.2: ``u_c`` = max width before the marker over all blocks; a block whose bays
        then end beyond ``L`` overflows (the part its own layout did not report)."""
        length, _ = frame(po.piece)
        s = self.k.s
        po.u_c = max(
            (blk.marker or 0 for bo in po.bands for blk in (bo.a, bo.b)),
            default=0,
        )
        for k, bo in enumerate(po.bands):
            for side, blk in (("A", bo.a), ("B", bo.b)):
                if blk.marker is None or blk.depth <= 0:
                    continue
                end = po.u_c + s + blk.post
                if end <= length:
                    continue
                own = blk.marker + s + blk.post - length  # already reported by the block
                over = end - length if own <= 0 else po.u_c - blk.marker
                if over > 0:
                    where = f"piece {po.index} band {k} block {side}"
                    po.extra.append(("PLAN_OVERFLOW", f"{where} over by {over} modules"))

    # ------------------------------------------------------------------ L shapes
    def search(self) -> list[_PieceOut] | None:
        fp = self.fp
        if len(fp.pieces) > 2:
            return self._tree()
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
            sec_lo = across_origin(sec_piece)
            sec_hi = sec_lo + frame(sec_piece)[1]
            # Q.2 (speed): when the secondary lies across the primary's whole connector
            # span, every spine inside it meets the connector and the link is a no-op
            # (same search, same result); the band descent then reuses unlinked bands.
            contained = prim_lo <= sec_lo and sec_hi <= prim_hi
            for k in range(0 if contained else n_sec):
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

        def at(ju: int) -> _Link:
            d_sec = j1_secondary_depth(prim_piece, sec_piece, ju)
            if band_fits(sec_piece, d_sec, s):
                return _Link([self.fixed_piece(1, d_sec)])
            detail = (
                f"junction finger at u = {ju} puts the secondary spine at {d_sec}, outside piece 1"
            )
            return _Link(extra=[("JUNCTION_MISALIGNED", detail)])

        def junction(v: int, a: BlockOut, b: BlockOut) -> _Link:
            block = a if facing == "A" else b
            if block.junction_u is None:  # pragma: no cover - facing block has depth >= 1
                return _Link(extra=[("JUNCTION_MISALIGNED", "junction finger not placed")])
            return at(u0 + block.junction_u)

        primary = self.piece(0, {jb: junction})
        if primary is None:  # pragma: no cover - the junction link never skips
            return None
        if primary.u_c is not None and primary.bands:
            # Inner connector: the search placed the junction as if u_c were its own
            # block's; re-align the secondary with the final connector position.
            bo = primary.bands[jb]
            block = bo.a if facing == "A" else bo.b
            ju = block.junction_at(primary.u_c)
            if ju is not None and ju != block.junction_u:
                fresh = self.band_at(0, jb, bo.depth, bo.d_a)
                fresh.link = at(u0 + ju)
                primary.bands[jb] = fresh
        return [primary, *primary.linked()]

    # ------------------------------------------------------------------ trees (G.1)
    def _band_link(self, p: int, k: int, u_c: int | None) -> LinkFn | None:
        """Combined link of every child of piece ``p`` attached to its band ``k`` (``None``
        when there is none). ``u_c``: final inner-connector position of the piece, if any."""
        n = len(self.plan.pieces[p].bands)
        fns: list[LinkFn] = []
        for j in self.fp.children(p):
            if j.kind == "J2":
                if k == 0:
                    fns.append(self._j2_link(j))
            elif k == (0 if j.facing_block == "A" else n - 1):
                fns.append(self._j1_link(j, u_c))
        if not fns:
            return None

        def link(v: int, a: BlockOut, b: BlockOut) -> _Link | None:
            out = _Link()
            for fn in fns:
                got = fn(v, a, b)
                if got is None:
                    return None
                out.pieces += got.pieces
                out.extra += got.extra
            return out

        return link

    def _in_cut(self, j: Junction, start: int) -> bool:
        """Whether the corridor strip ``[start, start + s)`` (absolute coordinate across the
        cut) lies inside the cut segment."""
        (x0, y0), (x1, y1) = j.cut
        lo, hi = (x0, x1) if y0 == y1 else (y0, y1)
        return lo <= start and start + self.k.s <= hi

    def _clamp_depth(self, j: Junction, d_sec: int) -> int:
        """``d_sec`` moved to the nearest ``D_A`` of piece ``j.child`` that keeps its spine
        inside the piece and inside the cut of ``j``."""
        child = self.fp.pieces[j.child]
        (x0, y0), (x1, y1) = j.cut
        lo, hi = (x0, x1) if y0 == y1 else (y0, y1)
        origin = across_origin(child)
        low = max(0, lo - origin)
        high = min(frame(child)[1] - self.k.s, hi - self.k.s - origin)
        return max(low, min(d_sec, high)) if low <= high else max(0, min(d_sec, high))

    def _j1_link(self, j: Junction, u_c: int | None) -> LinkFn:
        parent, child = self.fp.pieces[j.parent], self.fp.pieces[j.child]
        u0, _ = self.region(j.parent)
        s = self.k.s

        def link(v: int, a: BlockOut, b: BlockOut) -> _Link:
            block = a if j.facing_block == "A" else b
            fu = block.finger_at(j.child, u_c)
            if fu is None:  # pragma: no cover - the plan names every J1 child
                return _Link(extra=[("JUNCTION_MISALIGNED", f"no junction finger to {j.child}")])
            ju = u0 + fu
            d_sec = j1_secondary_depth(parent, child, ju)
            if band_fits(child, d_sec, s) and self._in_cut(j, along_origin(parent) + ju):
                return _Link([self.fixed_piece(j.child, d_sec)])
            detail = (
                f"junction finger at u = {ju} puts the spine of piece {j.child} at {d_sec},"
                f" outside piece {j.child} or its cut"
            )
            # Realise the child at the nearest depth that fits, so the failure does not hide
            # the child's own problems (the failure alone keeps the layout from being built).
            near = self._clamp_depth(j, d_sec)
            return _Link([self.fixed_piece(j.child, near)], extra=[("JUNCTION_MISALIGNED", detail)])

        return link

    def _j2_link(self, j: Junction) -> LinkFn:
        parent, child = self.fp.pieces[j.parent], self.fp.pieces[j.child]
        s = self.k.s

        def link(v: int, a: BlockOut, b: BlockOut) -> _Link | None:
            d_sec = j2_secondary_depth(parent, child, v)
            start = across_origin(parent) + v
            if not (band_fits(child, d_sec, s) and self.fits(j.child, d_sec)):
                return None
            if not self._in_cut(j, start):
                return None
            return _Link([self.fixed_piece(j.child, d_sec)])

        return link

    def _tree(self) -> list[_PieceOut] | None:
        """Realise a tree of pieces: the root's band search carries all children links."""
        n = len(self.plan.pieces[0].bands)
        links: dict[int, LinkFn] = {}
        for k in range(n):
            fn = self._band_link(0, k, None)
            if fn is not None:
                links[k] = fn
        root = self.piece(0, links)
        if root is None:
            return None
        if root.u_c is not None:
            # Inner connector: the search placed the fingers as if u_c were its own block's;
            # re-align the children with the final connector position.
            for k in links:
                bo = root.bands[k]
                fn = self._band_link(0, k, root.u_c)
                assert fn is not None
                fresh = self.band_at(0, k, bo.depth, bo.d_a)
                got = fn(bo.d_a + sum(b.depth for b in root.bands[:k]), fresh.a, fresh.b)
                fresh.link = got if got is not None else _Link(extra=[_NO_FIT])
                root.bands[k] = fresh
        return sorted(_flatten(root), key=lambda po: po.index)


_NO_FIT: Fail = ("JUNCTION_MISALIGNED", "a child piece does not fit its parent's spine band")


class _BayRealizer(_Realizer):
    """M.3b: a realiser whose blocks are laid out for the lattice of a :class:`BayHint`
    (:meth:`Solver.bay_plan`). Only :meth:`block` differs; the depth search then ranks the
    lattice cost ahead of the area deviation (it is part of ``BlockOut.area_dev``)."""

    def __init__(
        self,
        prepared: PreparedInput,
        plan: CorridorPlan,
        fp: FootprintPieces,
        consts: Consts,
        hint: BayHint,
    ) -> None:
        super().__init__(prepared, plan, fp, consts)
        self.hint = hint
        ox, oy = prepared.footprint.origin_m
        self._origin_mm = (round(ox * 1000), round(oy * 1000))

    def lattice(self, p: int, k: int, side: str, depth: int) -> BlockLattice:
        """The hint seen from block ``side`` of band ``k`` of piece ``p`` at ``depth``."""
        piece = self.fp.pieces[p]
        h = self.hint
        mod = self.k.module_mm
        along_x = piece.spine_axis == "X"
        u0, _ = self.region(p)
        a, c = (0, 1) if along_x else (1, 0)  # axis index along / across the spine
        start = self._origin_mm[a] + (along_origin(piece) + u0) * mod
        bay_mm = (h.bay_x_mm, h.bay_y_mm)[a]
        line_mm = (h.line_x_mm, h.line_y_mm)[a]
        col_mm = (h.col_x_mm, h.col_y_mm)[a]
        colline_mm = (h.colline_x_mm, h.colline_y_mm)[a]
        bay, bay_res = axis_lattice(line_mm, bay_mm, start, mod)
        col, col_res = axis_lattice(colline_mm, col_mm, start, mod)
        edge = WALL_MM // mod + 1
        across_mm = (h.col_x_mm, h.col_y_mm)[c]
        across_line = (h.colline_x_mm, h.colline_y_mm)[c]
        origin = self._origin_mm[c] + across_origin(piece) * mod
        if len(self.plan.pieces[p].bands) == 1:
            full = frame(piece)[1]
            v_lo = 0 if side == "A" else full - depth
            lo = origin + (v_lo + edge) * mod
            hi = origin + (v_lo + depth - edge) * mod
            n_cross = count_lines(across_line, across_mm, lo, hi)
        else:  # the block's position across the piece is not known here: expected count
            n_cross = max(0, ((depth - 2 * edge) * mod) // across_mm) if across_mm > 0 else 0
        return BlockLattice(
            bay=bay,
            bay_res=bay_res,
            col=col,
            col_res=col_res,
            tol=h.tol_mm // mod,
            edge=edge,
            n_cross=n_cross,
            small_mm2=h.small_mm2,
        )

    def block(self, p: int, k: int, side: str, depth: int) -> BlockOut:
        key = (p, k, side, depth)
        hit = self._blocks.get(key)
        if hit is None:
            band = self.plan.pieces[p].bands[k]
            bays = band.block_a.bays if side == "A" else band.block_b.bays
            _, length = self.region(p)
            where = f"piece {p} band {k} block {side}"
            lat = self.lattice(p, k, side, depth)
            hit = self.solver.block(bays, depth, length, where, self.exterior(p, k, side), lat)
            self._blocks[key] = hit
        return hit


def _flatten(po: _PieceOut) -> list[_PieceOut]:
    """``po`` and, recursively, every piece linked below it."""
    out = [po]
    for child in po.linked():
        out += _flatten(child)
    return out


def _bay_rooms(bay: AnyBay) -> tuple[str, ...]:
    if isinstance(bay, RoomBay):
        return (bay.room,)
    if isinstance(bay, ConnectorBay):
        return ()
    return (*bay.left, *bay.right)


def _occupied(bays: Bays) -> bool:
    """Whether a block holds a room or a finger (a lone connector marker does not count)."""
    return any(not isinstance(bay, ConnectorBay) for bay in bays)


def _block_rects(
    spine_v: int, items: list[Item], side: str, s: int
) -> tuple[list[tuple[Item, int]], list[tuple[Item, int]]]:
    """Rooms and circulation items of a block with their piece-local ``v``."""
    rooms: list[tuple[Item, int]] = []
    circ: list[tuple[Item, int]] = []
    for it in items:
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
        u_c = po.u_c
        if u_c is not None:
            add_circ(pc, u_c, 0, s, depth)
        elif po.connector != "none":
            add_circ(pc, 0 if po.connector == "start" else full - s, 0, s, depth)
        v0 = 0
        for bo in po.bands:
            spine_v = v0 + bo.d_a
            v0 += bo.depth
            if u_c is None:
                add_circ(pc, u0, spine_v, length, s)
            else:  # the inner connector crosses the spine
                for a, b in ((0, u_c), (u_c + s, length)):
                    if b > a:
                        add_circ(pc, a, spine_v, b - a, s)
            for side, block in (("A", bo.a), ("B", bo.b)):
                items = block.placed(u_c, length, s)
                block_rooms, block_circ = _block_rects(spine_v, items, side, s)
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
    """Realise ``plan`` on ``prepared``'s footprint and score it with :func:`evaluate`.

    With a :class:`ale.geometry.bay.BayHint` active (:func:`ale.geometry.bay.use_bay_hint`,
    M.3b) widths and depths are chosen for the lattice; a plan that then fails is realised
    again without it (counted in ``hint.stats.fallbacks``). Without a hint: unchanged.
    """
    hint = current_bay_hint()
    if hint is not None:
        got = _realize(prepared, plan, rulebook, config, seed, hint)
        if got.layout is not None:
            return got
        hint.stats.fallbacks += 1
    return _realize(prepared, plan, rulebook, config, seed, None)


def _realize(
    prepared: PreparedInput,
    plan: CorridorPlan,
    rulebook: Rulebook,
    config: AleConfig,
    seed: int,
    hint: BayHint | None,
) -> Realization:
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
    real = (
        _Realizer(prepared, plan, fp, consts)
        if hint is None
        else _BayRealizer(prepared, plan, fp, consts, hint)
    )
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
    if hint is not None:
        hint.stats.realisations += 1
        for po in outs:
            for bo in po.bands:
                for blk in (bo.a, bo.b):
                    if blk.bay_cost is None:
                        hint.stats.plain_blocks += 1
                    else:
                        hint.stats.lattice_blocks += 1
    layout = _build_layout(real, prepared, outs, seed)
    metrics = evaluate(layout, prepared, rulebook, config, plan)
    return Realization(
        layout=layout.model_copy(update={"metrics": metrics}), failures=(), depths=depths
    )
