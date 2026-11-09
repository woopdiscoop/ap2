"""Rooms of a vector-PDF page (PDF points, ``Y_DOWN``): polygonize and label.

* Polygonize: wall faces plus door closures are noded and polygonized. Kept faces have
  an area of 1.5-2000 m² when the scale is known (200-2·10⁶ pt² otherwise) and are not
  thin (a face vanishing under an inward buffer of half the minimum width — 0.5 m when
  the scale is known, 5 pt otherwise — is dropped). Faces lying mostly (≥ 50 % of their
  area) inside wall material (wall cavities, filled wall shapes) and the outer face (a
  face whose holes enclose other kept faces) are dropped.
* Labels: each text span (and each text line) whose box centre lies in a room is
  normalised with the taxonomy; the longest canonical synonym wins, exact matches before
  prefix matches (confidence 1.0 / 0.8, ``label_source PDF_TEXT``). Area texts
  (``12,40 m²``, ``S=12.4m2``) give ``area_text_m2``.
* Room ids ``r001``… in reading order (top first, then left; ``Y_DOWN``).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

import shapely
from shapely.validation import make_valid

from ale.contracts.enums import LabelSource
from ale.contracts.geometry import Polygon, polygon_from_shapely
from ale.contracts.models import LabelledPolygon
from ale.contracts.taxonomy import UNKNOWN, canon, load_taxonomy
from ale.pdfread.walls import Pt, Seg

__all__ = [
    "MAX_FACE_PT2",
    "MAX_ROOM_M2",
    "MIN_FACE_PT2",
    "MIN_ROOM_M2",
    "MIN_ROOM_WIDTH_M",
    "MIN_ROOM_WIDTH_PT",
    "RoomText",
    "label_rooms",
    "parse_area_text",
    "polygonize_rooms",
]

MIN_ROOM_M2 = 1.5
MAX_ROOM_M2 = 2000.0
MIN_FACE_PT2 = 200.0
MAX_FACE_PT2 = 2.0e6
MIN_ROOM_WIDTH_M = 0.5
MIN_ROOM_WIDTH_PT = 5.0
MATERIAL_SHARE_MAX = 0.5
_MAX_POLYGONIZE_SEGMENTS = 60_000
_MAX_FACES = 20_000

_AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*m\s*(?:²|2)(?![0-9])", re.IGNORECASE)


@dataclass(frozen=True)
class RoomText:
    """A text usable as a room label: its string and box centre (points)."""

    text: str
    center: Pt


def parse_area_text(text: str) -> float | None:
    """Area in m² written in ``text`` (``12,40 m²``, ``S=12.4m2``), else ``None``."""
    m = _AREA_RE.search(text)
    if m is None:
        return None
    value = float(m.group(1).replace(",", "."))
    return value if value > 0.0 else None


def _polygons(geom: shapely.Geometry) -> list[shapely.Polygon]:
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


def polygonize_rooms(
    lines: Sequence[Seg],
    material: Sequence[shapely.Geometry],
    m_per_unit: float | None,
    warnings: list[str],
) -> list[shapely.Polygon]:
    """Room faces of the wall linework (see module docstring)."""
    segs = [s for s in lines if s[0] != s[1]]
    if not segs:
        return []
    if len(segs) > _MAX_POLYGONIZE_SEGMENTS:
        warnings.append(f"polygonize skipped: {len(segs)} face segments")
        return []
    noded = shapely.unary_union(shapely.multilinestrings([list(s) for s in segs]))
    faces = _polygons(shapely.polygonize([noded]))
    if len(faces) > _MAX_FACES:
        warnings.append(f"polygonize: {len(faces)} faces, kept the first {_MAX_FACES}")
        faces = faces[:_MAX_FACES]
    if m_per_unit is None:
        lo, hi, min_w = MIN_FACE_PT2, MAX_FACE_PT2, MIN_ROOM_WIDTH_PT
    else:
        m2 = m_per_unit * m_per_unit
        lo, hi, min_w = MIN_ROOM_M2 / m2, MAX_ROOM_M2 / m2, MIN_ROOM_WIDTH_M / m_per_unit
    sized = [f for f in faces if lo <= f.area <= hi and not f.buffer(-min_w / 2.0).is_empty]
    if material and sized:
        wall_union = shapely.unary_union(list(material))
        sized = [f for f in sized if f.intersection(wall_union).area < MATERIAL_SHARE_MAX * f.area]
    kept: list[shapely.Polygon] = []
    for f in sized:
        if f.interiors:
            holes = [shapely.Polygon(r) for r in f.interiors]
            if any(
                h.contains(o.representative_point()) for h in holes for o in sized if o is not f
            ):
                continue
        kept.append(f)
    return kept


def _to_contract(p: shapely.Polygon) -> Polygon | None:
    try:
        return polygon_from_shapely(shapely.normalize(p))
    except ValueError:
        return None


def _choose(texts: Sequence[RoomText]) -> tuple[str | None, float, str | None]:
    """(type, confidence, raw_label) of the best text match in a room."""
    tax = load_taxonomy()
    best: tuple[int, int, str, float, str] | None = None
    first_raw: str | None = None
    for t in texts:
        if not canon(t.text):
            continue  # an area text ("12,40 m²") or a bare room number is not a name
        if first_raw is None:
            first_raw = t.text
        match = tax.normalize_label(t.text)
        if match.key == UNKNOWN or match.matched_synonym is None:
            continue
        length = len(canon(match.matched_synonym))
        exact = 1 if match.rule == "exact" else 0
        if best is None or (length, exact) > best[:2]:
            best = (length, exact, match.key, 1.0 if exact else 0.8, t.text)
    if best is None:
        return None, 0.0, first_raw
    return best[2], best[3], best[4]


def label_rooms(
    polygons: Sequence[shapely.Polygon], texts: Sequence[RoomText], warnings: list[str]
) -> list[LabelledPolygon]:
    """Labelled rooms, ids ``r001``… in reading order (``Y_DOWN``: top-left first)."""

    def key(p: shapely.Polygon) -> tuple[float, float]:
        rp = p.representative_point()
        return (round(rp.y, 6), round(rp.x, 6))

    rooms: list[LabelledPolygon] = []
    for poly in sorted(polygons, key=key):
        contract = _to_contract(poly)
        if contract is None:
            warnings.append("room polygon dropped: not representable")
            continue
        inside = [t for t in texts if poly.covers(shapely.Point(t.center))]
        rtype, conf, raw = _choose(inside)
        area = next((a for a in (parse_area_text(t.text) for t in inside) if a is not None), None)
        rooms.append(
            LabelledPolygon(
                id=f"r{len(rooms) + 1:03d}",
                polygon=contract,
                type=rtype,
                label_source=None if rtype is None else LabelSource.PDF_TEXT,
                confidence=conf,
                raw_label=raw,
                area_text_m2=area,
            )
        )
    return rooms
