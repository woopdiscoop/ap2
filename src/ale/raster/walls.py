"""Step 2 of the raster pipeline: axis-parallel wall segments from the ink mask.

Morphological opening with a horizontal and a vertical line kernel (length 2 % of the
short image side) keeps the long straight strokes. Each connected component of either
opened mask is a candidate bar; its centreline runs along the bar at the centroid, and
its thickness is the median run length across the bar. Bars shorter than 1.5 % of the
short side, stubby (length < 2 x thickness) or sparse are rejected; bars much thinner
than the typical wall (thin drawing lines) are dropped; collinear bars separated by a
tiny break are merged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np
from numpy.typing import NDArray

__all__ = [
    "KERNEL_SHARE",
    "MIN_LENGTH_SHARE",
    "WallExtraction",
    "WallSeg",
    "draw_segments",
    "extract_walls",
    "pixel_band",
]

U8 = NDArray[np.uint8]

#: Line-kernel length as a share of the short image side.
KERNEL_SHARE = 0.02
#: Minimum wall length as a share of the short image side.
MIN_LENGTH_SHARE = 0.015
#: Minimum length / thickness of a bar.
_MIN_ASPECT = 2.0
#: Minimum share of a bar's bounding box covered by its pixels.
_MIN_FILL = 0.5
#: Bars thinner than this share of the typical (area-weighted median) thickness are dropped.
_THIN_SHARE = 0.4
#: Components examined per orientation at most (largest first).
MAX_COMPONENTS = 20_000


@dataclass(frozen=True)
class WallSeg:
    """An axis-parallel wall in working pixels: centreline at ``pos`` from ``start`` to ``end``.

    For a horizontal wall ``pos`` is y and ``start``/``end`` are x (inclusive pixel
    indices); for a vertical wall the roles swap.
    """

    horizontal: bool
    pos: float
    start: float
    end: float
    thickness: float

    @property
    def length(self) -> float:
        return self.end - self.start

    def endpoints(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """Centreline endpoints ``((x, y), (x, y))``."""
        if self.horizontal:
            return (self.start, self.pos), (self.end, self.pos)
        return (self.pos, self.start), (self.pos, self.end)


@dataclass
class WallExtraction:
    """Result of :func:`extract_walls`."""

    segments: list[WallSeg]
    wall_mask: U8
    """Accepted segments rasterised (255 = wall)."""
    line_pixels: int
    """Pixels of the union of the two opened masks."""
    explained_pixels: int
    """Pixels of that union covered by accepted segments."""
    kernel_len: int
    median_thickness: float
    warnings: list[str] = field(default_factory=list)


def pixel_band(pos: float, thickness: float) -> tuple[int, int]:
    """Pixel indices ``lo..hi`` (inclusive) whose centres lie in ``[pos - t/2, pos + t/2)``."""
    half = thickness / 2.0
    lo = math.ceil(pos - half)
    return lo, max(lo, math.ceil(pos + half) - 1)


def draw_segments(shape: tuple[int, int], segments: list[WallSeg]) -> U8:
    """Rasterise segments as filled axis-parallel rectangles."""
    mask = np.zeros(shape, dtype=np.uint8)
    for s in segments:
        lo, hi = pixel_band(s.pos, s.thickness)
        a, b = round(s.start), round(s.end)
        if s.horizontal:
            cv2.rectangle(mask, (a, lo), (b, hi), 255, thickness=-1)
        else:
            cv2.rectangle(mask, (lo, a), (hi, b), 255, thickness=-1)
    return mask


def _bars(mask: U8, horizontal: bool, min_len: float) -> tuple[list[WallSeg], int]:
    """Candidate bars of one opened mask; returns (bars, components skipped by the cap)."""
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return [], 0
    areas = stats[1:, cv2.CC_STAT_AREA]
    order = 1 + np.argsort(-areas, kind="stable")
    skipped = max(0, len(order) - MAX_COMPONENTS)
    out: list[WallSeg] = []
    for k in order[:MAX_COMPONENTS]:
        x, y, w, h, area = (int(v) for v in stats[k])
        length = w if horizontal else h
        if length < min_len:
            continue
        sub = labels[y : y + h, x : x + w] == k
        runs = sub.sum(axis=0 if horizontal else 1)
        runs = runs[runs > 0]
        if runs.size == 0:  # pragma: no cover - a component has pixels
            continue
        thickness = float(np.median(runs))
        if length < _MIN_ASPECT * thickness or area < _MIN_FILL * w * h:
            continue
        pos = float(centroids[k][1] if horizontal else centroids[k][0])
        start, end = (x, x + w - 1) if horizontal else (y, y + h - 1)
        out.append(WallSeg(horizontal, pos, float(start), float(end), thickness))
    return out, skipped


def _merge(segs: list[WallSeg]) -> list[WallSeg]:
    """Merge collinear segments of one orientation whose gap is a tiny break."""
    ordered = sorted(segs, key=lambda s: (s.pos, s.start))
    groups: list[list[WallSeg]] = []
    for s in ordered:  # bounded: one pass over a finite list
        for g in groups[-8:]:  # recent groups only (sorted by pos)
            ref = g[-1]
            tol_pos = max(1.0, min(ref.thickness, s.thickness) / 2.0)
            tol_gap = max(2.0, min(ref.thickness, s.thickness) / 2.0)
            same_line = abs(ref.pos - s.pos) <= tol_pos
            end = max(x.end for x in g)
            if same_line and s.start - end - 1 <= tol_gap and s.end >= min(x.start for x in g):
                g.append(s)
                break
        else:
            groups.append([s])
    merged: list[WallSeg] = []
    for g in groups:
        if len(g) == 1:
            merged.append(g[0])
            continue
        total = sum(max(1.0, x.length) for x in g)
        pos = sum(x.pos * max(1.0, x.length) for x in g) / total
        thick = sum(x.thickness * max(1.0, x.length) for x in g) / total
        merged.append(
            WallSeg(g[0].horizontal, pos, min(x.start for x in g), max(x.end for x in g), thick)
        )
    return merged


def _weighted_median(values: list[float], weights: list[float]) -> float:
    idx = np.argsort(np.asarray(values), kind="stable")
    v = np.asarray(values)[idx]
    cum = np.cumsum(np.asarray(weights)[idx])
    return float(v[int(np.searchsorted(cum, cum[-1] / 2.0))])


def extract_walls(binary: U8) -> WallExtraction:
    """Extract axis-parallel wall segments from an ink mask (255 = ink)."""
    h, w = binary.shape
    short = min(h, w)
    kernel_len = max(3, round(KERNEL_SHARE * short)) | 1  # odd: an even opening shifts
    min_len = max(float(kernel_len), MIN_LENGTH_SHARE * short)
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_len, 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_len))
    hmask = np.asarray(cv2.morphologyEx(binary, cv2.MORPH_OPEN, hk), dtype=np.uint8)
    vmask = np.asarray(cv2.morphologyEx(binary, cv2.MORPH_OPEN, vk), dtype=np.uint8)
    union = np.asarray(cv2.bitwise_or(hmask, vmask), dtype=np.uint8)
    warnings: list[str] = []
    hbars, hskip = _bars(hmask, True, min_len)
    vbars, vskip = _bars(vmask, False, min_len)
    if hskip or vskip:
        warnings.append(f"{hskip + vskip} line component(s) skipped (cap {MAX_COMPONENTS})")
    bars = hbars + vbars
    median_t = 0.0
    if bars:
        median_t = _weighted_median(
            [b.thickness for b in bars], [b.length * b.thickness for b in bars]
        )
        kept = [b for b in bars if b.thickness >= _THIN_SHARE * median_t]
        if len(kept) < len(bars):
            warnings.append(f"{len(bars) - len(kept)} thin line(s) ignored")
        bars = kept
    segments = _merge([b for b in bars if b.horizontal]) + _merge(
        [b for b in bars if not b.horizontal]
    )
    segments.sort(key=lambda s: (not s.horizontal, s.pos, s.start))
    wall_mask = draw_segments((h, w), segments)
    line_pixels = int(np.count_nonzero(union))
    explained = int(np.count_nonzero(cv2.bitwise_and(union, wall_mask)))
    return WallExtraction(
        segments=segments,
        wall_mask=wall_mask,
        line_pixels=line_pixels,
        explained_pixels=explained,
        kernel_len=kernel_len,
        median_thickness=median_t,
        warnings=warnings,
    )
