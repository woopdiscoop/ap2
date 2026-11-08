"""Corridor-plan realisation: ``CorridorPlan`` → exact integer-module ``Layout`` (RD 3.3 §5).

Deterministic and exact (integer modules, ``Fraction`` targets); no randomness — ``seed``
is only recorded in the layout. Problems with a valid plan become :class:`Failure` entries,
never exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from pydantic import BaseModel, ConfigDict, StrictStr, model_validator

from ale.contracts.config import AleConfig
from ale.contracts.corridor_plan import CorridorPlan, FingerBay, PiecePlan, RoomBay
from ale.contracts.footprint import FootprintPieces, Piece, decompose_footprint
from ale.contracts.models import Layout, LayoutMetrics, PlacedRoom, RoomSpec, Rulebook
from ale.geometry.blocks import BlockOut, Consts, Item, Solver
from ale.geometry.evaluate import evaluate
from ale.geometry.junction import (
    band_fits,
    frame,
    j1_secondary_depth,
    j2_secondary_depth,
    to_abs,
)
from ale.guards import bounded
from ale.program.models import PreparedInput

__all__ = ["Failure", "Realization", "realize"]

_CONFIG = ConfigDict(extra="forbid", frozen=True)
_DEPTH_BUDGET_S = 5.0

Bays = tuple[RoomBay | FingerBay, ...]


class Failure(BaseModel):
    """Why a plan could not be realised: ``code`` (e.g. ``PLAN_OVERFLOW``) and ``detail``."""

    model_config = _CONFIG

    code: StrictStr
    detail: StrictStr


class Realization(BaseModel):
    """Result of :func:`realize`; ``layout`` is ``None`` iff ``failures`` is non-empty."""

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
class _PieceOut:
    piece: Piece
    d_a: int
    d_b: int
    a: BlockOut
    b: BlockOut

    @property
    def failures(self) -> list[tuple[str, str]]:
        return [*self.a.failures, *self.b.failures]

    @property
    def cost(self) -> Fraction:
        """RD 5.1 second criterion: area deviation cells + stack-end strip cells.

        End strips are left out: with them the sum is fixed by the depths alone (exact
        tiling), which would make the criterion blind to overshoot.
        """
        return self.a.area_dev + self.b.area_dev + self.a.strip_cells + self.b.strip_cells


@dataclass
class _Candidate:
    outs: list[_PieceOut]
    extra: list[tuple[str, str]]

    def failures(self) -> list[tuple[str, str]]:
        out = [f for po in self.outs for f in po.failures]
        return out + self.extra

    def key(self) -> tuple[int, Fraction, int, int]:
        first = self.outs[0]
        cost = sum((po.cost for po in self.outs), Fraction(0))
        return (len(self.failures()), cost, abs(first.d_a - first.d_b), first.d_a)


class _Realizer:
    def __init__(self, prepared: PreparedInput, plan: CorridorPlan, consts: Consts) -> None:
        self.plan = plan
        self.k = consts
        self.specs: dict[str, RoomSpec] = dict(prepared.instances)
        reqs = {iid: consts.req(spec) for iid, spec in self.specs.items()}
        self.solver = Solver(consts, reqs)
        self.timed_out = False

    def piece(self, index: int, piece: Piece, d_a: int) -> _PieceOut:
        length, depth = frame(piece)
        d_b = depth - self.k.s - d_a
        plan = self.plan.pieces[index]
        where = f"piece {index} block"
        a = self.solver.block(plan.block_a.bays, d_a, length, f"{where} A")
        b = self.solver.block(plan.block_b.bays, d_b, length, f"{where} B")
        return _PieceOut(piece, d_a, d_b, a, b)

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

    def depth_candidates(self, piece: Piece, plan: PiecePlan) -> range:
        """RD 5.1: forced depth for empty blocks, else ``[low_A, P - s - low_B]``."""
        _, depth = frame(piece)
        if not plan.block_a.bays:
            return range(0, 1)
        if not plan.block_b.bays:
            return range(depth - self.k.s, depth - self.k.s + 1)
        lo = self.min_depth(plan.block_a.bays)
        hi = depth - self.k.s - self.min_depth(plan.block_b.bays)
        if lo > hi:  # piece too shallow for both blocks: split evenly
            mid = (depth - self.k.s) // 2
            return range(mid, mid + 1)
        return range(lo, hi + 1)

    def _fits(self, index: int, piece: Piece, d_a: int) -> bool:
        """Whether both non-empty blocks of a J2 secondary reach their ``min_depth``."""
        plan = self.plan.pieces[index]
        d_b = frame(piece)[1] - self.k.s - d_a
        return all(
            not bays or d >= self.min_depth(bays)
            for bays, d in ((plan.block_a.bays, d_a), (plan.block_b.bays, d_b))
        )

    def search(self, fp: FootprintPieces) -> _Candidate | None:
        primary = fp.pieces[0]
        candidates = self.depth_candidates(primary, self.plan.pieces[0])
        best: _Candidate | None = None
        best_key: tuple[int, Fraction, int, int] | None = None
        with bounded(
            max_iter=frame(primary)[1] + 1,
            time_budget_s=_DEPTH_BUDGET_S,
            label="depth-search",
            on_exhaust="stop",
        ) as budget:
            for d_a in candidates:
                if not budget.tick():
                    self.timed_out = True
                    break
                cand = self._candidate(fp, d_a)
                if cand is None:
                    continue
                key = cand.key()
                if best_key is None or key < best_key:
                    best, best_key = cand, key
        return best

    def _candidate(self, fp: FootprintPieces, d_a: int) -> _Candidate | None:
        first = self.piece(0, fp.pieces[0], d_a)
        if fp.junction == "NONE":
            return _Candidate([first], [])
        primary, secondary = fp.pieces
        if fp.junction == "J2":
            d_sec = j2_secondary_depth(primary, secondary, d_a)
            if not band_fits(secondary, d_sec, self.k.s) or not self._fits(1, secondary, d_sec):
                return None
            return _Candidate([first, self.piece(1, secondary, d_sec)], [])
        block = first.a if fp.facing_block == "A" else first.b
        if block.junction_u is not None:
            d_sec = j1_secondary_depth(primary, secondary, block.junction_u)
            if band_fits(secondary, d_sec, self.k.s):
                return _Candidate([first, self.piece(1, secondary, d_sec)], [])
            detail = (
                f"junction finger at u = {block.junction_u} puts the secondary spine at "
                f"{d_sec}, outside piece 1"
            )
        else:  # pragma: no cover - defensive: the facing block always has depth >= 1
            detail = "junction finger could not be placed"
        return _Candidate([first], [("JUNCTION_MISALIGNED", detail)])


def _bay_rooms(bay: RoomBay | FingerBay) -> tuple[str, ...]:
    return (bay.room,) if isinstance(bay, RoomBay) else (*bay.left, *bay.right)


def _block_rects(
    po: _PieceOut, block: BlockOut, side: str, s: int
) -> tuple[list[tuple[Item, int]], list[tuple[Item, int]]]:
    """Rooms and circulation items of a block with their local ``v``."""
    rooms: list[tuple[Item, int]] = []
    circ: list[tuple[Item, int]] = []
    for it in block.items:
        v = po.d_a - it.t - it.dt if side == "A" else po.d_a + s + it.t
        (rooms if it.kind == "room" else circ).append((it, v))
    circ.sort(key=lambda iv: (iv[0].u, iv[1]))
    return rooms, circ


def _build_layout(
    real: _Realizer, prepared: PreparedInput, outs: list[_PieceOut], seed: int
) -> Layout:
    s = real.k.s
    rooms: list[PlacedRoom] = []
    circulation: list[PlacedRoom] = []

    def add_circ(po: _PieceOut, u: int, v: int, du: int, dv: int) -> None:
        circulation.append(
            PlacedRoom(
                instance_id=f"circ-{len(circulation) + 1:03d}",
                spec_id=None,
                rect=to_abs(po.piece, u, v, du, dv),
                target_area_m2=None,
            )
        )

    for po in outs:
        length, _ = frame(po.piece)
        add_circ(po, 0, po.d_a, length, s)
        for side, block in (("A", po.a), ("B", po.b)):
            block_rooms, block_circ = _block_rects(po, block, side, s)
            for it, v in block_circ:
                add_circ(po, it.u, v, it.du, it.dt)
            for it, v in block_rooms:
                assert it.room is not None
                spec = real.specs[it.room]
                rooms.append(
                    PlacedRoom(
                        instance_id=it.room,
                        spec_id=spec.id,
                        rect=to_abs(po.piece, it.u, v, it.du, it.dt),
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
    real = _Realizer(prepared, plan, consts)
    best = real.search(fp)
    if best is None and real.timed_out:
        return _fail("DEPTH_SEARCH_TIMEOUT", "depth search budget exhausted")
    if best is None:
        return _fail(
            "JUNCTION_MISALIGNED", "no primary depth puts the secondary spine inside piece 1"
        )
    depths = tuple((po.d_a, po.d_b) for po in best.outs)
    failures = best.failures()
    if failures:
        return Realization(
            layout=None,
            failures=tuple(Failure(code=c, detail=d) for c, d in failures),
            depths=depths,
        )
    layout = _build_layout(real, prepared, best.outs, seed)
    metrics = evaluate(layout, prepared, rulebook, config, plan)
    return Realization(
        layout=layout.model_copy(update={"metrics": metrics}), failures=(), depths=depths
    )
