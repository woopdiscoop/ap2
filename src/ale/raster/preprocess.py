"""Step 1 of the raster pipeline: grayscale, memory cap, deskew, denoise, binarise, crop.

Conventions: images are ``uint8`` numpy arrays, dark ink on a light background. Binary
masks hold 255 for ink and 0 elsewhere. Pixel coordinates put pixel centres on integer
coordinates (OpenCV convention), +x right, +y down.

:class:`Transform` maps working coordinates (deskewed, cropped, possibly downscaled) back
to the pixel frame of the caller's image, so every geometry the reader returns is in the
native pixels of the input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

__all__ = [
    "CROP_MARGIN",
    "MAX_WORK_PIXELS",
    "SKEW_MAX_DEG",
    "SKEW_MIN_DEG",
    "Preprocessed",
    "Transform",
    "preprocess",
    "to_gray",
]

U8 = NDArray[np.uint8]
F64 = NDArray[np.float64]

#: Pixel cap of the working image; larger inputs are downscaled (INTER_AREA) first.
MAX_WORK_PIXELS = 12_000_000
#: Skew angles searched (degrees, either side of the axes).
SKEW_MAX_DEG = 10.0
#: Below this absolute skew (degrees) the image is not rotated.
SKEW_MIN_DEG = 0.3
#: Crop margin around the largest dark component, as a share of its larger bbox side.
CROP_MARGIN = 0.02
#: Long side of the downscaled probe used for the Hough skew estimate.
_SKEW_PROBE_SIDE = 1600
#: Hough segments considered at most (longest first).
_MAX_HOUGH_LINES = 5000
#: Grid of tiles used to detect a non-uniform background.
_TILES = 8
#: Spread of the per-tile background level (grey levels) above which binarisation is adaptive.
_NON_UNIFORM_SPREAD = 50.0
#: A median grey level below this is taken as an inverted (light-on-dark) drawing.
_INVERTED_MEDIAN = 96


@dataclass(frozen=True)
class Transform:
    """Working (cropped, deskewed, scaled) pixel coordinates → caller's pixel coordinates."""

    scale: float
    """Working pixels per native pixel (≤ 1; < 1 when the input was downscaled)."""
    rotation: F64
    """3x3 affine matrix, scaled image → rotated canvas."""
    offset: tuple[int, int]
    """Crop origin ``(x, y)`` in the rotated canvas (may be negative after padding)."""

    def to_native(self, pts: F64) -> F64:
        """Map an ``(n, 2)`` array of working coordinates to native pixels."""
        p = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        p = p + np.array(self.offset, dtype=np.float64)
        inv = np.linalg.inv(self.rotation)
        hom = np.hstack([p, np.ones((p.shape[0], 1))])
        work = (inv @ hom.T).T[:, :2]
        out: F64 = (work + 0.5) / self.scale - 0.5
        return out

    def length_to_native(self, v: float) -> float:
        """Convert a working length (pixels) to native pixels."""
        return float(v) / self.scale


@dataclass
class Preprocessed:
    """Result of :func:`preprocess`."""

    gray: U8
    binary: U8
    transform: Transform
    skew_deg: float = 0.0
    adaptive: bool = False
    oblique_lines: int = 0
    content_share: float = 1.0
    """Bounding-box area of the largest dark component / area of the (rotated) image."""
    warnings: list[str] = field(default_factory=list)


