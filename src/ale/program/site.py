"""Read ``site.yaml`` (inline polygon or DXF polyline) into a ``SiteSpec`` (metres).

Also converts a site to its integer **module footprint** on the planning grid with
inward snapping (RD 3.1 section 5). Coordinates are handled as integer millimetres
internally; ``ezdxf`` is imported lazily (only for ``footprint_dxf``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ale.contracts.geometry import ModulePolygon, Polygon
from ale.contracts.models import GridSpec, SiteSpec
from ale.contracts.units import check_module_mm, m_to_mm, mm_to_m, to_decimal
from ale.program.models import InputError, Issue, ModuleFootprint, make_issue

__all__ = [
    "DXF_KEYS",
    "SITE_KEYS",
    "module_perimeter_mm",
    "normalise_footprint",
    "read_site",
    "site_from_mapping",
    "to_module_footprint",
]

SITE_KEYS: frozenset[str] = frozenset(
    {"footprint", "footprint_dxf", "north_angle_deg", "access_edge", "core_hint"}
)
DXF_KEYS: frozenset[str] = frozenset({"path", "layer", "units"})

#: Metres per drawing unit, by unit name and by DXF ``$INSUNITS`` code.
_UNIT_FACTORS: dict[str, Decimal] = {"mm": Decimal("0.001"), "cm": Decimal("0.01"), "m": Decimal(1)}
_INSUNITS: dict[int, str] = {4: "mm", 5: "cm", 6: "m"}

_MM2_PER_M2 = 1_000_000

MmPoint = tuple[int, int]


class _Fail(Exception):
    """Internal short-circuit carrying the issues that stop site reading."""

    def __init__(self, *issues: Issue) -> None:
        super().__init__(issues[0].message if issues else "")
        self.issues = issues


def _fail(code: str, message: str, value: object = None) -> _Fail:
    if value is None:
        return _Fail(make_issue(code, message))
    return _Fail(make_issue(code, message, value=value))


# --------------------------------------------------------------------------- edge lists


@dataclass(frozen=True)
class _Edge:
    """Directed edge ``a → b`` with the set of input edge indices it is the image of."""

    a: MmPoint
    b: MmPoint
    tags: frozenset[int]


def _cross(e1: _Edge, e2: _Edge) -> int:
    ux, uy = e1.b[0] - e1.a[0], e1.b[1] - e1.a[1]
    vx, vy = e2.b[0] - e2.a[0], e2.b[1] - e2.a[1]
    return ux * vy - uy * vx


def _dot(e1: _Edge, e2: _Edge) -> int:
    ux, uy = e1.b[0] - e1.a[0], e1.b[1] - e1.a[1]
    vx, vy = e2.b[0] - e2.a[0], e2.b[1] - e2.a[1]
    return ux * vx + uy * vy


def _simplify(edges: list[_Edge]) -> list[_Edge]:
    """Drop zero-length edges, then merge consecutive same-direction collinear edges.

    A zero-length edge disappears with its tags; merged edges take the union of tags.
    Direction reversals (spikes) are kept, so that validity checks reject them.
    """
    out = [e for e in edges if e.a != e.b]
    changed = True
    while changed and len(out) >= 2:
        changed = False
        n = len(out)
        for i in range(n):
            j = (i + 1) % n
            e1, e2 = out[i], out[j]
            if _cross(e1, e2) == 0 and _dot(e1, e2) > 0:
                merged = _Edge(e1.a, e2.b, e1.tags | e2.tags)
                out[i] = merged
                del out[j]
                changed = True
                break
    return out


def _twice_area(points: Sequence[MmPoint]) -> int:
    n = len(points)
    total = 0
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        total += x0 * y1 - x1 * y0
    return total


def _rotate_to_start(edges: list[_Edge]) -> list[_Edge]:
    """Rotate so that the first vertex is the lowest-then-leftmost one."""
    k = min(range(len(edges)), key=lambda i: (edges[i].a[1], edges[i].a[0]))
    return edges[k:] + edges[:k]


def _ring_edges(points: Sequence[MmPoint]) -> list[_Edge]:
    n = len(points)
    return [_Edge(points[i], points[(i + 1) % n], frozenset({i})) for i in range(n)]


def _is_simple(points: Sequence[MmPoint]) -> bool:
    import shapely

    return bool(shapely.Polygon(points).is_valid)


# --------------------------------------------------------------------------- normalisation


def normalise_footprint(
    points_mm: Sequence[MmPoint], access_edge: int
) -> tuple[tuple[MmPoint, ...], int]:
    """Normalise a footprint ring (integer mm) and remap ``access_edge``.

    Drops consecutive duplicates and collinear vertices, orients counter-clockwise and
    starts at the lowest-then-leftmost vertex. ``access_edge`` indexes the **input**
    edges (vertex i → i+1) and is mapped to the normalised edge that contains it.
    Raises ``InputError`` (``E_SITE_INVALID``, ``E_SITE_NOT_ORTHOGONAL``,
    ``E_SITE_ACCESS_EDGE``).
    """
    try:
        return _normalise(points_mm, access_edge)
    except _Fail as exc:
        raise InputError(exc.issues) from None


def _normalise(points_mm: Sequence[MmPoint], access_edge: int) -> tuple[tuple[MmPoint, ...], int]:
    n_in = len(points_mm)
    if not 0 <= access_edge < n_in:
        raise _fail(
            "E_SITE_ACCESS_EDGE",
            f"access_edge {access_edge} hors limites : l'emprise a {n_in} côtés (0 à {n_in - 1}).",
            access_edge,
        )
    edges = _simplify(_ring_edges(points_mm))
    pts = [e.a for e in edges]
    area2 = _twice_area(pts) if len(pts) >= 3 else 0
    if area2 == 0:
        raise _fail("E_SITE_INVALID", "Emprise dégénérée : surface nulle.")
    if area2 < 0:
        edges = [_Edge(e.b, e.a, e.tags) for e in reversed(edges)]
    edges = _rotate_to_start(edges)
    pts = [e.a for e in edges]
    if not _is_simple(pts):
        raise _fail(
            "E_SITE_INVALID", "Emprise invalide : le contour se recoupe (polygone non simple)."
        )
    for e in edges:
        if e.a[0] != e.b[0] and e.a[1] != e.b[1]:
            raise _fail(
                "E_SITE_NOT_ORTHOGONAL",
                "Emprise non orthogonale : faites pivoter le dessin pour que les murs soient "
                "parallèles aux axes et exprimez la rotation dans north_angle_deg.",
                (mm_to_m(e.a[0]), mm_to_m(e.a[1]), mm_to_m(e.b[0]), mm_to_m(e.b[1])),
            )
    for k, e in enumerate(edges):
        if access_edge in e.tags:
            return tuple(pts), k
    raise _fail(
        "E_SITE_ACCESS_EDGE",
        f"Le côté d'accès {access_edge} est de longueur nulle après arrondi au millimètre.",
        access_edge,
    )


# --------------------------------------------------------------------------- YAML


def _is_number(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _decimal(v: object) -> Decimal | None:
    if not _is_number(v):
        return None
    try:
        return to_decimal(v)  # type: ignore[arg-type]
    except ValueError:  # NaN / infinity
        return None


def _point(v: object) -> tuple[Decimal, Decimal] | None:
    if not isinstance(v, list | tuple) or len(v) != 2:
        return None
    x, y = _decimal(v[0]), _decimal(v[1])
    if x is None or y is None:
        return None
    return x, y


def read_site(path: Path) -> tuple[SiteSpec | None, tuple[Issue, ...]]:
    """Read ``site.yaml``; the ``SiteSpec`` is ``None`` iff there are issues (all errors)."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        issue = make_issue(
            "E_FILE_UNREADABLE", f"Fichier de site illisible : {exc}.", value=str(path)
        )
        return None, (issue,)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, (make_issue("E_SITE_SCHEMA", f"YAML invalide : {exc}."),)
    return site_from_mapping(data, p.parent)


