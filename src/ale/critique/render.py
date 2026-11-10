"""PNG rendering of a layout for the visual critique (Pillow, extra ``raster``).

Rooms are filled with their zone colour (same palette as ``preview.svg``), circulation
is light grey, every room and circulation strip carries its instance id, and a north
arrow sits in the top-right corner. The long side of the image is :data:`LONG_SIDE`
pixels. The output is deterministic: same layout, same bytes.
"""

from __future__ import annotations

import io
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ale.contracts.enums import MacroZone
from ale.contracts.geometry import ModuleRect
from ale.contracts.models import Layout
from ale.export.svg import CIRC_FILL, ZONE_COLOURS

if TYPE_CHECKING:
    from PIL import ImageDraw

__all__ = ["LONG_SIDE", "Box", "RenderError", "RenderedLayout", "render_layout"]

#: Long side of the rendered image, in pixels (the API's native image limit).
LONG_SIDE: Final = 1568
_MARGIN: Final = 72
_FONT_SIZES: Final = (22, 18, 15, 12, 10, 8, 6)
_UNKNOWN_FILL: Final = "#dddddd"
_RESIDUE_FILL: Final = "#f6dcdc"
_ROOM_STROKE: Final = "#333333"
_CIRC_STROKE: Final = "#bbbbbb"
_CIRC_TEXT: Final = "#666666"

#: ``(x0, y0, x1, y1)`` in image pixels, x right, y down, upper bounds exclusive.
Box = tuple[int, int, int, int]


class RenderError(RuntimeError):
    """The layout cannot be rendered (Pillow missing)."""


@dataclass(frozen=True)
class RenderedLayout:
    """The PNG, its ``(width, height)`` and the pixel boxes of rooms and labels.

    ``room_boxes`` / ``label_boxes`` are keyed by instance id (rooms and circulation);
    every label box lies inside the box of its room.
    """

    png: bytes
    size: tuple[int, int]
    room_boxes: dict[str, Box]
    label_boxes: dict[str, Box]


def render_layout(
    layout: Layout,
    zones: Mapping[str, MacroZone | None] | None = None,
    *,
    north_angle_deg: float = 0.0,
) -> RenderedLayout:
    """Render ``layout``; ``zones`` maps room instance ids to their macro-zone.

    ``north_angle_deg`` is the direction of true north, clockwise from the drawing +y
    axis (as in ``SiteSpec``).
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:  # pragma: no cover - Pillow is installed in CI
        raise RenderError("Pillow n'est pas installé : extra « raster »") from exc

    zone_of = zones or {}
    xs = [p[0] for p in layout.footprint.exterior]
    ys = [p[1] for p in layout.footprint.exterior]
    bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
    w_mod, h_mod = bx1 - bx0, by1 - by0
    scale = (LONG_SIDE - 2 * _MARGIN) / max(w_mod, h_mod)
    width = round(w_mod * scale) + 2 * _MARGIN
    height = round(h_mod * scale) + 2 * _MARGIN

    def px(x: int) -> int:
        return _MARGIN + round((x - bx0) * scale)

    def py(y: int) -> int:
        return _MARGIN + round((by1 - y) * scale)

    def box(r: ModuleRect) -> Box:
        return (px(r.x), py(r.y2()), px(r.x2()), py(r.y))

    img = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(img)
    room_boxes: dict[str, Box] = {}
    label_boxes: dict[str, Box] = {}

    for r in layout.residue:
        draw.rectangle(box(r), fill=_RESIDUE_FILL)
    for c in layout.circulation:
        room_boxes[c.instance_id] = box(c.rect)
        draw.rectangle(box(c.rect), fill=CIRC_FILL, outline=_CIRC_STROKE, width=1)
    for p in layout.rooms:
        zone = zone_of.get(p.instance_id)
        fill = ZONE_COLOURS[zone] if zone is not None else _UNKNOWN_FILL
        room_boxes[p.instance_id] = box(p.rect)
        draw.rectangle(box(p.rect), fill=fill, outline=_ROOM_STROKE, width=2)
    outline = [(px(x), py(y)) for x, y in layout.footprint.exterior]
    draw.line([*outline, outline[0]], fill="#000000", width=4)

    circ_ids = {c.instance_id for c in layout.circulation}
    for iid in sorted(room_boxes):
        rx0, ry0, rx1, ry1 = room_boxes[iid]
        rw, rh = rx1 - rx0, ry1 - ry0
        # The label is drawn on a crop of its room, so it can never leave the rectangle.
        tile = img.crop((rx0, ry0, rx1, ry1))
        tile_draw = ImageDraw.Draw(tile)
        for size in _FONT_SIZES:
            font = ImageFont.load_default(size=size)
            left, top, right, bottom = tile_draw.textbbox((0, 0), iid, font=font)
            tw, th = right - left, bottom - top
            if tw + 4 <= rw and th + 4 <= rh:
                break
        ox = (rw - tw) / 2 - left
        oy = (rh - th) / 2 - top
        bbox = tile_draw.textbbox((ox, oy), iid, font=font)
        colour = _CIRC_TEXT if iid in circ_ids else "#000000"
        tile_draw.text((ox, oy), iid, font=font, fill=colour)
        img.paste(tile, (rx0, ry0))
        label_boxes[iid] = (
            rx0 + max(0, math.floor(bbox[0])),
            ry0 + max(0, math.floor(bbox[1])),
            rx0 + min(rw, math.ceil(bbox[2])),
            ry0 + min(rh, math.ceil(bbox[3])),
        )

    _north_arrow(ImageDraw.Draw(img), width, north_angle_deg)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return RenderedLayout(
        png=out.getvalue(), size=(width, height), room_boxes=room_boxes, label_boxes=label_boxes
    )


def _north_arrow(draw: ImageDraw.ImageDraw, width: int, angle_deg: float) -> None:
    """Arrow to true north (``angle_deg`` clockwise from image "up"), top-right margin."""
    from PIL import ImageFont

    cx, cy = width - _MARGIN / 2, _MARGIN / 2
    a = math.radians(angle_deg)
    dx, dy = math.sin(a), -math.cos(a)
    half = 14.0
    tip = (cx + dx * half, cy + dy * half)
    tail = (cx - dx * half, cy - dy * half)
    nx, ny = -dy, dx
    head = half * 0.7
    left = (tip[0] - dx * head + nx * head * 0.5, tip[1] - dy * head + ny * head * 0.5)
    right = (tip[0] - dx * head - nx * head * 0.5, tip[1] - dy * head - ny * head * 0.5)
    draw.line([tail, tip], fill="#000000", width=3)
    draw.polygon([tip, left, right], fill="#000000")
    label = (cx + dx * (half + 11), cy + dy * (half + 11))
    draw.text(label, "N", font=ImageFont.load_default(size=16), fill="#000000", anchor="mm")
