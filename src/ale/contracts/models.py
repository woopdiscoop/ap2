"""Shared data model of ALE (pydantic v2, frozen, extra fields forbidden).

Units: program/site/rulebook values are metres and m²; ``Layout`` geometry is in integer
modules (see ``GridSpec``); ``PlanGeometry`` is in the source's native units until
``PlanGeometry.to_metric()``.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from collections.abc import Iterable
from decimal import localcontext
from fractions import Fraction
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_serializer,
    model_validator,
)

from ale.contracts.enums import (
    Bearing,
    Fidelity,
    Frame,
    LabelSource,
    MacroZone,
    OpeningKind,
    ScaleMethod,
    SourceKind,
    TypeCategory,
)
from ale.contracts.geometry import (
    Float,
    LineString,
    ModulePolygon,
    ModuleRect,
    Point2,
    Polygon,
)
from ale.contracts.serialization import canonical_json
from ale.contracts.taxonomy import RoomTypeKey, load_taxonomy
from ale.contracts.units import (
    MODULE_MM_MAX,
    MODULE_MM_MIN,
    cells_to_m2,
    modules_to_m,
    to_decimal,
)

__all__ = [
    "AdjEntry",
    "Adjacency",
    "CoreOffset",
    "CoreSpec",
    "Entrance",
    "GridSpec",
    "LabelledPolygon",
    "Layout",
    "LayoutMetrics",
    "Opening",
    "PlacedRoom",
    "PlanGeometry",
    "PolishExpression",
    "Program",
    "Quantiles",
    "RoomId",
    "RoomSpec",
    "Rulebook",
    "SiteSpec",
    "TextItem",
    "TypeStats",
    "Violation",
    "Wall",
]

_CONFIG = ConfigDict(extra="forbid", frozen=True)

RoomId = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,32}$")]
"""Identifier of a program room: 1-32 characters among ``A-Z a-z 0-9 _ -``."""

Unit = Annotated[Float, Field(ge=-1.0, le=1.0)]
Prob = Annotated[Float, Field(ge=0.0, le=1.0)]
NonNegInt = Annotated[StrictInt, Field(ge=0)]


_FORBIDDEN_CATEGORIES = (TypeCategory.SPECIAL, TypeCategory.CIRCULATION)


def _check_type_allowed(key: str, what: str) -> None:
    category = load_taxonomy().get(key).category
    if category in _FORBIDDEN_CATEGORIES:
        raise ValueError(f"{what}: type {key!r} of category {category} is not allowed")


def _duplicates(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    dups: list[str] = []
    for it in items:
        if it in seen and it not in dups:
            dups.append(it)
        seen.add(it)
    return dups


def _exact_sub_m2(a: Fraction, target_m2: float) -> float:
    """``a - target`` in m², computed exactly then rounded once to float."""
    return float(a - Fraction(to_decimal(target_m2)))


# --------------------------------------------------------------------------- 9.1 Program & site


class RoomSpec(BaseModel):
    """One program row (metres, m²)."""

    model_config = _CONFIG

    id: RoomId
    name: Annotated[
        StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ]
    type: RoomTypeKey
    target_area_m2: Annotated[Float, Field(gt=0.0, le=10_000.0)]
    quantity: Annotated[StrictInt, Field(ge=1, le=500)] = 1
    macro_zone: MacroZone
    needs_facade: StrictBool = False
    orientation_override: Annotated[dict[Bearing, Unit], Field(min_length=1)] | None = None
    min_width_m: Annotated[Float, Field(gt=0.0)] | None = None
    adjacent_to: tuple[RoomId, ...] = ()
    avoid: tuple[RoomId, ...] = ()
    floor: StrictInt = 0
    anchor: Literal["corner", "entrance"] | None = None
    """Hard line of the architect (A.4): ``corner`` = the room takes a corner of the building,
    ``entrance`` = the room is at the main entrance. Not used by the v1 engines."""

    @field_validator("type")
    @classmethod
    def _type_allowed(cls, v: str) -> str:
        _check_type_allowed(v, "program room")
        return v

    @field_validator("floor")
    @classmethod
    def _floor_non_negative(cls, v: int) -> int:
        """Levels start at 0 (A.4); v1 engines are single-floor (``prepare_input`` checks)."""
        if v < 0:
            raise ValueError("floor must be >= 0")
        return v

    @model_validator(mode="after")
    def _references(self) -> RoomSpec:
        for name in ("adjacent_to", "avoid"):
            refs: tuple[str, ...] = getattr(self, name)
            if self.id in refs:
                raise ValueError(f"{name} must not reference the room itself ({self.id!r})")
            dups = _duplicates(refs)
            if dups:
                raise ValueError(f"{name} contains duplicates: {dups}")
        both = sorted(set(self.adjacent_to) & set(self.avoid))
        if both:
            raise ValueError(f"ids both in adjacent_to and avoid: {both}")
        return self


class Program(BaseModel):
    """The room program (≥ 1 room)."""

    model_config = _CONFIG

    rooms: Annotated[tuple[RoomSpec, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _graph(self) -> Program:
        ids = [r.id for r in self.rooms]
        dups = _duplicates(ids)
        if dups:
            raise ValueError(f"duplicate room ids: {dups}")
        by_id = {r.id: r for r in self.rooms}
        for r in self.rooms:
            for ref in (*r.adjacent_to, *r.avoid):
                if ref not in by_id:
                    raise ValueError(f"room {r.id!r} references unknown id {ref!r}")
        for r in self.rooms:
            for ref in r.adjacent_to:
                if r.id in by_id[ref].avoid:
                    raise ValueError(f"room {r.id!r} requires {ref!r} but {ref!r} avoids {r.id!r}")
        return self

    def instances(self) -> tuple[tuple[str, RoomSpec], ...]:
        """Expand quantities: ``id`` if quantity == 1, else ``id#k`` (k zero-padded, 1-based)."""
        out: list[tuple[str, RoomSpec]] = []
        for r in self.rooms:
            if r.quantity == 1:
                out.append((r.id, r))
                continue
            width = len(str(r.quantity))
            out.extend((f"{r.id}#{str(k).zfill(width)}", r) for k in range(1, r.quantity + 1))
        return tuple(out)


