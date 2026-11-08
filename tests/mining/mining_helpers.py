"""Synthetic plans with declared ground-truth topology for the Ticket 2.1 tests.

Rooms are drawn on the inner faces of the walls (as the CAD polygonizer produces them);
wall centrelines carry the thickness. Ground truth: a contact's shared length is the length
along which the two rooms face each other; a façade length is the length of the room's
boundary facing the outside.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence

from ale.contracts.enums import Frame, OpeningKind, ScaleMethod, SourceKind
from ale.contracts.geometry import LineString, Polygon
from ale.contracts.models import LabelledPolygon, Opening, PlanGeometry, Wall

SHA = hashlib.sha256(b"ale mining test").hexdigest()

#: Grid of the T1/T3/T4 plans: inner column widths and row heights (m), wall thickness.
COL_W = (4.0, 5.0, 3.5)
ROW_H = (4.0, 6.0)
WALL_T = 0.2

Pt = tuple[float, float]


def _axes(sizes: Sequence[float], t: float) -> list[float]:
    out = [0.0]
    for s in sizes:
        out.append(out[-1] + t + s)
    return out


def rid(i: int, j: int) -> str:
    return f"r{i}{j}"


def grid_truth() -> tuple[dict[tuple[str, str], float], set[tuple[str, str]], dict[str, float]]:
    """(shared length per pair, DOOR pairs, façade length per room) of the grid plan."""
    shared: dict[tuple[str, str], float] = {}
    for j, h in enumerate(ROW_H):
        for i in range(len(COL_W) - 1):
            shared[(rid(i, j), rid(i + 1, j))] = h
    for i, w in enumerate(COL_W):
        for j in range(len(ROW_H) - 1):
            shared[(rid(i, j), rid(i, j + 1))] = w
    doors = {("r00", "r10"), ("r10", "r11"), ("r11", "r21")}
    facade: dict[str, float] = {}
    ni, nj = len(COL_W), len(ROW_H)
    for i, w in enumerate(COL_W):
        for j, h in enumerate(ROW_H):
            f = 0.0
            f += h if i in (0, ni - 1) else 0.0
            f += w if j in (0, nj - 1) else 0.0
            facade[rid(i, j)] = f
    return shared, doors, facade


def _plan(
    rooms: Sequence[LabelledPolygon],
    walls: Sequence[Wall] = (),
    openings: Sequence[Opening] = (),
    *,
    scale: float | None = 1.0,
    kind: SourceKind = SourceKind.DXF,
    frame: Frame = Frame.Y_UP,
) -> PlanGeometry:
    return PlanGeometry(
        source_sha256=SHA,
        page=0,
        plan_index=0,
        source_kind=kind,
        frame=frame,
        scale_m_per_unit=scale,
        scale_method=ScaleMethod.UNKNOWN if scale is None else ScaleMethod.DRAWING_UNITS,
        walls=tuple(walls),
        openings=tuple(openings),
        rooms=tuple(rooms),
    )


def rect(x0: float, y0: float, x1: float, y1: float) -> tuple[Pt, ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


def room(id_: str, ring: Sequence[Pt], type_: str | None = None) -> LabelledPolygon:
    from ale.contracts.enums import LabelSource

    return LabelledPolygon(
        id=id_,
        polygon=Polygon(exterior=tuple(ring)),
        type=type_,
        label_source=None if type_ is None else LabelSource.MANUAL,
    )


def wall(p: Pt, q: Pt, t: float | None = WALL_T) -> Wall:
    return Wall(centerline=LineString(coords=(p, q)), thickness=t)


def door(p: Pt, q: Pt, kind: OpeningKind = OpeningKind.DOOR) -> Opening:
    width = ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5
    return Opening(kind=kind, segment=LineString(coords=(p, q)), width_native=width)


def _jitter(ring: tuple[Pt, ...], rng: random.Random | None, amp: float) -> tuple[Pt, ...]:
    if rng is None:
        return ring
    return tuple((x + rng.uniform(-amp, amp), y + rng.uniform(-amp, amp)) for x, y in ring)


def grid_plan(
    *,
    jitter_m: float = 0.0,
    seed: int = 0,
    scale: float = 1.0,
    frame: Frame = Frame.Y_UP,
    kind: SourceKind = SourceKind.DXF,
    windows: bool = False,
) -> PlanGeometry:
    """3 x 2 grid of rooms (walls ``WALL_T``) with 3 doors; native unit = ``1/scale`` m."""
    t = WALL_T
    xs, ys = _axes(COL_W, t), _axes(ROW_H, t)
    rng = random.Random(seed) if jitter_m > 0.0 else None
    sign = -1.0 if frame is Frame.Y_DOWN else 1.0

    def nat(p: Pt) -> Pt:
        return (p[0] / scale, sign * p[1] / scale)

    rooms = []
    types = ("office", "meeting_room", None)
    for i in range(len(COL_W)):
        for j in range(len(ROW_H)):
            ring = rect(xs[i] + t / 2, ys[j] + t / 2, xs[i + 1] - t / 2, ys[j + 1] - t / 2)
            ring = _jitter(ring, rng, jitter_m)
            if frame is Frame.Y_DOWN:
                ring = tuple(reversed(ring))
            rooms.append(room(rid(i, j), [nat(p) for p in ring], types[(i + j) % 3]))
    walls = [wall(nat((x, ys[0])), nat((x, ys[-1])), t / scale) for x in xs]
    walls += [wall(nat((xs[0], y)), nat((xs[-1], y)), t / scale) for y in ys]
    # Doors (0.9 m) on the wall centrelines: r00|r10, r10/r11, r11|r21.
    ops = [
        door(nat((xs[1], 1.0)), nat((xs[1], 1.9))),
        door(nat((xs[1] + 1.0, ys[1])), nat((xs[1] + 1.9, ys[1]))),
        door(nat((xs[2], ys[1] + 2.0)), nat((xs[2], ys[1] + 2.9))),
    ]
    if windows:  # a window between r01 and r11 must not make a DOOR contact
        ops.append(door(nat((xs[1], ys[1] + 3.0)), nat((xs[1], ys[1] + 4.0)), OpeningKind.WINDOW))
    return _plan(rooms, walls, ops, scale=scale, kind=kind, frame=frame)


def thin_touch_plan(overlap_m: float = 0.4) -> PlanGeometry:
    """Two 4 x 4 rooms across a 0.2 m wall, facing each other on ``overlap_m`` only."""
    a = rect(0.0, 0.0, 4.0, 4.0)
    b = rect(4.2, 4.0 - overlap_m, 8.2, 8.0 - overlap_m)
    walls = [
        wall((4.1, -0.1), (4.1, 8.1)),
        wall((-0.1, -0.1), (-0.1, 4.1)),
        wall((8.3, 3.5), (8.3, 7.7)),
    ]
    return _plan([room("A", a), room("B", b)], walls)


def bare_plan(
    rooms: Sequence[LabelledPolygon],
    walls: Sequence[Wall] = (),
    openings: Sequence[Opening] = (),
    *,
    scale: float | None = 1.0,
    kind: SourceKind = SourceKind.DXF,
) -> PlanGeometry:
    return _plan(rooms, walls, openings, scale=scale, kind=kind)
