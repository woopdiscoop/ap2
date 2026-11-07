"""Shared fixtures for the ``ale.contracts`` tests: fully populated sample instances."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from ale.contracts.enums import (
    Bearing,
    Fidelity,
    Frame,
    LabelSource,
    MacroZone,
    OpeningKind,
    ScaleMethod,
    SourceKind,
)
from ale.contracts.geometry import LineString, ModulePolygon, ModuleRect, Polygon
from ale.contracts.models import (
    Adjacency,
    AdjEntry,
    CoreOffset,
    GridSpec,
    LabelledPolygon,
    Layout,
    LayoutMetrics,
    Opening,
    PlacedRoom,
    PlanGeometry,
    PolishExpression,
    Program,
    Quantiles,
    RoomSpec,
    Rulebook,
    SiteSpec,
    TextItem,
    TypeStats,
    Violation,
    Wall,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
CONTRACTS_DIR = SRC_DIR / "ale" / "contracts"
TICKET_DIR = REPO_ROOT / "specs" / "tickets" / "0.2_contracts"


def make_room_specs() -> tuple[RoomSpec, RoomSpec, RoomSpec]:
    r1 = RoomSpec(
        id="R1",
        name="  Bureau directeur  ",
        type="office",
        target_area_m2=12.5,
        quantity=2,
        macro_zone=MacroZone.ADMINISTRATIVE,
        needs_facade=True,
        orientation_override={Bearing.S: 0.5, Bearing.N: -0.25},
        min_width_m=2.4,
        adjacent_to=("R2",),
        avoid=("R3",),
        floor=0,
    )
    r2 = RoomSpec(
        id="R2",
        name="Salle de réunion",
        type="meeting_room",
        target_area_m2=20,
        macro_zone=MacroZone.ADMINISTRATIVE,
        adjacent_to=("R1",),
    )
    r3 = RoomSpec(
        id="R3",
        name="Sanitaires",
        type="sanitary",
        target_area_m2=6.0,
        macro_zone=MacroZone.SERVICES,
    )
    return r1, r2, r3


def make_program() -> Program:
    return Program(rooms=make_room_specs())


def make_site() -> SiteSpec:
    return SiteSpec(
        footprint=Polygon(
            exterior=((0, 0), (30, 0), (30, 12), (18, 12), (18, 20), (0, 20)),
            holes=(((2.0, 2.0), (2.0, 4.0), (4.0, 4.0), (4.0, 2.0)),),
        ),
        north_angle_deg=15.5,
        access_edge=0,
        core_hint=(10.0, 5.0),
    )


def make_layout() -> Layout:
    return Layout(
        grid=GridSpec(module_mm=100),
        footprint=ModulePolygon(
            exterior=((0, 0), (100, 0), (100, 40), (60, 40), (60, 80), (0, 80))
        ),
        rooms=(
            PlacedRoom(
                instance_id="R1#1",
                spec_id="R1",
                rect=ModuleRect(x=0, y=0, w=30, h=40),
                target_area_m2=12.5,
            ),
            PlacedRoom(
                instance_id="R1#2",
                spec_id="R1",
                rect=ModuleRect(x=30, y=0, w=30, h=40),
                target_area_m2=12.5,
            ),
        ),
        circulation=(
            PlacedRoom(
                instance_id="circ-001",
                spec_id=None,
                rect=ModuleRect(x=60, y=0, w=12, h=40),
                target_area_m2=None,
            ),
        ),
        residue=(ModuleRect(x=72, y=0, w=1, h=40),),
        seed=42,
        rulebook_version="seed-1.0.0",
        metrics=LayoutMetrics(
            total_cost=12.75,
            cost_breakdown={"area": 1.5, "adjacency": 0.25},
            total_overshoot_m2=0.4,
            circulation_area_m2=4.8,
            residue_area_m2=0.4,
            violations=(
                Violation(code="NO_FACADE", instance_ids=("R1#1",), detail="no facade contact"),
            ),
        ),
    )


def make_plan(frame: Frame = Frame.Y_DOWN) -> PlanGeometry:
    return PlanGeometry(
        source_sha256="ab" * 32,
        page=0,
        plan_index=1,
        source_kind=SourceKind.PDF_VECTOR,
        frame=frame,
        units_label="pt",
        scale_m_per_unit=0.01,
        scale_method=ScaleMethod.SCALE_BAR,
        scale_confidence=0.8,
        walls=(
            Wall(centerline=LineString(coords=((100, 50), (1100, 50))), thickness=20),
            Wall(centerline=LineString(coords=((100, 50), (100, 650), (900, 650)))),
        ),
        openings=(
            Opening(
                kind=OpeningKind.DOOR,
                segment=LineString(coords=((300, 50), (390, 50))),
                width_native=90,
                width_m=0.9,
                host_wall=0,
            ),
            Opening(
                kind=OpeningKind.WINDOW,
                segment=LineString(coords=((100, 200), (100, 320))),
                width_native=120,
            ),
        ),
        rooms=(
            LabelledPolygon(
                id="p1",
                polygon=Polygon(exterior=((100, 50), (600, 50), (600, 650), (100, 650))),
                type="office",
                label_source=LabelSource.CAD_TEXT,
                confidence=0.9,
                raw_label="BUREAU 12",
                area_text_m2=12.0,
            ),
            LabelledPolygon(
                id="p2",
                polygon=Polygon(exterior=((600, 50), (1100, 50), (1100, 650), (600, 650))),
            ),
        ),
        texts=(
            TextItem(
                text="BUREAU",
                insert=(300, 300),
                height=2.5,
                rotation_deg=90,
                layer="TXT",
                source="PDF",
            ),
        ),
        warnings=("scale from scale bar",),
    )


def _type_stats(p50_area: float) -> TypeStats:
    return TypeStats(
        aspect=Quantiles(p10=1.0, p50=1.4, p90=2.0, n=10),
        area_m2=Quantiles(p10=p50_area * 0.75, p50=p50_area, p90=p50_area * 1.5, n=10),
        orientation={Bearing.N: -0.2, Bearing.E: 0.0, Bearing.S: 0.5, Bearing.W: 0.1},
    )


def make_rulebook(p_office_meeting: float = 0.6) -> Rulebook:
    return Rulebook(
        version="1.0.0",
        kind="seed",
        author="Router",
        date="2026-11-07",
        n_plans=4,
        source_mix={Fidelity.CAD: 3, Fidelity.RASTER: 1},
        types={"office": _type_stats(12.0), "meeting_room": _type_stats(20.0)},
        adjacency=Adjacency(
            default_p=0.1,
            pairs=(
                AdjEntry(a="office", b="meeting_room", p=p_office_meeting, n_support=4),
                AdjEntry(a="office", b="office", p=0.5),
            ),
        ),
        core_offset=CoreOffset(dx_norm=0.1, dy_norm=-0.2, n=3),
    )


def make_polish() -> PolishExpression:
    return PolishExpression(tokens=("a", "b", "V", "c", "H"))


SAMPLE_FACTORIES = {
    "RoomSpec": lambda: make_room_specs()[0],
    "Program": make_program,
    "SiteSpec": make_site,
    "Layout": make_layout,
    "PlanGeometry": make_plan,
    "Rulebook": make_rulebook,
    "PolishExpression": make_polish,
}


@pytest.fixture
def samples() -> dict[str, BaseModel]:
    return {name: f() for name, f in SAMPLE_FACTORIES.items()}


def subprocess_env(pythonpath: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(pythonpath)
    env.pop("COVERAGE_PROCESS_START", None)
    return env


def run_module(args: list[str], pythonpath: Path = SRC_DIR) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        env=subprocess_env(pythonpath),
        cwd=pythonpath,
        timeout=60,
        check=False,
    )


def copy_package(tmp_path: Path) -> Path:
    """Copy ``src/ale`` into ``tmp_path/ale``; return ``tmp_path`` (the new PYTHONPATH)."""
    shutil.copytree(
        SRC_DIR / "ale",
        tmp_path / "ale",
        ignore=shutil.ignore_patterns("__pycache__", "CONTRACTS.lock"),
    )
    return tmp_path


@pytest.fixture
def h() -> SimpleNamespace:
    """Helpers and factories (exposed as a fixture so tests never import conftest)."""
    return SimpleNamespace(
        REPO_ROOT=REPO_ROOT,
        SRC_DIR=SRC_DIR,
        CONTRACTS_DIR=CONTRACTS_DIR,
        TICKET_DIR=TICKET_DIR,
        make_room_specs=make_room_specs,
        make_program=make_program,
        make_site=make_site,
        make_layout=make_layout,
        make_plan=make_plan,
        make_rulebook=make_rulebook,
        make_polish=make_polish,
        run_module=run_module,
        copy_package=copy_package,
    )
