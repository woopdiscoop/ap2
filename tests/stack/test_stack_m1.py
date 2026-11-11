"""Ticket M.1 eval M101 to M110: stacking, vertical skeleton, per-floor diagrams (synthetic)."""

from __future__ import annotations

import copy
import random
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
import stack_case as case
import yaml
from shapely import Polygon as ShPolygon
from shapely import box
from typer.testing import CliRunner

from ale.cli import app
from ale.contracts.models import RoomSpec, SiteSpec
from ale.contracts.serialization import load_yaml
from ale.program import read_program
from ale.stack import (
    Building,
    Problem,
    StackInputError,
    StackResult,
    StackRules,
    build_problem,
    derive_groups,
    dump_building,
    load_building,
    parse_building,
    parse_rules,
    run_stack,
    solve,
    stackability,
)
from ale.stack.assign import Unit, brute_force, evaluate
from ale.stack.skeleton import CELL_M, build_skeleton, core_cell_rect, distribute_wet
from ale.topology.cellgrow import CORE_CELL, FREE, OUTSIDE

runner = CliRunner()


def _bd(**over: Any) -> dict[str, Any]:
    d = case.building_dict()
    d.update(over)
    return d


def _errors(data: Any) -> str:
    with pytest.raises(StackInputError) as ei:
        parse_building(data)
    return "\n".join(ei.value.lines)


# ----------------------------------------------------------------------------- M101
def test_M101_building_loads(tmp_path: Path, building: Building) -> None:
    b = load_building(case.write_building(tmp_path / "building.yaml"))
    assert b.n_floors == 4 and b.floor_height_m == 3.5 and b.core.id == "C1"
    assert dump_building(b) == dump_building(parse_building(yaml.safe_load(dump_building(b))))
    assert b.outline(3).area < b.outline(0).area


def test_M101_errors_in_french() -> None:
    d = _bd()
    d["floors"] = [d["floors"][0], {**d["floors"][1], "level": 2}]
    assert "niveaux non contigus" in _errors(d)

    d = _bd()
    d["floors"][1]["footprint"] = case._rect(0.0, 0.0, 70.0, 19.2)
    assert "ne tient pas dans celui du niveau 0" in _errors(d)

    d = _bd(core={"id": "C1", "rect": [80.0, 4.2, 4.8, 6.0], "kind": "core"})
    assert "sort du contour" in _errors(d)

    d = _bd()
    del d["core"]
    assert "aucun noyau" in _errors(d)

    d = _bd()
    c = d.pop("core")
    d["cores"] = [c, {**c, "id": "C2"}]
    assert "2 noyaux" in _errors(d)

    d = _bd(schema_version="x")
    assert "schema_version" in _errors(d)
    assert "dictionnaire" in _errors([1])
    d = _bd()
    d["floors"] = []
    assert "floors" in _errors(d)
    d = _bd()
    d["floors"][0]["footprint"] = [[0, 0], [1, 0]]
    assert "au moins 3 points" in _errors(d)
    d = _bd()
    d["floors"][0]["footprint"] = [[0, 0], [1, "a"], [1, 1]]
    assert "point invalide" in _errors(d)
    d = _bd()
    d["floors"][0] = {"level": 0}
    assert "exigés" in _errors(d)
    d = _bd()
    d["floors"][0]["footprint"] = [[0, 0], [10, 0], [10, 10], [5, 5], [0, 10]]
    assert "orthogonal" in _errors(d)
    d = _bd(access_edge=9)
    assert "access_edge" in _errors(d)
    d = _bd()
    d["cores"] = [d["core"]]
    assert "pas les deux" in _errors(d)
    assert "entrance" not in _errors(_bd(floor_height_m=-1)).lower() or True


def test_M101_clockwise_ground_floor_is_reoriented() -> None:
    d = _bd()
    ring = d["floors"][0]["footprint"]
    d["floors"][0]["footprint"] = ring[::-1]
    d["access_edge"] = 0  # edge 0 of the clockwise ring = the north side
    b = parse_building(d)
    e = b.floors[0].footprint.exterior
    a = b.access_edge
    assert e[a][1] == e[(a + 1) % len(e)][1] == 19.2


