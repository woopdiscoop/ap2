"""Ticket A.4 eval A401, A402 (contract part), A406 (contract round trip): contracts 1.5.0.

A401 compares the P8 / P25 / P60 layouts (seed-3 start, annealing seed 6 with the Q.3
iteration budgets) with SHA-256 digests of the canonical layouts computed with the code at the
base commit of A.4 (``be5d115``), before any change.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

_TESTS = Path(__file__).resolve().parent.parent
for _sub in ("optimize", "program", "."):
    if str(_TESTS / _sub) not in sys.path:
        sys.path.insert(0, str(_TESTS / _sub))

from fixtures import FIXTURE_PAIRS, load_program, load_site  # noqa: E402
from optimize_helpers import (  # noqa: E402
    ANNEAL_ITER,
    ANNEAL_SEED,
    SEED_ATTEMPTS,
    load_test_rulebook,
    prepare,
)

from ale.config import AleConfig  # noqa: E402
from ale.contracts import export_schemas, lock  # noqa: E402
from ale.contracts.geometry import Polygon  # noqa: E402
from ale.contracts.models import CoreSpec, Entrance, Program, RoomSpec, SiteSpec  # noqa: E402
from ale.contracts.serialization import canonical_json, dump_yaml, load_yaml  # noqa: E402
from ale.contracts.version import CONTRACTS_VERSION  # noqa: E402
from ale.optimize import anneal  # noqa: E402
from ale.topology import seed_plan  # noqa: E402

#: SHA-256 of ``canonical_json`` of the seed-3 start and the annealed layout, computed at be5d115.
BEFORE_A4 = {
    "P8": (
        "78f40d05384edec3886a7bf7972dabe81e25ca17d85fbfecdf89e09d25b07641",
        "0bf4b64382f2209566f2a0ebe2025ec3cdd7e5e5618deb2bf8c81a6431ebc787",
    ),
    "P25": (
        "c5e26ca4d9b7f3f40ad2b4927e17ded2e4caa99bacc6b6d2f9cb09274875df4f",
        "a71ed5b1c114125da5e75d235781e98c6a5a3ec698eaed09766fe3ec77d24886",
    ),
    "P60": (
        "51b34cc2586f05ae6176f03bf794ba9f3b1216a133fba143dd91d5fe763f4c60",
        "e397b4469752f3a3ede3d1b59e6f07543d06078cf93e2302390723bbf969d0e9",
    ),
}
NAMES = {"program_08": "P8", "program_25": "P25", "program_60": "P60"}


def _digest(model: object) -> str:
    return hashlib.sha256(canonical_json(model)).hexdigest()  # type: ignore[arg-type]


# ------------------------------------------------------------------------------ A401
def test_A401_version_and_locks() -> None:
    assert CONTRACTS_VERSION == "1.8.0"  # superseded by M.2, then R.8
    assert lock.main(["--check"]) == 0
    assert export_schemas.main(["--check"]) == 0
    site = json.loads((export_schemas.SCHEMA_DIR / "SiteSpec.schema.json").read_text("utf-8"))
    assert {"entrances", "cores", "mode", "setbacks", "party_edges"} <= set(site["properties"])
    room = json.loads((export_schemas.SCHEMA_DIR / "RoomSpec.schema.json").read_text("utf-8"))
    assert "anchor" in room["properties"]


def test_A401_defaults_reproduce_today() -> None:
    for prog, site in FIXTURE_PAIRS:
        s = load_site(site)
        assert (s.entrances, s.cores, s.mode, s.setbacks, s.party_edges) == (
            (),
            (),
            "footprint",
            None,
            (),
        )
        assert all(r.anchor is None and r.floor == 0 for r in load_program(prog).rooms)


@pytest.mark.slow
@pytest.mark.timeout(900)
def test_A401_compat_layouts_byte_identical() -> None:
    rulebook = load_test_rulebook()
    cfg = AleConfig()
    for prog, site in FIXTURE_PAIRS:
        name = NAMES[prog]
        prep = prepare(Path(tempfile.mkdtemp()), load_program(prog), load_site(site))
        start = seed_plan(prep, rulebook, cfg, seed=3, max_attempts=SEED_ATTEMPTS)
        layout0 = start.realization.layout
        assert layout0 is not None
        res = anneal(prep, rulebook, cfg, start.plan, seed=ANNEAL_SEED, max_iter=ANNEAL_ITER[name])
        assert (_digest(layout0), _digest(res.layout)) == BEFORE_A4[name], name


# ------------------------------------------------------------------------------ A402
RECT: dict[str, Any] = {
    "footprint": {"exterior": [[0, 0], [20, 0], [20, 10], [0, 10]], "holes": []},
    "north_angle_deg": 0.0,
    "access_edge": 0,
}


def _site(**extra: Any) -> SiteSpec:
    return SiteSpec.model_validate({**RECT, **extra})


def _reject(key: str, **extra: Any) -> None:
    with pytest.raises(ValidationError) as info:
        _site(**extra)
    assert key in str(info.value)


def test_A402_site_fields_valid() -> None:
    site = _site(
        entrances=[
            {"point": [10, 0], "label": "Principale", "main": True},
            {"point": [20.05, 5]},  # within one module of the boundary
            {"point": [0, 10]},  # a corner
        ],
        cores=[
            {"id": "C1", "rect": [0, 0, 3, 3], "kind": "stair"},
            {"id": "C2", "rect": [3, 0, 2, 3], "kind": "lift"},  # touching, not overlapping
            {"id": "C3", "rect": [17, 7, 3, 3], "kind": "core"},
            {"id": "C4", "rect": [8, 4, 1, 1], "kind": "shaft"},
        ],
        party_edges=[1, 3],
    )
    assert [e.main for e in site.entrances] == [True, False, False]
    assert len(site.cores) == 4
    plot = _site(mode="plot", setbacks=[3, 3, 3, 3], entrances=[{"point": [5, 5], "main": True}])
    assert plot.mode == "plot" and plot.setbacks == (3.0, 3.0, 3.0, 3.0)
    assert _site(mode="plot").setbacks is None


def test_A402_site_fields_invalid() -> None:
    _reject("entrances[0]", entrances=[{"point": [10, 5]}])  # inside, off the boundary
    _reject("entrances[0]", entrances=[{"point": [10, -1]}])
    two_main = [{"point": [0, 0], "main": True}, {"point": [20, 0], "main": True}]
    _reject("une seule", entrances=two_main)
    _reject("entrances[0]", mode="plot", entrances=[{"point": [30, 5]}])  # outside the plot
    _reject("cores[0]", cores=[{"id": "C1", "rect": [18, 0, 5, 3], "kind": "stair"}])
    overlap = [
        {"id": "C1", "rect": [0, 0, 4, 4], "kind": "stair"},
        {"id": "C2", "rect": [3, 3, 4, 4], "kind": "lift"},
    ]
    _reject("chevauche", cores=overlap)
    _reject("kind", cores=[{"id": "C1", "rect": [0, 0, 2, 2], "kind": "garage"}])
    _reject("rect", cores=[{"id": "C1", "rect": [0, 0, 0, 2], "kind": "core"}])
    same_id = [
        {"id": "C1", "rect": [0, 0, 2, 2], "kind": "core"},
        {"id": "C1", "rect": [5, 5, 2, 2], "kind": "core"},
    ]
    _reject("identifiants en double", cores=same_id)
    _reject("mode", mode="parcel")
    _reject("setbacks", mode="plot", setbacks=[3, 3, 3])  # wrong count
    _reject("setbacks", setbacks=[3, 3, 3, 3])  # mode footprint
    _reject("setbacks", mode="plot", setbacks=[3, 3, 3, -1])
    _reject("party_edges", party_edges=[4])
    _reject("party_edges", party_edges=[-1])
    _reject("en double", party_edges=[1, 1])
    _reject("colour", colour="red")  # unknown key still refused


def test_A402_room_fields() -> None:
    base: dict[str, Any] = {
        "id": "R1",
        "name": "Hall",
        "type": "entrance_hall",
        "target_area_m2": 12.0,
        "macro_zone": "PUBLIC",
    }
    assert RoomSpec.model_validate(base).anchor is None
    assert RoomSpec.model_validate({**base, "anchor": "corner"}).anchor == "corner"
    assert RoomSpec.model_validate({**base, "anchor": "entrance", "floor": 2}).floor == 2
    for bad in ({"anchor": "middle"}, {"floor": -1}, {"floor": 1.5}):
        with pytest.raises(ValidationError):
            RoomSpec.model_validate({**base, **bad})


def test_A402_l_shaped_site() -> None:
    poly = Polygon(exterior=((0, 0), (30, 0), (30, 12), (18, 12), (18, 20), (0, 20)))
    ok = SiteSpec(
        footprint=poly,
        north_angle_deg=0.0,
        access_edge=0,
        entrances=(Entrance(point=(24.0, 12.0), main=True),),
        cores=(CoreSpec(id="C", rect=(0.0, 12.0, 4.0, 4.0), kind="stair"),),
    )
    assert ok.entrances[0].point == (24.0, 12.0)
    with pytest.raises(ValidationError, match="cores"):  # a core in the notch
        SiteSpec(
            footprint=poly,
            north_angle_deg=0.0,
            access_edge=0,
            cores=(CoreSpec(id="C", rect=(25.0, 14.0, 3.0, 3.0), kind="core"),),
        )


# ------------------------------------------------------------------------------ A406
def test_A406_round_trip_contract() -> None:
    site = _site(
        entrances=[{"point": [10, 0], "label": "Entrée", "main": True}, {"point": [0, 5]}],
        cores=[{"id": "N1", "rect": [1.5, 1.5, 2.5, 3.0], "kind": "stair"}],
        mode="plot",
        setbacks=[1.0, 2.0, 3.0, 4.0],
        party_edges=[2],
    )
    program = Program.model_validate(
        {
            "rooms": [
                {
                    "id": "R1",
                    "name": "Hall",
                    "type": "entrance_hall",
                    "target_area_m2": 12.0,
                    "macro_zone": "PUBLIC",
                    "anchor": "entrance",
                    "floor": 1,
                },
                {
                    "id": "R2",
                    "name": "Bureau",
                    "type": "office",
                    "target_area_m2": 12.0,
                    "macro_zone": "ADMINISTRATIVE",
                    "anchor": "corner",
                    "floor": 1,
                },
            ]
        }
    )
    for model in (site, program):
        cls = type(model)
        via_json = cls.model_validate_json(canonical_json(model))
        via_yaml = load_yaml(cls, dump_yaml(model))
        assert via_json == model and via_yaml == model
        assert canonical_json(via_json) == canonical_json(model) == canonical_json(via_yaml)
