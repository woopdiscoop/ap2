"""The M.1 synthetic case: a 64.8 x 19.2 m bar, R+3, the top floor receding on one side (a
terrace), one core, a programme sized like the AREP-MS Region (about 2,200 m2). No real files."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import yaml

_TESTS = Path(__file__).resolve().parent.parent
if str(_TESTS / "program") not in sys.path:
    sys.path.insert(0, str(_TESTS / "program"))

from program_helpers import program_to_xlsx  # noqa: E402

from ale.contracts.models import Program  # noqa: E402
from ale.contracts.serialization import load_yaml  # noqa: E402


def room(
    rid: str,
    name: str,
    typ: str,
    area: float,
    zone: str = "ADMINISTRATIVE",
    qty: int = 1,
    facade: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": rid,
        "name": name,
        "type": typ,
        "target_area_m2": area,
        "quantity": qty,
        "macro_zone": zone,
        "needs_facade": facade,
        **extra,
    }


ROOMS: list[dict[str, Any]] = [
    room("ACC01", "Hall", "entrance_hall", 80, "PUBLIC", facade=True, anchor="entrance"),
    room("ACC02", "Accueil", "reception", 30, "PUBLIC", anchor="entrance"),
    room("ACC03", "Attente", "waiting_area", 40, "PUBLIC", facade=True),
    room("SAL01", "Salle polyvalente", "multipurpose_room", 150, "PUBLIC", facade=True),
    room("SAL02", "Formation", "training_room", 40, "PUBLIC", qty=3, facade=True),
    room("PRES01", "President", "office", 30, facade=True),
    room("PRES02", "Salle du conseil", "meeting_room", 40, facade=True),
    room("PRES03", "Assistants", "office", 15, qty=2, facade=True),
    room("DAP01", "Bureau DAP", "office", 12, qty=8, facade=True),
    room("DAP02", "Plateau DAP", "open_office", 100, facade=True),
    room("DAP03", "Reunion DAP", "meeting_room", 24, qty=2, facade=True),
    room("DGS01", "Bureau DGS", "office", 12, qty=10, facade=True),
    room("DGS02", "Plateau DGS", "open_office", 80, facade=True),
    room("DGS03", "Reunion DGS", "meeting_room", 24, qty=2, facade=True),
    room("DRH01", "Bureau DRH", "office", 12, qty=8, facade=True),
    room("DRH02", "Reunion DRH", "meeting_room", 24),
    room("DRH03", "Archives DRH", "archive", 30, "SERVICES"),
    room("DFI01", "Bureau DFI", "office", 12, qty=10, facade=True),
    room("DFI02", "Plateau DFI", "open_office", 96, facade=True),
    room("DFI03", "Stock DFI", "storage", 20, "SERVICES"),
    room("DSI01", "Bureau DSI", "office", 12, qty=6, facade=True),
    room("DSI02", "Salle serveurs", "it_room", 40, "SERVICES"),
    room("LOG01", "Stock", "storage", 60, "SERVICES"),
    room("LOG02", "Archives", "archive", 80, "SERVICES"),
    room("LOG03", "Reprographie", "print_room", 20, "SERVICES"),
    room("SOC01", "Pause", "break_room", 50, "SERVICES"),
    room("SOC02", "Office", "kitchenette", 12, "SERVICES", qty=2),
    room("WC01", "Sanitaires", "sanitary", 16, "SERVICES", qty=10),
    room("NET01", "Menage", "cleaning_room", 6, "SERVICES", qty=4),
    room("TEC01", "Local technique", "technical_room", 20, "SERVICES", qty=2),
]

RULES: dict[str, Any] = {"pins": {"PRES": "top", "DAP": "top", "DGS": "top"}}


def rooms_list() -> list[dict[str, Any]]:
    return copy.deepcopy(ROOMS)


def program(rooms: list[dict[str, Any]] | None = None) -> Program:
    return load_yaml(Program, yaml.safe_dump({"rooms": rooms or rooms_list()}))


def _rect(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def building_dict() -> dict[str, Any]:
    return {
        "schema_version": "ale.building/1",
        "north_angle_deg": 0,
        "access_edge": 0,
        "entrances": [{"point": [32.4, 0.0], "label": "Entree principale", "main": True}],
        "floor_height_m": 3.5,
        "core": {"id": "C1", "rect": [30.0, 4.2, 4.8, 6.0], "kind": "core"},
        "floors": [
            {"level": 0, "footprint": _rect(0.0, 0.0, 64.8, 19.2)},
            {"level": 1, "footprint": _rect(0.0, 0.0, 64.8, 19.2)},
            {"level": 2, "footprint": _rect(0.0, 0.0, 64.8, 19.2)},
            {"level": 3, "footprint": _rect(6.0, 0.0, 58.8, 16.8)},
        ],
    }


def write_building(path: Path, data: dict[str, Any] | None = None) -> Path:
    path.write_text(yaml.safe_dump(data or building_dict(), sort_keys=False), encoding="utf-8")
    return path


def write_rules(path: Path, data: dict[str, Any] | None = None) -> Path:
    path.write_text(yaml.safe_dump(data or RULES, sort_keys=False), encoding="utf-8")
    return path


def write_inputs(d: Path) -> tuple[Path, Path, Path]:
    """``(programme.xlsx, building.yaml, rules.yaml)`` of the synthetic case."""
    return (
        program_to_xlsx(program(), d / "programme.xlsx"),
        write_building(d / "building.yaml"),
        write_rules(d / "rules.yaml"),
    )
