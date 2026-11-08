"""``read_cad``: one DXF → ``CadReadResult`` (list of ``PlanGeometry`` + warnings).

Model space only (paper space ignored). Block references are exploded virtually with
their transforms (entities on layer ``0`` inside a block take the layer of the INSERT);
INSERTs on DOOR/WINDOW layers are kept whole as openings. XREFs are bound when the
referenced DXF sits next to the drawing, else the warning ``missing xref <name>``.

Geometry stays in native drawing units, frame ``Y_UP``. ``read_cad`` never raises for a
readable DXF: every problem becomes a warning.
"""

from __future__ import annotations

import contextlib
import itertools
import logging
import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any

import shapely
from pydantic import BaseModel, ConfigDict, ValidationError

from ale.cad.cluster import bbox_of, cluster_walls, diagonal_of, gap_tolerance
from ale.cad.layers import LayerMap, LayerRole
from ale.cad.openings import ArcDoor, BlockOpening, build_openings, opening_closures
from ale.cad.rooms import LabelText, label_rooms, polygonize_rooms, valid_polygons
from ale.cad.units import UnitsInfo, resolve_units
from ale.cad.walls import Pt, Seg, WidthPolyline, extract_walls
from ale.contracts.config import AleConfig
from ale.contracts.enums import Frame, LabelSource, OpeningKind, ScaleMethod, SourceKind
from ale.contracts.models import Opening, PlanGeometry, TextItem, Wall
from ale.guards import bounded

__all__ = ["ASSUMED_M_PER_UNIT", "CadReadResult", "read_cad"]

log = logging.getLogger(__name__)

#: Metres per unit assumed for the metric thresholds when the units are unknown.
ASSUMED_M_PER_UNIT = 0.001
MIN_PLAN_WALLS = 3
MAX_ENTITIES = 2_000_000
MAX_BLOCK_DEPTH = 16
MAX_XREF_DEPTH = 4
_TIME_BUDGET_S = 120.0
_OPENING_MARGIN_M = 1.0
_FLATTEN_SEGMENTS = 64


