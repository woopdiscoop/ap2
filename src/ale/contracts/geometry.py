"""Plain-data geometry: float geometry (native units or metres) and integer module geometry.

Shapely is used only inside validators and conversion helpers (imported lazily so that
importing the contracts does not import numpy); it is never stored in a model.

Module geometry convention: origin at the lower-left corner of the footprint's module
grid, +x right, +y up, 1 unit = 1 module. ``ModuleRect(x, y, w, h)`` covers
``[x, x+w] x [y, y+h]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

if TYPE_CHECKING:
    import shapely

__all__ = [
    "Float",
    "LineString",
    "ModulePoint",
    "ModulePolygon",
    "ModuleRect",
    "Point2",
    "Polygon",
    "polygon_from_shapely",
    "to_shapely",
]


def _no_str_no_bool(v: Any) -> Any:
    """Reject strings and bools for float fields (ints are accepted and coerced)."""
    if isinstance(v, str | bytes | bytearray | bool):
        raise ValueError("expected a number, not a string or bool")
    return v


Float = Annotated[float, BeforeValidator(_no_str_no_bool)]
"""A float field that accepts ints but rejects strings and bools."""

Point2 = tuple[Float, Float]
"""A 2-D point ``(x, y)`` in native units or metres."""

ModulePoint = tuple[StrictInt, StrictInt]
"""A 2-D point ``(x, y)`` in integer modules."""

_CONFIG = ConfigDict(extra="forbid", frozen=True)


class LineString(BaseModel):
    """Polyline in native units or metres: ≥ 2 points, no consecutive duplicates."""

    model_config = _CONFIG

    coords: Annotated[tuple[Point2, ...], Field(min_length=2)]

    @field_validator("coords")
    @classmethod
    def _no_consecutive_duplicates(cls, v: tuple[Point2, ...]) -> tuple[Point2, ...]:
        for i in range(1, len(v)):
            if v[i] == v[i - 1]:
                raise ValueError(f"consecutive duplicate point at index {i}: {v[i]}")
        return v


def _check_ring(ring: tuple[Point2, ...], name: str) -> None:
    if len(ring) < 3:
        raise ValueError(f"{name} must have at least 3 points")
    if ring[0] == ring[-1]:
        raise ValueError(f"{name} must not be closed (first point repeated as last)")


class Polygon(BaseModel):
    """Polygon in native units or metres.

    Rings are stored open (first point not repeated), with ≥ 3 points each; the polygon
    must be valid according to shapely ``is_valid``.
    """

    model_config = _CONFIG

    exterior: tuple[Point2, ...]
    holes: tuple[tuple[Point2, ...], ...] = ()

    @model_validator(mode="after")
    def _valid(self) -> Polygon:
        _check_ring(self.exterior, "exterior")
        for k, hole in enumerate(self.holes):
            _check_ring(hole, f"hole {k}")
        import shapely

        geom = shapely.Polygon(self.exterior, self.holes)
        if not geom.is_valid:
            import shapely.validation

            raise ValueError(f"invalid polygon: {shapely.validation.explain_validity(geom)}")
        return self


class ModuleRect(BaseModel):
    """Axis-aligned rectangle in modules covering ``[x, x+w] x [y, y+h]`` (w, h ≥ 1).

    Accepts positional arguments ``ModuleRect(x, y, w, h)`` as well as keywords.
    """

    model_config = _CONFIG

    x: StrictInt
    y: StrictInt
    w: Annotated[StrictInt, Field(ge=1)]
    h: Annotated[StrictInt, Field(ge=1)]

    def __init__(self, *args: Any, **data: Any) -> None:
        names = ("x", "y", "w", "h")
        if len(args) > len(names):
            raise TypeError(f"ModuleRect takes at most 4 positional arguments ({len(args)} given)")
        for name, value in zip(names, args, strict=False):
            if name in data:
                raise TypeError(f"ModuleRect got multiple values for argument {name!r}")
            data[name] = value
        super().__init__(**data)

    def area_cells(self) -> int:
        """Area in module² cells."""
        return self.w * self.h

    def x2(self) -> int:
        """Right edge x coordinate, in modules."""
        return self.x + self.w

    def y2(self) -> int:
        """Top edge y coordinate, in modules."""
        return self.y + self.h

    def intersection_cells(self, other: ModuleRect) -> int:
        """Exact overlap area with ``other``, in module² cells (0 when touching or disjoint)."""
        dx = min(self.x2(), other.x2()) - max(self.x, other.x)
        dy = min(self.y2(), other.y2()) - max(self.y, other.y)
        if dx <= 0 or dy <= 0:
            return 0
        return dx * dy


def _signed_area2(pts: tuple[ModulePoint, ...]) -> int:
    """Twice the signed shoelace area (positive for counter-clockwise), in module²."""
    n = len(pts)
    total = 0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) if i + 1 < n else 0]
        total += x0 * y1 - x1 * y0
    return total


class ModulePolygon(BaseModel):
    """Rectilinear polygon in modules.

    Every edge is axis-parallel; vertices are counter-clockwise; the polygon is simple;
    ≥ 4 vertices; no two consecutive edges are collinear. Stored open (first vertex not
    repeated).
    """

    model_config = _CONFIG

    exterior: tuple[ModulePoint, ...]

    @model_validator(mode="after")
    def _valid(self) -> ModulePolygon:
        pts = self.exterior
        n = len(pts)
        if n < 4:
            raise ValueError("a module polygon needs at least 4 vertices")
        dirs: list[str] = []
        for i, (a, b) in enumerate(self.edges()):
            dx, dy = b[0] - a[0], b[1] - a[1]
            if dx != 0 and dy != 0:
                raise ValueError(f"edge {i} {a}->{b} is not axis-parallel (not rectilinear)")
            if dx == 0 and dy == 0:
                raise ValueError(f"edge {i} has zero length (duplicate vertex {a})")
            dirs.append("H" if dy == 0 else "V")
        for i in range(n):
            if dirs[i] == dirs[i - 1]:
                raise ValueError(f"collinear consecutive edges at vertex {i} {pts[i]}")
        if _signed_area2(pts) <= 0:
            raise ValueError("vertices must be counter-clockwise")
        import shapely

        if not shapely.Polygon(pts).is_valid:
            raise ValueError("module polygon is not simple")
        return self

    def area_cells(self) -> int:
        """Area in module² cells (exact shoelace)."""
        return _signed_area2(self.exterior) // 2

    def edges(self) -> tuple[tuple[ModulePoint, ModulePoint], ...]:
        """Edges in modules; edge ``i`` is ``(v[i], v[(i + 1) mod n])``."""
        pts = self.exterior
        n = len(pts)
        return tuple((pts[i], pts[i + 1 if i + 1 < n else 0]) for i in range(n))


def to_shapely(g: LineString | Polygon | ModulePolygon | ModuleRect) -> shapely.Geometry:
    """Convert a contract geometry to a shapely geometry (same units as the input)."""
    import shapely

    if isinstance(g, LineString):
        return shapely.LineString(g.coords)
    if isinstance(g, Polygon):
        return shapely.Polygon(g.exterior, g.holes)
    if isinstance(g, ModulePolygon):
        return shapely.Polygon(g.exterior)
    if isinstance(g, ModuleRect):
        return shapely.box(g.x, g.y, g.x2(), g.y2())
    raise TypeError(f"unsupported geometry type: {type(g).__name__}")


def _open_ring(coords: Any) -> tuple[Point2, ...]:
    pts = [(float(c[0]), float(c[1])) for c in coords]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    return tuple(pts)


def polygon_from_shapely(p: shapely.Polygon) -> Polygon:
    """Convert a shapely polygon to a ``Polygon`` (drops closing points, keeps orientation)."""
    return Polygon(
        exterior=_open_ring(p.exterior.coords),
        holes=tuple(_open_ring(r.coords) for r in p.interiors),
    )