#: Tolerance (metres) of the "entrance on the boundary" check: one module at the default
#: grid (100 mm). The contract has no grid, so the tolerance does not follow ``module_mm``.
ENTRANCE_TOLERANCE_M = 0.1
_GEOM_EPS = 1e-9


class Entrance(BaseModel):
    """An entrance of the building or plot (metres); at most one is ``main``."""

    model_config = _CONFIG

    point: Point2
    label: StrictStr = ""
    main: StrictBool = False


class CoreSpec(BaseModel):
    """A fixed vertical core: ``rect = (x, y, w, h)`` in metres (lower-left corner, size)."""

    model_config = _CONFIG

    id: RoomId
    rect: tuple[Float, Float, Annotated[Float, Field(gt=0.0)], Annotated[Float, Field(gt=0.0)]]
    kind: Literal["stair", "lift", "shaft", "core"]


class SiteSpec(BaseModel):
    """Buildable site (metres, y-up).

    ``core_hint`` is deprecated (kept for compatibility): use ``cores``. ``mode`` is
    ``"footprint"`` (the polygon is the building outline, today's behaviour) or ``"plot"``
    (the polygon is the plot and ``setbacks`` apply). ``party_edges`` lists exterior edges on a
    party wall. The other A.4 fields are not used by the v1 engines.

    Ticket M.2 (contracts 1.7.0): ``cores`` are now used. ``to_module_footprint`` turns each
    core rectangle into a solid of the module footprint (snapped **outward** to the grid, like
    courtyards), around which the engine lays out the floor. Sites without ``cores`` are
    unchanged (byte-identical outputs).
    """

    model_config = _CONFIG

    footprint: Polygon
    north_angle_deg: Annotated[Float, Field(ge=0.0, lt=360.0)]
    access_edge: StrictInt
    core_hint: Point2 | None = None
    entrances: tuple[Entrance, ...] = ()
    cores: tuple[CoreSpec, ...] = ()
    mode: Literal["footprint", "plot"] = "footprint"
    setbacks: tuple[Annotated[Float, Field(ge=0.0)], ...] | None = None
    party_edges: tuple[StrictInt, ...] = ()

    @model_validator(mode="after")
    def _site(self) -> SiteSpec:
        rings = (self.footprint.exterior, *self.footprint.holes)
        for ring in rings:
            n = len(ring)
            for i in range(n):
                a, b = ring[i], ring[i + 1 if i + 1 < n else 0]
                if a[0] != b[0] and a[1] != b[1]:
                    raise ValueError(f"footprint must be rectilinear (edge {a}->{b})")
        n_ext = len(self.footprint.exterior)
        if not 0 <= self.access_edge < n_ext:
            raise ValueError(f"access_edge {self.access_edge} out of range 0..{n_ext - 1}")
        self._check_anchors(n_ext)
        return self

    def _check_anchors(self, n_ext: int) -> None:
        if self.setbacks is not None:
            if self.mode != "plot":
                raise ValueError(
                    "setbacks : seulement avec mode « plot » (mode actuel : « footprint »)"
                )
            if len(self.setbacks) != n_ext:
                raise ValueError(
                    f"setbacks : {len(self.setbacks)} valeurs pour {n_ext} côtés extérieurs"
                )
        for i in self.party_edges:
            if not 0 <= i < n_ext:
                raise ValueError(f"party_edges : côté {i} hors limites (0 à {n_ext - 1})")
        dups = sorted({i for i in self.party_edges if self.party_edges.count(i) > 1})
        if dups:
            raise ValueError(f"party_edges : côtés en double {dups}")
        if sum(e.main for e in self.entrances) > 1:
            raise ValueError("entrances : une seule entrée peut être « main »")
        dup_ids = _duplicates(c.id for c in self.cores)
        if dup_ids:
            raise ValueError(f"cores : identifiants en double {dup_ids}")
        if not (self.entrances or self.cores):
            return
        from shapely import Point, box
        from shapely import Polygon as ShapelyPolygon

        site = ShapelyPolygon(self.footprint.exterior, self.footprint.holes)
        boundary = site.boundary
        for k, e in enumerate(self.entrances):
            pt = Point(e.point)
            if self.mode == "plot":
                if not site.buffer(_GEOM_EPS).covers(pt):
                    raise ValueError(f"entrances[{k}] : le point {e.point} est hors de la parcelle")
            elif boundary.distance(pt) > ENTRANCE_TOLERANCE_M + _GEOM_EPS:
                raise ValueError(
                    f"entrances[{k}] : le point {e.point} n'est pas sur le contour de l'emprise "
                    f"(tolérance {ENTRANCE_TOLERANCE_M} m)"
                )
        boxes: list[Any] = []
        for k, c in enumerate(self.cores):
            x, y, w, h = c.rect
            rect = box(x, y, x + w, y + h)
            if not site.buffer(_GEOM_EPS).covers(rect):
                raise ValueError(f"cores[{k}] ({c.id!r}) : le rectangle {c.rect} sort du site")
            for j, other in enumerate(boxes):
                if rect.intersection(other).area > _GEOM_EPS:
                    raise ValueError(
                        f"cores[{k}] ({c.id!r}) : chevauche cores[{j}] ({self.cores[j].id!r})"
                    )
            boxes.append(rect)