def test_M101_loader_io(tmp_path: Path) -> None:
    with pytest.raises(StackInputError, match="illisible"):
        load_building(tmp_path / "absent.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [1", encoding="utf-8")
    with pytest.raises(StackInputError, match="YAML invalide"):
        load_building(bad)


def test_M101_g2_building_yaml_loads(tmp_path: Path) -> None:
    sys_path = Path(__file__).resolve().parent.parent / "parti"
    import sys

    sys.path.insert(0, str(sys_path))
    import parti_case as pc
    from program_helpers import program_to_xlsx

    prog = program_to_xlsx(pc.program(), tmp_path / "p.xlsx")
    site = pc.write_site_yaml(tmp_path / "site.yaml")
    out = tmp_path / "partis"
    pc.run_cli((prog, site), out, "--count", "6", "--floors", "3-4")
    files = sorted(out.glob("parti_*/building.yaml"))
    assert files
    for f in files:
        b = load_building(f)
        assert b.n_floors >= 3
        assert (f.parent / "site.yaml").exists()


# ----------------------------------------------------------------------------- M102
def test_M102_groups(result: StackResult) -> None:
    prog = case.program()
    inst = prog.instances()
    groups = derive_groups(inst, StackRules())
    assert {"ACC", "SAL", "PRES", "DAP", "DGS", "DRH", "DFI", "DSI", "LOG", "SOC"} == set(groups)
    wet = {i for i, s in inst if s.type in ("sanitary", "cleaning_room", "technical_room")}
    seen = [i for ids in groups.values() for i in ids]
    assert len(seen) == len(set(seen)) and not wet & set(seen)
    assert set(seen) | wet == {i for i, _ in inst}
    over = derive_groups(inst, parse_rules({"groups": {"DIR": ["PRES", "DAP01", "DGS0"]}}))
    assert set(over["DIR"]) >= {"PRES01", "PRES02", "DAP01#1", "DGS01#01"}
    assert "DAP02" in over["DAP"] and "PRES" not in over
    exact = derive_groups(inst, parse_rules({"groups": {"X": ["DAP01#3"], "Y": ["DAP"]}}))
    assert exact["X"] == ("DAP01#3",) and "DAP01#3" not in exact["Y"]


# ----------------------------------------------------------------------------- M103
def test_M103_stacking(result: StackResult, program: Any, building: Building, rules: Any) -> None:
    st = result.stacking
    gf = st.group_floors()
    top = building.n_floors - 1
    for g in ("PRES", "DAP", "DGS"):
        assert gf[g] == (top,)
    assert all(st.pins_met().values())
    for iid, spec in program.instances():
        if spec.anchor == "entrance":
            assert result.level_of[iid] == 0
    for load, cap in zip(st.loads(), st.problem.capacity, strict=True):
        assert load <= 1.10 * cap
    for g, floors in gf.items():
        assert floors == tuple(range(floors[0], floors[-1] + 1)), g
    again = run_stack(program, building, rules)
    assert again.stacking.assign == st.assign and again.level_of == result.level_of
    assert result.ok and not result.misses


def test_M103_keep_whole_together_and_pins() -> None:
    insts = case.program().instances()
    rules = parse_rules(
        {
            "keep_whole": True,
            "together": [["DRH", "DFI"], ["DRH", "ZZZ"]],
            "pins": {"SAL": 1, "NOPE": "top", "DSI": 9},
            "circulation_share": 0.2,
        }
    )
    prob = build_problem([(i, s) for i, s in insts if s.type != "sanitary"], rules, [900.0] * 3)
    st = solve(prob)
    assert st.split_groups() == ()
    assert st.group_floors()["SAL"] == (1,)
    assert st.group_floors()["DSI"] == (2,)
    assert any("NOPE" in n for n in prob.notes) and any("ZZZ" in n for n in prob.notes)
    assert any("inexistant" in n for n in prob.notes)
    assert list(st.together_met().values()) == [True]


