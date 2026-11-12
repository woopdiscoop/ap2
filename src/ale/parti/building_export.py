"""``parti_NN/building.yaml`` (Ticket M.1): the per-floor outlines and the core of a parti, the
input of ``ale stack``. Outlines are cut by the parti's one-cell slit like the typical-floor
site, so that every outline is a hole-free ring."""

from __future__ import annotations

from pathlib import Path

from shapely import LineString, Point, box
from shapely import Polygon as ShPolygon
from shapely.geometry.polygon import orient
from shapely.ops import nearest_points

from ale.contracts.geometry import Polygon
from ale.contracts.models import CoreSpec, Entrance, SiteSpec
from ale.parti.massing import Massing, largest_polygon
from ale.stack.building import Building, Floor, dump_building

__all__ = ["building_of", "write_building"]

_EPS = 1e-6


def _ring(poly: ShPolygon) -> tuple[tuple[float, float], ...]:
    return tuple((round(x, 6), round(y, 6)) for x, y in list(poly.exterior.coords)[:-1])


def _flat(poly: ShPolygon, m: Massing) -> ShPolygon:
    if m.slit is not None:
        poly = largest_polygon(poly.difference(box(*m.slit)))
    return orient(largest_polygon(ShPolygon(poly.exterior).simplify(0)), 1.0)


def building_of(site: SiteSpec, m: Massing) -> Building:
    """The :class:`Building` of ``m``: floor outlines (each inside the one below), its core,
    the plot entrances moved onto the ground outline."""
    outlines: list[ShPolygon] = []
    for o in m.outlines:
        flat = _flat(o, m)
        if outlines and not outlines[-1].buffer(_EPS).covers(flat):
            flat = _flat(largest_polygon(flat.intersection(outlines[-1])), m)
        outlines.append(flat)
    ground = outlines[0]
    ext = [(round(x, 6), round(y, 6)) for x, y in list(ground.exterior.coords)[:-1]]
    ents = []
    for e in site.entrances:
        p = nearest_points(ground.exterior, Point(e.point))[0]
        ents.append(Entrance(point=(round(p.x, 6), round(p.y, 6)), label=e.label, main=e.main))
    ref = Point(ents[0].point) if ents else Point(site.footprint.exterior[site.access_edge])
    n = len(ext)
    edges = [LineString([ext[i], ext[(i + 1) % n]]) for i in range(n)]
    access = min(range(n), key=lambda i: (round(edges[i].distance(ref), 9), i))
    x0, y0, x1, y1 = m.core
    return Building(
        north_angle_deg=site.north_angle_deg,
        access_edge=access,
        entrances=tuple(ents),
        floor_height_m=3.5,
        core=CoreSpec(id="C1", rect=(x0, y0, x1 - x0, y1 - y0), kind="core"),
        floors=tuple(
            Floor(level=k, footprint=Polygon(exterior=_ring(o))) for k, o in enumerate(outlines)
        ),
    )


def write_building(path: Path, site: SiteSpec, m: Massing) -> Path:
    """Write ``building.yaml`` for ``m`` at ``path``."""
    path.write_text(dump_building(building_of(site, m)), encoding="utf-8", newline="\n")
    return path