def to_gray(image: NDArray[Any]) -> tuple[U8 | None, str | None]:
    """Convert any 2-D / 3-D numeric array to ``uint8`` grey (channels in BGR(A) order).

    Transparent pixels are composited on white. Returns ``(None, reason)`` when the array
    cannot be an image.
    """
    arr = np.asarray(image)
    if arr.size == 0:
        return None, "empty image"
    if arr.ndim == 3 and arr.shape[2] == 1:
        arr = arr[:, :, 0]
    if arr.ndim not in (2, 3) or (arr.ndim == 3 and arr.shape[2] not in (3, 4)):
        return None, f"unsupported image shape {arr.shape}"
    if arr.dtype == np.bool_:
        u8 = arr.astype(np.uint8) * 255
    elif arr.dtype == np.uint8:
        u8 = arr
    elif arr.dtype == np.uint16:
        u8 = (arr >> 8).astype(np.uint8)
    elif np.issubdtype(arr.dtype, np.floating):
        f = np.nan_to_num(arr.astype(np.float64), nan=1.0, posinf=1.0, neginf=0.0)
        if f.size and float(np.max(f)) <= 1.0:
            f = f * 255.0
        u8 = np.clip(np.rint(f), 0, 255).astype(np.uint8)
    elif np.issubdtype(arr.dtype, np.integer):
        u8 = np.clip(arr, 0, 255).astype(np.uint8)
    else:
        return None, f"unsupported image dtype {arr.dtype}"
    if u8.ndim == 2:
        return np.ascontiguousarray(u8), None
    if u8.shape[2] == 4:
        bgr = u8[:, :, :3].astype(np.float32)
        alpha = u8[:, :, 3:4].astype(np.float32) / 255.0
        comp = np.clip(bgr * alpha + 255.0 * (1.0 - alpha), 0, 255).astype(np.uint8)
        return np.ascontiguousarray(cv2.cvtColor(comp, cv2.COLOR_BGR2GRAY)), None
    return np.ascontiguousarray(cv2.cvtColor(np.ascontiguousarray(u8), cv2.COLOR_BGR2GRAY)), None


def _otsu_ink(gray: U8) -> U8:
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    return np.asarray(binary, dtype=np.uint8)


def _fold(angle_deg: float) -> float:
    """Fold an undirected line angle to ``(-45, 45]`` degrees."""
    a = math.fmod(angle_deg, 90.0)
    if a > 45.0:
        a -= 90.0
    elif a <= -45.0:
        a += 90.0
    return a


