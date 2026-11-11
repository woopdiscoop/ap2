"""Ticket R.3 evaluation S301-S305 and S308: space-syntax measures (hand-computed values)."""

from __future__ import annotations

import subprocess
import sys
from fractions import Fraction as F
from pathlib import Path

import networkx as nx
from export_helpers import make_layout

from ale.analysis import CIRC, ENTRANCE, analyse, build_graph, measures
from ale.config import AleConfig
from ale.contracts.enums import MacroZone
from ale.contracts.geometry import ModuleRect
from ale.contracts.models import GridSpec, Layout, PlacedRoom
from ale.program.models import PreparedInput

CFG = AleConfig()  # module 100 mm, door edge c = 12 modules
ROOT = Path(__file__).resolve().parents[2]

Rect = tuple[int, int, int, int]


def _layout(rooms: dict[str, Rect], circ: dict[str, Rect], module_mm: int = 100) -> Layout:
    """The export fixture's layout with other rooms and corridors (ids sorted)."""

    def placed(items: dict[str, Rect]) -> tuple[PlacedRoom, ...]:
        return tuple(
            PlacedRoom(instance_id=i, spec_id=None, rect=ModuleRect(*r), target_area_m2=None)
            for i, r in sorted(items.items())
        )

    return make_layout().model_copy(
        update={
            "grid": GridSpec(module_mm=module_mm),
            "rooms": placed(rooms),
            "circulation": placed(circ),
        }
    )


#: Single corridor y 40..52 (not touching the access edge y = 0), 3 rooms each side.
HAND_ROOMS: dict[str, Rect] = {
    "A1": (0, 0, 33, 40),
    "A2": (33, 0, 33, 40),
    "A3": (66, 0, 34, 40),
    "B1": (0, 52, 33, 48),
    "B2": (33, 52, 33, 48),
    "B3": (66, 52, 34, 48),
}
HAND_CIRC: dict[str, Rect] = {"C": (0, 40, 100, 12)}


def test_S301_hand_values(prepared: PreparedInput) -> None:
    res = analyse(_layout(HAND_ROOMS, HAND_CIRC), prepared, CFG)
    # 8 nodes: ENTRANCE - CIRC - 6 rooms. Room: distances 1 (CIRC), 2 (ENTRANCE + 5 rooms)
    # -> MD = 13/7, RA = 2(13/7 - 1)/6 = 2/7, integration 7/2, control 1/7 (only CIRC, degree 7).
    assert len(res.rooms) == 6
    for r in res.rooms:
        assert r.depth == 2
        assert r.mean_depth == F(13, 7)
        assert r.relative_asymmetry == F(2, 7)
        assert r.integration == F(7, 2)
        assert r.control == F(1, 7)
    c = res.nodes[CIRC]
    assert (c.depth, c.mean_depth, c.relative_asymmetry) == (1, F(1), F(0))
    assert c.integration is None  # RA = 0 -> infinite
    assert c.control == 7  # ENTRANCE and the 6 rooms are of degree 1
    e = res.nodes[ENTRANCE]
    assert (e.depth, e.mean_depth, e.relative_asymmetry) == (0, F(13, 7), F(2, 7))
    assert e.integration == F(7, 2) and e.control == F(1, 7)
    assert res.mean_depth == 2
    assert res.zone_mean_depth == {}  # rooms without spec have no zone


def test_S301_measures_small_graphs() -> None:
    assert measures(nx.Graph()) == {}
    g: nx.Graph = nx.Graph()
    g.add_node("x")
    m = measures(g)  # root absent, one node
    assert m["x"].depth is None and m["x"].mean_depth is None and m["x"].integration is None
    g.add_edge(ENTRANCE, "x")  # k = 2: MD defined, RA not
    m = measures(g)
    assert m["x"].mean_depth == 1 and m["x"].relative_asymmetry is None and m["x"].depth == 1
    g.add_edge("x", "y")  # path of 3: x in the middle MD 1, RA 0; ends MD 3/2, RA 1
    m = measures(g)
    assert m["x"].relative_asymmetry == 0 and m["x"].integration is None
    assert m[ENTRANCE].relative_asymmetry == 1 and m[ENTRANCE].integration == 1
    assert m["x"].control == 2
    g.add_node("island")  # unreachable from the entrance
    assert measures(g)["island"].depth is None


