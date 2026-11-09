"""Synthetic ``PlanTopology`` / ``PlanGeometry`` inputs of the Ticket 2.2 tests (metres)."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Sequence

from ale.contracts.config import AleConfig
from ale.contracts.enums import (
    ContactKind,
    Frame,
    LabelSource,
    ScaleMethod,
    SourceKind,
    fidelity_of,
)
from ale.contracts.geometry import Polygon
from ale.contracts.models import (
    Adjacency,
    AdjEntry,
    CoreOffset,
    LabelledPolygon,
    PlanGeometry,
    Quantiles,
    Rulebook,
    TypeStats,
)
from ale.mining import Contact, PlanTopology

TODAY = dt.date(2026, 11, 8)
Rect = tuple[float, float, float, float]
RoomDef = tuple[str, str | None, Rect]


def sha(i: int) -> str:
    return hashlib.sha256(f"ale rulebook test plan {i}".encode()).hexdigest()


def rect_ring(r: Rect) -> tuple[tuple[float, float], ...]:
    x0, y0, x1, y1 = r
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


def geometry(i: int, rooms: Sequence[RoomDef], kind: SourceKind = SourceKind.DXF) -> PlanGeometry:
    return PlanGeometry(
        source_sha256=sha(i),
        page=0,
        plan_index=0,
        source_kind=kind,
        frame=Frame.Y_UP,
        units_label="m",
        scale_m_per_unit=1.0,
        scale_method=ScaleMethod.DRAWING_UNITS,
        rooms=tuple(
            LabelledPolygon(
                id=rid,
                polygon=Polygon(exterior=rect_ring(r)),
                type=t,
                label_source=None if t is None else LabelSource.MANUAL,
            )
            for rid, t, r in rooms
        ),
    )


def plan(
    i: int,
    rooms: Sequence[RoomDef],
    contacts: Sequence[tuple[str, str]] = (),
    kind: SourceKind = SourceKind.DXF,
    door: bool = False,
) -> tuple[PlanTopology, PlanGeometry]:
    """A plan whose topology is declared (contacts given, no façades)."""
    geom = geometry(i, rooms, kind)
    topo = PlanTopology(
        source_sha256=sha(i),
        page=0,
        plan_index=0,
        fidelity=fidelity_of(kind),
        rooms=tuple(
            (rid, t, (r[2] - r[0]) * (r[3] - r[1]))
            for rid, t, r in sorted(rooms, key=lambda x: x[0])
        ),
        contacts=tuple(
            Contact(
                a=min(a, b),
                b=max(a, b),
                kind=ContactKind.DOOR if door else ContactKind.WALL,
                shared_m=3.0,
                openings=1 if door else 0,
            )
            for a, b in contacts
        ),
        exterior=(),
    )
    return topo, geom


def office_meeting(
    i: int, contact: bool, kind: SourceKind = SourceKind.DXF
) -> tuple[PlanTopology, PlanGeometry]:
    rooms: list[RoomDef] = [
        ("r1", "office", (0.0, 0.0, 4.0, 3.0)),
        ("r2", "meeting_room", (4.2, 0.0, 9.2, 4.0)),
        ("r3", None, (0.0, 3.2, 4.0, 5.0)),
    ]
    return plan(i, rooms, [("r1", "r2")] if contact else [], kind)


def split(
    pairs: Sequence[tuple[PlanTopology, PlanGeometry]],
) -> tuple[list[PlanTopology], list[PlanGeometry]]:
    return [p[0] for p in pairs], [p[1] for p in pairs]


def config(**rulebook: float) -> AleConfig:
    return AleConfig.model_validate({"rulebook": rulebook})


def uniform_stats(orientation: dict[str, float] | None = None) -> TypeStats:
    return TypeStats(
        aspect=Quantiles(p10=1.0, p50=1.4, p90=2.0),
        area_m2=Quantiles(p10=2.0, p50=12.0, p90=80.0),
        orientation=orientation or {"N": 0.0, "E": 0.0, "S": 0.0, "W": 0.0},
    )


def seed_rulebook(
    pairs: Sequence[tuple[str, str, float]] = (),
    types: dict[str, TypeStats] | None = None,
    core: tuple[float, float] = (0.0, 0.0),
) -> Rulebook:
    return Rulebook(
        version="seed-test",
        kind="seed",
        author="test",
        date="2026-11-07",
        types=types if types is not None else {"office": uniform_stats()},
        adjacency=Adjacency(
            default_p=0.5, pairs=tuple(AdjEntry(a=a, b=b, p=p, n_support=0) for a, b, p in pairs)
        ),
        core_offset=CoreOffset(dx_norm=core[0], dy_norm=core[1]),
    )