def site_from_mapping(data: object, base_dir: Path) -> tuple[SiteSpec | None, tuple[Issue, ...]]:
    """``SiteSpec`` from parsed ``site.yaml`` content (DXF paths relative to ``base_dir``)."""
    try:
        return _site(data, Path(base_dir)), ()
    except _Fail as exc:
        return None, exc.issues


def _schema_issues(data: Mapping[str, Any]) -> list[Issue]:
    issues: list[Issue] = []

    def bad(message: str, value: object = None) -> None:
        issues.append(make_issue("E_SITE_SCHEMA", message, value=value))

    for key in sorted(str(k) for k in data if k not in SITE_KEYS):
        bad(f"Clé inconnue « {key} » dans site.yaml.", key)
    has_poly, has_dxf = "footprint" in data, "footprint_dxf" in data
    if has_poly == has_dxf:
        bad("Il faut exactement une des clés footprint et footprint_dxf.")
    if has_dxf:
        spec = data["footprint_dxf"]
        if not isinstance(spec, Mapping):
            bad("footprint_dxf doit être un dictionnaire {path, layer, units}.", spec)
        else:
            for key in sorted(str(k) for k in spec if k not in DXF_KEYS):
                bad(f"Clé inconnue « {key} » dans footprint_dxf.", key)
            for key in ("path", "layer"):
                if not isinstance(spec.get(key), str) or not spec[key].strip():
                    bad(f"footprint_dxf.{key} doit être un texte non vide.", spec.get(key))
            units = spec.get("units")
            if units is not None and units not in _UNIT_FACTORS:
                bad("footprint_dxf.units doit valoir null, mm, cm ou m.", units)
    angle = data.get("north_angle_deg", 0)
    d = _decimal(angle)
    if d is None or not Decimal(0) <= d < Decimal(360):
        bad("north_angle_deg doit être un nombre dans [0, 360).", angle)
    access = data.get("access_edge", 0)
    if isinstance(access, bool) or not isinstance(access, int):
        bad("access_edge doit être un entier.", access)
    hint = data.get("core_hint")
    if hint is not None and _point(hint) is None:
        bad("core_hint doit être null ou [x, y] en mètres.", hint)
    return issues


