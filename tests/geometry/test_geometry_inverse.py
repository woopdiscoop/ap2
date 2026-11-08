"""Inverse-generation property tests G01-G04 (eval.md section 2)."""

from __future__ import annotations

from typing import Any

import pytest
from geometry_helpers import load_test_rulebook, prepared_poly
from grammar_gen import Case, S, l_cases, rect_cases
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ale.config import AleConfig
from ale.contracts.footprint import decompose_footprint
from ale.contracts.models import Program
from ale.geometry import Realization, check_layout, realize
from ale.geometry.checks import share_length
from ale.geometry.junction import frame, to_abs

SETTINGS: dict[str, Any] = {
    "max_examples": 150,
    "derandomize": True,
    "deadline": None,
    "suppress_health_check": [HealthCheck.too_slow, HealthCheck.filter_too_much],
}
CONFIG = AleConfig()
RULEBOOK = load_test_rulebook()


def _run(case: Case) -> tuple[Realization, Any]:
    prepared = prepared_poly(case.points, case.rooms, RULEBOOK)
    assert prepared.program == Program(rooms=tuple(case.rooms))
    return realize(prepared, case.plan, RULEBOOK, CONFIG), prepared


def _zero_overshoot(case: Case, real: Realization) -> None:
    assert real.layout is not None
    placed = {p.instance_id: p.rect.area_cells() for p in real.layout.rooms}
    assert placed == case.cells


@settings(**SETTINGS)
@given(rect_cases())
def test_G01_realizable(case: Case) -> None:
    real, _ = _run(case)
    assert real.failures == ()
    assert real.layout is not None


@settings(**SETTINGS)
@given(rect_cases())
def test_G02_invariants(case: Case) -> None:
    real, prepared = _run(case)
    assert real.layout is not None
    assert check_layout(real.layout, prepared, CONFIG) == ()


@settings(**SETTINGS)
@given(rect_cases())
def test_G03_zero_overshoot(case: Case) -> None:
    real, _ = _run(case)
    _zero_overshoot(case, real)


@pytest.mark.parametrize("junction", ["J1", "J2"])
@settings(**SETTINGS)
@given(data=st.data())
def test_G04_L_shapes(junction: str, data: Any) -> None:
    case: Case = data.draw(l_cases(junction))
    real, prepared = _run(case)
    assert real.failures == ()
    assert real.layout is not None
    assert check_layout(real.layout, prepared, CONFIG) == ()
    _zero_overshoot(case, real)
    fp = decompose_footprint(prepared.footprint.polygon)
    assert fp.junction == junction
    primary, secondary = fp.pieces
    (d_a, _), (d_sec, _) = real.depths
    spine_p = to_abs(primary, 0, d_a, frame(primary)[0], S)
    spine_s = to_abs(secondary, 0, d_sec, frame(secondary)[0], S)
    circ = [c.rect for c in real.layout.circulation]
    assert spine_p in circ
    assert spine_s in circ
    if junction == "J2":
        assert share_length(spine_p, spine_s) >= S
    else:
        fingers = [
            c for c in circ if c != spine_p and c != spine_s and share_length(c, spine_s) >= S
        ]
        assert fingers, "no junction finger meets the secondary spine"
        assert any(share_length(f, spine_p) >= S for f in fingers)