def estimate_skew(gray: U8) -> tuple[float, int]:
    """Dominant line angle in degrees within ±SKEW_MAX_DEG, and the count of oblique lines.

    The angle is the length-weighted median of probabilistic-Hough segments, folded to
    the nearest axis; segments further than SKEW_MAX_DEG from both axes are counted as
    oblique. Returns ``(0.0, n)`` when no segment is found.
    """
    h, w = gray.shape
    f = min(1.0, _SKEW_PROBE_SIDE / max(h, w))
    probe = gray
    if f < 1.0:
        size = (max(1, round(w * f)), max(1, round(h * f)))
        probe = np.asarray(cv2.resize(gray, size, interpolation=cv2.INTER_AREA), dtype=np.uint8)
    probe = np.asarray(cv2.medianBlur(probe, 3), dtype=np.uint8)
    ink, _ = binarise(probe)
    short = min(probe.shape)
    min_len = max(10, round(0.05 * short))
    lines = cv2.HoughLinesP(
        ink,
        1.0,
        math.pi / 360.0,
        threshold=max(10, min_len // 2),
        minLineLength=min_len,
        maxLineGap=2,
    )
    if lines is None or len(lines) == 0:
        return 0.0, 0
    segs = np.asarray(lines, dtype=np.float64).reshape(-1, 4)
    lengths = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    order = np.argsort(-lengths, kind="stable")[:_MAX_HOUGH_LINES]
    angles: list[float] = []
    weights: list[float] = []
    oblique = 0
    for k in order:
        x0, y0, x1, y1 = segs[k]
        a = _fold(math.degrees(math.atan2(y1 - y0, x1 - x0)))
        if abs(a) <= SKEW_MAX_DEG:
            angles.append(a)
            weights.append(float(lengths[k]))
        else:
            oblique += 1
    if not angles:
        return 0.0, oblique
    idx = np.argsort(np.asarray(angles), kind="stable")
    a_sorted = np.asarray(angles)[idx]
    w_cum = np.cumsum(np.asarray(weights)[idx])
    median = float(a_sorted[int(np.searchsorted(w_cum, w_cum[-1] / 2.0))])
    return median, oblique


def _rotate(gray: U8, angle_deg: float) -> tuple[U8, F64]:
    """Rotate so that lines at ``angle_deg`` become axis-parallel; the canvas grows to fit."""
    h, w = gray.shape
    centre = ((w - 1) / 2.0, (h - 1) / 2.0)
    m = cv2.getRotationMatrix2D(centre, angle_deg, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    new_w = math.ceil(h * sin + w * cos)
    new_h = math.ceil(h * cos + w * sin)
    m[0, 2] += (new_w - 1) / 2.0 - centre[0]
    m[1, 2] += (new_h - 1) / 2.0 - centre[1]
    background = int(np.percentile(gray, 90))  # pad with the paper colour
    out = cv2.warpAffine(
        gray,
        m,
        (new_w, new_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=background,
    )
    full = np.vstack([np.asarray(m, dtype=np.float64), [0.0, 0.0, 1.0]])
    return np.asarray(out, dtype=np.uint8), full


def _non_uniform(gray: U8) -> bool:
    """True if the background level (per-tile 90th percentile) varies a lot."""
    h, w = gray.shape
    if min(h, w) < 4 * _TILES:
        return False
    levels: list[float] = []
    for i in range(_TILES):
        for j in range(_TILES):
            tile = gray[
                i * h // _TILES : (i + 1) * h // _TILES, j * w // _TILES : (j + 1) * w // _TILES
            ]
            levels.append(float(np.percentile(tile, 90)))
    return max(levels) - min(levels) > _NON_UNIFORM_SPREAD


def binarise(gray: U8) -> tuple[U8, bool]:
    """Ink mask (255 = ink): Otsu, or adaptive Gaussian when the background is non-uniform."""
    if _non_uniform(gray):
        block = max(15, (min(gray.shape) // 20) | 1)
        out = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block, 10
        )
        return np.asarray(out, dtype=np.uint8), True
    return _otsu_ink(gray), False


def preprocess(image: U8) -> Preprocessed | None:
    """Run step 1 on a ``uint8`` grey image; ``None`` when there is no dark content."""
    h0, w0 = image.shape
    warnings: list[str] = []
    gray = image
    scale = 1.0
    if h0 * w0 > MAX_WORK_PIXELS:
        scale = math.sqrt(MAX_WORK_PIXELS / (h0 * w0))
        size = (max(1, int(w0 * scale)), max(1, int(h0 * scale)))
        scale = size[0] / w0
        gray = np.asarray(cv2.resize(image, size, interpolation=cv2.INTER_AREA), dtype=np.uint8)
        warnings.append(f"image downscaled by {scale:.4f} (memory cap {MAX_WORK_PIXELS} px)")
    if float(np.median(gray)) < _INVERTED_MEDIAN:
        gray = np.asarray(255 - gray, dtype=np.uint8)
        warnings.append("dark background: image inverted")
    rotation: F64 = np.eye(3, dtype=np.float64)
    skew, oblique = estimate_skew(gray) if min(gray.shape) >= 16 else (0.0, 0)
    if abs(skew) > SKEW_MIN_DEG:
        gray, rotation = _rotate(gray, skew)
        warnings.append(f"deskewed by {skew:.2f} deg")
    else:
        skew = 0.0
    if min(gray.shape) >= 3:
        gray = np.asarray(cv2.medianBlur(gray, 3), dtype=np.uint8)
    binary, adaptive = binarise(gray)
    if adaptive:
        warnings.append("non-uniform background: adaptive threshold")
    if not np.any(binary):
        return None
    n, _labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 1:  # pragma: no cover - np.any(binary) guarantees a component
        return None
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, bw, bh = (int(v) for v in stats[k, :4])
    margin = max(2, round(CROP_MARGIN * max(bw, bh)))
    x0, y0, x1, y1 = x - margin, y - margin, x + bw + margin, y + bh + margin
    gh, gw = gray.shape
    pad = (max(0, -y0), max(0, y1 - gh), max(0, -x0), max(0, x1 - gw))
    if any(pad):
        background = int(np.percentile(gray, 90))
        gray = np.asarray(
            cv2.copyMakeBorder(gray, *pad, cv2.BORDER_CONSTANT, value=background),
            dtype=np.uint8,
        )
        binary = np.asarray(
            cv2.copyMakeBorder(binary, *pad, cv2.BORDER_CONSTANT, value=0), dtype=np.uint8
        )
    cy, cx = y0 + pad[0], x0 + pad[2]
    gray_c = np.ascontiguousarray(gray[cy : cy + (y1 - y0), cx : cx + (x1 - x0)])
    bin_c = np.ascontiguousarray(binary[cy : cy + (y1 - y0), cx : cx + (x1 - x0)])
    transform = Transform(scale=scale, rotation=rotation, offset=(x0, y0))
    return Preprocessed(
        gray=gray_c,
        binary=bin_c,
        transform=transform,
        skew_deg=skew,
        adaptive=adaptive,
        oblique_lines=oblique,
        content_share=min(1.0, (bw * bh) / float(gh * gw)),
        warnings=warnings,
    )
