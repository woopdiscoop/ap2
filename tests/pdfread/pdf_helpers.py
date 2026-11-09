"""PDF page builders with declared ground truth for the Ticket 1.3 tests.

Reference plan at 1:100 (1 m = 72 / 2.54 pt ≈ 28.35 pt), drawn on an A4 page in PyMuPDF
page space (y down). Wall centreline rectangle 10 m x 6 m, walls 0.2 m thick, one
partition on x = 4 m with a 0.9 m door (gap y = 2.0..2.9 m, hinge at the jamb on the
right face, leaf and quarter arc of radius 0.9 m into the right room).
Rooms: left 3.8 x 5.8 m = 22.04 m² ("BUREAU"), right 5.8 x 5.8 m = 33.64 m²
("S. RÉUNION").
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pymupdf

from ale.contracts.config import AleConfig
from ale.pdfread import PdfReadResult, read_pdf_page

SHA = hashlib.sha256(b"ale pdf test").hexdigest()
DENOM = 100
M_PER_PT = DENOM * 0.0254 / 72.0
PT_PER_M = 1.0 / M_PER_PT
ORIGIN = (100.0, 150.0)  # page position (pt) of the plan's (0 m, 0 m)
T = 0.2  # wall thickness (m)
GT_AREAS_M2 = {"office": 3.8 * 5.8, "meeting_room": 5.8 * 5.8}
DOOR_M = 0.9
DOOR_Y = (2.0, 2.9)

Rect = tuple[float, float, float, float]  # x0, y0, x1, y1 in metres


def P(x: float, y: float) -> tuple[float, float]:
    """Page point (pt) of plan coordinates (m)."""
    return (ORIGIN[0] + x * PT_PER_M, ORIGIN[1] + y * PT_PER_M)


def _rect_lines(shape: Any, r: Rect) -> None:
    x0, y0, x1, y1 = r
    pts = [P(x0, y0), P(x1, y0), P(x1, y1), P(x0, y1)]
    for i in range(4):
        shape.draw_line(pts[i], pts[(i + 1) % 4])


def _line(shape: Any, a: tuple[float, float], b: tuple[float, float]) -> None:
    shape.draw_line(P(*a), P(*b))


def draw_plan_lines(page: Any) -> None:
    """Reference plan as parallel wall faces (thin strokes)."""
    h = T / 2.0
    sh = page.new_shape()
    _rect_lines(sh, (-h, -h, 10 + h, 6 + h))  # outer faces
    # left room inner faces (right side broken by the door)
    _line(sh, (h, h), (4 - h, h))
    _line(sh, (h, h), (h, 6 - h))
    _line(sh, (h, 6 - h), (4 - h, 6 - h))
    _line(sh, (4 - h, h), (4 - h, DOOR_Y[0]))
    _line(sh, (4 - h, DOOR_Y[1]), (4 - h, 6 - h))
    # right room inner faces
    _line(sh, (4 + h, h), (10 - h, h))
    _line(sh, (10 - h, h), (10 - h, 6 - h))
    _line(sh, (4 + h, 6 - h), (10 - h, 6 - h))
    _line(sh, (4 + h, h), (4 + h, DOOR_Y[0]))
    _line(sh, (4 + h, DOOR_Y[1]), (4 + h, 6 - h))
    # jambs
    _line(sh, (4 - h, DOOR_Y[0]), (4 + h, DOOR_Y[0]))
    _line(sh, (4 - h, DOOR_Y[1]), (4 + h, DOOR_Y[1]))
    sh.finish(width=0.5, color=(0, 0, 0), closePath=False)
    sh.commit()


def wall_rects() -> list[Rect]:
    """Reference plan walls as 6 rectangles: one per façade, the partition split by the door."""
    h = T / 2.0
    return [
        (-h, -h, 10 + h, h),  # top
        (-h, 6 - h, 10 + h, 6 + h),  # bottom
        (-h, h, h, 6 - h),  # left
        (10 - h, h, 10 + h, 6 - h),  # right
        (4 - h, -h, 4 + h, DOOR_Y[0]),  # partition, upper piece
        (4 - h, DOOR_Y[1], 4 + h, 6 + h),  # partition, lower piece
    ]


def draw_plan_filled(page: Any) -> None:
    """Reference plan as filled wall rectangles."""
    sh = page.new_shape()
    for x0, y0, x1, y1 in wall_rects():
        sh.draw_rect(pymupdf.Rect(*P(x0, y0), *P(x1, y1)))
    sh.finish(fill=(0, 0, 0), color=None, width=0)
    sh.commit()


def draw_door(page: Any) -> None:
    """Door leaf (thin line) and quarter arc into the right room."""
    h = T / 2.0
    hinge = P(4 + h, DOOR_Y[0])
    tip = P(4 + h + DOOR_M, DOOR_Y[0])
    sh = page.new_shape()
    sh.draw_line(hinge, tip)
    sh.finish(width=0.3, color=(0, 0, 0), closePath=False)
    # from the leaf tip, 90° towards the closed position (4 + h, DOOR_Y[1])
    sh.draw_sector(hinge, tip, -90, fullSector=False)
    sh.finish(width=0.3, color=(0, 0, 0), closePath=False)
    sh.commit()


def draw_labels(page: Any) -> None:
    page.insert_text(P(1.2, 3.0), "BUREAU", fontname="helv", fontsize=8)
    page.insert_text(P(6.0, 3.0), "S. RÉUNION", fontname="helv", fontsize=8)
    page.insert_text(P(6.0, 3.6), "33,64 m²", fontname="helv", fontsize=7)


def draw_title(
    page: Any, text: str = "ÉCHELLE 1:100", at: tuple[float, float] = (0.0, 7.2)
) -> None:
    page.insert_text(P(*at), text, fontname="helv", fontsize=9)


def save_page(path: Path, build: Callable[[Any], None]) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    build(page)
    doc.save(path)
    doc.close()
    return path


def reference_page(
    *, filled: bool = False, title: str | None = "ÉCHELLE 1:100"
) -> Callable[[Any], None]:
    def build(page: Any) -> None:
        (draw_plan_filled if filled else draw_plan_lines)(page)
        draw_door(page)
        draw_labels(page)
        if title is not None:
            draw_title(page, title)

    return build


def read(path: Path, page: int = 0) -> PdfReadResult:
    return read_pdf_page(path, page, source_sha256=SHA, config=AleConfig())


def text_page(page: Any) -> None:
    for i in range(40):
        page.insert_text(
            (60, 60 + 18 * i), f"Ligne de texte {i}: rapport 1/12, version 2.1", fontsize=10
        )


def bar_chart_page(page: Any) -> None:
    """Bar chart: axes, horizontal grid lines, 10 filled bars 20 pt wide, legend text."""
    sh = page.new_shape()
    x0, y0, x1, y1 = 80.0, 150.0, 520.0, 650.0
    sh.draw_line((x0, y0), (x0, y1))
    sh.draw_line((x0, y1), (x1, y1))
    sh.finish(width=1.0, color=(0, 0, 0), closePath=False)
    for k in range(1, 11):
        y = y1 - 45.0 * k
        sh.draw_line((x0, y), (x1, y))
    sh.finish(width=0.3, color=(0.6, 0.6, 0.6), closePath=False)
    rng = random.Random(3)
    for k in range(10):
        bx = x0 + 20.0 + 42.0 * k
        top = y1 - rng.uniform(150.0, 480.0)
        sh.draw_rect(pymupdf.Rect(bx, top, bx + 20.0, y1))
    sh.finish(fill=(0.2, 0.4, 0.8), color=(0, 0, 0), width=0.5)
    sh.commit()
    page.insert_text((80, 120), "Surfaces par niveau (m2)", fontsize=12)
    for k in range(10):
        page.insert_text((x0 + 22.0 + 42.0 * k, y1 + 14), f"N{k}", fontsize=8)


def random_segments_page(n: int, seed: int = 0) -> Callable[[Any], None]:
    def build(page: Any) -> None:
        rng = random.Random(seed)
        sh = page.new_shape()
        for _ in range(n):
            x, y = rng.uniform(20, 575), rng.uniform(20, 822)
            dx, dy = rng.uniform(-60, 60), rng.uniform(-60, 60)
            sh.draw_line((x, y), (x + dx, y + dy))
        sh.finish(width=0.5, color=(0, 0, 0), closePath=False)
        sh.commit()

    return build
