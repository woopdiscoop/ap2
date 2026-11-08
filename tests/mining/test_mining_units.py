"""Ticket 2.1 unit tests: edge cases of :func:`ale.mining.extract_topology`."""

from __future__ import annotations

import logging

import pytest
from mining_helpers import bare_plan, grid_plan, rect, room, wall

from ale.contracts.config import AleConfig
from ale.contracts.enums import ContactKind, Fidelity, SourceKind
from ale.contracts.geometry import Polygon
from ale.contracts.models import LabelledPolygon, PlanGeometry
from ale.mining import PlanTopology, extract_topology
from ale.mining import topology as topo_mod

CFG = AleConfig()


def _topo(plan: PlanGeometry) -> PlanTopology:
    out = extract_topology(plan, CFG)
    assert out is not None
    return out


def test_window_is_not_a_door() -> None:
    topo = _topo(grid_plan(windows=True))
    by_pair = {(c.a, c.b): c for c in topo.contacts}
    assert by_pair[("r01", "r11")].kind is ContactKind.WALL
    assert by_pair[("r01", "r11")].openings == 0


@pytest.mark.parametrize(
    ("kind", "fidelity"),
    [
        (SourceKind.DWG, Fidelity.CAD),
        (SourceKind.PDF_VECTOR, Fidelity.PDF_VECTOR),
        (SourceKind.PDF_SCANNED, Fidelity.RASTER),
        (SourceKind.RASTER, Fidelity.RASTER),
    ],
)
def test_fidelity(kind: SourceKind, fidelity: Fidelity) -> None:
    topo = _topo(grid_plan(kind=kind))
    assert topo.fidelity is fidelity
    assert topo.source_sha256 == grid_plan().source_sha256
    assert (topo.page, topo.plan_index) == (0, 0)


def test_default_thickness_without_walls() -> None:
    # No wall: thickness 0.10 m → touch gap 0.05 + 0.05 + 0.10 = 0.20 m.
    near = bare_plan([room("A", rect(0, 0, 4, 4)), room("B", rect(4.15, 0, 8, 4))])
    assert [c.shared_m for c in _topo(near).contacts] == [4.0]
    far = bare_plan([room("A", rect(0, 0, 4, 4)), room("B", rect(4.25, 0, 8, 4))])
    assert _topo(far).contacts == ()


def test_walls_without_thickness_or_far_are_ignored() -> None:
    rooms = [room("A", rect(0, 0, 4, 4)), room("B", rect(4.25, 0, 8, 4))]
    walls = [wall((4.1, 0), (4.1, 4), None), wall((50, 0), (50, 4), 0.6)]
    assert _topo(bare_plan(rooms, walls)).contacts == ()
    thick = [wall((4.12, 0), (4.12, 4), 0.25)]
    assert [c.shared_m for c in _topo(bare_plan(rooms, thick)).contacts] == [4.0]


def test_touching_polygons_and_types() -> None:
    # Rooms drawn to the wall centreline (shared edge, gap 0) are in contact too.
    rooms = [
        room("Z", rect(0, 0, 3, 3), "office"),
        room("A", rect(3, 0, 6, 3), "storage"),
    ]
    topo = _topo(bare_plan(rooms))
    assert topo.rooms == (("A", "storage", 9.0), ("Z", "office", 9.0))
    assert [(c.a, c.b, c.shared_m) for c in topo.contacts] == [("A", "Z", 3.0)]
    assert dict(topo.exterior) == {"A": 9.0, "Z": 9.0}


def test_oblique_edges_do_not_face() -> None:
    # A triangle whose hypotenuse is at 45° to the neighbour's edge: no facing contact.
    tri = room("T", ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0)))
    other = room("U", ((4.2, 0.0), (8.0, 0.0), (8.0, 4.0), (4.2, 4.0)))
    diag = room("D", ((-0.1, 0.2), (3.8, 4.1), (-0.1, 4.1)))
    topo = _topo(bare_plan([tri, other, diag], [wall((4.1, 0), (4.1, 4))]))
    assert [(c.a, c.b) for c in topo.contacts] == [("D", "T"), ("T", "U")]
    assert topo.contacts[1].shared_m == pytest.approx(4.0)


