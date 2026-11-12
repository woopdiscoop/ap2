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
from ale.contracts.models import CoreSpec, Entrance, GridSpec, SiteSpec
from ale.contracts.units import check_module_mm, m_to_mm, mm_to_m, to_decimal
from ale.program.models import InputError, Issue, ModuleFootprint, make_issue

__all__ = [
    "CORE_KEYS",
    "DXF_KEYS",
    "ENTRANCE_KEYS",
    "FOOTPRINT_KEYS",
    "SITE_KEYS",
    "module_perimeter_mm",
    "normalise_footprint",
    "read_site",
    "site_from_mapping",
    "solid_labels",
    "to_module_footprint",
]

SITE_KEYS: frozenset[str] = frozenset(
    {
        "footprint",
        "footprint_dxf",
        "north_angle_deg",
        "access_edge",
        "core_hint",
        "entrances",
        "cores",
        "mode",
        "setbacks",
        "party_edges",
    }
)
ENTRANCE_KEYS: frozenset[str] = frozenset({"point", "label", "main"})
CORE_KEYS: frozenset[str] = frozenset({"id", "rect", "kind"})
CORE_KINDS: tuple[str, ...] = ("stair", "lift", "shaft", "core")
DXF_KEYS: frozenset[str] = frozenset({"path", "layer", "units"})
FOOTPRINT_KEYS: frozenset[str] = frozenset({"exterior", "holes"})

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
    edges, k = _normalise_edges(points_mm, access_edge)
    return tuple(e.a for e in edges), k


def _normalise_edges(points_mm: Sequence[MmPoint], access_edge: int) -> tuple[list[_Edge], int]:
    n_in = len(points_mm)
    if not 0 <= access_edge < n_in:
        raise _fail(
            "E_SITE_ACCESS_EDGE",
            f"access_edge {access_edge} hors limites : l'emprise a {n_in} côtés (0 à {n_in - 1}).",
            access_edge,
        )
    edges = _clean_edges(points_mm)
    for k, e in enumerate(edges):
        if access_edge in e.tags:
            return edges, k
    raise _fail(
        "E_SITE_ACCESS_EDGE",
        f"Le côté d'accès {access_edge} est de longueur nulle après arrondi au millimètre.",
        access_edge,
    )


def _clean_edges(points_mm: Sequence[MmPoint]) -> list[_Edge]:
    """Simplified, CCW, rotated, simple and orthogonal edge list of a ring (E_SITE_* errors)."""
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
    return edges


def _hole_ring(points_mm: Sequence[MmPoint], k: int) -> tuple[MmPoint, ...]:
    """Courtyard ``k`` normalised: clockwise, starting at its lowest-then-leftmost vertex."""
    try:
        edges = _clean_edges(points_mm)
    except _Fail as exc:
        first = exc.issues[0]
        text = first.message.replace("Emprise", "emprise", 1)
        raise _fail(first.code, f"Cour intérieure {k} (holes[{k}]) : {text}", k) from None
    ccw = [e.a for e in edges]
    cw = [ccw[0], *reversed(ccw[1:])]  # same start vertex, opposite orientation
    return tuple(cw)