def test_S302_required_door(prepared: PreparedInput) -> None:
    # R01 requires R02 (program_08); R03#1 / R03#2 have no REQUIRED adjacency.
    def graph(r2_y: int) -> nx.Graph:
        rooms: dict[str, Rect] = {
            "R01": (0, 0, 30, 40),
            "R02": (30, r2_y, 23, 40),
            "R03#1": (0, 60, 30, 40),
            "R03#2": (30, 60, 23, 40),
        }
        return build_graph(_layout(rooms, {}), prepared, CFG).graph

    g = graph(0)  # both pairs share 40 modules
    assert g.has_edge("R01", "R02")  # required and shares >= c
    assert not g.has_edge("R03#1", "R03#2")  # shares >= c but not required
    assert g.has_edge("R01", "R02") and graph(28).has_edge("R01", "R02")  # shares 12 = c
    assert not graph(29).has_edge("R01", "R02")  # shares 11 < c
    assert not graph(30).has_edge("R01", "R02")  # shares 10 < c
    assert not graph(41).has_edge("R01", "R02")  # no contact


def test_S303_walk(prepared: PreparedInput) -> None:
    # Export fixture: access edge y = 0 (mid (50, 0)); nearest corridor C01 (0,40,60,12) at
    # (50, 40); centreline y = 46. Hand Manhattan lengths in modules (module = 0.1 m):
    # R02: 6 + |50 - 41.5| + 6 = 20.5; R05: 6 + 9.5 + 6 = 21.5; R01: 6 + 35 + 6 = 47;
    # R03#2 via the C01/C02 boundary mid (60, 46): 16 + (31.5 + 6) = 53.5.
    res = analyse(make_layout(), prepared, CFG)
    walk = {r.instance_id: r.walk_m for r in res.rooms}
    assert walk["R02"] == F(205, 100)
    assert walk["R05"] == F(215, 100)
    assert walk["R01"] == F(47, 10)
    assert walk["R03#2"] == F(535, 100)
    assert walk["R06"] is None  # 9 modules wide: no door on the corridor
    assert res.max_walk_m == F(535, 100)


def test_S303_walk_vertical_corridor(prepared: PreparedInput) -> None:
    # Vertical corridor x 44..56 touching the access edge on x 44..56: entrance point (50, 0),
    # centreline x = 50. Left room contact (44, 25): 0 + 25 + 6 = 31; right (56, 75): 81.
    layout = _layout({"L": (0, 0, 44, 50), "R": (56, 50, 44, 50)}, {"C": (44, 0, 12, 100)})
    res = analyse(layout, prepared, CFG)
    assert not res.entrance_inferred
    assert {r.instance_id: r.walk_m for r in res.rooms} == {"L": F(31, 10), "R": F(81, 10)}
    # 200 mm modules: metres double
    res2 = analyse(_layout({"L": (0, 0, 44, 50)}, {"C": (44, 0, 12, 100)}, 200), prepared, CFG)
    assert res2.rooms[0].walk_m == F(31, 5)


def test_S303_walk_two_contacts(prepared: PreparedInput) -> None:
    # A room along an L-shaped corridor touches both arms; the nearer contact counts.
    # Entrance on the longest contact (C2, x 0..44, point (22, 0)); contact with C2 at
    # (22, 12), C2 horizontal with centreline y = 6: 6 + 0 + 6 = 12 modules = 1.2 m.
    layout = _layout({"W": (0, 12, 44, 88)}, {"C1": (44, 0, 12, 100), "C2": (0, 0, 44, 12)})
    (w,) = analyse(layout, prepared, CFG).rooms
    assert w.walk_m == F(6, 5)


def test_S304_entrance_not_inferred(prepared: PreparedInput) -> None:
    layout = _layout({"A": (0, 12, 50, 88), "B": (50, 12, 50, 88)}, {"C": (0, 0, 100, 12)})
    sg = build_graph(layout, prepared, CFG)
    assert not sg.entrance_inferred
    assert sg.graph.has_edge(ENTRANCE, CIRC)
    assert sg.entrance_point == (F(50), F(0)) and sg.entrance_rect == 0
    assert analyse(layout, prepared, CFG).entrance_inferred is False


def test_S304_entrance_inferred(prepared: PreparedInput) -> None:
    layout = make_layout()  # corridors y 40..52, access edge y = 0
    sg = build_graph(layout, prepared, CFG)
    assert sg.entrance_inferred
    assert sg.graph.has_edge(ENTRANCE, CIRC)  # C01 and C02 touch: one component
    res = analyse(layout, prepared, CFG)
    assert res.entrance_inferred
    assert all(r.depth is not None for r in res.rooms if r.instance_id != "R06")
    assert res.max_walk_m is not None  # still computed
    # no circulation at all: inferred, nothing to measure, no crash
    bare = _layout({"A": (0, 0, 50, 50)}, {})
    sg0 = build_graph(bare, prepared, CFG)
    assert sg0.entrance_inferred and sg0.entrance_point is None and sg0.entrance_rect is None
    res0 = analyse(bare, prepared, CFG)
    assert res0.max_walk_m is None and res0.mean_depth is None and res0.rooms[0].depth is None


