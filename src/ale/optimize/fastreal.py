"""Memoised realisation for the annealer (RD 3.4 §3, throughput).

:func:`ale.geometry.realize` rebuilds every block and band from scratch for each plan.
A move changes one or two blocks, so the annealer keeps a :class:`RealizeCache` across
calls: one shared stack / room-bay solver, the laid-out blocks keyed by ``(bays, depth,
length, where)`` and the unlinked band searches keyed by ``(piece, band, band plan, depth,
length)``. :meth:`RealizeCache.realize` returns exactly what :func:`ale.geometry.realize`
returns (checked by the tests); ``ale.geometry`` is used, not modified.

The cached ``BlockOut`` / band objects are never mutated after construction by the
realiser, so sharing them between realisations is safe.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from ale.contracts.config import AleConfig
from ale.contracts.corridor_plan import CorridorPlan
from ale.contracts.footprint import FootprintPieces, decompose_footprint
from ale.contracts.models import Rulebook
from ale.geometry.blocks import BlockOut, Consts, Solver
from ale.geometry.evaluate import evaluate
from ale.geometry.junction import frame
from ale.geometry.realize import (
    Failure,
    Realization,
    _BandOut,
    _build_layout,
    _Realizer,
)
from ale.guards import bounded
from ale.program.models import PreparedInput

__all__ = ["RealizeCache"]

_DEPTH_BUDGET_S = 5.0
"""Same per-band depth-search budget as ``ale.geometry.realize``."""
_MAX_ENTRIES = 200_000
"""Each memo is cleared when it grows beyond this many entries (bounded memory)."""


@dataclass
class _MemoBand(_BandOut):
    """A band candidate whose ``cost`` is computed once.

    The realiser sets ``link`` before it first asks for ``cost`` / ``key`` and never
    changes the band afterwards, so the memo is exact.
    """

    _cost: Fraction | None = field(default=None, repr=False, compare=False)

    def cost(self) -> Fraction:
        if self._cost is None:
            self._cost = super().cost()
        return self._cost


class _CachedRealizer(_Realizer):
    """A :class:`_Realizer` whose solver, blocks and unlinked bands come from a cache."""

    def __init__(
        self,
        prepared: PreparedInput,
        plan: CorridorPlan,
        fp: FootprintPieces,
        consts: Consts,
        cache: RealizeCache,
    ) -> None:
        super().__init__(prepared, plan, fp, consts)
        self.solver = cache.solver
        self._cache = cache
        self._local_bands: dict[tuple[int, int, int], Any] = {}
        self._scores: dict[tuple[int, int, str, int], tuple[int, Fraction | int]] = {}

    def band_at(self, p: int, k: int, depth: int, d_a: int) -> _BandOut:
        d_b = depth - self.k.s - d_a
        a = self.block(p, k, "A", d_a)
        b = self.block(p, k, "B", d_b)
        return _MemoBand(depth=depth, d_a=d_a, a=a, b=b, b_depth=d_b)

    def block(self, p: int, k: int, side: str, depth: int) -> BlockOut:
        local = (p, k, side, depth)
        got = self._blocks.get(local)
        if got is not None:
            return got
        got, score = self._shared_block(p, k, side, depth)
        self._blocks[local] = got
        self._scores[local] = score
        return got

    def _score(self, p: int, k: int, side: str, depth: int) -> tuple[int, Fraction | int]:
        """``(failures, scaled area deviation + strip cells)`` of a block (depth search)."""
        local = (p, k, side, depth)
        hit = self._scores.get(local)
        if hit is None:
            self.block(p, k, side, depth)
            hit = self._scores[local]
        return hit

    def _shared_block(
        self, p: int, k: int, side: str, depth: int
    ) -> tuple[BlockOut, tuple[int, Fraction | int]]:
        band = self.plan.pieces[p].bands[k]
        bays = band.block_a.bays if side == "A" else band.block_b.bays
        _, length = self.region(p)
        where = f"piece {p} band {k} block {side}"
        key = (bays, depth, length, where)
        memo = self._cache.blocks
        hit = memo.get(key)
        if hit is None:
            out = self.solver.block(bays, depth, length, where)
            dev = (out.area_dev + out.strip_cells) * self._cache.scale
            score = (len(out.failures), dev.numerator if dev.denominator == 1 else dev)
            hit = (out, score)
            if len(memo) >= _MAX_ENTRIES:
                memo.clear()
            memo[key] = hit
        return hit

    def band(self, p: int, k: int, v0: int, depth: int, link: Any) -> Any:
        if link is not None:
            return super().band(p, k, v0, depth, link)
        local = (p, k, depth)
        if local in self._local_bands:
            return self._local_bands[local]
        _, length = self.region(p)
        key = (p, k, self.plan.pieces[p].bands[k], depth, length)
        memo = self._cache.bands
        if key in memo:
            out = memo[key]
        else:
            was_timed_out = self.timed_out
            out = self._unlinked_band(p, k, depth)
            if self.timed_out != was_timed_out:  # never memoise a search cut by its budget
                return out
            if len(memo) >= _MAX_ENTRIES:
                memo.clear()
            memo[key] = out
        self._local_bands[local] = out
        return out

    def _unlinked_band(self, p: int, k: int, depth: int) -> _BandOut | None:
        """``_Realizer.band`` without a link: the same search and key, on cached scores.

        Scores are scaled by a common denominator of the room targets (order-preserving),
        so the comparison needs no ``Fraction`` arithmetic in the common case.
        """
        plan = self.plan.pieces[p].bands[k]
        best_key: tuple[int, Fraction | int, int, int] | None = None
        best_da = 0
        s = self.k.s
        with bounded(
            max_iter=depth + 1,
            time_budget_s=_DEPTH_BUDGET_S,
            label="depth-search",
            on_exhaust="stop",
        ) as budget:
            for d_a in self.depth_candidates(plan, depth):
                if not budget.tick():  # pragma: no cover - needs a 5 s depth search
                    self.timed_out = True
                    break
                d_b = depth - s - d_a
                fa, da = self._score(p, k, "A", d_a)
                fb, db = self._score(p, k, "B", d_b)
                key = (fa + fb, da + db, abs(d_a - d_b), d_a)
                if best_key is None or key < best_key:
                    best_key, best_da = key, d_a
        if best_key is None:
            return None
        return self.band_at(p, k, depth, best_da)


class RealizeCache:
    """Cross-call memo of the realisation of plans on one ``prepared`` / ``config``."""

    def __init__(self, prepared: PreparedInput, config: AleConfig) -> None:
        self.prepared = prepared
        self.config = config
        self.consts = Consts.from_config(config)
        reqs = {iid: self.consts.req(spec) for iid, spec in prepared.instances}
        self.solver = Solver(self.consts, reqs)
        self.scale = math.lcm(1, *(Fraction(r.target).denominator for r in reqs.values()))
        self.blocks: dict[object, tuple[BlockOut, tuple[int, Fraction | int]]] = {}
        self.bands: dict[object, object] = {}
        self.instance_ids = tuple(iid for iid, _ in prepared.instances)
        self._fp: FootprintPieces | None = None
        self._fp_error: str | None = None
        try:
            self._fp = decompose_footprint(prepared.footprint.polygon)
        except ValueError as exc:
            self._fp_error = str(exc)

    def realize(self, plan: CorridorPlan, rulebook: Rulebook, *, seed: int = 0) -> Realization:
        """Same result as ``ale.geometry.realize(prepared, plan, rulebook, config, seed=seed)``."""
        fp = self._fp
        if fp is None:
            return _fail("FOOTPRINT_UNSUPPORTED", self._fp_error or "")
        problems = plan.check_against(self.instance_ids, fp)
        if problems:
            return _fail("PLAN_INVALID", "; ".join(problems))
        consts = self.consts
        for i, piece in enumerate(fp.pieces):
            if frame(piece)[1] < consts.s:
                return _fail("PIECE_TOO_SMALL", f"piece {i} is narrower than the spine width")
        real = _CachedRealizer(self.prepared, plan, fp, consts, self)
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
        layout = _build_layout(real, self.prepared, outs, seed)
        metrics = evaluate(layout, self.prepared, rulebook, self.config, plan)
        return Realization(
            layout=layout.model_copy(update={"metrics": metrics}), failures=(), depths=depths
        )


def _fail(code: str, detail: str) -> Realization:
    return Realization(layout=None, failures=(Failure(code=code, detail=detail),), depths=())
