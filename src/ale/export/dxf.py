"""Layered ``layout.dxf`` (ezdxf, DXF R2018, metres) — requires the ``cad`` extra.

Layers (ACI colours): ``ALE_FOOTPRINT`` 7, ``ALE_ROOM`` 5, ``ALE_CIRC`` 8, ``ALE_LABEL`` 2,
``ALE_GRID`` 9 (off). Ticket M.2: layouts with solids add ``ALE_SOLID`` 6 (outline, hatch and
core id) and ``ALE_FIXED`` 3 (fixed rooms). Coordinates are metres in the site drawing axes (see
:class:`ale.export.report.MetricFrame`).
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any

from ale.contracts.models import Layout
from ale.export.report import MetricFrame, area_label, room_infos
from ale.program.models import PreparedInput

__all__ = [
    "GRID_SPACING_MM",
    "LABEL_HEIGHT_M",
    "LAYERS",
    "SOLID_LAYERS",
    "grid_step_modules",
    "load_ezdxf",
    "write_dxf",
]

#: Layer name → ACI colour.
LAYERS: dict[str, int] = {
    "ALE_FOOTPRINT": 7,
    "ALE_ROOM": 5,
    "ALE_CIRC": 8,
    "ALE_LABEL": 2,
    "ALE_GRID": 9,
}
#: Layers added only for layouts with solids (Ticket M.2).
SOLID_LAYERS: dict[str, int] = {"ALE_SOLID": 6, "ALE_FIXED": 3}
LABEL_HEIGHT_M = 0.25
GRID_SPACING_MM = 1200
_INSUNITS_METRES = 6
_MTEXT_MIDDLE_CENTER = 5


def load_ezdxf() -> ModuleType | None:
    """The ``ezdxf`` module, or ``None`` when it cannot be imported."""
    try:
        return importlib.import_module("ezdxf")
    except ImportError:
        return None


def grid_step_modules(module_mm: int) -> int:
    """Grid spacing in modules: ``ceil(1.2 m / module)``."""
    return -(-GRID_SPACING_MM // module_mm)


def _mtext_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _draw_solids(msp: Any, layout: Layout, prepared: PreparedInput, frame: MetricFrame) -> None:
    """Solids (outline, hatch, core id) and the fixed rooms placed inside them (Ticket M.2)."""
    names = [c.id for c in prepared.site.cores]
    for k, ring in enumerate(layout.footprint.solids):
        pts = [frame.point(p) for p in ring]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "ALE_SOLID"})
        hatch = msp.add_hatch(color=6, dxfattribs={"layer": "ALE_SOLID"})
        hatch.set_pattern_fill("ANSI31", scale=0.1)
        hatch.paths.add_polyline_path(pts, is_closed=True)
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        label = names[k] if k < len(names) else f"solid_{k}"
        msp.add_mtext(
            _mtext_escape(label),
            dxfattribs={
                "layer": "ALE_SOLID",
                "insert": ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2),
                "char_height": LABEL_HEIGHT_M,
                "attachment_point": _MTEXT_MIDDLE_CENTER,
            },
        )
    for room in layout.fixed:
        msp.add_lwpolyline(frame.rect_ccw(room.rect), close=True, dxfattribs={"layer": "ALE_FIXED"})
        msp.add_mtext(
            _mtext_escape(room.instance_id),
            dxfattribs={
                "layer": "ALE_FIXED",
                "insert": frame.rect_centre(room.rect),
                "char_height": LABEL_HEIGHT_M * 0.8,
                "attachment_point": _MTEXT_MIDDLE_CENTER,
            },
        )


def write_dxf(layout: Layout, prepared: PreparedInput, path: Path) -> None:
    """Write ``layout.dxf``; raises ``ImportError`` when ezdxf is not installed."""
    ezdxf = load_ezdxf()
    if ezdxf is None:
        raise ImportError("ezdxf is not installed (extra 'cad')")
    frame = MetricFrame(layout.grid.module_mm, prepared.footprint.origin_m)
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = _INSUNITS_METRES
    doc.header["$MEASUREMENT"] = 1
    for name, colour in LAYERS.items():
        layer = doc.layers.add(name, color=colour)
        if name == "ALE_GRID":
            layer.off()
    if layout.footprint.solids:
        for name, colour in SOLID_LAYERS.items():
            doc.layers.add(name, color=colour)
    msp = doc.modelspace()

    footprint = [frame.point(p) for p in layout.footprint.exterior]
    msp.add_lwpolyline(footprint, close=True, dxfattribs={"layer": "ALE_FOOTPRINT"})
    for room in layout.rooms:
        msp.add_lwpolyline(frame.rect_ccw(room.rect), close=True, dxfattribs={"layer": "ALE_ROOM"})
    for circ in layout.circulation:
        msp.add_lwpolyline(frame.rect_ccw(circ.rect), close=True, dxfattribs={"layer": "ALE_CIRC"})

    _draw_solids(msp, layout, prepared, frame)

    for info in room_infos(layout, prepared):
        text = "\\P".join(_mtext_escape(s) for s in (info.name, info.type_label, area_label(info)))
        msp.add_mtext(
            text,
            dxfattribs={
                "layer": "ALE_LABEL",
                "insert": frame.rect_centre(info.rect),
                "char_height": LABEL_HEIGHT_M,
                "attachment_point": _MTEXT_MIDDLE_CENTER,
            },
        )

    xs = [p[0] for p in layout.footprint.exterior]
    ys = [p[1] for p in layout.footprint.exterior]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    step = grid_step_modules(layout.grid.module_mm)
    for gx in range(x0, x1 + 1, step):
        msp.add_line(
            (frame.x(gx), frame.y(y0)), (frame.x(gx), frame.y(y1)), dxfattribs={"layer": "ALE_GRID"}
        )
    for gy in range(y0, y1 + 1, step):
        msp.add_line(
            (frame.x(x0), frame.y(gy)), (frame.x(x1), frame.y(gy)), dxfattribs={"layer": "ALE_GRID"}
        )
    doc.saveas(Path(path))