# --------------------------------------------------------------------------- 9.2 Layout


class GridSpec(BaseModel):
    """Module grid; ``module_mm`` in millimetres (100..1200, default 100 = 0.10 m)."""

    model_config = _CONFIG

    module_mm: Annotated[StrictInt, Field(ge=MODULE_MM_MIN, le=MODULE_MM_MAX)] = 100


class PlacedRoom(BaseModel):
    """A room (or circulation strip) placed on the module grid."""

    model_config = _CONFIG

    instance_id: StrictStr
    spec_id: StrictStr | None
    rect: ModuleRect
    target_area_m2: Float | None

    def area_m2(self, grid: GridSpec) -> float:
        """Placed area in m²."""
        return cells_to_m2(self.rect.area_cells(), grid.module_mm)

    def aspect_ratio(self) -> float:
        """``max(w, h) / min(w, h)`` (unitless, ≥ 1)."""
        return max(self.rect.w, self.rect.h) / min(self.rect.w, self.rect.h)

    def bbox_m(self, grid: GridSpec) -> tuple[float, float, float, float]:
        """Bounding box ``(x0, y0, x1, y1)`` in metres."""
        m = grid.module_mm
        r = self.rect
        return (
            modules_to_m(r.x, m),
            modules_to_m(r.y, m),
            modules_to_m(r.x2(), m),
            modules_to_m(r.y2(), m),
        )

    def area_delta_m2(self, grid: GridSpec) -> float | None:
        """Placed - target area in m² (``None`` when there is no target, e.g. circulation)."""
        if self.target_area_m2 is None:
            return None
        placed = Fraction(self.rect.area_cells() * grid.module_mm**2, 1_000_000)
        return _exact_sub_m2(placed, self.target_area_m2)


