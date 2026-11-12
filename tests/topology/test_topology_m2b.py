"""Tests B201-B203 and B205 (Ticket M.2b): bar plates around an interior solid.

B201 is the diagnosis in ``specs/tickets/M.2b_bar-skeleton/eval_report.md``. The engine seeds
bars reliably up to a ``fill_ratio`` of about 0.7 (RD target 0.85-1.0, not reached: the xfail
test records it).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _sub in ("program", "geometry", "topology"):
    if str(_TESTS / _sub) not in sys.path:
        sys.path.insert(0, str(_TESTS / _sub))

from bar_helpers import bar_case, seeds_ok  # noqa: E402
from program_helpers import load_test_rulebook  # noqa: E402

from ale.contracts.footprint import decompose_footprint  # noqa: E402
from ale.contracts.geometry import ModulePolygon  # noqa: E402

RB = load_test_rulebook()


def test_B201_bar_decomposition_is_a_wing_with_flipped_spine() -> None:
    """The M.1 bar (64.8 x 19.2 m, solid 16.8 x 7.2 m): a full-depth wing is the root with its
    spine across the bar; the strips beside the solid hang on it by J1 fingers."""
    fp = ModulePolygon(
        exterior=((0, 0), (648, 0), (648, 192), (0, 192)),
        solids=(((240, 60), (240, 132), (408, 132), (408, 60)),),
    )
    got = decompose_footprint(fp)
    root = got.pieces[0]
    assert (root.rect.h, root.spine_axis) == (192, "Y")
    assert [j.kind for j in got.junctions if j.parent == 0] == ["J1", "J1"]


def test_B205_squarish_plate_keeps_pinwheel_figure() -> None:
    fp = ModulePolygon(
        exterior=((0, 0), (288, 0), (288, 192), (0, 192)),
        solids=(((126, 78), (126, 108), (156, 108), (156, 78)),),
    )
    got = decompose_footprint(fp)
    assert len(got.pieces) == 4
    assert [j.kind for j in got.junctions if j.parent == 0] == ["J1", "J1"]


def test_B202_smoke_central_bar() -> None:
    _, pi = bar_case("central_65", 0.70, RB)
    assert seeds_ok(pi, RB, range(3)) >= 2


@pytest.mark.slow
@pytest.mark.timeout(900)
@pytest.mark.parametrize("name", ["central_54", "central_65"])
def test_B202_bar_central(name: str) -> None:
    _, pi = bar_case(name, 0.70, RB)
    assert seeds_ok(pi, RB, range(10)) >= 8


@pytest.mark.slow
@pytest.mark.timeout(900)
@pytest.mark.parametrize("name", ["third_65", "side_65"])
def test_B203_bar_offcentre(name: str) -> None:
    _, pi = bar_case(name, 0.70, RB)
    assert seeds_ok(pi, RB, range(10)) >= 8


@pytest.mark.slow
@pytest.mark.timeout(900)
@pytest.mark.xfail(reason="RD load 0.85-1.0 not reached: see report", strict=False)
@pytest.mark.parametrize("name", ["central_54", "central_65", "third_65", "side_65"])
def test_B202_B203_rd_load(name: str) -> None:
    fr, pi = bar_case(name, 0.98, RB)
    assert fr >= 0.85
    assert seeds_ok(pi, RB, range(10)) >= 8