def _site(data: object, base_dir: Path) -> SiteSpec:
    if not isinstance(data, Mapping):
        raise _fail("E_SITE_SCHEMA", "site.yaml doit contenir un dictionnaire.", data)
    issues = _schema_issues(data)
    if issues:
        raise _Fail(*issues)
    if "footprint" in data:
        raw = data["footprint"]
        if not isinstance(raw, list | tuple) or len(raw) < 3:
            raise _fail("E_SITE_SCHEMA", "footprint doit être une liste d'au moins 3 points.", raw)
        points: list[tuple[Decimal, Decimal]] = []
        for v in raw:
            pt = _point(v)
            if pt is None:
                raise _fail("E_SITE_SCHEMA", "Chaque point de footprint doit être [x, y].", v)
            points.append(pt)
    else:
        spec = data["footprint_dxf"]
        points = _read_dxf(base_dir / spec["path"], spec["layer"], spec.get("units"))
    mm = [(m_to_mm(x), m_to_mm(y)) for x, y in points]
    ring, access = _normalise(mm, data.get("access_edge", 0))
    hint = data.get("core_hint")
    hint_pt = _point(hint) if hint is not None else None
    try:
        return SiteSpec(
            footprint=Polygon(exterior=tuple((mm_to_m(x), mm_to_m(y)) for x, y in ring)),
            north_angle_deg=float(data.get("north_angle_deg", 0)),
            access_edge=access,
            core_hint=None if hint_pt is None else (float(hint_pt[0]), float(hint_pt[1])),
        )
    except ValidationError as exc:  # pragma: no cover - checks above are stricter
        raise _fail("E_SITE_INVALID", f"Site refusé par le contrat : {exc}.") from None


# --------------------------------------------------------------------------- DXF


def _read_dxf(path: Path, layer: str, units: str | None) -> list[tuple[Decimal, Decimal]]:
    if path.suffix.lower() == ".dwg":
        raise _fail(
            "E_SITE_DWG",
            "Les emprises DWG ne sont pas lues : convertissez en DXF "
            "(convert to DXF; DWG sites arrive with Ticket 1.2).",
            path.name,
        )
    if not path.is_file():
        raise _fail("E_SITE_DXF", f"Fichier DXF introuvable : {path.name}.", str(path))
    from ezdxf.entities.lwpolyline import LWPolyline
    from ezdxf.entities.polyline import Polyline
    from ezdxf.filemanagement import readfile

    try:
        doc = readfile(path)
    except Exception as exc:  # ezdxf structure / encoding / OS errors
        raise _fail("E_SITE_DXF", f"DXF illisible : {type(exc).__name__}: {exc}.") from None
    if units is None:
        code = doc.header.get("$INSUNITS", 0)
        units = _INSUNITS.get(code) if isinstance(code, int) else None
        if units is None:
            raise _fail(
                "E_SITE_UNITS",
                "Unités du DXF inconnues ($INSUNITS) : précisez footprint_dxf.units (mm, cm ou m).",
                code,
            )
    factor = _UNIT_FACTORS[units]
    found: list[tuple[list[tuple[float, float]], bool]] = []
    wanted = layer.casefold()
    for entity in doc.modelspace().query("LWPOLYLINE POLYLINE"):
        if str(entity.dxf.layer).casefold() != wanted:
            continue
        if isinstance(entity, LWPolyline):
            xyb = list(entity.get_points("xyb"))
            pts = [(float(x), float(y)) for x, y, _ in xyb]
            curved = any(b for _, _, b in xyb)
            closed = bool(entity.closed)
        elif isinstance(entity, Polyline):
            if not (entity.is_2d_polyline or entity.is_3d_polyline):
                continue
            verts = list(entity.vertices)
            pts = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in verts]
            curved = any(v.dxf.get("bulge", 0) for v in verts)
            closed = bool(entity.is_closed)
        else:  # pragma: no cover - the query only yields polylines
            continue
        if not closed and len(pts) >= 3 and pts[0] == pts[-1]:
            closed = True
            pts = pts[:-1]
        if closed:
            found.append((pts, curved))
    if len(found) != 1:
        raise _fail(
            "E_SITE_DXF",
            f"Il faut exactement une polyligne fermée sur le calque « {layer} » "
            f"(trouvé : {len(found)}).",
            len(found),
        )
    pts, curved = found[0]
    if curved:
        raise _fail(
            "E_SITE_NOT_ORTHOGONAL",
            "La polyligne d'emprise contient des arcs : seuls des segments droits parallèles "
            "aux axes sont acceptés.",
        )
    if len(pts) < 3:
        raise _fail("E_SITE_INVALID", "La polyligne d'emprise a moins de 3 sommets.", len(pts))
    return [(to_decimal(x) * factor, to_decimal(y) * factor) for x, y in pts]


