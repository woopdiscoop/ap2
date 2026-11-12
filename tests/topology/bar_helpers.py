"""Bar plates with an interior solid (Ticket M.2b): synthetic cases and a success counter."""

from __future__ import annotations

from typing import Any

from ale.config import AleConfig
from ale.contracts.geometry import Polygon
from ale.contracts.models import CoreSpec, Program, RoomSpec, SiteSpec
from ale.geometry.checks import check_layout
from ale.geometry.evaluate import hard_codes_of
from ale.program.models import PreparedInput
from ale.topology import seed_plan
from ale.topology.seed import HARD_CODES

BARS = {
    "central_54": (54.0, 15.6, (21.6, 4.2, 10.8, 7.2)),
    "central_65": (64.8, 19.2, (24.0, 6.0, 16.8, 7.2)),
    "third_65": (64.8, 19.2, (13.2, 6.0, 16.8, 7.2)),
    "side_65": (64.8, 19.2, (24.0, 3.6, 16.8, 7.2)),
}


def _room(
    rid: str, typ: str, area: float, qty: int = 1, zone: str = "ADMINISTRATIVE", f: bool = False
) -> RoomSpec:
    return RoomSpec(
        id=rid,
        name=rid,
        type=typ,
        target_area_m2=area,
        quantity=qty,
        macro_zone=zone,
        needs_facade=f,
    )


def _program(groups: int, wc: int, extra: int) -> Program:
    rooms: list[RoomSpec] = []
    for k in range(groups):
        p = f"G{k}"
        rooms += [
            _room(p + "a", "office", 12, 10, f=True),
            _room(p + "b", "meeting_room", 30, f=True),
            _room(p + "c", "open_office", 100, f=True),
            _room(p + "d", "storage", 40, zone="SERVICES"),
            _room(p + "e", "archive", 40, zone="SERVICES"),
        ]
    if wc:
        rooms.append(_room("WC", "sanitary", 16, wc, "SERVICES"))
    if extra:
        rooms.append(_room("EX", "office", 12, extra, f=True))
    return Program(rooms=tuple(rooms))


def bar_case(name: str, max_fill: float, rulebook: Any) -> tuple[float, PreparedInput]:
    """Programme of bar ``name`` with the largest ``fill_ratio`` not above ``max_fill``."""
    from geometry_helpers import prepared_from

    w, h, solid = BARS[name]
    site = SiteSpec(
        footprint=Polygon(exterior=((0.0, 0.0), (w, 0.0), (w, h), (0.0, h))),
        north_angle_deg=0.0,
        access_edge=0,
        cores=(CoreSpec(id="C", rect=solid, kind="core"),),
    )
    best: tuple[float, PreparedInput] | None = None
    for groups in range(1, 12):
        for wc in (0, 2, 4, 6):
            for extra in (0, 4, 8, 12, 16):
                pi = prepared_from(_program(groups, wc, extra), site, rulebook)
                fr = pi.feasibility.fill_ratio
                if fr <= max_fill and (best is None or fr > best[0]):
                    best = (fr, pi)
    assert best is not None
    return best


def seeds_ok(prepared: PreparedInput, rulebook: Any, seeds: range, attempts: int = 12) -> int:
    """Number of seeds giving a seeded plan with no hard violation other than ``NO_FACADE``
    and no ``check_layout`` problem."""
    cfg = AleConfig()
    ok = 0
    for s in seeds:
        res = seed_plan(prepared, rulebook, cfg, seed=s, time_budget_s=30.0, max_attempts=attempts)
        lay = res.realization.layout
        if lay is None:
            continue
        codes = hard_codes_of(lay.metrics, HARD_CODES) - {"NO_FACADE"}
        if not any(v.code in codes for v in lay.metrics.violations) and not check_layout(
            lay, prepared, cfg
        ):
            ok += 1
    return ok
