"""The G.2 test case: a 100 x 80 m plot (one street side on the south, one party wall on the
east) and a programme of about 2,800 m2 sized like the AREP-MS Region. Synthetic only."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import yaml

_TESTS = Path(__file__).resolve().parent.parent
for sub in ("form", "program"):
    if str(_TESTS / sub) not in sys.path:
        sys.path.insert(0, str(_TESTS / sub))

import case_helpers as g3  # noqa: E402

from ale.contracts.models import Program, SiteSpec  # noqa: E402
from ale.contracts.serialization import load_yaml  # noqa: E402

SITE: dict[str, Any] = {
    "footprint": {"exterior": [[0, 0], [100, 0], [100, 80], [0, 80]], "holes": []},
    "north_angle_deg": 0.0,
    "access_edge": 0,
    "mode": "plot",
    "setbacks": [4.8, 0.0, 3.0, 3.0],
    "party_edges": [1],
    "entrances": [{"point": [50, 0], "label": "Entree principale", "main": True}],
}


def rooms(factor: int = 4) -> list[dict[str, Any]]:
    out = copy.deepcopy(g3.ROOMS)
    for r in out:
        r["quantity"] = r.get("quantity", 1) * factor
    for r in out:
        if r["id"] in ("H01", "T02", "K01"):  # single rooms stay single
            r["quantity"] = 1
    return out


def program(factor: int = 4) -> Program:
    return load_yaml(Program, yaml.safe_dump({"rooms": rooms(factor)}))


def site(**over: Any) -> SiteSpec:
    return load_yaml(SiteSpec, yaml.safe_dump({**SITE, **over}))


def write_site_yaml(path: Path, **over: Any) -> Path:
    data = {**SITE, **over}
    data["footprint"] = data["footprint"]["exterior"]
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path
