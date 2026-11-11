"""Synthetic sheets, programmes and Annexe files for the R.10 tests (no real file is used).

A plan is a grid of rooms drawn with filled wall rectangles (0.2 m) at 1:100 on a wide
page; each room carries its written area (``NN,NN m²``) and optionally a name.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import ezdxf
import pymupdf

from ale.contracts.enums import MacroZone
from ale.contracts.models import Program, RoomSpec
from ale.program.template import program_rows, write_template

SHA = hashlib.sha256(b"ale score test").hexdigest()
DENOM = 100
PT_PER_M = 1.0 / (DENOM * 0.0254 / 72.0)
T = 0.2
ORIGIN = (30.0, 60.0)

#: A cell of a plan: (written area text, name or None, interior size override or None).
Cell = tuple[str | None, str | None]


def _pt(x: float, y: float) -> tuple[float, float]:
    return (ORIGIN[0] + x * PT_PER_M, ORIGIN[1] + y * PT_PER_M)


def draw_grid_plan(
    page: Any,
    ox: float,
    cells: Sequence[Sequence[Cell]],
    *,
    col_w: float = 4.5,
    row_h: float = 4.0,
) -> tuple[float, float]:
    """Draw a ``rows x cols`` grid of rooms at ``ox`` (m); returns the plan (width, height) in m."""
    nrows, ncols = len(cells), len(cells[0])
    width = ncols * col_w + (ncols + 1) * T
    height = nrows * row_h + (nrows + 1) * T
    sh = page.new_shape()
    for i in range(ncols + 1):
        x = ox + i * (col_w + T)
        sh.draw_rect(pymupdf.Rect(*_pt(x, 0), *_pt(x + T, height)))
    for j in range(nrows + 1):
        y = j * (row_h + T)
        sh.draw_rect(pymupdf.Rect(*_pt(ox, y), *_pt(ox + width, y + T)))
    sh.finish(fill=(0, 0, 0), color=None, width=0)
    sh.commit()
    for j, row in enumerate(cells):
        for i, (area, name) in enumerate(row):
            cx = ox + T + i * (col_w + T) + col_w / 2.0
            cy = T + j * (row_h + T) + row_h / 2.0
            if name:
                page.insert_text(_pt(cx - 1.2, cy - 0.3), name, fontname="helv", fontsize=7)
            if area:
                page.insert_text(_pt(cx - 1.2, cy + 0.4), area, fontname="helv", fontsize=7)
    return width, height


def area_text(value: float) -> str:
    return f"{value:.2f}".replace(".", ",") + " m²"


def save_sheet(path: Path, plans: Sequence[Sequence[Sequence[Cell]]], gap_m: float = 6.0) -> Path:
    """One A3-ish page with the plans side by side (``gap_m`` apart) and the scale title."""
    doc = pymupdf.open()
    page = doc.new_page(width=1500, height=700)
    ox = 1.0
    for cells in plans:
        width, _ = draw_grid_plan(page, ox, cells)
        ox += width + gap_m
    page.insert_text(_pt(1.0, -0.8), "ÉCHELLE 1:100", fontname="helv", fontsize=9)
    doc.save(path)
    doc.close()
    return path


def grid_of(
    areas: Sequence[float], ncols: int, names: Sequence[str | None] | None = None
) -> list[list[Cell]]:
    cells: list[Cell] = [
        (area_text(a), None if names is None else names[i]) for i, a in enumerate(areas)
    ]
    return [cells[k : k + ncols] for k in range(0, len(cells), ncols)]


def spec(
    rid: str,
    name: str,
    area: float,
    *,
    type_: str = "office",
    facade: bool = False,
    qty: int = 1,
) -> RoomSpec:
    return RoomSpec(
        id=rid,
        name=name,
        type=type_,
        target_area_m2=area,
        quantity=qty,
        macro_zone=MacroZone.ADMINISTRATIVE,
        needs_facade=facade,
    )


def save_programme(path: Path, specs: Sequence[RoomSpec]) -> Path:
    import openpyxl

    write_template(path)
    wb = openpyxl.load_workbook(path)
    ws = wb["Programme"]
    for row in program_rows(Program(rooms=tuple(specs))):
        ws.append(row)
    wb.save(path)
    return path


def save_annexe(path: Path, lines: Sequence[tuple[str, str, int, float]]) -> Path:
    """Minimal Annexe workbook: ``(entity, espace, nombre, surface unitaire)`` rows."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["PROGRAMME PHYSIQUE : SIEGE TEST"])
    ws.append(["ENTITE", "ESPACE", "NOMBRE", "SURFACE UNITAIRE EN m2", "SURFACE TOTALE EN m2"])
    for entity, espace, n, unit in lines:
        ws.append([entity, espace, n, unit, n * unit])
    wb.save(path)
    return path


def save_dxf_sheet(path: Path, plan_cells: Sequence[Sequence[float]]) -> Path:
    """Two-room DXF in millimetres (reference geometry of the CAD tests), unnamed rooms."""
    doc = ezdxf.new("R2010", setup=False)
    doc.header["$INSUNITS"] = 4
    doc.layers.add("MUR")
    msp = doc.modelspace()
    outer = [(-100.0, -100.0), (8100.0, -100.0), (8100.0, 5100.0), (-100.0, 5100.0)]
    segs = list(zip(outer, [*outer[1:], outer[0]], strict=True))
    segs += [
        ((100, 100), (4000, 100)),
        ((100, 4900), (4000, 4900)),
        ((100, 100), (100, 4900)),
        ((4100, 100), (7900, 100)),
        ((4100, 4900), (7900, 4900)),
        ((7900, 100), (7900, 4900)),
        ((4000, 100), (4000, 4900)),
        ((4100, 100), (4100, 4900)),
    ]
    for a, b in segs:
        msp.add_line(a, b, dxfattribs={"layer": "MUR"})
    doc.saveas(path)
    return path
