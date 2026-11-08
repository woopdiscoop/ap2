"""Inverse generation with bands (eval_bands.md N02/N03): a valid layout first, program after.

A piece of depth ``P`` is split into bands (each ``block A | spine | block B``); with two or
more bands a connector of width ``S`` spans the piece depth at the start or end and the
bands use the rest of the length. Inside a band, blocks and bays are drawn as in
:mod:`grammar_gen` (room bays, finger bays with 1-3-room stacks, sides >= 12, aspect <= 2,
no stack-end strips); every room's target is its realised area. Band depths are the equal
split the realiser starts from (see the module note in ``test_geometry_bands.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from geometry_helpers import AnyBay, band
from grammar_gen import MIN_SIDE, S, _block, _ccw_start, _depths, _Ids, _l_points, _rooms
from hypothesis import assume
from hypothesis import strategies as st

from ale.contracts.corridor_plan import BandPlan, CorridorPlan, FingerBay, PiecePlan
from ale.contracts.footprint import FootprintPieces, Piece, decompose_footprint
from ale.contracts.geometry import ModulePolygon
from ale.contracts.models import RoomSpec
from ale.geometry.junction import across_origin, along_origin, cut_side, frame

Connector = Literal["none", "start", "end"]
MIN_BAND = 3 * MIN_SIDE


@dataclass
class BandCase:
    points: list[tuple[int, int]]
    rooms: list[RoomSpec]
    plan: CorridorPlan
    junction: str
    kind: str
    cells: dict[str, int] = field(default_factory=dict)
    note: str = ""


def _piece_plan(bands: list[BandPlan], connector: Connector) -> PiecePlan:
    return PiecePlan(bands=tuple(bands), connector=connector if len(bands) > 1 else "none")


def _band_depths(total: int, n: int) -> list[int]:
    """The realiser's starting band depths: equal split, remainder to the last band."""
    depths = [total // n] * n
    depths[-1] += total - n * (total // n)
    assume(all(d >= MIN_BAND for d in depths))
    return depths


def _band(
    draw: st.DrawFn,
    length: int,
    depth: int,
    ids: _Ids,
    lo: int = 0,
    hi: int | None = None,
) -> tuple[BandPlan, int]:
    """A band with rooms in at least one block; ``D_A`` within ``[lo, hi]``."""
    want_a, want_b, d_a = _depths(draw, depth, lo, hi)
    d_b = depth - S - d_a
    a = _block(draw, length, d_a, ids)[0] if want_a and d_a >= MIN_SIDE else []
    b = _block(draw, length, d_b, ids)[0] if want_b and d_b >= MIN_SIDE else []
    assume(bool(a) == want_a and bool(b) == want_b)
    return band(a, b), d_a


def _band_fixed(draw: st.DrawFn, length: int, depth: int, d_a: int, ids: _Ids) -> BandPlan:
    """A band at a forced ``D_A`` (aligned secondary); blocks may stay empty."""
    d_b = depth - S - d_a
    a = _block(draw, length, d_a, ids)[0] if draw(st.booleans()) and d_a >= MIN_SIDE else []
    b = _block(draw, length, d_b, ids)[0] if draw(st.booleans()) and d_b >= MIN_SIDE else []
    return band(a, b)


def _region(length: int, n: int) -> int:
    return length - S if n > 1 else length


@st.composite
def band_rect_cases(draw: st.DrawFn) -> BandCase:
    n = draw(st.integers(1, 4))
    connector: Connector = draw(st.sampled_from(["start", "end"])) if n > 1 else "none"
    depth = draw(st.integers(max(60, n * MIN_BAND), min(200 * n, 400)))
    length = draw(st.integers(max(80, depth), max(400, depth)))
    ids = _Ids()
    depths = _band_depths(depth, n)
    drawn = [_band(draw, _region(length, n), d, ids) for d in depths]
    bands = [b for b, _ in drawn]
    points = [(0, 0), (length, 0), (length, depth), (0, depth)]
    if length != depth and draw(st.booleans()):  # spine axis Y
        points = [(0, 0), (depth, 0), (depth, length), (0, length)]
    plan = CorridorPlan(pieces=(_piece_plan(bands, connector),))
    note = f"band depths {depths}, D_A {[d for _, d in drawn]}"
    return BandCase(points, _rooms(ids), plan, "NONE", f"rect-{n}", ids.cells, note)


def _bands_for(
    draw: st.DrawFn,
    pc: Piece,
    n: int,
    connector: Connector,
    ids: _Ids,
    spine_range: tuple[int, int] | None = None,
) -> list[BandPlan]:
    """Bands for piece ``pc``; with ``spine_range`` = absolute ``[lo, hi)`` across range,
    every band spine lies inside it (J2 secondary without connector, 1-band primary)."""
    length, depth = frame(pc)
    assume(depth >= n * MIN_BAND)
    depths = _band_depths(depth, n)
    out: list[BandPlan] = []
    v0 = 0
    for d in depths:
        lo, hi = 0, d - S
        if spine_range is not None:
            base = across_origin(pc) + v0
            lo = max(lo, spine_range[0] - base)
            hi = min(hi, spine_range[1] - S - base)
            assume(lo <= hi)
        out.append(_band(draw, _region(length, n), d, ids, lo, hi)[0])
        v0 += d
    return out


def _l_footprint(draw: st.DrawFn, junction: str) -> tuple[list[tuple[int, int]], FootprintPieces]:
    points = _ccw_start(_l_points(draw))
    fp = decompose_footprint(ModulePolygon(exterior=tuple(points)))
    assume(fp.junction == junction)
    return points, fp


def _range(pc: Piece) -> tuple[int, int]:
    lo = across_origin(pc)
    return lo, lo + frame(pc)[1]


@st.composite
def band_l_cases(draw: st.DrawFn, kind: str) -> BandCase:
    """``kind``: ``j2_single`` (both 1 band), ``j2_primary`` (primary multi-band),
    ``j2_secondary`` (secondary-only multi-band) or ``j1_primary`` (primary multi-band)."""
    junction = "J1" if kind.startswith("j1") else "J2"
    points, fp = _l_footprint(draw, junction)
    primary, secondary = fp.pieces
    ids = _Ids()
    if kind == "j2_single":
        n0, n1 = 1, 1
    elif kind == "j2_primary":
        n0, n1 = draw(st.integers(2, 3)), draw(st.integers(1, 2))
    elif kind == "j2_secondary":
        n0, n1 = 1, draw(st.integers(2, 3))
    else:
        n0, n1 = draw(st.integers(2, 3)), 1
    if junction == "J2":
        c0: Connector = cut_side(fp, 0) if n0 > 1 else "none"
        c1: Connector = cut_side(fp, 1) if n1 > 1 else "none"
        if n0 == 1:
            # The primary spine must meet the secondary spine (1 band) or connector.
            if n1 == 1:  # collinear spines
                return _j2_aligned(draw, points, fp, ids)
            sec = _bands_for(draw, secondary, n1, c1, ids)
            prim = _bands_for(draw, primary, 1, "none", ids, spine_range=_range(secondary))
        else:
            prim = _bands_for(draw, primary, n0, c0, ids)
            # A secondary without its own connector ends its spines on the primary's.
            rng = _range(primary) if n1 == 1 else None
            sec = _bands_for(draw, secondary, n1, c1, ids, spine_range=rng)
        plan = CorridorPlan(pieces=(_piece_plan(prim, c0), _piece_plan(sec, c1)))
        return BandCase(points, _rooms(ids), plan, junction, kind, ids.cells)
    return _j1_case(draw, points, fp, n0, ids)


def _j2_aligned(
    draw: st.DrawFn,
    points: list[tuple[int, int]],
    fp: FootprintPieces,
    ids: _Ids,
) -> BandCase:
    """J2 with one band per piece: the primary's spine band fixes the secondary's."""
    primary, secondary = fp.pieces
    _, p_depth = frame(primary)
    lo = across_origin(secondary) - across_origin(primary)
    assume(p_depth >= 60)
    prim_band, d_a = _band(draw, frame(primary)[0], p_depth, ids, lo, lo + frame(secondary)[1] - S)
    d_sec = across_origin(primary) + d_a - across_origin(secondary)
    sec_band = _band_fixed(draw, frame(secondary)[0], frame(secondary)[1], d_sec, ids)
    plan = CorridorPlan(pieces=(_piece_plan([prim_band], "none"), _piece_plan([sec_band], "none")))
    return BandCase(points, _rooms(ids), plan, "J2", "j2_single", ids.cells)


def _j1_case(
    draw: st.DrawFn,
    points: list[tuple[int, int]],
    fp: FootprintPieces,
    n: int,
    ids: _Ids,
) -> BandCase:
    primary, secondary = fp.pieces
    facing = fp.facing_block
    connector: Connector = draw(st.sampled_from(["start", "end"]))
    length, depth = frame(primary)
    region = length - S
    u0 = S if connector == "start" else 0
    assume(depth >= n * MIN_BAND)
    depths = _band_depths(depth, n)
    jb = 0 if facing == "A" else n - 1
    bands: list[BandPlan] = []
    d_sec = 0
    for k, d in enumerate(depths):
        if k != jb:
            bands.append(_band(draw, region, d, ids)[0])
            continue
        want_a, want_b, d_a = _depths(draw, d)
        want_f, want_o = (want_a, want_b) if facing == "A" else (want_b, want_a)
        assume(want_f)
        d_b = d - S - d_a
        depth_f, depth_o = (d_a, d_b) if facing == "A" else (d_b, d_a)
        bays, widths = _block(draw, region - S, depth_f, ids)
        other: list[AnyBay] = (
            _block(draw, region, depth_o, ids)[0] if want_o and depth_o >= MIN_SIDE else []
        )
        assume(bool(bays) and bool(other) == want_o)
        lo = across_origin(secondary) - along_origin(primary) - u0
        hi = lo + frame(secondary)[1] - S
        prefix = [sum(widths[:i]) for i in range(len(bays) + 1)]
        valid = [i for i, u in enumerate(prefix) if lo <= u <= hi]
        assume(bool(valid))
        i = draw(st.sampled_from(valid))
        bays.insert(i, FingerBay(junction=True))
        a, b = (bays, other) if facing == "A" else (other, bays)
        bands.append(band(a, b))
        d_sec = along_origin(primary) + u0 + prefix[i] - across_origin(secondary)
    sec_band = _band_fixed(draw, frame(secondary)[0], frame(secondary)[1], d_sec, ids)
    plan = CorridorPlan(pieces=(_piece_plan(bands, connector), _piece_plan([sec_band], "none")))
    return BandCase(points, _rooms(ids), plan, "J1", "j1_primary", ids.cells)
