"""SVG of the cell diagram (Ticket R.9): one colour per room type, cores hatched, the main
entrance marked, the unclaimed cells (circulation reserve) light grey, room ids at the
centroids. Plain SVG 1.1 written by hand; the bytes are deterministic for a diagram. Cell
``(cx, cy)`` is drawn at ``(cx, -cy - 1)`` (y up like the plans), one unit per cell."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from ale.topology.cellgrow import CORE_CELL, FREE, CellDiagram

__all__ = ["PALETTE", "diagram_svg", "write_diagram_svg"]

PALETTE: tuple[str, ...] = (
    "#f4d35e",
    "#9ad1d4",
    "#ee964b",
    "#a3c4a0",
    "#c9a0dc",
    "#f08080",
    "#8fb8de",
    "#d9c5a0",
    "#b5b5d6",
    "#e6b8a2",
    "#a0d9b4",
    "#d6d6a0",
)
RESERVE_FILL = "#eeeeee"
_PX_PER_CELL = 12


def _label(room: str) -> str:
    return escape(room)


def diagram_svg(diagram: CellDiagram) -> str:
    """SVG text of ``diagram``."""
    colours = {
        t: PALETTE[i % len(PALETTE)] for i, t in enumerate(sorted(set(diagram.types.values())))
    }
    w, h = diagram.width, diagram.height
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 {-h} {w} {h}" '
        f'width="{w * _PX_PER_CELL}" height="{h * _PX_PER_CELL}">',
        '<defs><pattern id="core-hatch" width="0.4" height="0.4" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><rect width="0.4" height="0.4" fill="#ffffff"/>'
        '<line x1="0" y1="0" x2="0" y2="0.4" stroke="#444444" '
        'stroke-width="0.12"/></pattern></defs>',
        f'<rect x="0" y="{-h}" width="{w}" height="{h}" fill="#ffffff"/>',
    ]
    for cy, row in enumerate(diagram.owner):
        for cx, v in enumerate(row):
            if v == CORE_CELL:
                fill = "url(#core-hatch)"
            elif v == FREE:
                fill = RESERVE_FILL
            elif v >= 0:
                fill = colours[diagram.types[diagram.rooms[v]]]
            else:
                continue
            out.append(
                f'<rect x="{cx}" y="{-cy - 1}" width="1" height="1" fill="{fill}" '
                'stroke="#ffffff" stroke-width="0.05"/>'
            )
    for room in diagram.rooms:
        if not diagram.cells[room]:
            continue
        sx = sum(c[0] for c in diagram.cells[room]) / len(diagram.cells[room]) + 0.5
        sy = sum(c[1] for c in diagram.cells[room]) / len(diagram.cells[room]) + 0.5
        out.append(
            f'<text x="{sx:.2f}" y="{-sy:.2f}" font-size="0.9" text-anchor="middle" '
            f'font-family="sans-serif">{_label(room)}</text>'
        )
    if diagram.entrance is not None:
        ex, ey = diagram.entrance
        out.append(
            f'<circle id="entrance" cx="{ex + 0.5}" cy="{-ey - 0.5}" r="0.7" fill="#d62728" '
            'stroke="#ffffff" stroke-width="0.15"/>'
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def write_diagram_svg(diagram: CellDiagram, path: Path | str) -> Path:
    """Write :func:`diagram_svg` to ``path`` (UTF-8, LF) and return the path."""
    target = Path(path)
    target.write_text(diagram_svg(diagram), encoding="utf-8", newline="\n")
    return target
