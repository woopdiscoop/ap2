"""Ticket 3.2 eval T01-T02: adjacency graph and planarity."""

from __future__ import annotations

from ale.contracts.models import Program, RoomSpec, Rulebook
from ale.contracts.taxonomy import load_taxonomy
from ale.program.models import PreparedInput
from ale.topology import build_graph
from ale.topology.graph import CORE, edges_of_kind, planarity


def _kind(graph, kind: str) -> set[tuple[str, str]]:  # type: ignore[no-untyped-def]
    return set(edges_of_kind(graph, kind))


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def test_T01_graph(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    g = build_graph(prep_25, rulebook)
    assert g.number_of_nodes() == 26
    assert CORE in g
    # Expanded adjacent_to of the P25 fixture, written out by hand.
    required = {
        _pair("H01", "H02"),
        _pair("H01", "V02"),
        _pair("H02", "M01#1"),
        _pair("S01#1", "S02"),
        _pair("S01#2", "S02"),
        _pair("T02", "T03"),
        _pair("V01", "V02"),
    }
    assert _kind(g, "required") == required
    avoid = {_pair(m, s) for m in ("M01#1", "M01#2", "K01") for s in ("S01#1", "S01#2")}
    assert _kind(g, "avoid") == avoid
    assert all(g.edges[a, b]["weight"] == -1.0 for a, b in avoid)
    tax = load_taxonomy()
    core_rooms = {iid for iid, spec in prep_25.instances if tax.get(spec.type).service_core}
    assert core_rooms
    assert {b if a == CORE else a for a, b in _kind(g, "core")} == core_rooms
    node = g.nodes["B01#01"]
    assert node["spec_id"] == "B01" and node["zone"] == "ADMINISTRATIVE"
    assert node["needs_facade"] is True and node["area_m2"] == 12.0
    # The test rulebook has no pair with p >= 0.6: no PREFERRED edge.
    assert _kind(g, "preferred") == set()


def test_T01_preferred_edges(prep_25: PreparedInput, rulebook: Rulebook) -> None:
    data = rulebook.model_dump()
    data["adjacency"]["pairs"] = [
        {"a": "office", "b": "open_office", "p": 0.9},
        {"a": "meeting_room", "b": "office", "p": 0.7},
    ]
    rb = Rulebook.model_validate(data)
    g = build_graph(prep_25, rb)
    pref = _kind(g, "preferred")
    assert pref
    degree: dict[str, int] = {}
    for a, b in pref:
        assert g.nodes[a]["type"] != g.nodes[b]["type"]
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    assert max(degree.values()) <= 3
    assert all(g.edges[e]["weight"] in (0.9, 0.7) for e in pref)


def _k5_prepared(prep_8: PreparedInput) -> PreparedInput:
    ids = [f"R{i}" for i in range(1, 6)]
    rooms = tuple(
        RoomSpec(
            id=r,
            name="Bureau",
            type="office",
            target_area_m2=10.0,
            macro_zone="ADMINISTRATIVE",
            adjacent_to=tuple(x for x in ids if x != r),
        )
        for r in ids
    )
    program = Program(rooms=rooms)
    return prep_8.model_copy(update={"program": program, "instances": program.instances()})


def test_T02_planarity(prep_8: PreparedInput, prep_25: PreparedInput, rulebook: Rulebook) -> None:
    planar, conflicts = planarity(build_graph(_k5_prepared(prep_8), rulebook))
    assert planar is False
    assert len(conflicts) == 10
    assert conflicts == tuple(sorted(conflicts))
    assert set(conflicts) == {_pair(f"R{i}", f"R{j}") for i in range(1, 6) for j in range(i + 1, 6)}
    assert planarity(build_graph(prep_25, rulebook)) == (True, ())