def test_S304_two_components_and_longest_contact(prepared: PreparedInput) -> None:
    # C1 touches the access edge on 20 modules, C2 on 30 (entrance on C2); C3 is a separate
    # component: unreachable, named CIRC#2.
    layout = _layout(
        {"A": (0, 12, 20, 40), "B": (20, 12, 30, 40), "Z": (70, 60, 30, 40)},
        {"C1": (0, 0, 20, 12), "C2": (20, 0, 30, 12), "C3": (70, 40, 30, 20)},
    )
    sg = build_graph(layout, prepared, CFG)
    assert sg.circ_nodes == ("CIRC#1", "CIRC#1", "CIRC#2")
    assert not sg.entrance_inferred and sg.entrance_rect == 1
    by = {r.instance_id: r for r in analyse(layout, prepared, CFG).rooms}
    assert by["A"].depth == 2 and by["Z"].depth is None and by["Z"].walk_m is None
    # nothing touches the edge: inferred towards the nearest rectangle
    far = _layout({"A": (0, 20, 30, 30)}, {"C1": (0, 12, 20, 8), "C2": (60, 60, 30, 12)})
    sgf = build_graph(far, prepared, CFG)
    assert sgf.entrance_inferred and sgf.entrance_rect == 0
    assert sgf.entrance_point == (F(20), F(12))  # (50, 0) clamped onto C1


def test_S304_vertical_access_edge(prepared: PreparedInput) -> None:
    # Access edge 3 is x = 0 (vertical). Corridor C1 meets it (entrance point (0, 46)); C2 does
    # not. A room touching the corridor right at the entrance point is at walking distance 0.
    fp = prepared.footprint.model_copy(update={"access_edge": 3})
    vertical = prepared.model_copy(update={"footprint": fp})
    layout = _layout(
        {"E": (-30, 40, 30, 12), "N": (0, 52, 50, 48), "Z": (80, 0, 20, 40)},
        {"C1": (0, 40, 50, 12), "C2": (80, 40, 20, 12)},
    )
    sg = build_graph(layout, vertical, CFG)
    assert not sg.entrance_inferred and sg.entrance_point == (F(0), F(46))
    assert sg.entrance_rect == 0
    by = {r.instance_id: r.walk_m for r in analyse(layout, vertical, CFG).rooms}
    # N: contact (25, 52): 0 + 25 + 6 = 31 modules; Z is on the other component
    assert by == {"E": F(0), "N": F(31, 10), "Z": None}


def test_S305_fixtures(seeded_layouts: dict[str, tuple[PreparedInput, Layout]]) -> None:
    for name, (prep, layout) in seeded_layouts.items():
        a = analyse(layout, prep, CFG)
        b = analyse(layout, prep, CFG)
        assert a == b, name
        assert len(a.rooms) == len(layout.rooms)
        for r in a.rooms:
            assert r.depth is not None and r.depth >= 2, (name, r.instance_id)
            assert r.mean_depth is not None, (name, r.instance_id)
            assert r.walk_m is not None and r.walk_m > 0, (name, r.instance_id)
        assert a.mean_depth is not None and a.max_walk_m is not None
        assert set(a.zone_mean_depth) <= set(MacroZone)
        sg1, sg2 = build_graph(layout, prep, CFG), build_graph(layout, prep, CFG)
        assert sorted(sg1.graph.edges) == sorted(sg2.graph.edges)


def _run(*cmd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", *cmd], cwd=ROOT, capture_output=True, text=True, check=False
    )


def test_S308_gates() -> None:
    """Lint, format, strict typing of the R.3 files and the contract lock (coverage and the
    whole suite are measured by the ticket's gate run)."""
    files = [
        "src/ale/analysis",
        "src/ale/export/report.py",
        "tests/analysis",
        "tests/export/test_export_syntax.py",
    ]
    lock = _run("ale.contracts.lock", "--check")
    assert lock.returncode == 0, lock.stdout + lock.stderr
    for cmd in (("ruff", "check", *files), ("ruff", "format", "--check", *files)):
        out = _run(*cmd)
        assert out.returncode == 0, out.stdout + out.stderr
    mypy = _run("mypy", "src/ale/analysis", "src/ale/export/report.py")
    assert mypy.returncode == 0, mypy.stdout + mypy.stderr
