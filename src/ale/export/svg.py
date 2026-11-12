"""``preview.svg``: plain SVG 1.1 written by hand (no dependency).

The ``viewBox`` is the footprint bounding box in metres (site drawing axes) with y flipped:
a drawing point ``(x, y)`` is written at SVG ``(x, -y)``. Stroke widths and font sizes are
in metres.
"""

from __future__ import annotations

import math
from xml.sax.saxutils import escape, quoteattr

from ale.contracts.enums import MacroZone
from ale.contracts.models import Layout
from ale.export.report import MetricFrame, fr_num, room_infos
from ale.program.models import PreparedInput

__all__ = ["CIRC_FILL", "CIRC_STROKE", "ZONE_COLOURS", "render_svg", "svg_num"]

ZONE_COLOURS: dict[MacroZone, str] = {
    MacroZone.PUBLIC: "#f4d35e",
    MacroZone.ADMINISTRATIVE: "#9ad1d4",
    MacroZone.SERVICES: "#c8c8c8",
}
CIRC_FILL = "#eeeeee"
CIRC_STROKE = "#ffffff"
_UNKNOWN_FILL = "#dddddd"
_FONT_SIZE = 0.25
_PX_PER_M = 50


def svg_num(v: float) -> str:
    """A coordinate with at most 4 decimals, trailing zeros stripped (``-0`` → ``0``)."""
    text = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _rect(x0: float, y0: float, x1: float, y1: float) -> str:
    return (
        f'x="{svg_num(x0)}" y="{svg_num(-y1)}" '
        f'width="{svg_num(x1 - x0)}" height="{svg_num(y1 - y0)}"'
    )


def render_svg(layout: Layout, prepared: PreparedInput) -> str:
    """SVG text of the preview."""
    frame = MetricFrame(layout.grid.module_mm, prepared.footprint.origin_m)
    bx0, by0, bx1, by1 = frame.bbox(layout.footprint)
    w, h = bx1 - bx0, by1 - by0
    size = min(w, h)
    thin = svg_num(max(size / 500, 0.01))
    thick = svg_num(max(size / 200, 0.02))
    out: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'viewBox="{svg_num(bx0)} {svg_num(-by1)} {svg_num(w)} {svg_num(h)}" '
        f'width="{svg_num(w * _PX_PER_M)}" height="{svg_num(h * _PX_PER_M)}">',
    ]
    infos = room_infos(layout, prepared)
    out.append('<g id="rooms">')
    for info in infos:
        fill = ZONE_COLOURS[info.zone] if info.zone is not None else _UNKNOWN_FILL
        x0, y0 = frame.x(info.rect.x), frame.y(info.rect.y)
        x1, y1 = frame.x(info.rect.x2()), frame.y(info.rect.y2())
        out.append(
            f"<rect id={quoteattr('room-' + info.instance_id)} {_rect(x0, y0, x1, y1)} "
            f'fill="{fill}" stroke="#333333" stroke-width="{thin}"/>'
        )
    out.append("</g>")
    out.append('<g id="circulation">')
    for c in layout.circulation:
        x0, y0 = frame.x(c.rect.x), frame.y(c.rect.y)
        x1, y1 = frame.x(c.rect.x2()), frame.y(c.rect.y2())
        out.append(
            f"<rect id={quoteattr('circ-' + c.instance_id)} {_rect(x0, y0, x1, y1)} "
            f'fill="{CIRC_FILL}" stroke="{CIRC_STROKE}" stroke-width="{thin}"/>'
        )
    out.append("</g>")
    out.extend(_solids_svg(layout, prepared, frame, thin))
    pts = " ".join(
        f"{svg_num(x)},{svg_num(-y)}"
        for x, y in (frame.point(p) for p in layout.footprint.exterior)
    )
    out.append(
        f'<polygon id="footprint" points="{pts}" fill="none" stroke="#000000" '
        f'stroke-width="{thick}"/>'
    )
    out.append(
        f'<g id="labels" font-family="sans-serif" font-size="{svg_num(_FONT_SIZE)}" '
        'text-anchor="middle" fill="#000000">'
    )
    for info in infos:
        cx, cy = frame.rect_centre(info.rect)
        sx, sy = svg_num(cx), svg_num(-cy)
        out.append(
            f'<text x="{sx}" y="{sy}">'
            f'<tspan x="{sx}" dy="-0.05">{escape(info.name)}</tspan>'
            f'<tspan x="{sx}" dy="{svg_num(_FONT_SIZE * 1.2)}">'
            f"{escape(fr_num(info.placed_m2))} m²</tspan></text>"
        )
    out.append("</g>")
    out.append(_north_arrow(bx1, by1, size, prepared.site.north_angle_deg, thick))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _solids_svg(
    layout: Layout, prepared: PreparedInput, frame: MetricFrame, thin: str
) -> list[str]:
    """Hatched solids with the core id, and the fixed rooms (Ticket M.2); empty without solids."""
    if not layout.footprint.solids:
        return []
    names = [c.id for c in prepared.site.cores]
    out = [
        "<defs>",
        '<pattern id="solid-hatch" width="0.3" height="0.3" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)">'
        f'<line x1="0" y1="0" x2="0" y2="0.3" stroke="#555555" stroke-width="{thin}"/></pattern>',
        "</defs>",
        '<g id="solids">',
    ]
    for k, ring in enumerate(layout.footprint.solids):
        pts = [frame.point(p) for p in ring]
        coords = " ".join(f"{svg_num(x)},{svg_num(-y)}" for x, y in pts)
        label = names[k] if k < len(names) else f"solid_{k}"
        cx = sum(q[0] for q in pts) / len(pts)
        cy = sum(q[1] for q in pts) / len(pts)
        out.append(
            f'<polygon id={quoteattr("solid-" + label)} class="solid" points="{coords}" '
            f'fill="url(#solid-hatch)" stroke="#333333" stroke-width="{thin}"/>'
        )
        out.append(
            f'<text class="solid-label" x="{svg_num(cx)}" y="{svg_num(-cy)}" '
            f'font-family="sans-serif" font-size="{svg_num(_FONT_SIZE)}" '
            f'text-anchor="middle">{escape(label)}</text>'
        )
    out.append("</g>")
    out.append('<g id="fixed">')
    for room in layout.fixed:
        x0, y0 = frame.x(room.rect.x), frame.y(room.rect.y)
        x1, y1 = frame.x(room.rect.x2()), frame.y(room.rect.y2())
        out.append(
            f'<rect id={quoteattr("fixed-" + room.instance_id)} class="fixed" '
            f'{_rect(x0, y0, x1, y1)} fill="#d9c7e8" stroke="#333333" stroke-width="{thin}"/>'
        )
    out.append("</g>")
    return out


