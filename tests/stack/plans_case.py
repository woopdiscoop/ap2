"""The M.2 synthetic case: the room types of the M.1 case in a 4-floor block with a central core.

Four identical groups (NA..ND: ten offices, a meeting room, an open office, a store and an
archive, 330 m2 each) plus the wet rooms (four sanitary rooms, one cleaning room) fill four
30.0 x 21.6 m floor plates, one 4.8 x 4.8 m core at the centre of each. The exact-plan engine
tiles the whole footprint, so the floor plates must match the programme: the 64.8 x 19.2 m bar
of the M.1 case (loaded at 45 %), or any plate with a long, shallow gap between the stack and
the outline, is beyond what the corridor grammar realises around a solid (see the report).
No pins, no real files.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import stack_case as case
import yaml

from ale.contracts.models import Program
from ale.contracts.serialization import dump_yaml
from ale.parti.evaluate import neutral_rulebook

W = 30.0
H = 21.6
RULES: dict[str, Any] = {}


def _rect(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def building_dict() -> dict[str, Any]:
    data = copy.deepcopy(case.building_dict())
    data["entrances"][0]["point"] = [W / 2, 0.0]
    data["core"] = {"id": "C1", "rect": [12.6, 8.4, 4.8, 4.8], "kind": "core"}
    data["floors"] = [{"level": k, "footprint": _rect(0.0, 0.0, W, H)} for k in range(4)]
    return data


def _group(p: str) -> list[dict[str, Any]]:
    r = case.room
    return [
        r(f"{p}01", "Bureau", "office", 12, qty=10, facade=True),
        r(f"{p}02", "Reunion", "meeting_room", 30, facade=True),
        r(f"{p}03", "Plateau", "open_office", 100, facade=True),
        r(f"{p}04", "Stock", "storage", 40, "SERVICES"),
        r(f"{p}05", "Archives", "archive", 40, "SERVICES"),
    ]


def rooms_list() -> list[dict[str, Any]]:
    rows = [row for p in ("NA", "NB", "NC", "ND") for row in _group(p)]
    rows += [
        case.room("WC01", "Sanitaires", "sanitary", 16, "SERVICES", qty=4),
        case.room("NET01", "Menage", "cleaning_room", 6, "SERVICES"),
    ]
    return rows


def program() -> Program:
    return case.program(rooms_list())


def write_inputs(d: Path) -> tuple[Path, Path, Path, Path]:
    """``(programme.xlsx, building.yaml, rules.yaml, rulebook.yaml)`` of the case."""
    d.mkdir(parents=True, exist_ok=True)
    prog = case.program_to_xlsx(program(), d / "programme.xlsx")
    bld = case.write_building(d / "building.yaml", building_dict())
    rules = d / "rules.yaml"
    rules.write_text(yaml.safe_dump(RULES), encoding="utf-8")
    rb = d / "rulebook.yaml"
    rb.write_text(dump_yaml(neutral_rulebook(program())), encoding="utf-8")
    return prog, bld, rules, rb