class CadReadResult(BaseModel):
    """Result of :func:`read_cad`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plans: tuple[PlanGeometry, ...]
    warnings: tuple[str, ...]
    layer_names: tuple[str, ...]


@dataclass
class _Collected:
    wall_segs: list[Seg] = field(default_factory=list)
    width_polys: list[WidthPolyline] = field(default_factory=list)
    zones: list[shapely.Polygon] = field(default_factory=list)
    blocks: list[BlockOpening] = field(default_factory=list)
    arcs: list[ArcDoor] = field(default_factory=list)
    texts: list[TextItem] = field(default_factory=list)
    labels: list[LabelText] = field(default_factory=list)
    layers: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Item:
    entity: Any
    parent_layer: str | None
    depth: int
    xref_chain: tuple[str, ...]


def _xy(p: Any) -> Pt:
    return (float(p[0]), float(p[1]))


def _finite(*pts: Pt) -> bool:
    return all(math.isfinite(c) for p in pts for c in p)


class _Reader:
    def __init__(self, path: Path, layer_map: LayerMap) -> None:
        self.path = path
        self.layer_map = layer_map
        self.out = _Collected()
        self._block_boxes: dict[tuple[int, str], tuple[Pt, Pt] | None] = {}
        self._xref_docs: dict[str, Any] = {}

    # ------------------------------------------------------------------ traversal

    def collect(self, entities: Iterable[Any]) -> _Collected:
        stack: list[Iterator[_Item]] = [
            (_Item(e, None, 0, (str(self.path.resolve()),)) for e in entities)
        ]
        with bounded(
            MAX_ENTITIES, _TIME_BUDGET_S, label="cad.read.entities", on_exhaust="stop"
        ) as budget:
            while stack:
                item = next(stack[-1], None)
                if item is None:
                    stack.pop()
                    continue
                if not budget.tick():
                    self.out.warnings.append("entity traversal stopped: budget exhausted")
                    break
                try:
                    children = self._visit(item)
                except Exception as exc:  # one bad entity must not stop the read
                    self.out.warnings.append(
                        f"entity skipped ({_dxftype(item.entity)}): {type(exc).__name__}: {exc}"
                    )
                    continue
                if children is not None:
                    stack.append(children)
        return self.out

    def _visit(self, item: _Item) -> Iterator[_Item] | None:
        e = item.entity
        kind = e.dxftype()
        layer = str(e.dxf.get("layer", "0"))
        if item.parent_layer is not None and layer == "0":
            layer = item.parent_layer
        self.out.layers.add(layer)
        role = self.layer_map.role(layer)
        if kind == "INSERT":
            return self._insert(item, layer, role)
        if kind in ("TEXT", "MTEXT", "ATTRIB"):
            self._text(e, kind, layer, role)
        elif kind == "LINE":
            if role is LayerRole.WALL:
                a, b = _xy(e.dxf.start), _xy(e.dxf.end)
                if _finite(a, b):
                    self.out.wall_segs.append((a, b))
        elif kind in ("LWPOLYLINE", "POLYLINE"):
            self._polyline(e, kind, role)
        elif kind == "ARC":
            if role is LayerRole.DOOR:
                self._arc(e)
        elif kind == "HATCH" and role is LayerRole.ZONE:
            self._hatch(e)
        return None

    # ------------------------------------------------------------------ entity kinds

    def _insert(self, item: _Item, layer: str, role: LayerRole) -> Iterator[_Item] | None:
        e = item.entity
        doc = e.doc
        name = str(e.dxf.name)
        block = doc.blocks.get(name) if doc is not None else None
        if block is None:
            self.out.warnings.append(f"missing block {name}")
            return None
        if block.block.is_xref or block.block.is_xref_overlay:
            return self._xref(item, block, layer)
        for attrib in getattr(e, "attribs", ()):
            a_layer = str(attrib.dxf.get("layer", "0"))
            a_layer = layer if a_layer == "0" else a_layer
            self.out.layers.add(a_layer)
            a_role = self.layer_map.role(a_layer)
            if role is LayerRole.ZONE and a_role is not LayerRole.ZONE:
                a_role = LayerRole.ZONE
            self._text(attrib, "ATTRIB", a_layer, a_role)
        if role in (LayerRole.DOOR, LayerRole.WINDOW):
            corners = self._insert_corners(e, block)
            if corners is not None:
                kind = OpeningKind.DOOR if role is LayerRole.DOOR else OpeningKind.WINDOW
                self.out.blocks.append(BlockOpening(kind=kind, corners=corners))
            return None
        if item.depth >= MAX_BLOCK_DEPTH:
            self.out.warnings.append(f"block nesting deeper than {MAX_BLOCK_DEPTH}: {name}")
            return None
        children = e.virtual_entities()
        return (_Item(c, layer, item.depth + 1, item.xref_chain) for c in children)

    def _insert_corners(self, e: Any, block: Any) -> tuple[Pt, Pt, Pt, Pt] | None:
        import ezdxf.bbox

        key = (id(block), str(block.name))
        if key not in self._block_boxes:
            box = ezdxf.bbox.extents(block)
            self._block_boxes[key] = (_xy(box.extmin), _xy(box.extmax)) if box.has_data else None
        bb = self._block_boxes[key]
        if bb is None:
            return None
        (x0, y0), (x1, y1) = bb
        m = e.matrix44()
        pts = [_xy(m.transform((x, y, 0.0))) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        if not _finite(*pts):
            return None
        return (pts[0], pts[1], pts[2], pts[3])

    def _xref(self, item: _Item, block: Any, layer: str) -> Iterator[_Item] | None:
        name = str(block.name)
        raw = str(block.block.dxf.get("xref_path", "") or "")
        filename = PureWindowsPath(raw).name if raw else ""
        candidate = self.path.parent / filename if filename else None
        if candidate is None or not candidate.is_file():
            self.out.warnings.append(f"missing xref {name}")
            return None
        if candidate.suffix.lower() != ".dxf":
            self.out.warnings.append(f"xref {name} is not a DXF file: not bound")
            return None
        resolved = str(candidate.resolve())
        if resolved in item.xref_chain or len(item.xref_chain) > MAX_XREF_DEPTH:
            self.out.warnings.append(f"xref {name}: circular or too deep, not bound")
            return None
        xdoc = self._load_xref(resolved)
        if xdoc is None:
            self.out.warnings.append(f"xref {name}: cannot read {filename}")
            return None
        m = item.entity.matrix44()
        chain = (*item.xref_chain, resolved)

        def gen() -> Iterator[_Item]:
            for src in xdoc.modelspace():
                try:
                    copy = src.copy()
                    copy.transform(m)
                except Exception:  # entity kinds without copy/transform support
                    continue
                yield _Item(copy, None, item.depth + 1, chain)

        return gen()

    def _load_xref(self, resolved: str) -> Any:
        if resolved not in self._xref_docs:
            self._xref_docs[resolved] = _open_dxf(Path(resolved))[0]
        return self._xref_docs[resolved]

    def _text(self, e: Any, kind: str, layer: str, role: LayerRole) -> None:
        if kind == "MTEXT":
            text = str(e.plain_text(split=False))
            insert = _xy(e.dxf.insert)
            height = float(e.dxf.get("char_height", 0.0) or 0.0)
            rotation = float(e.get_rotation())
        else:
            text = str(e.plain_text())
            use_align = (e.dxf.get("halign", 0) or e.dxf.get("valign", 0)) and e.dxf.hasattr(
                "align_point"
            )
            insert = _xy(e.dxf.align_point if use_align else e.dxf.insert)
            height = float(e.dxf.get("height", 0.0) or 0.0)
            rotation = float(e.dxf.get("rotation", 0.0) or 0.0)
        text = text.strip()
        if not text or not _finite(insert):
            return
        self.out.texts.append(
            TextItem(
                text=text,
                insert=insert,
                height=height if height > 0.0 and math.isfinite(height) else None,
                rotation_deg=rotation if math.isfinite(rotation) else 0.0,
                layer=layer,
                source="CAD",
            )
        )
        if role is LayerRole.ROOM_LABEL:
            self.out.labels.append(LabelText(text, insert, LabelSource.CAD_TEXT, True))
        elif role is LayerRole.AREA_LABEL:
            self.out.labels.append(LabelText(text, insert, LabelSource.CAD_TEXT, False))
        elif role is LayerRole.ZONE:
            self.out.labels.append(LabelText(text, insert, LabelSource.CAD_ZONE, True))

    def _polyline(self, e: Any, kind: str, role: LayerRole) -> None:
        if role not in (LayerRole.WALL, LayerRole.ZONE):
            return
        if kind == "LWPOLYLINE":
            pts = [_xy(p) for p in e.vertices_in_wcs()]
            widths = [(float(s), float(w)) for _x, _y, s, w in e.get_points("xyse")]
            width = float(e.dxf.get("const_width", 0.0) or 0.0)
            closed = bool(e.closed)
        else:
            if not (e.is_2d_polyline or e.is_3d_polyline):
                return
            pts = [_xy(p) for p in e.points_in_wcs()]
            widths = [
                (float(v.dxf.get("start_width", 0.0)), float(v.dxf.get("end_width", 0.0)))
                for v in e.vertices
            ]
            width = float(e.dxf.get("default_start_width", 0.0) or 0.0)
            closed = bool(e.is_closed)
        if not _finite(*pts) or len(pts) < 2:
            return
        if width <= 0.0 and widths:
            flat = {w for pair in widths for w in pair}
            if len(flat) == 1:
                width = next(iter(flat))
        if role is LayerRole.WALL:
            if width > 0.0 and math.isfinite(width):
                self.out.width_polys.append(WidthPolyline(tuple(pts), closed, width))
            else:
                ring = [*pts, pts[0]] if closed else pts
                for a, b in itertools.pairwise(ring):
                    if a != b:
                        self.out.wall_segs.append((a, b))
            return
        is_closed = closed or (len(pts) >= 4 and pts[0] == pts[-1])
        if is_closed and len(pts) >= 3:
            self.out.zones.extend(valid_polygons(shapely.Polygon(pts)))

    def _arc(self, e: Any) -> None:
        c = _xy(e.dxf.center)
        r = float(e.dxf.radius)
        start, end = _xy(e.start_point), _xy(e.end_point)
        if r > 0.0 and _finite(c, start, end) and math.isfinite(r):
            self.out.arcs.append(ArcDoor(center=c, radius=r, start=start, end=end))

    def _hatch(self, e: Any) -> None:
        from ezdxf import path as ezpath

        geom: shapely.Geometry | None = None
        for p in ezpath.from_hatch(e):
            pts = [_xy(v) for v in p.flattening(distance=0.0, segments=_FLATTEN_SEGMENTS)]
            if len(pts) < 3 or not _finite(*pts):
                continue
            for poly in valid_polygons(shapely.Polygon(pts)):
                geom = poly if geom is None else shapely.symmetric_difference(geom, poly)
        if geom is not None:
            self.out.zones.extend(valid_polygons(geom))


def _dxftype(e: Any) -> str:
    try:
        return str(e.dxftype())
    except Exception:  # pragma: no cover - defensive
        return "?"


def _open_dxf(path: Path) -> tuple[Any, str | None]:
    """(document, None) or (None, reason); tries ``ezdxf.recover`` on structure errors."""
    from ezdxf import recover
    from ezdxf.filemanagement import readfile

    try:
        return readfile(path), None
    except OSError as exc:
        return None, f"cannot open {path.name}: {exc}"
    except Exception as exc:
        first = f"{type(exc).__name__}: {exc}"
    try:
        doc, _auditor = recover.readfile(path)
        return doc, None
    except Exception as exc:
        return None, f"cannot read {path.name}: {first}; recover failed: {exc}"


# ---------------------------------------------------------------------- assembly


def _box_distance(box: tuple[float, float, float, float], p: Pt) -> float:
    dx = max(box[0] - p[0], 0.0, p[0] - box[2])
    dy = max(box[1] - p[1], 0.0, p[1] - box[3])
    return math.hypot(dx, dy)


def _assign(boxes: list[tuple[float, float, float, float]], p: Pt, margin: float) -> int | None:
    best: tuple[int | None, float] = (None, math.inf)
    for k, box in enumerate(boxes):
        d = _box_distance(box, p)
        if d < best[1]:
            best = (k, d)
    return best[0] if best[1] <= margin else None


def _with_width_m(op: Opening, scale: float | None) -> Opening:
    if scale is None:
        return op
    return op.model_copy(update={"width_m": op.width_native * scale})


@dataclass
class _PlanParts:
    walls: list[Wall]
    face_lines: list[Seg] = field(default_factory=list)
    zones: list[shapely.Polygon] = field(default_factory=list)
    blocks: list[BlockOpening] = field(default_factory=list)
    arcs: list[ArcDoor] = field(default_factory=list)
    texts: list[TextItem] = field(default_factory=list)
    labels: list[LabelText] = field(default_factory=list)


def _assemble(
    col: _Collected,
    units: UnitsInfo,
    *,
    source_sha256: str,
    source_kind: SourceKind,
    global_warnings: list[str],
) -> list[PlanGeometry]:
    m = units.m_per_unit if units.m_per_unit is not None else ASSUMED_M_PER_UNIT
    wr = extract_walls(col.wall_segs, col.width_polys, m)
    global_warnings.extend(wr.warnings)
    walls = wr.walls
    if not walls:
        global_warnings.append("no walls found")
        return []
    diag = diagonal_of(bbox_of(walls))
    tol = gap_tolerance(diag, m)
    clusters = cluster_walls(walls, tol)
    parts = [_PlanParts(walls=[walls[i] for i in members]) for members in clusters]
    boxes = [bbox_of(p.walls) for p in parts]
    near = _OPENING_MARGIN_M / m
    far = tol / 2.0
    for seg in wr.face_lines:
        mid = ((seg[0][0] + seg[1][0]) / 2.0, (seg[0][1] + seg[1][1]) / 2.0)
        k = _assign(boxes, mid, near)
        if k is not None:
            parts[k].face_lines.append(seg)
    for z in col.zones:
        k = _assign(boxes, _xy(z.representative_point().coords[0]), far)
        if k is not None:
            parts[k].zones.append(z)
    for b in col.blocks:
        k = _assign(boxes, b.center, near)
        if k is not None:
            parts[k].blocks.append(b)
    for a in col.arcs:
        k = _assign(boxes, a.center, near)
        if k is not None:
            parts[k].arcs.append(a)
    for t in col.texts:
        k = _assign(boxes, t.insert, far)
        if k is not None:
            parts[k].texts.append(t)
    for lt in col.labels:
        k = _assign(boxes, lt.insert, far)
        if k is not None:
            parts[k].labels.append(lt)

    plans: list[PlanGeometry] = []
    for part, box in zip(parts, boxes, strict=True):
        plan_warnings: list[str] = []
        openings = build_openings(part.blocks, part.arcs, part.walls, m)
        if part.zones:
            polys = part.zones
        else:
            lines = [*part.face_lines, *opening_closures(openings, part.walls)]
            polys = polygonize_rooms(lines, m, plan_warnings)
        if len(part.walls) < MIN_PLAN_WALLS or not polys:
            global_warnings.append(
                f"ignored fragment: {len(part.walls)} walls, {len(polys)} rooms "
                f"at ({box[0]:.6g}, {box[1]:.6g})"
            )
            continue
        rooms = label_rooms(polys, part.labels, plan_warnings)
        try:
            plan = PlanGeometry(
                source_sha256=source_sha256,
                page=0,
                plan_index=len(plans),
                source_kind=source_kind,
                frame=Frame.Y_UP,
                units_label=units.label,
                scale_m_per_unit=units.m_per_unit,
                scale_method=units.method,
                scale_confidence=units.confidence,
                walls=tuple(part.walls),
                openings=tuple(_with_width_m(o, units.m_per_unit) for o in openings),
                rooms=tuple(rooms),
                texts=tuple(part.texts),
                warnings=tuple(dict.fromkeys([*units.warnings, *plan_warnings])),
            )
        except ValidationError as exc:
            global_warnings.append(f"plan dropped: invalid geometry ({exc.error_count()} errors)")
            continue
        global_warnings.extend(plan_warnings)
        plans.append(plan)
    return plans


def _layer_names(doc: Any, used: set[str]) -> tuple[str, ...]:
    names = set(used)
    with contextlib.suppress(Exception):
        names.update(str(layer.dxf.name) for layer in doc.layers)
    return tuple(sorted(names))


def _insunits(doc: Any) -> int | None:
    try:
        value = doc.header.get("$INSUNITS", None)
        return None if value is None else int(value)
    except Exception:  # pragma: no cover - defensive
        return None


def read_cad(
    path: Path,
    *,
    source_sha256: str,
    layer_map: LayerMap,
    config: AleConfig,
    units_override: str | None = None,
    source_kind: SourceKind = SourceKind.DXF,
) -> CadReadResult:
    """Read one DXF (``source_kind`` DWG when it was converted from a DWG)."""
    del config  # reserved: no tunable of AleConfig applies to DXF reading yet
    doc, reason = _open_dxf(Path(path))
    if doc is None:
        return CadReadResult(plans=(), warnings=(reason or "cannot read DXF",), layer_names=())
    reader = _Reader(Path(path), layer_map)
    warnings: list[str] = []
    try:
        col = reader.collect(doc.modelspace())
    except Exception as exc:  # pragma: no cover - collect() already guards each entity
        col = reader.out
        warnings.append(f"traversal error: {type(exc).__name__}: {exc}")
    layer_names = _layer_names(doc, col.layers)
    warnings.extend(col.warnings)
    door_widths = [b.width for b in col.blocks if b.kind is OpeningKind.DOOR]
    units = resolve_units(_insunits(doc), door_widths, units_override)
    warnings.extend(units.warnings)
    if units.method is ScaleMethod.UNKNOWN:
        warnings.append("metric thresholds assume millimetres")
    try:
        plans = _assemble(
            col,
            units,
            source_sha256=source_sha256,
            source_kind=source_kind,
            global_warnings=warnings,
        )
    except Exception as exc:  # never raise for a readable DXF
        log.warning("read_cad: %s: %s", type(exc).__name__, exc)
        warnings.append(f"extraction error: {type(exc).__name__}: {exc}")
        plans = []
    if not plans:
        warnings.append("no plan found")
    return CadReadResult(
        plans=tuple(plans),
        warnings=tuple(dict.fromkeys(warnings)),
        layer_names=layer_names,
    )
