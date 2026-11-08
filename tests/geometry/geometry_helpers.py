"""Test utilities of Ticket 3.3: prepared inputs built in memory, plan shorthands."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fixtures import ProgramName, SiteName, load_program, load_site

from ale.config import AleConfig
from ale.contracts.corridor_plan import BlockPlan, CorridorPlan, FingerBay, PiecePlan, RoomBay
from ale.contracts.enums import MacroZone
from ale.contracts.geometry import Polygon
from ale.contracts.models import GridSpec, Program, RoomSpec, Rulebook, SiteSpec
from ale.contracts.serialization import load_yaml
from ale.program import PreparedInput, check_feasibility, to_module_footprint

RULEBOOK_TEST = Path(__file__).resolve().parent.parent / "program" / "data" / "rulebook_test.yaml"

AnyBay = RoomBay | FingerBay


def load_test_rulebook() -> Rulebook:
    return load_yaml(Rulebook, RULEBOOK_TEST.read_text(encoding="utf-8"))


def room(
    rid: str,
    area: float,
    *,
    rtype: str = "office",
    zone: MacroZone = MacroZone.ADMINISTRATIVE,
    **kw: Any,
) -> RoomSpec:
    """A program room (quantity 1 unless given)."""
    return RoomSpec(id=rid, name=rid, type=rtype, target_area_m2=area, macro_zone=zone, **kw)


def site_modules(
    points: Sequence[tuple[int, int]],
    *,
    north: float = 0.0,
    core_hint: tuple[float, float] | None = None,
    module_m: float = 0.1,
) -> SiteSpec:
    """A site whose footprint is ``points`` given in modules (CCW)."""
    ext = tuple((round(x * module_m, 6), round(y * module_m, 6)) for x, y in points)
    return SiteSpec(
        footprint=Polygon(exterior=ext), north_angle_deg=north, access_edge=0, core_hint=core_hint
    )


def rect_pts(w: int, h: int) -> list[tuple[int, int]]:
    return [(0, 0), (w, 0), (w, h), (0, h)]


def prepared_from(
    program: Program,
    site: SiteSpec,
    rulebook: Rulebook | None = None,
    config: AleConfig | None = None,
) -> PreparedInput:
    """A ``PreparedInput`` built in memory (no workbook)."""
    config = config or AleConfig()
    rulebook = rulebook or load_test_rulebook()
    grid = GridSpec(module_mm=config.grid.module_mm)
    footprint = to_module_footprint(site, grid)
    return PreparedInput(
        program=program,
        instances=program.instances(),
        site=site,
        footprint=footprint,
        grid=grid,
        rulebook_version=rulebook.version,
        feasibility=check_feasibility(program, footprint, rulebook, config),
        warnings=(),
    )


def prepared_poly(
    points: Sequence[tuple[int, int]],
    rooms: Sequence[RoomSpec],
    rulebook: Rulebook | None = None,
    **site_kw: Any,
) -> PreparedInput:
    return prepared_from(Program(rooms=tuple(rooms)), site_modules(points, **site_kw), rulebook)


def prepared_rect(
    w: int, h: int, rooms: Sequence[RoomSpec], rulebook: Rulebook | None = None, **site_kw: Any
) -> PreparedInput:
    return prepared_poly(rect_pts(w, h), rooms, rulebook, **site_kw)


def fixture_prepared(program: ProgramName, site: SiteName) -> PreparedInput:
    return prepared_from(load_program(program), load_site(site))


def piece(a: Sequence[AnyBay] = (), b: Sequence[AnyBay] = ()) -> PiecePlan:
    return PiecePlan(block_a=BlockPlan(bays=tuple(a)), block_b=BlockPlan(bays=tuple(b)))


def one_piece(a: Sequence[AnyBay] = (), b: Sequence[AnyBay] = ()) -> CorridorPlan:
    return CorridorPlan(pieces=(piece(a, b),))


def rb(rid: str) -> RoomBay:
    return RoomBay(room=rid)


def fb(left: Sequence[str] = (), right: Sequence[str] = (), junction: bool = False) -> FingerBay:
    return FingerBay(left=tuple(left), right=tuple(right), junction=junction)


def rect_tuple(p: Any) -> tuple[int, int, int, int]:
    r = p.rect
    return (r.x, r.y, r.w, r.h)
