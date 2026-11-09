"""Conversion between VLM normalised boxes and plan native coordinates.

This module is the **only** place that converts between the VLM box convention
(``[ymin, xmin, ymax, xmax]``, integers normalised to 0..1000 of the image height/width,
origin at the top-left corner of the image) and the plan's native coordinates.

Rendering model: the plan's native ``extent`` ``(x0, y0, x1, y1)`` is drawn into the image
with a **uniform** scale ``s = min(W / (x1 - x0), H / (y1 - y0))`` (pixels per native unit)
and centred, so a mismatch of aspect ratios leaves equal margins on both sides of one axis.
Image rows grow downwards: for a ``Frame.Y_UP`` plan the top image row is ``y1``; for a
``Frame.Y_DOWN`` plan it is ``y0``.

Arithmetic is exact (``fractions.Fraction``) and rounded to float once, so the corners of
the extent map exactly to and from the normalised coordinates.
"""

from __future__ import annotations

import struct
from fractions import Fraction

from ale.contracts.enums import Frame

__all__ = [
    "NORM_MAX",
    "Extent",
    "NativeBox",
    "NormBox",
    "native_to_normalized",
    "normalized_to_native",
    "png_size",
]

#: Upper bound of the normalised coordinate range (0..NORM_MAX).
NORM_MAX = 1000

Extent = tuple[float, float, float, float]
"""Native extent ``(xmin, ymin, xmax, ymax)``."""
NativeBox = tuple[float, float, float, float]
"""Native box ``(xmin, ymin, xmax, ymax)``."""
NormBox = tuple[float, float, float, float]
"""Normalised box ``(ymin, xmin, ymax, xmax)`` in 0..NORM_MAX (image top-left origin)."""

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(data: bytes) -> tuple[int, int] | None:
    """``(width, height)`` in pixels read from a PNG header, ``None`` if not a valid PNG."""
    if len(data) < 24 or data[:8] != _PNG_SIGNATURE or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        return None
    return int(width), int(height)


class _Mapping:
    """Exact affine mapping between image pixels and native coordinates."""

    def __init__(self, image_size: tuple[int, int], extent: Extent, frame: Frame) -> None:
        w, h = image_size
        if w <= 0 or h <= 0:
            raise ValueError(f"image size must be positive, got {image_size}")
        x0, y0, x1, y1 = (Fraction(v) for v in extent)
        ew, eh = x1 - x0, y1 - y0
        if ew <= 0 or eh <= 0:
            raise ValueError(f"extent must have positive width and height, got {extent}")
        self.w, self.h = Fraction(w), Fraction(h)
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.s = min(self.w / ew, self.h / eh)
        self.off_x = (self.w - ew * self.s) / 2
        self.off_y = (self.h - eh * self.s) / 2
        self.y_up = Frame(frame) is Frame.Y_UP

    def pixel_to_native(self, px: Fraction, py: Fraction) -> tuple[Fraction, Fraction]:
        x = self.x0 + (px - self.off_x) / self.s
        d = (py - self.off_y) / self.s
        y = self.y1 - d if self.y_up else self.y0 + d
        return x, y

    def native_to_pixel(self, x: Fraction, y: Fraction) -> tuple[Fraction, Fraction]:
        px = self.off_x + (x - self.x0) * self.s
        d = (self.y1 - y) if self.y_up else (y - self.y0)
        py = self.off_y + d * self.s
        return px, py


def normalized_to_native(
    bbox: tuple[float, float, float, float],
    *,
    image_size: tuple[int, int],
    extent: Extent,
    frame: Frame,
) -> NativeBox:
    """Native ``(xmin, ymin, xmax, ymax)`` of a normalised ``[ymin, xmin, ymax, xmax]`` box.

    ``image_size`` is ``(width, height)`` in pixels. Raises ``ValueError`` on a
    non-positive image size or a degenerate extent.
    """
    m = _Mapping(image_size, extent, frame)
    n_ymin, n_xmin, n_ymax, n_xmax = (Fraction(v) for v in bbox)
    ax, ay = m.pixel_to_native(n_xmin * m.w / NORM_MAX, n_ymin * m.h / NORM_MAX)
    bx, by = m.pixel_to_native(n_xmax * m.w / NORM_MAX, n_ymax * m.h / NORM_MAX)
    return (float(min(ax, bx)), float(min(ay, by)), float(max(ax, bx)), float(max(ay, by)))


def native_to_normalized(
    box: NativeBox,
    *,
    image_size: tuple[int, int],
    extent: Extent,
    frame: Frame,
) -> NormBox:
    """Normalised ``(ymin, xmin, ymax, xmax)`` (floats, 0..1000 inside the image) of a box.

    Inverse of :func:`normalized_to_native`. Raises ``ValueError`` like it.
    """
    m = _Mapping(image_size, extent, frame)
    x_a, y_a, x_b, y_b = (Fraction(v) for v in box)
    pax, pay = m.native_to_pixel(x_a, y_a)
    pbx, pby = m.native_to_pixel(x_b, y_b)
    nx = sorted((pax * NORM_MAX / m.w, pbx * NORM_MAX / m.w))
    ny = sorted((pay * NORM_MAX / m.h, pby * NORM_MAX / m.h))
    return (float(ny[0]), float(nx[0]), float(ny[1]), float(nx[1]))