# --------------------------------------------------------------------------- module footprint


def _floor_div(a: int, b: int) -> int:
    return a // b


def _ceil_div(a: int, b: int) -> int:
    return -((-a) // b)


def to_module_footprint(site: SiteSpec, grid: GridSpec) -> ModuleFootprint:
    """Snap a (normalised, rectilinear, CCW) site inward onto the module grid.

    Grid origin = (min x, min y) of the footprint. Edge running +x takes ``CEIL`` for its
    y, -x ``FLOOR``, +y ``FLOOR`` for its x, -y ``CEIL``. Collinear vertices are then
    dropped and the ring starts at its lowest-then-leftmost vertex. Raises ``InputError``
    (``E_SITE_INVALID``, ``E_SITE_TOO_SMALL``, ``E_SITE_ACCESS_EDGE``).
    """
    try:
        return _module_footprint(site, grid)
    except _Fail as exc:
        raise InputError(exc.issues) from None


def _module_footprint(site: SiteSpec, grid: GridSpec) -> ModuleFootprint:
    module = check_module_mm(grid.module_mm)
    if site.footprint.holes:
        raise _fail("E_SITE_INVALID", "Les emprises avec trous ne sont pas prises en charge.")
    ext = [(m_to_mm(x), m_to_mm(y)) for x, y in site.footprint.exterior]
    n = len(ext)
    if _twice_area(ext) <= 0:
        raise _fail("E_SITE_INVALID", "L'emprise doit être orientée dans le sens trigonométrique.")
    x0 = min(p[0] for p in ext)
    y0 = min(p[1] for p in ext)
    rel = [(x - x0, y - y0) for x, y in ext]
    xs: list[int | None] = [None] * n  # snapped x of vertical edges, by edge index
    ys: list[int | None] = [None] * n  # snapped y of horizontal edges
    for i in range(n):
        a, b = rel[i], rel[(i + 1) % n]
        if a[1] == b[1]:
            ys[i] = _ceil_div(a[1], module) if b[0] > a[0] else _floor_div(a[1], module)
        else:
            xs[i] = _floor_div(a[0], module) if b[1] > a[1] else _ceil_div(a[0], module)
    snapped: list[MmPoint] = []
    for i in range(n):
        prev = (i - 1) % n
        x = xs[i] if xs[i] is not None else xs[prev]
        y = ys[i] if ys[i] is not None else ys[prev]
        if x is None or y is None:
            raise _fail(
                "E_SITE_INVALID",
                f"Sommet {i} sans côté horizontal et vertical : emprise non normalisée.",
            )
        snapped.append((x, y))
    edges = _simplify(_ring_edges(snapped))
    too_small = _fail(
        "E_SITE_TOO_SMALL",
        f"Emprise trop petite ou trop étroite pour la trame de {module} mm.",
    )
    if len(edges) < 4:
        raise too_small
    edges = _rotate_to_start(edges)
    try:
        polygon = ModulePolygon(exterior=tuple(e.a for e in edges))
    except ValidationError:
        raise too_small from None
    if polygon.area_cells() <= 0:  # pragma: no cover - ModulePolygon requires CCW
        raise too_small
    access = next((k for k, e in enumerate(edges) if site.access_edge in e.tags), None)
    if access is None:
        raise _fail(
            "E_SITE_ACCESS_EDGE",
            f"Le côté d'accès {site.access_edge} disparaît une fois l'emprise calée sur la trame.",
            site.access_edge,
        )
    metric_mm2 = Fraction(_twice_area(ext), 2)
    module_mm2 = polygon.area_cells() * module * module
    sliver = (metric_mm2 - module_mm2) / _MM2_PER_M2
    return ModuleFootprint(
        polygon=polygon,
        origin_m=(mm_to_m(x0), mm_to_m(y0)),
        access_edge=access,
        sliver_loss_m2=float(sliver),
    )


def module_perimeter_mm(polygon: ModulePolygon, grid: GridSpec) -> int:
    """Perimeter of a module polygon in millimetres (exact)."""
    total = 0
    for a, b in polygon.edges():
        total += abs(b[0] - a[0]) + abs(b[1] - a[1])
    return total * check_module_mm(grid.module_mm)
