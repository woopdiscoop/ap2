"""Rooms (native units): zone polygons, else polygonized wall linework; room labelling.

* Zones: closed polylines / hatch boundaries on ZONE layers become rooms directly
  (made valid with shapely ``make_valid``; a self-intersecting zone gives one room per
  polygon part).
* Polygonize: wall faces plus opening closures are noded and polygonized; faces with
  1.5 m² ≤ area ≤ 2000 m² are kept, faces thinner than 0.5 m (wall cavities) and the
  outer face (a face whose holes enclose other room faces) are dropped.
* Labels: TEXT/MTEXT whose insertion point lies in a room is normalised with the
  taxonomy; the longest canonical match wins (exact → confidence 1.0, prefix → 0.8).
  Area texts (``12,40 m²``, ``S=12.4m2``) give ``area_text_m2``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

import shapely
from shapely.validation import make_valid

from ale.cad.walls import Pt, Seg
from ale.contracts.enums import LabelSource
from ale.contracts.geometry import Polygon, polygon_from_shapely
from ale.contracts.models import LabelledPolygon
from ale.contracts.taxonomy import UNKNOWN, canon, load_taxonomy

__all__ = [
    "MAX_ROOM_M2",
    "MIN_ROOM_M2",
    "MIN_ROOM_WIDTH_M",
    "LabelText",
    "label_rooms",
    "parse_area_text",
    "polygonize_rooms",
    "valid_polygons",
]

MIN_ROOM_M2 = 1.5
MAX_ROOM_M2 = 2000.0
MIN_ROOM_WIDTH_M = 0.5
_MAX_POLYGONIZE_SEGMENTS = 60_000

_AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*m\s*(?:²|2)(?![0-9])", re.IGNORECASE)


@dataclass(frozen=True)
class LabelText:
    """A text usable as a room label (native units)."""

    text: str
    insert: Pt
    source: LabelSource  # CAD_TEXT (ROOM_LABEL/AREA_LABEL layers) or CAD_ZONE
    is_name: bool  # False for texts on AREA_LABEL layers (area only)


def parse_area_text(text: str) -> float | None:
    """Area in m² written in ``text`` (``12,40 m²``, ``S=12.4m2``), else ``None``."""
    m = _AREA_RE.search(text)
    if m is None:
        return None
    try:
        value = float(m.group(1).replace(",", "."))
    except ValueError:  # pragma: no cover - the regex only matches numbers
        return None
    return value if value > 0.0 else None


def valid_polygons(geom: shapely.Geometry) -> list[shapely.Polygon]:
    """Polygon parts (area > 0) of ``geom`` after ``make_valid``."""
    if shapely.is_empty(geom):
        return []
    g = geom if shapely.is_valid(geom) else make_valid(geom)
    parts: list[shapely.Polygon] = []
    stack = [g]
    while stack:  # bounded: shapely collections are finite trees
        cur = stack.pop()
        if isinstance(cur, shapely.Polygon):
            if cur.area > 0.0:
                parts.append(cur)
        elif hasattr(cur, "geoms"):
            stack.extend(cur.geoms)
    return parts


def _too_thin(face: shapely.Polygon, m_per_unit: float) -> bool:
    return bool(face.buffer(-(MIN_ROOM_WIDTH_M / 2.0) / m_per_unit).is_empty)


def polygonize_rooms(
    lines: Sequence[Seg], m_per_unit: float, warnings: list[str]
) -> list[shapely.Polygon]:
    """Room faces of the noded linework (see module docstring)."""
    segs = [s for s in lines if s[0] != s[1]]
    if not segs:
        return []
    if len(segs) > _MAX_POLYGONIZE_SEGMENTS:
        warnings.append(f"polygonize skipped: {len(segs)} segments")
        return []
    noded = shapely.unary_union(shapely.multilinestrings([list(s) for s in segs]))
    faces = valid_polygons(shapely.polygonize([noded]))
    m2 = m_per_unit * m_per_unit
    lo, hi = MIN_ROOM_M2 / m2, MAX_ROOM_M2 / m2
    sized = [f for f in faces if lo <= f.area <= hi and not _too_thin(f, m_per_unit)]
    kept: list[shapely.Polygon] = []
    for f in sized:
        if f.interiors:
            hole_geoms = [shapely.Polygon(r) for r in f.interiors]
            encloses = any(
                h.contains(o.representative_point())
                for h in hole_geoms
                for o in sized
                if o is not f
            )
            if encloses:
                continue
        kept.append(f)
    return kept


def to_contract_polygon(p: shapely.Polygon) -> Polygon | None:
    """Contract polygon of ``p`` (``None`` if it cannot be represented)."""
    try:
        return polygon_from_shapely(shapely.normalize(p))
    except ValueError:
        return None


def _choose(
    texts: Sequence[LabelText],
) -> tuple[str | None, LabelSource | None, float, str | None]:
    """(type, source, confidence, raw_label) of the best text match in a room."""
    tax = load_taxonomy()
    best: tuple[int, int, str, LabelSource, float, str] | None = None
    first_raw: str | None = None
    for t in texts:
        if not t.is_name:
            continue
        if first_raw is None and t.text.strip():
            first_raw = t.text
        match = tax.normalize_label(t.text)
        if match.key == UNKNOWN or match.matched_synonym is None:
            continue
        length = len(canon(match.matched_synonym))
        exact = 1 if match.rule == "exact" else 0
        conf = 1.0 if exact else 0.8
        key = (length, exact)
        if best is None or key > best[:2]:
            best = (length, exact, match.key, t.source, conf, t.text)
    if best is None:
        return None, None, 0.0, first_raw
    return best[2], best[3], best[4], best[5]


def label_rooms(
    polygons: Sequence[shapely.Polygon], texts: Sequence[LabelText], warnings: list[str]
) -> list[LabelledPolygon]:
    """Labelled rooms, ids ``r001``… in reading order (top-left first)."""
    order = sorted(
        polygons,
        key=lambda p: (-round(p.representative_point().y, 6), round(p.representative_point().x, 6)),
    )
    rooms: list[LabelledPolygon] = []
    for poly in order:
        contract = to_contract_polygon(poly)
        if contract is None:
            warnings.append("room polygon dropped: not representable")
            continue
        inside = [t for t in texts if poly.covers(shapely.Point(t.insert))]
        rtype, source, conf, raw = _choose(inside)
        area = None
        for t in inside:
            area = parse_area_text(t.text)
            if area is not None:
                break
        rooms.append(
            LabelledPolygon(
                id=f"r{len(rooms) + 1:03d}",
                polygon=contract,
                type=rtype,
                label_source=source,
                confidence=conf,
                raw_label=raw,
                area_text_m2=area,
            )
        )
    return rooms
