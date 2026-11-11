"""The G.3 test case: a plot with three street sides and one party wall, a ground-floor
programme of about 800 m2 (the prototype's case rebuilt), two cores and a main entrance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ale.contracts.models import Program, SiteSpec
from ale.contracts.serialization import load_yaml

ROOMS: list[dict[str, Any]] = [
    {
        "id": "H01",
        "name": "Hall",
        "type": "entrance_hall",
        "target_area_m2": 60.0,
        "macro_zone": "PUBLIC",
        "needs_facade": True,
        "anchor": "entrance",
        "adjacent_to": ["H02"],
    },
    {
        "id": "H02",
        "name": "Accueil",
        "type": "reception",
        "target_area_m2": 24.0,
        "macro_zone": "PUBLIC",
    },
    {
        "id": "P01",
        "name": "Salle polyvalente",
        "type": "multipurpose_room",
        "target_area_m2": 90.0,
        "macro_zone": "PUBLIC",
        "needs_facade": True,
    },
    {
        "id": "P02",
        "name": "Formation",
        "type": "training_room",
        "target_area_m2": 36.0,
        "quantity": 2,
        "macro_zone": "PUBLIC",
        "needs_facade": True,
    },
    {
        "id": "B01",
        "name": "Bureau",
        "type": "office",
        "target_area_m2": 12.0,
        "quantity": 12,
        "macro_zone": "ADMINISTRATIVE",
        "needs_facade": True,
    },
    {
        "id": "B02",
        "name": "Plateau",
        "type": "open_office",
        "target_area_m2": 96.0,
        "macro_zone": "ADMINISTRATIVE",
        "needs_facade": True,
    },
    {
        "id": "M01",
        "name": "Reunion",
        "type": "meeting_room",
        "target_area_m2": 24.0,
        "quantity": 3,
        "macro_zone": "ADMINISTRATIVE",
        "needs_facade": True,
    },
    {
        "id": "K01",
        "name": "Office",
        "type": "kitchenette",
        "target_area_m2": 12.0,
        "macro_zone": "ADMINISTRATIVE",
    },
    {
        "id": "S01",
        "name": "Sanitaires",
        "type": "sanitary",
        "target_area_m2": 12.0,
        "quantity": 3,
        "macro_zone": "SERVICES",
    },
    {
        "id": "T01",
        "name": "Rangement",
        "type": "storage",
        "target_area_m2": 12.0,
        "quantity": 3,
        "macro_zone": "SERVICES",
    },
    {
        "id": "T02",
        "name": "Local technique",
        "type": "technical_room",
        "target_area_m2": 18.0,
        "macro_zone": "SERVICES",
    },
    {
        "id": "T03",
        "name": "Archives",
        "type": "archive",
        "target_area_m2": 30.0,
        "macro_zone": "SERVICES",
    },
]

SITE: dict[str, Any] = {
    "footprint": {
        "exterior": [[0.0, 0.0], [54.0, 0.0], [54.0, 42.0], [0.0, 42.0]],
        "holes": [],
    },
    "north_angle_deg": 0.0,
    "access_edge": 0,
    "mode": "plot",
    "setbacks": [4.8, 0.0, 3.0, 3.0],
    "party_edges": [1],
    "entrances": [{"point": [24.0, 0.0], "label": "Entree principale", "main": True}],
    "cores": [
        {"id": "C1", "rect": [16.2, 21.0, 3.0, 3.6], "kind": "stair"},
        {"id": "C2", "rect": [36.0, 15.0, 3.0, 3.0], "kind": "lift"},
    ],
}


def program(rooms: list[dict[str, Any]] | None = None) -> Program:
    return load_yaml(Program, yaml.safe_dump({"rooms": rooms or ROOMS}))


def site(**over: Any) -> SiteSpec:
    return load_yaml(SiteSpec, yaml.safe_dump({**SITE, **over}))


def write_site_yaml(path: Path, **over: Any) -> Path:
    """The plot as an ``ale form`` input (``footprint`` is a plain list of points)."""
    data = {**SITE, **over}
    data["footprint"] = data["footprint"]["exterior"]
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path
