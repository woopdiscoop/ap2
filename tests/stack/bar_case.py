"""The M.2b synthetic case: the M.1 bar (64.8 x 19.2 m, R+3, receding top floor) loaded on every
floor (the M.1 programme x 1.7 on offices, meeting and training rooms, open offices; no pins).
The core sits at x = 24.0 m so both wings of the top floor stay at least 18 m wide.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import stack_case as case
import yaml

from ale.contracts.models import Program
from ale.contracts.serialization import dump_yaml
from ale.parti.evaluate import neutral_rulebook

FACTOR = 1.7
RULES: dict[str, Any] = {}
SCALED = ("office", "meeting_room", "open_office", "training_room")


def building_dict() -> dict[str, Any]:
    data = case.building_dict()
    data["core"]["rect"][0] = 24.0
    data["entrances"][0]["point"][0] = 32.4
    return data


def rooms_list() -> list[dict[str, Any]]:
    rows = case.rooms_list()
    for r in rows:
        if r["macro_zone"] != "SERVICES" and r["type"] in SCALED:
            r["quantity"] = max(1, round(r["quantity"] * FACTOR))
            if r["type"] == "open_office":
                r["target_area_m2"] = r["target_area_m2"] * FACTOR
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