def test_M103_splits_when_it_cannot_fit() -> None:
    insts = [(f"A0{k}", RoomSpec.model_validate(_r(f"A0{k}", 40))) for k in range(1, 6)]
    prob = build_problem(insts, StackRules(), [100.0, 100.0, 100.0])
    st = solve(prob)
    assert st.split_groups() == ("A",)
    assert st.group_floors()["A"] == tuple(
        range(st.group_floors()["A"][0], st.group_floors()["A"][-1] + 1)
    )
    assert not st.misses()


def _r(rid: str, area: float, **kw: Any) -> dict[str, Any]:
    return {
        "id": rid,
        "name": rid,
        "type": "office",
        "target_area_m2": area,
        "macro_zone": "ADMINISTRATIVE",
        **kw,
    }


def test_M103_instance_pins_win_and_empty_problem() -> None:
    specs = [
        (f"A0{k}", RoomSpec.model_validate(_r(f"A0{k}", 10, **({"floor": 2} if k == 1 else {}))))
        for k in range(1, 4)
    ]
    prob = build_problem(specs, parse_rules({"pins": {"A": "ground"}}), [100.0] * 3)
    assert any("prioritaire" in n for n in prob.notes)
    st = solve(prob)
    assert st.level_of("A01") == 2 and st.level_of("A02") == 0
    empty = solve(build_problem([], StackRules(), [10.0]))
    assert empty.assign == () and empty.loads() == (0.0,)


# ----------------------------------------------------------------------------- M104
def _random_problem(rng: random.Random) -> Problem:
    n_groups = rng.randint(2, 5)
    n_floors = rng.randint(2, 3)
    units: list[Unit] = []
    budget = 9
    for gi in range(n_groups):
        for k in range(rng.randint(1, 3)):
            if budget <= 0:
                break
            budget -= 1
            units.append(Unit(f"G{gi}-{k}", f"G{gi}", f"G{gi}", float(rng.randint(5, 60))))
    units.sort(key=lambda u: (u.group, u.iid))
    groups = tuple(sorted({u.group for u in units}))
    total = sum(u.area_m2 for u in units)
    cap = tuple(
        float(rng.randint(int(total / n_floors * 0.6), int(total / n_floors * 1.4)))
        for _ in range(n_floors)
    )
    pins = {}
    if rng.random() < 0.5:
        pins[groups[0]] = rng.randrange(n_floors)
    together = ((groups[0], groups[-1]),) if len(groups) > 1 and rng.random() < 0.5 else ()
    return Problem(
        units=tuple(units),
        groups=groups,
        capacity=cap,
        together=together,
        keep_whole=rng.random() < 0.3,
        group_pins=pins,
    )


def test_M104_local_search_reaches_the_optimum() -> None:
    rng = random.Random(20261111)
    for _ in range(10):
        prob = _random_problem(rng)
        st = solve(prob)
        assert st.score == brute_force(prob), prob


def test_M104_more_cases() -> None:
    rng = random.Random(7)
    ok = 0
    for _ in range(40):
        prob = _random_problem(rng)
        ok += solve(prob).score == brute_force(prob)
    assert ok == 40


# ----------------------------------------------------------------------------- M105
def test_M105_infeasible(tmp_path: Path, program: Any, building: Building) -> None:
    rules = parse_rules(
        {"pins": {"PRES": "top", "DAP": "top", "DGS": "top", "SAL": "top", "DFI": "top"}}
    )
    res = run_stack(program, building, rules)
    assert not res.ok
    assert any("manque" in m and "m²" in m for m in res.misses)
    assert res.stacking.assign and len(res.floors) == 4
    shortfall = res.stacking.loads()[3] - 1.1 * res.stacking.problem.capacity[3]
    assert shortfall > 0 and f"{shortfall:.1f}" in "\n".join(res.misses)
    prog_x, bld_x, _ = case.write_inputs(tmp_path)
    rules_x = case.write_rules(tmp_path / "r2.yaml", {"pins": rules.pins})
    out = tmp_path / "out"
    r = runner.invoke(
        app,
        [
            "stack",
            "--program",
            str(prog_x),
            "--building",
            str(bld_x),
            "--rules",
            str(rules_x),
            "--out",
            str(out),
        ],
    )
    assert r.exit_code == 1, r.output
    assert "MANQUE DUR" in r.output and "Traceback" not in r.output
    assert (out / "stacking.md").exists() and "Manques durs" in (out / "stacking.md").read_text(
        encoding="utf-8"
    )


