"""Helpers of the Ticket 3.5 tests (written independently of ``ale.export``)."""

from __future__ import annotations

from pathlib import Path

from program_helpers import RULEBOOK_TEST, program_to_xlsx, site_to_yaml

from ale.config import AleConfig
from ale.contracts.geometry import ModulePolygon, ModuleRect
from ale.contracts.models import (
    GridSpec,
    Layout,
    LayoutMetrics,
    PlacedRoom,
    Program,
    SiteSpec,
    Violation,
)
from ale.program import prepare_input
from ale.program.models import PreparedInput

#: Hand tiling of the 100 x 100 module footprint (module 0.10 m):
#: bottom band y 0..40, corridor y 40..52, top band y 52..100, residue at the top right.
ROOMS: dict[str, tuple[str, float, tuple[int, int, int, int]]] = {
    "R01": ("R01", 12.0, (0, 0, 30, 40)),
    "R02": ("R02", 9.0, (30, 0, 23, 40)),
    "R03#1": ("R03", 12.0, (53, 0, 30, 40)),
    "R03#2": ("R03", 12.0, (83, 0, 17, 40)),
    "R04": ("R04", 16.0, (0, 52, 34, 48)),
    "R05": ("R05", 6.0, (34, 52, 13, 48)),
    "R06": ("R06", 4.0, (47, 52, 9, 48)),
    "R07": ("R07", 4.0, (56, 52, 16, 48)),
}
CIRC: dict[str, tuple[int, int, int, int]] = {
    "C01": (0, 40, 60, 12),
    "C02": (60, 40, 40, 12),
}
RESIDUE = (72, 52, 28, 48)

VIOLATIONS = (
    Violation(code="AREA_UNDER", instance_ids=("R03#2",), detail="6,80 m² < 11,64 m²"),
    Violation(code="ASPECT", instance_ids=("R06",), detail="aspect 5.33 > 2.0"),
    Violation(code="ASPECT", instance_ids=("R07",), detail="aspect 3.00 > 2.0"),
)
COST = {"area_overshoot": 2.5, "aspect": 3.25, "zz_unknown_term": 1.0}


def prepare(tmp: Path, program: Program, site: SiteSpec) -> PreparedInput:
    xlsx = program_to_xlsx(program, tmp / "programme.xlsx")
    yml = site_to_yaml(site, tmp / "site.yaml")
    return prepare_input(xlsx, yml, RULEBOOK_TEST, AleConfig())


def make_layout(
    *,
    violations: tuple[Violation, ...] = VIOLATIONS,
    module_mm: int = 100,
    footprint: tuple[tuple[int, int], ...] = ((0, 0), (100, 0), (100, 100), (0, 100)),
) -> Layout:
    rooms = tuple(
        PlacedRoom(instance_id=iid, spec_id=sid, rect=ModuleRect(*r), target_area_m2=t)
        for iid, (sid, t, r) in sorted(ROOMS.items())
    )
    circ = tuple(
        PlacedRoom(instance_id=iid, spec_id=None, rect=ModuleRect(*r), target_area_m2=None)
        for iid, r in sorted(CIRC.items())
    )
    return Layout(
        grid=GridSpec(module_mm=module_mm),
        footprint=ModulePolygon(exterior=footprint),
        rooms=rooms,
        circulation=circ,
        residue=(ModuleRect(*RESIDUE),),
        seed=7,
        rulebook_version="test-3.1",
        metrics=LayoutMetrics(
            total_cost=9.75,
            cost_breakdown=COST,
            total_overshoot_m2=1.52,
            circulation_area_m2=12.0,
            residue_area_m2=13.44,
            violations=violations,
        ),
    )


def fr2(x: float) -> str:
    """Independent re-implementation: 2 decimals, comma separator."""
    s = f"{x:.2f}"
    if s == "-0.00":
        s = "0.00"
    return s.replace(".", ",")


def fr2s(x: float) -> str:
    s = fr2(x)
    return s if s.startswith("-") else "+" + s