def _hole_geometry_issues(ext: Sequence[MmPoint], holes: Sequence[tuple[MmPoint, ...]]) -> None:
    """Every hole strictly inside the exterior and the holes apart from each other."""
    import shapely

    outer = shapely.Polygon(ext)
    polys = [shapely.Polygon(h) for h in holes]
    for k, poly in enumerate(polys):
        if not outer.contains(poly):
            raise _fail(
                "E_SITE_INVALID",
                f"Cour intérieure {k} (holes[{k}]) : hors de l'emprise extérieure.",
                k,
            )
        if poly.intersects(outer.exterior):
            raise _fail(
                "E_SITE_INVALID",
                f"Cour intérieure {k} (holes[{k}]) : touche le contour extérieur "
                "(une cour doit être strictement à l'intérieur).",
                k,
            )
    for k, a in enumerate(polys):
        for j in range(k + 1, len(polys)):
            if a.intersects(polys[j]):
                raise _fail(
                    "E_SITE_INVALID",
                    f"Cour intérieure {j} (holes[{j}]) : chevauche ou touche la cour {k}.",
                    j,
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
    issues.extend(_anchor_schema_issues(data))
    return issues


def _bad_schema(message: str, value: object = None) -> Issue:
    return make_issue("E_SITE_SCHEMA", message, value=value)


def _anchor_schema_issues(data: Mapping[str, Any]) -> list[Issue]:
    """Shape errors of the A.4 keys (each message names the key)."""
    out: list[Issue] = []
    mode = data.get("mode", "footprint")
    if mode not in ("footprint", "plot"):
        out.append(_bad_schema("mode doit valoir footprint ou plot.", mode))
    entrances = data.get("entrances", [])
    if not isinstance(entrances, list | tuple):
        out.append(_bad_schema("entrances doit être une liste.", entrances))
    else:
        for k, e in enumerate(entrances):
            if not isinstance(e, Mapping):
                out.append(_bad_schema(f"entrances[{k}] doit être un dictionnaire.", e))
                continue
            for key in sorted(str(x) for x in e if x not in ENTRANCE_KEYS):
                out.append(_bad_schema(f"Clé inconnue « {key} » dans entrances[{k}].", key))
            if _point(e.get("point")) is None:
                out.append(
                    _bad_schema(f"entrances[{k}].point doit être [x, y] en mètres.", e.get("point"))
                )
            if not isinstance(e.get("label", ""), str):
                out.append(_bad_schema(f"entrances[{k}].label doit être un texte.", e.get("label")))
            if not isinstance(e.get("main", False), bool):
                out.append(_bad_schema(f"entrances[{k}].main doit être true ou false.", e["main"]))
    cores = data.get("cores", [])
    if not isinstance(cores, list | tuple):
        out.append(_bad_schema("cores doit être une liste.", cores))
    else:
        for k, c in enumerate(cores):
            if not isinstance(c, Mapping):
                out.append(_bad_schema(f"cores[{k}] doit être un dictionnaire.", c))
                continue
            for key in sorted(str(x) for x in c if x not in CORE_KEYS):
                out.append(_bad_schema(f"Clé inconnue « {key} » dans cores[{k}].", key))
            if not isinstance(c.get("id"), str) or not c["id"].strip():
                out.append(_bad_schema(f"cores[{k}].id doit être un texte non vide.", c.get("id")))
            rect = c.get("rect")
            dims = (
                [_decimal(v) for v in rect]
                if isinstance(rect, list | tuple) and len(rect) == 4
                else None
            )
            if dims is None or any(v is None for v in dims):
                out.append(_bad_schema(f"cores[{k}].rect doit être [x, y, l, h] en mètres.", rect))
            elif dims[2] is not None and dims[3] is not None and (dims[2] <= 0 or dims[3] <= 0):
                out.append(
                    _bad_schema(f"cores[{k}].rect : largeur et hauteur doivent être > 0.", rect)
                )
            if c.get("kind") not in CORE_KINDS:
                out.append(
                    _bad_schema(
                        f"cores[{k}].kind doit valoir stair, lift, shaft ou core.", c.get("kind")
                    )
                )
    setbacks = data.get("setbacks")
    if setbacks is not None:
        values = [_decimal(v) for v in setbacks] if isinstance(setbacks, list | tuple) else None
        if values is None or any(v is None or v < 0 for v in values):
            out.append(_bad_schema("setbacks doit être une liste de nombres ≥ 0 (m).", setbacks))
    party = data.get("party_edges", [])
    if not isinstance(party, list | tuple) or any(
        isinstance(v, bool) or not isinstance(v, int) for v in party
    ):
        out.append(_bad_schema("party_edges doit être une liste d'entiers.", party))
    return out


def _edge_images(edges: list[_Edge], n_in: int) -> dict[int, int]:
    """Input edge index → normalised edge index (zero-length input edges are absent)."""
    return {i: k for k, e in enumerate(edges) for i in e.tags if i < n_in}


def _remap_anchors(
    data: Mapping[str, Any], edges: list[_Edge], n_in: int
) -> tuple[tuple[int, ...], tuple[float, ...] | None]:
    """``party_edges`` and ``setbacks`` of the input edges, expressed on the normalised ones."""
    image = _edge_images(edges, n_in)
    party: list[int] = []
    for i in data.get("party_edges", []):
        if not 0 <= i < n_in:
            raise _fail(
                "E_SITE_SCHEMA",
                f"party_edges : côté {i} hors limites : l'emprise a {n_in} côtés (0 à {n_in - 1}).",
                i,
            )
        if i not in image:
            raise _fail(
                "E_SITE_SCHEMA",
                f"party_edges : le côté {i} est de longueur nulle après arrondi au millimètre.",
                i,
            )
        if image[i] not in party:
            party.append(image[i])
    setbacks = data.get("setbacks")
    if setbacks is None:
        return tuple(sorted(party)), None
    if len(setbacks) != n_in:
        raise _fail(
            "E_SITE_SCHEMA",
            f"setbacks : {len(setbacks)} valeurs pour {n_in} côtés extérieurs.",
            len(setbacks),
        )
    out: list[float] = []
    for k, e in enumerate(edges):
        values = {float(setbacks[i]) for i in e.tags if i < n_in}
        if len(values) != 1:
            raise _fail(
                "E_SITE_SCHEMA",
                f"setbacks : les côtés fusionnés en un seul côté {k} ont des retraits différents.",
                sorted(values),
            )
        out.append(values.pop())
    return tuple(sorted(party)), tuple(out)


def _contract_issues(exc: ValidationError) -> tuple[Issue, ...]:
    """French issues of a contract error on the A.4 keys (messages already name the key)."""
    out: list[Issue] = []
    for err in exc.errors(include_url=False):
        msg = str(err["msg"]).removeprefix("Value error, ")
        loc = ".".join(str(p) for p in err["loc"])
        text = msg if err["type"] == "value_error" else f"{loc} : {msg}"
        out.append(_bad_schema(f"Site refusé par le contrat : {text}."))
    return tuple(out)


def _entrance(e: Mapping[str, Any]) -> Entrance:
    pt = _point(e["point"])
    assert pt is not None  # checked by the schema pass
    return Entrance(
        point=(float(pt[0]), float(pt[1])), label=e.get("label", ""), main=e.get("main", False)
    )


def _core(c: Mapping[str, Any]) -> CoreSpec:
    x, y, w, h = (float(v) for v in c["rect"])
    return CoreSpec(id=c["id"].strip(), rect=(x, y, w, h), kind=c["kind"])


def _ring_points(raw: object, name: str) -> list[tuple[Decimal, Decimal]]:
    """Points ``[x, y]`` (metres) of a ring given in ``site.yaml``."""
    if not isinstance(raw, list | tuple) or len(raw) < 3:
        raise _fail("E_SITE_SCHEMA", f"{name} doit être une liste d'au moins 3 points.", raw)
    points: list[tuple[Decimal, Decimal]] = []
    for v in raw:
        pt = _point(v)
        if pt is None:
            raise _fail("E_SITE_SCHEMA", f"Chaque point de {name} doit être [x, y].", v)
        points.append(pt)
    return points


def _site(data: object, base_dir: Path) -> SiteSpec:
    if not isinstance(data, Mapping):
        raise _fail("E_SITE_SCHEMA", "site.yaml doit contenir un dictionnaire.", data)
    issues = _schema_issues(data)
    if issues:
        raise _Fail(*issues)
    holes_mm: list[tuple[MmPoint, ...]] = []
    if "footprint" in data:
        raw = data["footprint"]
        raw_holes: object = []
        if isinstance(raw, Mapping):
            for key in sorted(str(k) for k in raw if k not in FOOTPRINT_KEYS):
                raise _fail("E_SITE_SCHEMA", f"Clé inconnue « {key} » dans footprint.", key)
            if "exterior" not in raw:
                raise _fail("E_SITE_SCHEMA", "footprint doit contenir la clé exterior.")
            raw_holes = raw.get("holes", [])
            raw = raw["exterior"]
        points = _ring_points(
            raw, "footprint" if not isinstance(data["footprint"], Mapping) else "footprint.exterior"
        )
        if not isinstance(raw_holes, list | tuple):
            raise _fail(
                "E_SITE_SCHEMA", "footprint.holes doit être une liste d'anneaux.", raw_holes
            )
        for k, hole in enumerate(raw_holes):
            hole_pts = _ring_points(hole, f"footprint.holes[{k}]")
            holes_mm.append(tuple((m_to_mm(x), m_to_mm(y)) for x, y in hole_pts))
    else:
        spec = data["footprint_dxf"]
        points = _read_dxf(base_dir / spec["path"], spec["layer"], spec.get("units"))
    mm = [(m_to_mm(x), m_to_mm(y)) for x, y in points]
    edges, access = _normalise_edges(mm, data.get("access_edge", 0))
    ring = tuple(e.a for e in edges)
    holes = tuple(_hole_ring(h, k) for k, h in enumerate(holes_mm))
    if holes:
        _hole_geometry_issues(ring, holes)
    party, setbacks = _remap_anchors(data, edges, len(mm))
    hint = data.get("core_hint")
    hint_pt = _point(hint) if hint is not None else None
    try:
        return SiteSpec(
            footprint=Polygon(
                exterior=tuple((mm_to_m(x), mm_to_m(y)) for x, y in ring),
                holes=tuple(tuple((mm_to_m(x), mm_to_m(y)) for x, y in h) for h in holes),
            ),
            north_angle_deg=float(data.get("north_angle_deg", 0)),
            access_edge=access,
            core_hint=None if hint_pt is None else (float(hint_pt[0]), float(hint_pt[1])),
            entrances=tuple(_entrance(e) for e in data.get("entrances", [])),
            cores=tuple(_core(c) for c in data.get("cores", [])),
            mode=data.get("mode", "footprint"),
            setbacks=setbacks,
            party_edges=party,
        )
    except ValidationError as exc:
        raise _Fail(*_contract_issues(exc)) from None


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


def to_module_footprint(
    site: SiteSpec, grid: GridSpec, *, strict_cores: bool = False
) -> ModuleFootprint:
    """Snap a (normalised, rectilinear, CCW) site inward onto the module grid.

    Ticket M.2: each core rectangle becomes a solid of the polygon, snapped outward (touching
    cores merge into one solid). A solid that cannot be valid (it touches the outline or a
    courtyard) is an ``E_SITE_INVALID`` error with ``strict_cores``; otherwise it is left
    out, as cores were before M.2 (callers that only use ``SiteSpec.cores`` themselves).

    Grid origin = (min x, min y) of the footprint. Edge running +x takes ``CEIL`` for its
    y, -x ``FLOOR``, +y ``FLOOR`` for its x, -y ``CEIL``. Collinear vertices are then
    dropped and the ring starts at its lowest-then-leftmost vertex. Raises ``InputError``
    (``E_SITE_INVALID``, ``E_SITE_TOO_SMALL``, ``E_SITE_ACCESS_EDGE``).
    """
    try:
        return _module_footprint(site, grid, strict_cores)
    except _Fail as exc:
        raise InputError(exc.issues) from None


def _snap_ring(ring: Sequence[MmPoint], x0: int, y0: int, module: int) -> list[MmPoint]:
    """Inward snap of a ring (material on the left of each edge) onto the module grid."""
    n = len(ring)
    rel = [(x - x0, y - y0) for x, y in ring]
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
    return snapped


def _module_holes(
    holes_mm: Sequence[Sequence[MmPoint]], x0: int, y0: int, module: int
) -> tuple[tuple[MmPoint, ...], ...]:
    """Courtyards snapped outward (the material shrinks), each at least 3 x 3 modules."""
    out: list[tuple[MmPoint, ...]] = []
    for k, ring in enumerate(holes_mm):
        snapped = _snap_ring(ring, x0, y0, module)
        edges = _simplify(_ring_edges(snapped))
        pts = tuple(e.a for e in _rotate_to_start(edges)) if len(edges) >= 4 else ()
        xs_ = [p[0] for p in pts]
        ys_ = [p[1] for p in pts]
        if not pts or max(xs_) - min(xs_) < 3 or max(ys_) - min(ys_) < 3:
            raise _fail(
                "E_SITE_TOO_SMALL",
                f"Cour intérieure {k} (holes[{k}]) : trop petite pour la trame de {module} mm "
                "(au moins 3 x 3 modules).",
                k,
            )
        out.append(pts)
    return tuple(out)


def _core_rects(site: SiteSpec, x0: int, y0: int, module: int) -> list[tuple[int, int, int, int]]:
    """Core rectangles snapped outward onto the module grid: ``(x0, y0, x1, y1)`` in modules."""
    out: list[tuple[int, int, int, int]] = []
    for core in site.cores:
        x, y, w, h = core.rect
        out.append(
            (
                _floor_div(m_to_mm(x) - x0, module),
                _floor_div(m_to_mm(y) - y0, module),
                _ceil_div(m_to_mm(x + w) - x0, module),
                _ceil_div(m_to_mm(y + h) - y0, module),
            )
        )
    return out


def _module_solids(
    site: SiteSpec, x0: int, y0: int, module: int
) -> tuple[tuple[MmPoint, ...], ...]:
    """Cores as solids (Ticket M.2): each rectangle snapped outward onto the module grid.

    Cores that touch (a stair core and the wet stack beside it) merge into one solid, so the
    solids never touch each other. Rings are clockwise, starting at the lowest-leftmost vertex.
    """
    if not site.cores:
        return ()
    import shapely

    union: Any = shapely.union_all([shapely.box(*r) for r in _core_rects(site, x0, y0, module)])
    parts: list[Any] = list(union.geoms) if union.geom_type == "MultiPolygon" else [union]
    out: list[tuple[MmPoint, ...]] = []
    for part in parts:
        if part.interiors:
            raise _fail("E_SITE_INVALID", "Des noyaux accolés entourent une cour : non géré.")
        pts = [(round(x), round(y)) for x, y in part.exterior.coords][:-1]
        if _twice_area(pts) > 0:
            pts.reverse()  # clockwise
        edges = _rotate_to_start(_simplify(_ring_edges(pts)))
        out.append(tuple(e.a for e in edges))
    return tuple(sorted(out, key=lambda r: (r[0][1], r[0][0])))


def _solid_fits(
    exterior: Sequence[MmPoint], holes: Sequence[Sequence[MmPoint]], ring: Sequence[MmPoint]
) -> bool:
    """Whether a solid ring lies strictly inside the region (no touching)."""
    try:
        ModulePolygon(
            exterior=tuple(exterior),
            holes=tuple(tuple(h) for h in holes),
            solids=(tuple(ring),),
        )
    except ValidationError:
        return False
    return True


def _cores_in_solids(
    site: SiteSpec, polygon: ModulePolygon, x0: int, y0: int, module: int
) -> list[CoreSpec]:
    """The cores that ended up inside one of the polygon's solids."""
    if not polygon.solids:
        return []
    import shapely

    rings = [shapely.Polygon(r) for r in polygon.solids]
    rects = _core_rects(site, x0, y0, module)
    return [
        c
        for c, r in zip(site.cores, rects, strict=True)
        if any(g.contains(shapely.box(*r).representative_point()) for g in rings)
    ]


def solid_labels(site: SiteSpec, footprint: ModuleFootprint, grid: GridSpec) -> tuple[str, ...]:
    """Label of every solid of ``footprint.polygon``: the ids of the cores it merges, joined
    by ``+`` (Ticket M.2; used by the DXF / SVG exports)."""
    if not footprint.polygon.solids:
        return ()
    import shapely

    module = check_module_mm(grid.module_mm)
    x0 = min(m_to_mm(p[0]) for p in site.footprint.exterior)
    y0 = min(m_to_mm(p[1]) for p in site.footprint.exterior)
    rects = _core_rects(site, x0, y0, module)
    out: list[str] = []
    for ring in footprint.polygon.solids:
        poly = shapely.Polygon(ring)
        ids = [
            c.id
            for c, r in zip(site.cores, rects, strict=True)
            if poly.contains(shapely.box(*r).representative_point())
        ]
        out.append("+".join(ids))
    return tuple(out)


def _module_footprint(site: SiteSpec, grid: GridSpec, strict_cores: bool) -> ModuleFootprint:
    module = check_module_mm(grid.module_mm)
    ext = [(m_to_mm(x), m_to_mm(y)) for x, y in site.footprint.exterior]
    if _twice_area(ext) <= 0:
        raise _fail("E_SITE_INVALID", "L'emprise doit être orientée dans le sens trigonométrique.")
    x0 = min(p[0] for p in ext)
    y0 = min(p[1] for p in ext)
    snapped = _snap_ring(ext, x0, y0, module)
    holes_mm = [[(m_to_mm(x), m_to_mm(y)) for x, y in h] for h in site.footprint.holes]
    edges = _simplify(_ring_edges(snapped))
    too_small = _fail(
        "E_SITE_TOO_SMALL",
        f"Emprise trop petite ou trop étroite pour la trame de {module} mm.",
    )
    if len(edges) < 4:
        raise too_small
    edges = _rotate_to_start(edges)
    solids = _module_solids(site, x0, y0, module)
    holes = _module_holes(holes_mm, x0, y0, module)
    ring = tuple(e.a for e in edges)
    if solids and not strict_cores:
        solids = tuple(s_ for s_ in solids if _solid_fits(ring, holes, s_))
    try:
        polygon = ModulePolygon(exterior=ring, holes=holes, solids=solids)
    except ValidationError as exc:
        if solids:
            raise _fail(
                "E_SITE_INVALID",
                "Noyau (cores) invalide une fois calé sur la trame (au contact du contour, "
                f"d'une cour ou d'un autre noyau) : {exc.errors()[0]['msg']}.",
            ) from None
        if holes_mm:
            raise _fail(
                "E_SITE_INVALID",
                "Cour intérieure invalide une fois l'emprise calée sur la trame "
                f"(cour fusionnée avec le contour ou une autre cour) : {exc.errors()[0]['msg']}.",
            ) from None
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
    core_mm2 = sum(
        Fraction(m_to_mm(c.rect[2] + c.rect[0]) - m_to_mm(c.rect[0]))
        * Fraction(m_to_mm(c.rect[3] + c.rect[1]) - m_to_mm(c.rect[1]))
        for c in _cores_in_solids(site, polygon, x0, y0, module)
    )
    metric_mm2 = Fraction(_twice_area(ext) + sum(_twice_area(h) for h in holes_mm), 2) - core_mm2
    module_mm2 = polygon.area_cells() * module * module
    sliver = (metric_mm2 - module_mm2) / _MM2_PER_M2
    return ModuleFootprint(
        polygon=polygon,
        origin_m=(mm_to_m(x0), mm_to_m(y0)),
        access_edge=access,
        sliver_loss_m2=float(sliver),
    )


def module_perimeter_mm(polygon: ModulePolygon, grid: GridSpec) -> int:
    """Perimeter of a module polygon in millimetres (exact), courtyard faces included."""
    total = 0
    for a, b in polygon.edges():
        total += abs(b[0] - a[0]) + abs(b[1] - a[1])
    for hole in polygon.holes:
        for i, a in enumerate(hole):
            b = hole[(i + 1) % len(hole)]
            total += abs(b[0] - a[0]) + abs(b[1] - a[1])
    return total * check_module_mm(grid.module_mm)