def test_slanted_edge_partially_within_gap() -> None:
    # B's left edge diverges from A's right edge: only the part within the gap counts.
    a = room("A", rect(0, 0, 4, 4))
    b = room("B", ((4.2, 0.0), (8.0, 0.0), (8.0, 4.0), (4.6, 4.0)))
    topo = _topo(bare_plan([a, b], [wall((4.1, 0), (4.1, 4))]))
    assert len(topo.contacts) == 1
    # gap 0.3 m: the perpendicular distance to B's line grows ~0.1 m per m; facing ≈ 1.0 m.
    assert 0.6 <= topo.contacts[0].shared_m < 4.0


def test_room_with_hole_and_separate_buildings() -> None:
    ring = room(
        "R",
        rect(0, 0, 10, 10),
    )
    holed = LabelledPolygon(
        id="H",
        polygon=Polygon(exterior=rect(0, 0, 10, 10), holes=(rect(3, 3, 7, 7),)),
    )
    inner = room("I", rect(3.2, 3.2, 6.8, 6.8))
    far = room("F", rect(100, 100, 104, 104))
    topo = _topo(bare_plan([holed, inner, far], [wall((3.1, 3.1), (6.9, 3.1))]))
    pairs = {(c.a, c.b): c.shared_m for c in topo.contacts}
    assert pairs == {("H", "I"): pytest.approx(4 * 3.6)}
    ext = dict(topo.exterior)
    assert ext == {"F": pytest.approx(16.0), "H": pytest.approx(40.0)}
    assert ring.id == "R"


def test_empty_plan() -> None:
    topo = _topo(bare_plan([]))
    assert (topo.rooms, topo.contacts, topo.exterior) == ((), (), ())


def test_unconvertible_plan_returns_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    plan = grid_plan()

    def boom(self: PlanGeometry) -> PlanGeometry:
        raise ValueError("invalid polygon after scaling")

    monkeypatch.setattr(PlanGeometry, "to_metric", boom)
    with caplog.at_level(logging.WARNING, logger="ale.mining.topology"):
        assert extract_topology(plan, CFG) is None
    assert "cannot be converted" in caplog.text


def test_edge_budget_skips_with_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(topo_mod, "_MAX_EDGE_PAIRS", 3)
    with caplog.at_level(logging.WARNING, logger="ale.mining.topology"):
        topo = _topo(grid_plan())
    assert topo.contacts == ()
    assert topo.exterior == ()
    assert "too detailed" in caplog.text


def test_merged_length_and_helpers() -> None:
    assert topo_mod._merged_length([]) == 0.0
    assert topo_mod._merged_length([(2.0, 3.0), (0.0, 1.0), (0.5, 1.5)]) == pytest.approx(2.5)
    assert topo_mod._ring_edges([(0, 0), (1, 0), (1, 0), (1, 1), (0, 0)]) == [
        ((0.0, 0.0), (1.0, 0.0)),
        ((1.0, 0.0), (1.0, 1.0)),
        ((1.0, 1.0), (0.0, 0.0)),
    ]
    # Parallel edges whose projections do not overlap, or too far apart.
    assert topo_mod._facing_interval(((0, 0), (1, 0)), ((2, 0.1), (3, 0.1)), 0.3) is None
    assert topo_mod._facing_interval(((0, 0), (1, 0)), ((0, 0.5), (1, 0.5)), 0.3) is None
    assert topo_mod._facing_interval(((0, 0), (1, 0)), ((1, 0.2), (0, 0.2)), 0.3) == (0.0, 1.0)
    # Slanted: distance 0.25 → 0.75 along the edge; perpendicular distance <= 0.3 for s <= 0.171.
    lo, hi = topo_mod._facing_interval(((0, 0), (1, 0)), ((0, 0.25), (1, 0.75)), 0.3) or (0, 0)
    assert (lo, hi) == (pytest.approx(0.0), pytest.approx(0.1708, abs=1e-3))
    assert topo_mod._facing_interval(((0, 0), (1, 0)), ((0, 0.5), (1, 0.75)), 0.3) is None