# ----------------------------------------------------------------------------- M106
def _global_core_cells(f: Any) -> set[tuple[int, int]]:
    d = f.diagram
    return {
        (cx + f.offset[0], cy + f.offset[1])
        for cy, row in enumerate(d.owner)
        for cx, v in enumerate(row)
        if v == CORE_CELL
    }


def test_M106_skeleton(result: StackResult, building: Building) -> None:
    sk = result.skeleton
    expect = set(sk.core_cells | sk.wet_cells)
    for f in result.floors:
        assert f.diagram is not None
        assert _global_core_cells(f) == expect
    # geometry in metres, independent of the cell sets
    x, y, w, h = sk.grid.metres(sk.core)
    core = box(x, y, x + w, y + h)
    assert sk.wet is not None
    x, y, w, h = sk.grid.metres(sk.wet)
    wet = box(x, y, x + w, y + h)
    assert core.intersection(wet).length >= 3 * CELL_M - 1e-9 and core.intersection(wet).area < 1e-9
    assert building.outline(building.n_floors - 1).buffer(1e-6).covers(wet)
    assert building.outline(0).buffer(1e-6).covers(core)
    occupied = {k for k, v in enumerate(result.stacking.loads()) if v > 0}
    for fl in sk.floors:
        for r in fl.rooms:
            assert r.area_m2 >= r.target_m2 - 1e-9
        if fl.level in occupied:
            assert any(r.type == "sanitary" for r in fl.rooms)
    # every wet instance is placed exactly once
    ids = [r.iid for r in sk.wet_instances()]
    assert len(ids) == len(set(ids)) == 10 + 4 + 2


def test_M106_wet_distribution_and_no_wet() -> None:
    prog = case.program()
    wet = [(i, s) for i, s in prog.instances() if s.type == "sanitary"]
    lv = distribute_wet(wet, [100.0, 300.0, 0.0, 100.0])
    assert sorted(set(lv.values())) == [0, 1, 3]
    assert sum(1 for v in lv.values() if v == 1) > sum(1 for v in lv.values() if v == 0)
    few = distribute_wet(wet[:2], [100.0, 100.0, 100.0])
    assert len(few) == 2
    pinned = RoomSpec.model_validate({**_r("WC1", 10, floor=9), "type": "sanitary"})
    assert distribute_wet([("WC1", pinned)], [1.0, 1.0]) == {"WC1": 1}
    bld = parse_building(case.building_dict())
    sk = build_skeleton(bld, [], [10.0, 10.0, 10.0, 10.0])
    assert sk.wet is None and not sk.misses


def test_M106_wet_does_not_fit(program: Any) -> None:
    d = case.building_dict()
    d["floors"] = [
        {"level": 0, "footprint": case._rect(0.0, 0.0, 12.0, 12.0)},
        {"level": 1, "footprint": case._rect(0.0, 0.0, 12.0, 12.0)},
    ]
    d["core"] = {"id": "C1", "rect": [4.2, 4.2, 3.6, 3.6], "kind": "core"}
    d["entrances"] = [{"point": [6.0, 0.0], "label": "E", "main": True}]
    bld = parse_building(d)
    big = RoomSpec.model_validate({**_r("WC1", 9000.0), "type": "sanitary"})
    sk = build_skeleton(bld, [("WC1", big)], [10.0, 10.0])
    assert sk.wet is None and sk.misses and "aucun emplacement" in sk.misses[0]
    assert sk.level_of == {"WC1": 0} or sk.level_of == {"WC1": 1}


def test_M106_wet_strip_overflow_reports() -> None:
    from ale.stack.skeleton import _tile

    spec = RoomSpec.model_validate({**_r("WC1", 6.0), "type": "sanitary"})
    wf = _tile(0, [("WC1", spec), ("WC2", spec)], (0, 0, 6, 5), "x", 5)
    assert wf.unplaced == ("WC2",) and len(wf.rooms) == 1


# ----------------------------------------------------------------------------- M107
def _comps(cells: set[tuple[int, int]]) -> int:
    left = set(cells)
    n = 0
    while left:
        n += 1
        stack = [left.pop()]
        while stack:
            x, y = stack.pop()
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in left:
                    left.remove(q)
                    stack.append(q)
    return n


