"""DXF builders with declared ground truth for the Ticket 1.2 tests (millimetres).

Reference plan: wall centreline rectangle 8 000 x 5 000, exterior walls 200 thick,
one partition 100 thick on x = 4 050. Rooms: 3.9 x 4.8 m (left) and 3.8 x 4.8 m (right).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf.document import Drawing

from ale.cad import CadReadResult, LayerMap, propose_layer_map, read_cad
from ale.contracts.config import AleConfig
from ale.contracts.models import PlanGeometry, Wall

SHA = hashlib.sha256(b"ale cad test").hexdigest()

Pt = tuple[float, float]
#: Ground-truth walls: (start, end, thickness) in mm.
GT_WALLS: tuple[tuple[Pt, Pt, float], ...] = (
    ((0.0, 0.0), (8000.0, 0.0), 200.0),
    ((0.0, 5000.0), (8000.0, 5000.0), 200.0),
    ((0.0, 0.0), (0.0, 5000.0), 200.0),
    ((8000.0, 0.0), (8000.0, 5000.0), 200.0),
    ((4050.0, 0.0), (4050.0, 5000.0), 100.0),
)
GT_ROOM_AREAS_MM2 = (3900.0 * 4800.0, 3800.0 * 4800.0)


def new_doc(insunits: int | None = 4) -> Drawing:
    doc = ezdxf.new("R2010", setup=False)
    if insunits is None:
        if "$INSUNITS" in doc.header:
            del doc.header["$INSUNITS"]
    else:
        doc.header["$INSUNITS"] = insunits
    return doc


def _rect_lines(msp: Any, x0: float, y0: float, x1: float, y1: float, layer: str) -> None:
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for a, b in zip(pts, [*pts[1:], pts[0]], strict=True):
        msp.add_line(a, b, dxfattribs={"layer": layer})


def add_plan_pairs(
    layout: Any,
    dx: float = 0.0,
    dy: float = 0.0,
    layer: str = "MUR",
    door_gap: tuple[float, float] | None = None,
    scale: float = 1.0,
) -> None:
    """Reference plan drawn as wall faces (parallel LINEs)."""

    def p(x: float, y: float) -> tuple[float, float]:
        return (dx + x * scale, dy + y * scale)

    def line(a: Pt, b: Pt) -> None:
        layout.add_line(p(*a), p(*b), dxfattribs={"layer": layer})

    outer = [(-100.0, -100.0), (8100.0, -100.0), (8100.0, 5100.0), (-100.0, 5100.0)]
    for a, b in zip(outer, [*outer[1:], outer[0]], strict=True):
        line(a, b)
    # left room inner faces
    line((100, 100), (4000, 100))
    line((100, 4900), (4000, 4900))
    line((100, 100), (100, 4900))
    # right room inner faces
    line((4100, 100), (7900, 100))
    line((4100, 4900), (7900, 4900))
    line((7900, 100), (7900, 4900))
    # partition faces (x = 4000 and x = 4100), optionally with a door gap
    for x in (4000.0, 4100.0):
        if door_gap is None:
            line((x, 100), (x, 4900))
        else:
            line((x, 100), (x, door_gap[0]))
            line((x, door_gap[1]), (x, 4900))


def add_plan_width(layout: Any, layer: str = "MUR", extra_partition: bool = False) -> None:
    """Reference plan drawn as LWPOLYLINEs with a constant width."""
    layout.add_lwpolyline(
        [(0, 0), (8000, 0), (8000, 5000), (0, 5000)],
        close=True,
        dxfattribs={"layer": layer, "const_width": 200.0},
    )
    layout.add_lwpolyline(
        [(4050, 0), (4050, 5000)], dxfattribs={"layer": layer, "const_width": 100.0}
    )
    if extra_partition:
        layout.add_lwpolyline(
            [(4050, 2500), (8000, 2500)], dxfattribs={"layer": layer, "const_width": 100.0}
        )


def add_block(doc: Drawing, name: str, w: float, h: float) -> None:
    blk = doc.blocks.new(name)
    blk.add_lwpolyline([(0, 0), (w, 0), (w, h), (0, h)], close=True)


def save(doc: Drawing, path: Path) -> Path:
    doc.saveas(path)
    return path


def layer_map_for(doc: Drawing, extra: Sequence[str] = ()) -> LayerMap:
    names = {str(e.dxf.layer) for e in doc.modelspace()}
    names.update(str(layer.dxf.name) for layer in doc.layers)
    for blk in doc.blocks:
        names.update(str(e.dxf.layer) for e in blk)
    names.update(extra)
    return propose_layer_map(sorted(names))


def read(
    path: Path,
    layer_map: LayerMap | None = None,
    units_override: str | None = None,
    extra_layers: Sequence[str] = (),
) -> CadReadResult:
    if layer_map is None:
        layer_map = layer_map_for(ezdxf.readfile(path), extra_layers)
    return read_cad(
        path,
        source_sha256=SHA,
        layer_map=layer_map,
        config=AleConfig(),
        units_override=units_override,
    )


def _dir(w: Wall) -> tuple[Pt, Pt]:
    return w.centerline.coords[0], w.centerline.coords[-1]


def wall_matches(
    w: Wall, gt: tuple[Pt, Pt, float], tol: float = 5.0, min_cover: float = 0.8
) -> bool:
    """Wall parallel to ``gt``, centreline within ``tol``, thickness within ``tol``."""
    (a, b), (ga, gb, gt_t) = _dir(w), gt
    gl = math.dist(ga, gb)
    ux, uy = (gb[0] - ga[0]) / gl, (gb[1] - ga[1]) / gl
    for p in (a, b):
        if abs(ux * (p[1] - ga[1]) - uy * (p[0] - ga[0])) > tol:
            return False
    if w.thickness is None or abs(w.thickness - gt_t) > tol:
        return False
    s = sorted(((p[0] - ga[0]) * ux + (p[1] - ga[1]) * uy) for p in (a, b))
    inner_lo, inner_hi = 200.0, gl - 200.0
    cover = max(0.0, min(s[1], inner_hi) - max(s[0], inner_lo))
    return cover >= min_cover * (inner_hi - inner_lo)


def transform_gt(
    gt: Sequence[tuple[Pt, Pt, float]], rot_deg: float, scale: float, offset: Pt
) -> list[tuple[Pt, Pt, float]]:
    c, s = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))

    def tp(p: Pt) -> Pt:
        x, y = p[0] * scale, p[1] * scale
        return (offset[0] + c * x - s * y, offset[1] + s * x + c * y)

    return [(tp(a), tp(b), t * scale) for a, b, t in gt]


def assert_walls_match(plan: PlanGeometry, gt: Sequence[tuple[Pt, Pt, float]]) -> None:
    assert len(plan.walls) == len(gt), [w.centerline.coords for w in plan.walls]
    for g in gt:
        hits = [w for w in plan.walls if wall_matches(w, g)]
        assert len(hits) == 1, (g, [(w.centerline.coords, w.thickness) for w in plan.walls])
