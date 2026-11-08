"""Evaluation tests V01-V03 (eval.md section 3)."""

from __future__ import annotations

import math

from geometry_helpers import fb, load_test_rulebook, one_piece, prepared_rect, rb, room

from ale.config import AleConfig
from ale.contracts.enums import Bearing, MacroZone
from ale.contracts.models import Rulebook
from ale.geometry import evaluate, realize
from ale.geometry.evaluate import WEIGHT_NAMES

CONFIG = AleConfig()
RULEBOOK = load_test_rulebook()
E02_PLAN = one_piece(b=[rb("r1"), fb(["r2", "r3"], ["r4"])])


def test_V01_violations() -> None:
    rooms = [
        room("r1", 12.0, zone=MacroZone.PUBLIC, avoid=("r2",)),
        room("r2", 6.0, needs_facade=True),
        room("r3", 6.0),
        room("r4", 12.0, zone=MacroZone.PUBLIC, adjacent_to=("r1",)),
    ]
    prepared = prepared_rect(110, 52, rooms)
    real = realize(prepared, E02_PLAN, RULEBOOK, CONFIG)
    assert real.layout is not None
    found = {(v.code, v.instance_ids) for v in real.layout.metrics.violations}
    assert ("NO_FACADE", ("r2",)) in found  # inner stack room
    assert ("REQUIRED_ADJ", ("r4",)) in found  # r4 is far from r1
    assert ("AVOID_ADJ", ("r1", "r2")) in found  # r1 touches r2
    zone = [v for v in real.layout.metrics.violations if v.code == "ZONE_SPLIT"]
    assert any("zone PUBLIC split in piece 0 block B" in v.detail for v in zone)
    keys = [(v.code, v.instance_ids) for v in real.layout.metrics.violations]
    assert keys == sorted(keys)
    # Without a plan there is no ZONE_SPLIT.
    bare = evaluate(real.layout, prepared, RULEBOOK, CONFIG)
    assert all(v.code != "ZONE_SPLIT" for v in bare.violations)


def _v02_rulebook() -> Rulebook:
    data = RULEBOOK.model_dump(mode="json")
    orient = {"N": 0.5, "E": 0.25, "S": 1.0, "W": -0.5}
    for stats in data["types"].values():
        stats["orientation"] = dict(orient)
    data["types"]["office"]["aspect"] = {"p10": 1.0, "p50": 1.1, "p90": 1.2}
    data["types"]["meeting_room"]["aspect"] = {"p10": 1.6, "p50": 1.8, "p90": 3.0}
    data["types"]["sanitary"]["aspect"] = {"p10": 1.0, "p50": 1.4, "p90": 2.0}
    data["adjacency"] = {
        "default_p": 0.5,
        "pairs": [{"a": "office", "b": "meeting_room", "p": 0.9}],
    }
    data["core_offset"] = {"dx_norm": 0.0, "dy_norm": 0.0}
    return Rulebook.model_validate(data)


def test_V02_cost_terms() -> None:
    rulebook = _v02_rulebook()
    rooms = [
        room("r1", 12.0, rtype="office"),
        room("r2", 6.0, rtype="meeting_room"),
        room("r3", 6.0, rtype="sanitary"),
        room("r4", 12.0, rtype="meeting_room", adjacent_to=("r1",)),
    ]
    prepared = prepared_rect(110, 52, rooms, rulebook)
    real = realize(prepared, E02_PLAN, rulebook, CONFIG)
    assert real.layout is not None
    metrics = real.layout.metrics
    w = {"W": -0.5, "N": 0.5}
    # Geometry of E02: r1 (0,12,30,40), r2 (30,12,30,20), r3 (30,32,30,20), r4 (72,12,30,40).
    expected = {
        # r4 → r1 not sharing >= 12.
        "required_adjacency": 1.0,
        # Touching pairs: r1-r2 (office/meeting 0.9), r1-r3, r2-r3 (default 0.5).
        "rulebook_adjacency": ((0.5 - 0.9) + 0.0 + 0.0) / 4,
        # Bands: office [1, 1.2], meeting [1.6, 2] (p90 clipped), sanitary [1, 2].
        "aspect": ((40 / 30 - 1.2) + (1.6 - 30 / 20) + 0.0 + (1.6 - 40 / 30)) / 4,
        "area_overshoot": 0.0,
        # r1 longest contact = west edge (40 > 30); r3, r4 north; r2 inner.
        "facade_orientation": -(w["W"] + w["N"] + w["N"]) / 4,
        # Sanitary r3 centre (45, 42); core target = bbox centre (55, 26).
        "core_distance": math.hypot(45 - 55, 42 - 26) / math.hypot(110, 52),
        # Circulation 110x12 + 12x40 + 8x40 cells = 21.2 m²; net 36 m².
        "circulation_length": 21.2 / (36.0 * 0.18) - 1.0,
    }
    assert set(metrics.cost_breakdown) == set(WEIGHT_NAMES)
    for name, value in expected.items():
        assert math.isclose(metrics.cost_breakdown[name], value, rel_tol=0, abs_tol=1e-9), name
    weights = CONFIG.optimizer.weights.model_dump()
    total = sum(weights[n] * metrics.cost_breakdown[n] for n in WEIGHT_NAMES)
    assert math.isclose(metrics.total_cost, total, rel_tol=0, abs_tol=1e-9)
    assert metrics.total_overshoot_m2 == 0.0
    assert math.isclose(metrics.circulation_area_m2, 21.2, abs_tol=1e-9)
    assert metrics.residue_area_m2 == 0.0
    assert Bearing.S in rulebook.types["office"].orientation


def test_V03_circulation_budget() -> None:
    rooms = [room("r1", 12.0), room("r2", 12.0)]
    prepared = prepared_rect(60, 52, rooms)
    plan = one_piece(b=[rb("r1"), rb("r2")])
    generous = AleConfig.model_validate({"circulation": {"ratio": 0.5}})
    real = realize(prepared, plan, RULEBOOK, generous)
    assert real.layout is not None
    # Circulation = spine 60 x 12 = 7.2 m² <= 0.5 x 24 m².
    assert real.layout.metrics.cost_breakdown["circulation_length"] == 0.0
    tight = evaluate(real.layout, prepared, RULEBOOK, CONFIG)
    expected = 7.2 / (24.0 * 0.18) - 1.0
    assert tight.cost_breakdown["circulation_length"] > 0
    assert math.isclose(tight.cost_breakdown["circulation_length"], expected, abs_tol=1e-12)