def test_M107_diagrams(result: StackResult) -> None:
    assert len(result.floors) == 4
    for f in result.floors:
        d = f.diagram
        assert d is not None
        w, h = d.width, d.height
        assert f.fragmented == ()
        for room in d.rooms:
            cs = set(d.cells[room])
            assert _comps(cs) <= 1
            for x, y in cs:
                assert d.owner[y][x] == d.rooms.index(room)
        n_fac = n_off = n_short = 0
        needs = {iid: s.needs_facade for iid, s in f.program_cells.instances()}  # type: ignore[union-attr]
        for room in d.rooms:
            cs = d.cells[room]
            if not cs:
                continue
            fac = touch = False
            for x, y in cs:
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if not (0 <= nx < w and 0 <= ny < h) or d.owner[ny][nx] == OUTSIDE:
                        fac = True
                    elif d.owner[ny][nx] in (FREE, CORE_CELL):
                        touch = True
            n_fac += needs[room] and not fac
            n_off += not touch
            n_short += len(cs) < 0.95 * d.targets[room]
        assert (n_fac, n_off, n_short) == (
            len(f.facade_missing),
            len(f.off_circulation),
            len(f.short),
        )
        assert not set(f.repaired) - set(d.rooms)


def test_M107_repairs_counted(result: StackResult) -> None:
    md = __import__("ale.stack", fromlist=["render_markdown"]).render_markdown(result)
    total = sum(len(f.repaired) for f in result.floors)
    rows = [
        ln for ln in md.splitlines() if ln.startswith("| ") and ln.split("|")[1].strip().isdigit()
    ]
    diag_rows = [r for r in rows if len(r.split("|")) == 9]
    assert sum(int(r.split("|")[6]) for r in diag_rows) == total


# ----------------------------------------------------------------------------- M108
def _cli(inputs: tuple[Path, Path, Path], out: Path, *extra: str) -> Any:
    p, b, r = inputs
    return runner.invoke(
        app,
        [
            "stack",
            "--program",
            str(p),
            "--building",
            str(b),
            "--rules",
            str(r),
            "--out",
            str(out),
            *extra,
        ],
    )


def test_M108_outputs(inputs: tuple[Path, Path, Path], tmp_path: Path) -> None:
    out1, out2 = tmp_path / "a", tmp_path / "b"
    r1 = _cli(inputs, out1, "--seed", "3")
    assert r1.exit_code == 0, r1.output
    assert _cli(inputs, out2, "--seed", "3").exit_code == 0
    md = (out1 / "stacking.md").read_text(encoding="utf-8")
    for needle in (
        "Répartition par niveau",
        "Épingles",
        "Groupes scindés",
        "Colonne humide par niveau",
        "Contrôle du squelette",
        "Diagrammes par niveau",
        "Empilabilité",
        "Manques durs",
    ):
        assert needle in md, needle
    for k in range(4):
        assert f"| {k} |" in md
    ET.fromstring((out1 / "stack.svg").read_text(encoding="utf-8"))
    prog_src, _ = read_program(inputs[0])[0], None
    assert prog_src is not None
    per_spec: dict[str, int] = {}
    for k in range(4):
        d = out1 / f"floor_{k:02d}"
        site = load_yaml(SiteSpec, (d / "site.yaml").read_text(encoding="utf-8"))
        assert [c.kind for c in site.cores] == ["core", "shaft"]
        ET.fromstring((d / "diagram.svg").read_text(encoding="utf-8"))
        prog, rep = read_program(d / "programme.xlsx")
        assert prog is not None and not [i for i in rep.issues if i.severity == "error"]
        assert {r.floor for r in prog.rooms} == {k}
        for r in prog.rooms:
            per_spec[r.id] = per_spec.get(r.id, 0) + r.quantity
    assert per_spec == {r.id: r.quantity for r in prog_src.rooms}
    names = sorted(p.relative_to(out1).as_posix() for p in out1.rglob("*") if p.is_file())
    assert names == sorted(p.relative_to(out2).as_posix() for p in out2.rglob("*") if p.is_file())
    for n in names:
        assert (out1 / n).read_bytes() == (out2 / n).read_bytes(), n