class Violation(BaseModel):
    """A rule violation reported for a layout."""

    model_config = _CONFIG

    code: StrictStr
    instance_ids: tuple[StrictStr, ...]
    detail: StrictStr


class LayoutMetrics(BaseModel):
    """Cost and quality metrics of a layout (areas in m²)."""

    model_config = _CONFIG

    total_cost: Float
    cost_breakdown: dict[StrictStr, Float]
    total_overshoot_m2: Float
    circulation_area_m2: Float
    residue_area_m2: Float
    violations: tuple[Violation, ...]


class Layout(BaseModel):
    """Output of Phase 3: placed rooms on the module grid (+y up, 1 unit = 1 module).

    Ticket M.2 (contracts 1.7.0): ``fixed`` holds the rooms the vertical skeleton places
    inside the footprint's ``solids`` (core, wet rooms, ``reserve_technique``), sorted by
    ``instance_id``; empty by default and then left out of the serialised form. They are not
    part of the tiling invariant: each lies inside a solid and none overlaps another.
    """

    # ``constants``: the wrap serializer below would otherwise turn a NaN metric into ``null``
    # instead of letting ``canonical_json`` reject it.
    model_config = ConfigDict(extra="forbid", frozen=True, ser_json_inf_nan="constants")

    schema_version: Literal["ale.layout/1"] = "ale.layout/1"
    grid: GridSpec
    footprint: ModulePolygon
    rooms: tuple[PlacedRoom, ...]
    circulation: tuple[PlacedRoom, ...]
    residue: tuple[ModuleRect, ...] = ()
    seed: StrictInt
    rulebook_version: StrictStr
    metrics: LayoutMetrics
    fixed: tuple[PlacedRoom, ...] = ()

    @model_serializer(mode="wrap")
    def _drop_empty_fixed(self, handler: Any) -> Any:
        out = handler(self)
        if isinstance(out, dict) and not out.get("fixed"):
            out.pop("fixed", None)
        return out

    @model_validator(mode="after")
    def _cheap_checks(self) -> Layout:
        ids = [p.instance_id for p in (*self.rooms, *self.circulation, *self.fixed)]
        dups = _duplicates(ids)
        if dups:
            raise ValueError(f"duplicate instance ids: {dups}")
        for name in ("rooms", "circulation", "fixed"):
            seq: tuple[PlacedRoom, ...] = getattr(self, name)
            keys = [p.instance_id for p in seq]
            if keys != sorted(keys):
                raise ValueError(f"{name} must be sorted by instance_id")
        for p in self.circulation:
            if p.spec_id is not None:
                raise ValueError(f"circulation entry {p.instance_id!r} must have spec_id None")
        if self.fixed:
            self._check_fixed()
        return self

    def _check_fixed(self) -> None:
        from shapely import Polygon as ShapelyPolygon
        from shapely import box

        solids = [ShapelyPolygon(r) for r in self.footprint.solids]
        boxes: list[Any] = []
        for p in self.fixed:
            r = p.rect
            b = box(r.x, r.y, r.x2(), r.y2())
            if not any(s.covers(b) for s in solids):
                raise ValueError(f"fixed room {p.instance_id!r} does not lie inside a solid")
            for q, other in zip(self.fixed, boxes, strict=False):
                if b.intersection(other).area > 0:
                    raise ValueError(f"fixed rooms {q.instance_id!r} and {p.instance_id!r} overlap")
            boxes.append(b)


# --------------------------------------------------------------------------- 9.3 Slicing tree

_LEAF_RE = re.compile(r"^[A-Za-z0-9_#-]{1,40}$")
_OPERATORS = ("H", "V")


