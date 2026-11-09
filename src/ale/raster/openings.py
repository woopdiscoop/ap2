"""Step 4 (and the gap bridging of step 3): door gaps in wall lines.

From each end of each wall segment a ray is cast outward along the centreline over the
wall mask. If it meets another wall within ``max_gap`` pixels, the free run in between is
a *gap*: it is bridged (drawn as wall) before rooms are traced, which seals door gaps
both between collinear wall pieces and between a wall end and a crossing wall. Gaps
whose length is within ``[0.5, 1.5] x`` the median gap length become doors.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from ale.raster.walls import WallSeg, pixel_band

__all__ = [
    "DOOR_BAND",
    "MAX_GAP_SHARE",
    "MAX_GAP_THICKNESS",
    "Gap",
    "bridge_gaps",
    "doors_from_gaps",
    "find_gaps",
    "max_gap_px",
]

U8 = NDArray[np.uint8]

#: Longest bridged gap, in multiples of the median wall thickness.
MAX_GAP_THICKNESS = 10.0
#: Longest bridged gap, as a share of the short image side.
MAX_GAP_SHARE = 0.15
#: Gaps within this band of the median gap length are doors.
DOOR_BAND = (0.5, 1.5)


@dataclass(frozen=True)
class Gap:
    """A free run along a wall centreline, from ``a`` to ``b`` (working pixels).

    ``a`` and ``b`` are the positions (along the wall axis) of the gap's boundaries:
    half a pixel beyond the last wall pixel on each side, so ``length = b - a``.
    """

    host: int
    horizontal: bool
    pos: float
    a: float
    b: float
    thickness: float

    @property
    def length(self) -> float:
        return self.b - self.a

    def endpoints(self) -> tuple[tuple[float, float], tuple[float, float]]:
        if self.horizontal:
            return (self.a, self.pos), (self.b, self.pos)
        return (self.pos, self.a), (self.pos, self.b)


def max_gap_px(median_thickness: float, short_side: int) -> int:
    """Longest gap bridged, in working pixels."""
    return max(1, int(min(MAX_GAP_THICKNESS * median_thickness, MAX_GAP_SHARE * short_side)))


def _same_gap(a: Gap, b: Gap) -> bool:
    """Same orientation, centrelines within half a thickness, overlapping runs."""
    tol = max(1.0, min(a.thickness, b.thickness) / 2.0)
    return (
        a.horizontal == b.horizontal
        and abs(a.pos - b.pos) <= tol
        and min(a.b, b.b) - max(a.a, b.a) > 0.0
    )


def find_gaps(segments: list[WallSeg], wall_mask: U8, max_gap: int) -> list[Gap]:
    """Cast a bounded ray from both ends of every segment; return the deduplicated gaps."""
    h, w = wall_mask.shape
    buckets: dict[tuple[bool, int], list[Gap]] = {}
    # bucket width >= the duplicate tolerance, so neighbours (b - 1, b + 1) suffice
    bucket = max([1.0] + [s.thickness / 2.0 for s in segments])
    gaps: list[Gap] = []
    for i, s in enumerate(segments):
        line = math.floor(s.pos)
        if not 0 <= line < (h if s.horizontal else w):
            continue
        limit = w if s.horizontal else h
        for end, step in ((round(s.end), 1), (round(s.start), -1)):
            hit: int | None = None
            for k in range(1, max_gap + 2):  # bounded by max_gap
                q = end + step * k
                if not 0 <= q < limit:
                    break
                v = wall_mask[line, q] if s.horizontal else wall_mask[q, line]
                if v:
                    hit = q
                    break
            if hit is None or abs(hit - end) <= 1:
                continue
            lo, hi = sorted((end, hit))
            gap = Gap(i, s.horizontal, s.pos, lo + 0.5, hi - 0.5, s.thickness)
            b = int(s.pos // bucket)
            near = [g for k in (b - 1, b, b + 1) for g in buckets.get((s.horizontal, k), [])]
            if any(_same_gap(gap, g) for g in near):
                continue  # the same gap seen from its other side
            buckets.setdefault((s.horizontal, b), []).append(gap)
            gaps.append(gap)
    return gaps


def bridge_gaps(wall_mask: U8, gaps: list[Gap]) -> U8:
    """Copy of ``wall_mask`` with every gap drawn as a wall piece of its host's thickness."""
    out = wall_mask.copy()
    for g in gaps:
        lo, hi = pixel_band(g.pos, g.thickness)
        a, b = round(g.a - 0.5), round(g.b + 0.5)
        if g.horizontal:
            cv2.rectangle(out, (a, lo), (b, hi), 255, thickness=-1)
        else:
            cv2.rectangle(out, (lo, a), (hi, b), 255, thickness=-1)
    return out


def doors_from_gaps(gaps: list[Gap]) -> list[Gap]:
    """Gaps whose length is within DOOR_BAND x the median gap length."""
    if not gaps:
        return []
    med = statistics.median(g.length for g in gaps)
    lo, hi = DOOR_BAND[0] * med, DOOR_BAND[1] * med
    return [g for g in gaps if lo <= g.length <= hi]
