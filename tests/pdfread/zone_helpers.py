"""Synthetic zone sheets (Archicad-style filled rooms) for the Ticket X.2 tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pymupdf
from pdf_helpers import PT_PER_M

COLORS = [(0.8, 0.9, 1.0), (1.0, 0.85, 0.7), (0.75, 1.0, 0.75), (1.0, 0.8, 0.9)]
CW, CH = 4.0, 3.5  # cell size (m)
GAP = 0.1


def pt(ox: float, oy: float, x: float, y: float) -> tuple[float, float]:
    return (ox + x * PT_PER_M, oy + y * PT_PER_M)


def zone_rect(ox: float, oy: float, i: int, j: int) -> pymupdf.Rect:
    x, y = i * CW, j * CH
    return pymupdf.Rect(*pt(ox, oy, x + GAP, y + GAP), *pt(ox, oy, x + CW - GAP, y + CH - GAP))


def area_of(k: int) -> float:
    return 11.0 + 1.37 * k


def area_str(k: int) -> str:
    return f"{area_of(k):.2f}".replace(".", ",") + " m²"


def draw_zone_grid(
    page: Any,
    ox: float,
    oy: float,
    ncols: int = 4,
    nrows: int = 3,
    *,
    rotate: bool = False,
    frame: bool = False,
    duplicate: bool = False,
    walls: bool = True,
    start: int = 0,
) -> list[pymupdf.Rect]:
    """A grid of filled rooms with written areas; walls are single strokes with door gaps."""
    sh = page.new_shape()
    if frame:
        sh.draw_rect(pymupdf.Rect(*pt(ox, oy, 0, 0), *pt(ox, oy, ncols * CW, nrows * CH)))
        sh.finish(fill=(0.9, 0.9, 0.9), color=None, width=0)
    rects: list[pymupdf.Rect] = []
    for j in range(nrows):
        for i in range(ncols):
            k = start + j * ncols + i
            r = zone_rect(ox, oy, i, j)
            rects.append(r)
            for _ in range(2 if duplicate else 1):
                sh.draw_rect(r)
                sh.finish(fill=COLORS[k % 4], color=None, width=0)
    sh.commit()
    if walls:
        w = page.new_shape()
        for i in range(ncols + 1):  # verticals broken by a door gap in each row
            for j in range(nrows):
                x, y = i * CW, j * CH
                w.draw_line(pt(ox, oy, x, y), pt(ox, oy, x, y + 1.0))
                w.draw_line(pt(ox, oy, x, y + 2.0), pt(ox, oy, x, y + CH))
        for j in range(nrows + 1):
            for i in range(ncols):
                x, y = i * CW, j * CH
                w.draw_line(pt(ox, oy, x, y), pt(ox, oy, x + 1.0, y))
                w.draw_line(pt(ox, oy, x + 2.0, y), pt(ox, oy, x + CW, y))
        w.finish(width=1.5, color=(0, 0, 0), closePath=False)
        w.commit()
    for n, r in enumerate(rects):
        text = area_str(start + n)
        if rotate:
            page.insert_text((r.x0 + 30, r.y1 - 10), text, fontname="helv", fontsize=8, rotate=90)
        else:
            cx, cy = (r.x0 + r.x1) / 2 - 20, (r.y0 + r.y1) / 2
            page.insert_text((cx, cy), text, fontname="helv", fontsize=8)
    return rects


def sheet(build: Callable[[Any], None]) -> Callable[[Any], None]:
    def go(page: Any) -> None:
        build(page)
        page.insert_text((30, 30), "ÉCHELLE 1:100", fontname="helv", fontsize=9)

    return go