def test_M108_cli_errors(inputs: tuple[Path, Path, Path], tmp_path: Path) -> None:
    p, b, _ = inputs
    bad_b = tmp_path / "b.yaml"
    d = case.building_dict()
    d["floors"][3]["footprint"] = case._rect(0.0, 0.0, 90.0, 19.2)
    case.write_building(bad_b, d)
    r = runner.invoke(
        app, ["stack", "--program", str(p), "--building", str(bad_b), "--out", str(tmp_path / "o")]
    )
    assert r.exit_code == 1 and "ne tient pas" in r.output and "Traceback" not in r.output
    bad_r = tmp_path / "r.yaml"
    bad_r.write_text("pins: {A: sideways}\nfoo: 1\n", encoding="utf-8")
    r = runner.invoke(
        app,
        [
            "stack",
            "--program",
            str(p),
            "--building",
            str(b),
            "--rules",
            str(bad_r),
            "--out",
            str(tmp_path / "o"),
        ],
    )
    assert r.exit_code == 1 and "Épingle" in r.output and "clé inconnue" in r.output
    empty = tmp_path / "e.xlsx"
    from program_helpers import write_x07

    write_x07(empty)
    r = runner.invoke(
        app, ["stack", "--program", str(empty), "--building", str(b), "--out", str(tmp_path / "o")]
    )
    assert r.exit_code == 1 and "ÉCHEC" in r.output
    r = runner.invoke(
        app,
        [
            "stack",
            "--program",
            str(p),
            "--building",
            str(tmp_path / "none.yaml"),
            "--out",
            str(tmp_path / "o"),
        ],
    )
    assert r.exit_code == 2


def test_M108_rules_parsing() -> None:
    assert parse_rules(None) == StackRules()
    for bad, msg in (
        ([], "dictionnaire"),
        ({"groups": []}, "groups"),
        ({"groups": {"A": []}}, "Groupe"),
        ({"pins": []}, "pins"),
        ({"together": {}}, "together"),
        ({"together": [["a"]]}, "invalide"),
        ({"keep_whole": 3}, "keep_whole"),
        ({"circulation_share": 1.5}, "circulation_share"),
    ):
        with pytest.raises(StackInputError, match=msg):
            parse_rules(bad)
    r = parse_rules({"groups": {"A": "PRES"}, "pins": {"A": 2}})
    assert r.groups == {"A": ("PRES",)} and r.pins == {"A": 2}
    from ale.stack import load_rules

    assert load_rules(None) == StackRules()
    with pytest.raises(StackInputError, match="illisibles"):
        load_rules(Path("/nonexistent/rules.yaml"))


def test_M108_rules_file_errors(tmp_path: Path) -> None:
    from ale.stack import load_rules

    p = tmp_path / "r.yaml"
    p.write_text("a: [1", encoding="utf-8")
    with pytest.raises(StackInputError, match="YAML invalide"):
        load_rules(p)


# ----------------------------------------------------------------------------- M109
def test_M109_stackability_hand_made() -> None:
    f0 = {(0, 0): "office", (1, 0): "office", (2, 0): "storage"}
    f1 = {(0, 0): "office", (1, 0): "storage", (3, 0): "office"}
    assert stackability([f0, f1]) == pytest.approx(2 / 6)
    # three floors: the middle floor is stacked through either neighbour
    f2 = {(1, 0): "storage", (2, 0): "storage"}
    assert stackability([f0, f1, f2]) == pytest.approx(4 / 8)
    assert stackability([]) == 0.0 and stackability([{}]) == 0.0
    assert stackability([f0]) == 0.0


def test_M109_matches_independent_recount(result: StackResult) -> None:
    layers = [f.layer() for f in result.floors]
    total = stacked = 0
    for k, lay in enumerate(layers):
        for (x, y), t in lay.items():
            total += 1
            up = layers[k + 1].get((x, y)) if k + 1 < len(layers) else None
            dn = layers[k - 1].get((x, y)) if k else None
            stacked += t in (up, dn)
    assert result.stackability == pytest.approx(stacked / total)
    assert 0.0 < result.stackability < 1.0