def _north_arrow(x1: float, y1: float, size: float, angle_deg: float, stroke: str) -> str:
    """Arrow pointing to true north (``angle_deg`` clockwise from drawing +y), top-right."""
    length = size * 0.08
    cx, cy = x1 - length, -(y1 - length)  # SVG coordinates of the arrow centre
    a = math.radians(angle_deg)
    dx, dy = math.sin(a), -math.cos(a)  # unit vector to north, SVG axes (y down)
    half = length / 2
    tip = (cx + dx * half, cy + dy * half)
    tail = (cx - dx * half, cy - dy * half)
    px, py = -dy, dx
    head = length * 0.25
    left = (tip[0] - dx * head + px * head * 0.5, tip[1] - dy * head + py * head * 0.5)
    right = (tip[0] - dx * head - px * head * 0.5, tip[1] - dy * head - py * head * 0.5)

    def p(q: tuple[float, float]) -> str:
        return f"{svg_num(q[0])},{svg_num(q[1])}"

    label = (tip[0] + dx * head, tip[1] + dy * head)
    return (
        f'<g id="north-arrow" data-north-angle-deg="{svg_num(angle_deg)}">'
        f'<path d="M {p(tail)} L {p(tip)}" stroke="#000000" stroke-width="{stroke}" fill="none"/>'
        f'<path d="M {p(tip)} L {p(left)} L {p(right)} Z" fill="#000000"/>'
        f'<text x="{svg_num(label[0])}" y="{svg_num(label[1])}" '
        f'font-size="{svg_num(_FONT_SIZE)}" text-anchor="middle" '
        f'dominant-baseline="middle">N</text></g>'
    )
