"""Synthetic corpora with constructed façade depths / widths (Ticket R.8 tests, metres)."""

from __future__ import annotations

from collections.abc import Sequence

from rulebook_helpers import RoomDef, plan

from ale.contracts.enums import SourceKind
from ale.contracts.models import PlanGeometry
from ale.mining import PlanTopology

Pair = tuple[PlanTopology, PlanGeometry]


def facade_plan(
    i: int,
    rtype: str,
    width: float,
    depth: float,
    kind: SourceKind = SourceKind.DXF,
    interior: str | None = None,
) -> Pair:
    """One ``rtype`` room ``width`` x ``depth`` on the south façade between two untyped
    fillers, an untyped corridor behind: its only exterior edge is the south one (length
    ``width``), so the learned depth / width are exactly ``depth`` / ``width``. ``interior``
    adds a room of that type fully enclosed (no façade), ``width`` x 4 m."""
    rooms: list[RoomDef] = [
        ("a", None, (-4.0, 0.0, 0.0, depth)),
        ("r", rtype, (0.0, 0.0, width, depth)),
        ("b", None, (width, 0.0, width + 4.0, depth)),
        ("c", None, (-4.0, depth, width + 4.0, depth + 2.0)),
    ]
    if interior is not None:
        top = depth + 2.0
        rooms += [
            ("w", None, (-4.0, top, 0.0, top + 4.0)),
            ("x", interior, (0.0, top, width, top + 4.0)),
            ("y", None, (width, top, width + 4.0, top + 4.0)),
            ("z", None, (-4.0, top + 4.0, width + 4.0, top + 6.0)),
        ]
    return plan(i, rooms, kind=kind)


def corpus(
    rtype: str, spec: Sequence[tuple[float, float]], start: int = 0, interior: str | None = None
) -> list[Pair]:
    """One plan per ``(width, depth)`` of ``spec``."""
    return [facade_plan(start + k, rtype, w, d, interior=interior) for k, (w, d) in enumerate(spec)]
