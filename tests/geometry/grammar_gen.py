"""Inverse generation (eval.md section 2): a valid grammar layout first, the program after.

Each case is built in module coordinates: random footprint, block depths, bays (room bays
and finger bays with 1-3-room stacks, every side >= 12, aspect <= 2) and end strips >= 0.
Every room's target is its realised area exactly (cells / 100 m² at the 0.10 m module).
Empty blocks have depth 0 (the grammar's normal form); in an L footprint the secondary
spine is aligned as RD 5.5 requires (same band for J2, junction finger band for J1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction

from geometry_helpers import AnyBay, piece, rb, room
from hypothesis import assume
from hypothesis import strategies as st

from ale.contracts.corridor_plan import CorridorPlan, FingerBay
from ale.contracts.footprint import FootprintPieces, Piece, decompose_footprint
from ale.contracts.geometry import ModulePolygon
from ale.contracts.models import RoomSpec
from ale.geometry.junction import across_origin, along_origin, frame

S = 12  # spine / finger width at the default config
MIN_SIDE = 12


@dataclass
class Case:
    points: list[tuple[int, int]]
    rooms: list[RoomSpec]
    plan: CorridorPlan
    junction: str
    cells: dict[str, int] = field(default_factory=dict)


@dataclass
class _Ids:
    n: int = 0
    cells: dict[str, int] = field(default_factory=dict)

    def new(self, cells: int) -> str:
        rid = f"G{self.n:03d}"
        self.n += 1
        self.cells[rid] = cells
        return rid


def _stack(
    draw: st.DrawFn, depth: int, k: int, cap: int, ids: _Ids
) -> tuple[tuple[str, ...], int] | None:
    k = min(k, depth // MIN_SIDE)
    for kk in (k, 1):
        if kk <= 0:
            continue
        extra = depth - MIN_SIDE * kk
        cuts = sorted(draw(st.lists(st.integers(0, extra), min_size=kk - 1, max_size=kk - 1)))
        bounds = [0, *cuts, extra]
        heights = [MIN_SIDE + bounds[i + 1] - bounds[i] for i in range(kk)]
        lo = max(MIN_SIDE, math.ceil(max(heights) / 2))
        hi = min(2 * min(heights), cap)
        if lo <= hi:
            w = draw(st.integers(lo, hi))
            return tuple(ids.new(w * h) for h in heights), w
    return None


def _block(draw: st.DrawFn, length: int, depth: int, ids: _Ids) -> tuple[list[AnyBay], list[int]]:
    """Random bays filling at most ``length``; returns the bays and their widths."""
    bays: list[AnyBay] = []
    widths: list[int] = []
    used = 0
    for _ in range(draw(st.integers(1, 5))):
        cap = length - used
        if draw(st.booleans()):
            lo, hi = max(MIN_SIDE, math.ceil(depth / 2)), min(2 * depth, cap)
            if lo > hi:
                continue
            w = draw(st.integers(lo, hi))
            bays.append(rb(ids.new(w * depth)))
        else:
            if cap - S < MIN_SIDE:
                continue
            kl, kr = draw(st.integers(0, 3)), draw(st.integers(0, 3))
            left = _stack(draw, depth, kl, cap - S, ids) if kl else None
            wl = left[1] if left else 0
            right = _stack(draw, depth, kr, cap - S - wl, ids) if kr else None
            if left is None and right is None:
                continue
            w = wl + S + (right[1] if right else 0)
            bays.append(FingerBay(left=left[0] if left else (), right=right[0] if right else ()))
        widths.append(w)
        used += w
    return bays, widths


def _depths(
    draw: st.DrawFn, depth: int, lo: int = 0, hi: int | None = None
) -> tuple[bool, bool, int]:
    """Which blocks hold rooms and the normal-form ``D_A`` (within ``[lo, hi]``)."""
    hi = depth - S if hi is None else hi
    which = draw(st.sampled_from(["AB", "AB", "A", "B"]))
    if which == "A":
        d_a = depth - S
    elif which == "B":
        d_a = 0
    else:
        a, b = max(lo, MIN_SIDE), min(hi, depth - S - MIN_SIDE)
        assume(a <= b)
        d_a = draw(st.integers(a, b))
    assume(lo <= d_a <= hi)
    return "A" in which, "B" in which, d_a


def _fill(
    draw: st.DrawFn, pc: Piece, d_a: int, want_a: bool, want_b: bool, ids: _Ids
) -> tuple[list[AnyBay], list[AnyBay], list[int]]:
    length, depth = frame(pc)
    d_b = depth - S - d_a
    a, wa = _block(draw, length, d_a, ids) if want_a and d_a >= MIN_SIDE else ([], [])
    b, _ = _block(draw, length, d_b, ids) if want_b and d_b >= MIN_SIDE else ([], [])
    return a, b, wa


def _rooms(ids: _Ids) -> list[RoomSpec]:
    return [room(rid, float(Fraction(c, 100))) for rid, c in ids.cells.items()]


@st.composite
def rect_cases(draw: st.DrawFn) -> Case:
    length = draw(st.integers(80, 400))
    depth = draw(st.integers(60, min(200, length)))
    want_a, want_b, d_a = _depths(draw, depth)
    ids = _Ids()
    pc = Piece.model_validate(
        {"rect": {"x": 0, "y": 0, "w": length, "h": depth}, "spine_axis": "X"}
    )
    a, b, _ = _fill(draw, pc, d_a, want_a, want_b, ids)
    assume(bool(a) == want_a and bool(b) == want_b)
    points = [(0, 0), (length, 0), (length, depth), (0, depth)]
    if length != depth and draw(st.booleans()):  # spine axis Y
        points = [(0, 0), (depth, 0), (depth, length), (0, length)]
    return Case(points, _rooms(ids), CorridorPlan(pieces=(piece(a, b),)), "NONE", ids.cells)


def _l_points(draw: st.DrawFn) -> list[tuple[int, int]]:
    w = draw(st.integers(120, 400))
    h = draw(st.integers(120, 400))
    nw = draw(st.integers(40, w - 72))
    nh = draw(st.integers(40, h - 72))
    corner = draw(st.sampled_from(["tr", "tl", "br", "bl"]))
    if corner == "tr":
        return [(0, 0), (w, 0), (w, h - nh), (w - nw, h - nh), (w - nw, h), (0, h)]
    if corner == "tl":
        return [(0, 0), (w, 0), (w, h), (nw, h), (nw, h - nh), (0, h - nh)]
    if corner == "br":
        return [(0, 0), (w - nw, 0), (w - nw, nh), (w, nh), (w, h), (0, h)]
    return [(nw, 0), (w, 0), (w, h), (0, h), (0, nh), (nw, nh)]


def _ccw_start(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    k = min(range(len(points)), key=lambda i: (points[i][1], points[i][0]))
    return points[k:] + points[:k]


@st.composite
def l_cases(draw: st.DrawFn, junction: str) -> Case:
    points = _ccw_start(_l_points(draw))
    fp: FootprintPieces = decompose_footprint(ModulePolygon(exterior=tuple(points)))
    assume(fp.junction == junction)
    primary, secondary = fp.pieces
    _, p_depth = frame(primary)
    _, s_depth = frame(secondary)
    assume(p_depth >= 60 and s_depth >= S)
    ids = _Ids()
    if junction == "J2":
        lo = across_origin(secondary) - across_origin(primary)
        want_a, want_b, d_a = _depths(draw, p_depth, lo, lo + s_depth - S)
        a, b, _ = _fill(draw, primary, d_a, want_a, want_b, ids)
        assume(bool(a) == want_a and bool(b) == want_b)
        d_sec = across_origin(primary) + d_a - across_origin(secondary)
    else:
        facing = fp.facing_block
        want_a, want_b, d_a = _depths(draw, p_depth)
        want_f, want_o = (want_a, want_b) if facing == "A" else (want_b, want_a)
        assume(want_f)
        length, _ = frame(primary)
        d_b = p_depth - S - d_a
        depth_f, depth_o = (d_a, d_b) if facing == "A" else (d_b, d_a)
        bays, widths = _block(draw, length - S, depth_f, ids)
        other = _block(draw, length, depth_o, ids)[0] if want_o and depth_o >= MIN_SIDE else []
        assume(bool(bays) and bool(other) == want_o)
        lo = across_origin(secondary) - along_origin(primary)
        hi = lo + s_depth - S
        prefix = [sum(widths[:i]) for i in range(len(bays) + 1)]
        valid = [i for i, u in enumerate(prefix) if lo <= u <= hi]
        assume(bool(valid))
        i = draw(st.sampled_from(valid))
        bays.insert(i, FingerBay(junction=True))
        a, b = (bays, other) if facing == "A" else (other, bays)
        d_sec = along_origin(primary) + prefix[i] - across_origin(secondary)
    want_sa = draw(st.booleans())
    want_sb = draw(st.booleans())
    sa, sb, _ = _fill(draw, secondary, d_sec, want_sa, want_sb, ids)
    assume(ids.cells)
    plan = CorridorPlan(pieces=(piece(a, b), piece(sa, sb)))
    return Case(points, _rooms(ids), plan, junction, ids.cells)
