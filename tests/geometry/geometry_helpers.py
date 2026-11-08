"""Test utilities of Ticket 3.3: prepared inputs built in memory, plan shorthands."""

from __future__ import annotations

import random
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fixtures import ProgramName, SiteName, load_program, load_site

from ale.config import AleConfig
from ale.contracts.corridor_plan import (
    BandPlan,
    BlockPlan,
    CorridorPlan,
    FingerBay,
    PiecePlan,
    RoomBay,
)
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


def band(a: Sequence[AnyBay] = (), b: Sequence[AnyBay] = ()) -> BandPlan:
    return BandPlan(block_a=BlockPlan(bays=tuple(a)), block_b=BlockPlan(bays=tuple(b)))


def piece(a: Sequence[AnyBay] = (), b: Sequence[AnyBay] = ()) -> PiecePlan:
    """A one-band piece (no connector)."""
    return PiecePlan(bands=(band(a, b),))


def bands_piece(bands: Sequence[BandPlan], connector: str = "start") -> PiecePlan:
    """A piece with the given bands (connector ``"none"`` forced for a single band)."""
    conn = "none" if len(bands) == 1 else connector
    return PiecePlan.model_validate({"bands": tuple(bands), "connector": conn})


def one_piece(a: Sequence[AnyBay] = (), b: Sequence[AnyBay] = ()) -> CorridorPlan:
    return CorridorPlan(pieces=(piece(a, b),))


def rb(rid: str) -> RoomBay:
    return RoomBay(room=rid)


def fb(left: Sequence[str] = (), right: Sequence[str] = (), junction: bool = False) -> FingerBay:
    return FingerBay(left=tuple(left), right=tuple(right), junction=junction)


def rect_tuple(p: Any) -> tuple[int, int, int, int]:
    r = p.rect
    return (r.x, r.y, r.w, r.h)


def random_plan(prepared: PreparedInput, rng: random.Random) -> CorridorPlan:
    """A random valid one-piece plan: 1-3 bands, random connector, random bays."""
    ids = [iid for iid, _ in prepared.instances]
    rng.shuffle(ids)
    n = rng.randint(1, 3)
    blocks: list[list[AnyBay]] = [[] for _ in range(2 * n)]
    i = 0
    while i < len(ids):  # consumes at least one id per iteration
        target = blocks[rng.randrange(2 * n)]
        if rng.random() < 0.5:
            target.append(rb(ids[i]))
            i += 1
            continue
        nl, nr = rng.randint(0, 3), rng.randint(0, 3)
        if nl + nr == 0:
            nl = 1
        left = ids[i : i + nl]
        right = ids[i + nl : i + nl + nr]
        i += nl + nr
        target.append(fb(left, right) if left or right else rb(ids[i - 1]))
    bands = [band(blocks[2 * k], blocks[2 * k + 1]) for k in range(n)]
    return CorridorPlan(pieces=(bands_piece(bands, rng.choice(["start", "end"])),))