class PolishExpression(BaseModel):
    """Normalised postfix (Polish) slicing expression.

    ``a b V`` = a left of b (vertical cut); ``a b H`` = a below b (horizontal cut).
    """

    model_config = _CONFIG

    tokens: tuple[StrictStr, ...]

    @field_validator("tokens")
    @classmethod
    def _valid(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        operands = operators = 0
        leaves: list[str] = []
        prev: str | None = None
        for i, tok in enumerate(v):
            if tok in _OPERATORS:
                operators += 1
                if prev == tok:
                    raise ValueError(f"not normalised: consecutive {tok!r} at position {i}")
            else:
                if not _LEAF_RE.match(tok):
                    raise ValueError(f"invalid leaf id {tok!r}")
                operands += 1
                leaves.append(tok)
            if operands <= operators:
                raise ValueError(f"balloting property violated at position {i}")
            prev = tok
        if operands != operators + 1:
            raise ValueError(
                f"expression is incomplete: {operands} operands for {operators} operators"
            )
        dups = _duplicates(leaves)
        if dups:
            raise ValueError(f"duplicate leaf ids: {dups}")
        return v

    def leaves(self) -> tuple[str, ...]:
        """Leaf ids in order of appearance."""
        return tuple(t for t in self.tokens if t not in _OPERATORS)


# --------------------------------------------------------------------------- 9.4 Extraction


class TextItem(BaseModel):
    """A text entity of a plan (native units; rotation in degrees)."""

    model_config = _CONFIG

    text: StrictStr
    insert: Point2
    height: Float | None = None
    rotation_deg: Float = 0.0
    layer: StrictStr | None = None
    source: Literal["CAD", "PDF", "OCR"]


class Wall(BaseModel):
    """A wall centreline (native units)."""

    model_config = _CONFIG

    centerline: LineString
    thickness: Float | None = None


class Opening(BaseModel):
    """A door or window along a host wall (native units; ``width_m`` in metres)."""

    model_config = _CONFIG

    kind: OpeningKind
    segment: LineString
    width_native: Annotated[Float, Field(gt=0.0)]
    width_m: Float | None = None
    host_wall: StrictInt | None = None

    @field_validator("segment")
    @classmethod
    def _two_points(cls, v: LineString) -> LineString:
        if len(v.coords) != 2:
            raise ValueError("an opening segment must have exactly 2 points")
        return v


class LabelledPolygon(BaseModel):
    """A room polygon of a plan (native units) with its label."""

    model_config = _CONFIG

    id: StrictStr
    polygon: Polygon
    type: RoomTypeKey | None = None
    label_source: LabelSource | None = None
    confidence: Prob = 0.0
    raw_label: StrictStr | None = None
    area_text_m2: Float | None = None

    @model_validator(mode="after")
    def _label_coupling(self) -> LabelledPolygon:
        if (self.type is None) != (self.label_source is None):
            raise ValueError("type is None if and only if label_source is None")
        return self


def _mul(a: float, s: float) -> float:
    """``a * s`` computed in exact decimal arithmetic, rounded once to float."""
    with localcontext() as ctx:
        ctx.prec = 80
        return float(to_decimal(a) * to_decimal(s))


class PlanGeometry(BaseModel):
    """Phase 1 extraction result for one plan, in the source's native units and frame."""

    model_config = _CONFIG

    schema_version: Literal["ale.plan/1"] = "ale.plan/1"
    source_sha256: Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    page: NonNegInt
    plan_index: NonNegInt
    source_kind: SourceKind
    frame: Frame
    units_label: StrictStr | None = None
    scale_m_per_unit: Annotated[Float, Field(gt=0.0)] | None = None
    scale_method: ScaleMethod = ScaleMethod.UNKNOWN
    scale_confidence: Prob = 0.0
    walls: tuple[Wall, ...] = ()
    openings: tuple[Opening, ...] = ()
    rooms: tuple[LabelledPolygon, ...] = ()
    texts: tuple[TextItem, ...] = ()
    warnings: tuple[StrictStr, ...] = ()

    @model_validator(mode="after")
    def _consistency(self) -> PlanGeometry:
        if (self.scale_method is ScaleMethod.UNKNOWN) != (self.scale_m_per_unit is None):
            raise ValueError("scale_method is UNKNOWN if and only if scale_m_per_unit is None")
        n_walls = len(self.walls)
        for i, op in enumerate(self.openings):
            if op.host_wall is not None and not 0 <= op.host_wall < n_walls:
                raise ValueError(f"opening {i}: host_wall {op.host_wall} out of range")
        scale = self.scale_m_per_unit
        if scale is not None:
            for i, op in enumerate(self.openings):
                if op.width_m is None:
                    continue
                expected = _mul(op.width_native, scale)
                if abs(op.width_m - expected) > 1e-6 * max(1.0, op.width_m):
                    raise ValueError(
                        f"opening {i}: width_m {op.width_m} inconsistent with "
                        f"width_native * scale = {expected}"
                    )
        dups = _duplicates(r.id for r in self.rooms)
        if dups:
            raise ValueError(f"duplicate room polygon ids: {dups}")
        return self

    def to_metric(self) -> PlanGeometry:
        """Copy in metres, ``Frame.Y_UP`` (``Y_DOWN`` is flipped about y = 0).

        Requires a known scale (``ValueError`` otherwise). ``units_label`` becomes ``"m"``,
        the scale 1.0 (method and confidence preserved), and every opening gets ``width_m``.
        Text rotations are negated when flipping a ``Y_DOWN`` plan.
        """
        s = self.scale_m_per_unit
        if s is None:
            raise ValueError("to_metric() requires a known scale")
        flip = self.frame is Frame.Y_DOWN

        def pt(p: Point2) -> Point2:
            y = _mul(p[1], s)
            return (_mul(p[0], s), -y if flip else y)

        def ring(r: tuple[Point2, ...]) -> tuple[Point2, ...]:
            return tuple(pt(p) for p in r)

        def line(ls: LineString) -> LineString:
            return LineString(coords=ring(ls.coords))

        def opt(v: float | None) -> float | None:
            return None if v is None else _mul(v, s)

        walls = tuple(
            Wall(centerline=line(w.centerline), thickness=opt(w.thickness)) for w in self.walls
        )
        openings = tuple(
            o.model_copy(
                update={
                    "segment": line(o.segment),
                    "width_native": _mul(o.width_native, s),
                    "width_m": _mul(o.width_native, s),
                }
            )
            for o in self.openings
        )
        rooms = tuple(
            r.model_copy(
                update={
                    "polygon": Polygon(
                        exterior=ring(r.polygon.exterior),
                        holes=tuple(ring(h) for h in r.polygon.holes),
                    )
                }
            )
            for r in self.rooms
        )
        texts = tuple(
            t.model_copy(
                update={
                    "insert": pt(t.insert),
                    "height": opt(t.height),
                    "rotation_deg": (-t.rotation_deg if flip else t.rotation_deg) + 0.0,
                }
            )
            for t in self.texts
        )
        data: dict[str, Any] = self.model_dump()
        data.update(
            frame=Frame.Y_UP,
            units_label="m",
            scale_m_per_unit=1.0,
            walls=[w.model_dump() for w in walls],
            openings=[o.model_dump() for o in openings],
            rooms=[r.model_dump() for r in rooms],
            texts=[t.model_dump() for t in texts],
        )
        return PlanGeometry.model_validate(data)


# --------------------------------------------------------------------------- 9.5 Rulebook


class Quantiles(BaseModel):
    """10th / 50th / 90th percentiles of a statistic; ``n`` = sample size."""

    model_config = _CONFIG

    p10: Float
    p50: Float
    p90: Float
    n: NonNegInt = 0

    @model_validator(mode="after")
    def _ordered(self) -> Quantiles:
        if not self.p10 <= self.p50 <= self.p90:
            raise ValueError("quantiles must satisfy p10 <= p50 <= p90")
        return self


class TypeStats(BaseModel):
    """Statistics of one room type: aspect (long/short), area (m²), orientation preference."""

    model_config = _CONFIG

    aspect: Quantiles
    area_m2: Quantiles
    orientation: dict[Bearing, Unit]
    # Ticket R.8 (contracts 1.8.0): façade statistics learned from built plans: depth from the
    # façade (m), length of the longest façade edge (m), façade length per m² (rooms without
    # façade count as 0) and the number of rooms with a façade. Absent (None / 0) they are left
    # out of the serialised form, so rulebooks without them serialise exactly as before.
    depth_m: Quantiles | None = None
    facade_width_m: Quantiles | None = None
    facade_m_per_m2: Float | None = None
    n_facade_samples: NonNegInt = 0

    @model_serializer(mode="wrap")
    def _drop_empty_facade(self, handler: Any) -> Any:
        out = handler(self)
        if isinstance(out, dict):
            for name in ("depth_m", "facade_width_m", "facade_m_per_m2"):
                if out.get(name) is None:
                    out.pop(name, None)
            if not out.get("n_facade_samples"):
                out.pop("n_facade_samples", None)
        return out

    @model_validator(mode="after")
    def _ranges(self) -> TypeStats:
        if self.aspect.p10 < 1.0:
            raise ValueError("aspect.p10 must be >= 1.0")
        if self.aspect.p90 > 6.0:
            raise ValueError("aspect.p90 must be <= 6.0")
        if self.area_m2.p10 <= 0.0:
            raise ValueError("area_m2.p10 must be > 0")
        if set(self.orientation) != set(Bearing):
            raise ValueError("orientation must contain exactly the 4 bearings N, E, S, W")
        return self


class AdjEntry(BaseModel):
    """Adjacency probability of an unordered pair of room types (stored with ``a <= b``)."""

    model_config = _CONFIG

    a: RoomTypeKey
    b: RoomTypeKey
    p: Prob
    n_support: StrictInt = 0

    @model_validator(mode="before")
    @classmethod
    def _order(cls, data: Any) -> Any:
        if isinstance(data, dict):
            a, b = data.get("a"), data.get("b")
            if isinstance(a, str) and isinstance(b, str) and b < a:
                data = {**data, "a": b, "b": a}
        return data


class Adjacency(BaseModel):
    """Adjacency probabilities; ``default_p`` applies to pairs not listed."""

    model_config = _CONFIG

    default_p: Prob
    pairs: tuple[AdjEntry, ...]

    @field_validator("pairs")
    @classmethod
    def _sorted_unique(cls, v: tuple[AdjEntry, ...]) -> tuple[AdjEntry, ...]:
        out = tuple(sorted(v, key=lambda e: (e.a, e.b)))
        dups = _duplicates(f"({e.a}, {e.b})" for e in out)
        if dups:
            raise ValueError(f"duplicate adjacency pairs: {dups}")
        return out

    def p(self, a: str, b: str) -> float:
        """Order-insensitive probability lookup, falling back to ``default_p``."""
        lo, hi = (a, b) if a <= b else (b, a)
        for e in self.pairs:
            if e.a == lo and e.b == hi:
                return e.p
        return self.default_p


Half = Annotated[Float, Field(ge=-0.5, le=0.5)]


class CoreOffset(BaseModel):
    """Normalised offset of the service core from the footprint centroid (unitless)."""

    model_config = _CONFIG

    dx_norm: Half
    dy_norm: Half
    n: StrictInt = 0


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Rulebook(BaseModel):
    """Per-type statistics and adjacency priors (areas in m²)."""

    model_config = _CONFIG

    schema_version: Literal["ale.rulebook/1"] = "ale.rulebook/1"
    version: Annotated[StrictStr, StringConstraints(min_length=1)]
    kind: Literal["seed", "mined", "blended"]
    author: StrictStr | None = None
    date: StrictStr | None = None
    n_plans: StrictInt = 0
    source_mix: dict[Fidelity, StrictInt] = {}
    types: dict[RoomTypeKey, TypeStats]
    adjacency: Adjacency
    core_offset: CoreOffset

    @field_validator("date")
    @classmethod
    def _date_format(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _DATE_RE.match(v):
            raise ValueError("date must be YYYY-MM-DD")
        try:
            _dt.date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"date {v!r} is not a valid calendar date") from exc
        return v

    @field_validator("types")
    @classmethod
    def _types_allowed(cls, v: dict[str, TypeStats]) -> dict[str, TypeStats]:
        for key in v:
            _check_type_allowed(key, "rulebook types")
        return v

    @model_validator(mode="after")
    def _seed_fields(self) -> Rulebook:
        if self.kind == "seed":
            if not self.author:
                raise ValueError("author (non-empty) is required when kind == 'seed'")
            if self.date is None:
                raise ValueError("date is required when kind == 'seed'")
        return self

    def missing_types(self, needed: Iterable[str]) -> tuple[str, ...]:
        """Sorted keys of ``needed`` that have no entry in ``types``."""
        return tuple(sorted({k for k in needed if k not in self.types}))

    def content_sha256(self) -> str:
        """SHA-256 (hex) of ``canonical_json(self)``."""
        return hashlib.sha256(canonical_json(self)).hexdigest()