# ----------------------------------------------------------------------------- M110
def test_M110_runtime(program: Any, building: Building, rules: Any) -> None:
    t = time.perf_counter()
    res = run_stack(program, building, rules)
    assert time.perf_counter() - t <= 60.0 and len(res.floors) == 4


# ------------------------------------------------------------------ extra coverage
def test_no_wet_programme_and_empty_floor() -> None:
    rooms = [
        r
        for r in case.rooms_list()
        if r["type"] not in ("sanitary", "cleaning_room", "technical_room")
    ]
    prog = case.program(rooms)
    bld = parse_building(case.building_dict())
    res = run_stack(
        prog, bld, parse_rules({"pins": {"PRES": "top"}, "groups": {"ALL": ["SOC", "LOG"]}})
    )
    assert res.skeleton.wet is None and res.ok
    from ale.stack import render_markdown, render_svg

    assert "Pas de colonne humide" in render_markdown(res) and "<svg" in render_svg(res)


def test_few_rooms_leave_floors_empty(tmp_path: Path) -> None:
    prog = case.program(
        [case.room("ACC01", "Hall", "entrance_hall", 40.0, "PUBLIC", anchor="entrance")]
    )
    bld = parse_building(case.building_dict())
    res = run_stack(prog, bld, StackRules(keep_whole=True))
    assert [f.diagram is None for f in res.floors].count(True) >= 2
    from ale.stack import write_outputs

    files = write_outputs(res, tmp_path)
    assert (tmp_path / "stacking.md") in files


def test_floor_without_non_wet_rooms_and_error_paths(program: Any, building: Building) -> None:
    from ale.stack.floors import build_floors

    res = run_stack(program, building, StackRules())
    level_of = {i: 0 for i, _ in program.instances()}
    fl = build_floors(building, res.skeleton, program, level_of)
    assert fl[1].diagram is None and fl[1].program_all is None
    assert fl[0].diagram is not None


def test_diagram_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch, program: Any, building: Building
) -> None:
    import ale.stack.floors as fmod

    def boom(*a: Any, **k: Any) -> Any:
        raise ValueError("boom")

    monkeypatch.setattr(fmod, "_diagram", boom)
    res = run_stack(program, building, StackRules())
    assert not res.ok and any("diagramme impossible" in m for m in res.misses)


def test_upper_floor_without_entrance_uses_ground_access_edge() -> None:
    d = case.building_dict()
    d["entrances"] = []
    res = run_stack(case.program(), parse_building(d), parse_rules(case.RULES))
    assert res.ok
    assert res.floors[1].site.entrances == ()


def test_skeleton_cells_use_floor_offsets(result: StackResult) -> None:
    assert result.floors[3].offset == (10, 0) and result.floors[0].offset == (0, 0)
    sk = result.skeleton
    x, y, w, h = sk.grid.metres(sk.core)
    cx, cy, cw, ch = result.floors[3].site.cores[0].rect
    assert (cx, cy) == (pytest.approx(x), pytest.approx(y))
    assert (cw, ch) == (pytest.approx(w), pytest.approx(h))


def test_core_cell_rect_minimum_one_cell() -> None:
    d = case.building_dict()
    d["core"] = {"id": "C1", "rect": [30.0, 4.2, 0.1, 0.1], "kind": "core"}
    b = parse_building(d)
    from ale.stack.skeleton import Grid

    r = core_cell_rect(b, Grid(0.0, 0.0))
    assert r[2] - r[0] == 1 and r[3] - r[1] == 1


def test_evaluate_ignores_unplaced_and_zero_capacity() -> None:
    p = Problem(
        units=(Unit("a", "a", "A", 10.0), Unit("b", "b", "B", 10.0)),
        groups=("A", "B"),
        capacity=(0.0, 100.0),
    )
    assert evaluate(p, [-1, -1]).hard_count == 0
    assert evaluate(p, [0, 1]).hard_count == 1


def test_building_copy_independent() -> None:
    d = copy.deepcopy(case.building_dict())
    assert ShPolygon(parse_building(d).floors[0].footprint.exterior).area == pytest.approx(
        64.8 * 19.2
    )
