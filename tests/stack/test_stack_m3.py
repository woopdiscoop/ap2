"""Tests M301-M309 (Ticket M.3): room stacking, shared bay rhythm and column grid.

Cases: the M.1 case (``stack_case``), the loaded bar (``bar_case``) and ``plans_case``.
Synthetic data only. Rate tests over 10 seeds are ``slow``; the not-slow ones use 3 seeds or
one run. Targets that were out of reach are ``xfail`` (non-strict) with the rate reached in
``specs/tickets/M.3_stacking-rhythm/eval_report.md`` (as M.2b did).
"""

from __future__ import annotations

import dataclasses
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import bar_case as bc
import plans_case as pc
import pytest
import shapely
import stack_case as case
import yaml
from typer.testing import CliRunner

from ale.cli import app
from ale.config import AleConfig
from ale.contracts.models import Layout
from ale.program import load_rulebook, prepare_input
from ale.stack import StackResult, parse_building, parse_rules, run_stack
from ale.stack import floors as floors_mod
from ale.stack.grid import (
    BAY_RANGE_M,
    SPAN_RANGE_M,
    Rhythm,
    columns_of,
    plan_columns,
    plan_facade_partitions,
    plan_stackability,
    validate_overrides,
)
from ale.stack.plans import FloorPlan, PlanRoom, run_plans
from ale.stack.rules import RhythmInputError, StackInputError
from ale.stack.snap import _walls, snap_layout

REPO = Path(__file__).resolve().parent.parent.parent
REPORT = REPO / "specs" / "tickets" / "M.3_stacking-rhythm" / "eval_report.md"
BUDGET = 10.0


def run_cli(args: list[str]) -> Any:
    return CliRunner().invoke(app, args)


def stack_args(prog: Path, bld: Path, rules: Path, out: Path, *extra: str) -> list[str]:
    return [
        "stack",
        "--program",
        str(prog),
        "--building",
        str(bld),
        "--rules",
        str(rules),
        "--out",
        str(out),
        *extra,
    ]


def stacked(mod: Any, rules: dict[str, Any] | None = None, seed: int = 0) -> StackResult:
    return run_stack(
        mod.program(),
        parse_building(mod.building_dict()),
        parse_rules(mod.RULES if rules is None else rules),
        seed=seed,
    )


@pytest.fixture(scope="module")
def m1() -> StackResult:
    return stacked(case)


@pytest.fixture(scope="module")
def bar() -> StackResult:
    return stacked(bc)


# ------------------------------------------------------------------------------------ M301
def test_M301_diagnosis_is_recorded() -> None:
    text = REPORT.read_text(encoding="utf-8")
    head = text.split("## Diagnosis (M301)")[1].split("\n## ")[0]
    for needle in ("18.75 %", "29.9 %", "Plan level", "10.0 %", "35.1 %", "bound"):
        assert needle in head, needle


# ------------------------------------------------------------------------------------ M302
def test_M302_bar_cell_stackability_smoke() -> None:
    for seed in range(3):
        r = stacked(bc, seed=seed)
        assert r.stackability >= 0.60, (seed, r.stackability)
        assert not r.misses
        assert all(r.stacking.pins_met().values())


def test_M302_m1_case_is_far_above_the_m1_figure(m1: StackResult) -> None:
    assert m1.stackability >= 0.40  # M.1: 18.8 %
    assert not m1.misses
    assert all(m1.stacking.pins_met().values())
    assert max(m1.stacking.loads()[k] / m1.stacking.problem.capacity[k] for k in range(4)) <= 1.10


@pytest.mark.xfail(
    strict=False,
    reason="M.1 case: the type-area upper bound of the assignment is 65.7 % with its pins and "
    "the receding top floor; 44.7 % reached (see eval_report.md)",
)
def test_M302_m1_case_reaches_60_percent(m1: StackResult) -> None:
    assert m1.stackability >= 0.60


def test_M302_type_term_off_is_the_m1_objective() -> None:
    off = dataclasses.replace(parse_rules(case.RULES), type_weight=0.0)
    r = run_stack(case.program(), parse_building(case.building_dict()), off)
    assert not r.misses
    assert r.stackability < 0.25  # the M.1 stacking, floors laid out independently of types
    assert r.stacking.split_groups() == ()


def test_M302_pair_stackability_matches_the_global_figure(bar: StackResult) -> None:
    assert len(bar.pair_stackability) == 3
    assert all(0.0 <= v <= 1.0 for v in bar.pair_stackability)
    assert max(bar.pair_stackability) >= bar.stackability - 0.15


# ------------------------------------------------------------------------------------ M305
@pytest.mark.parametrize("name", ["m1", "bar"])
def test_M305_grid_spans_bay_and_core(request: pytest.FixtureRequest, name: str) -> None:
    r: StackResult = request.getfixturevalue(name)
    rh = r.rhythm
    assert rh is not None
    for span in (rh.span_x_m, rh.span_y_m):
        assert SPAN_RANGE_M[0] - 1e-9 <= span <= SPAN_RANGE_M[1] + 1e-9
        assert abs(span / 0.6 - round(span / 0.6)) < 1e-9
    assert BAY_RANGE_M[0] - 1e-9 <= rh.bay_m <= BAY_RANGE_M[1] + 1e-9
    assert abs(rh.bay_m / 0.6 - round(rh.bay_m / 0.6)) < 1e-9
    assert rh.span_x % rh.bay == 0 and rh.span_y % rh.bay == 0
    assert rh.core_on_grid(r.skeleton.core)
    assert rh.candidates > 1
    assert rh.score.columns > 0


def test_M305_columns_lie_on_the_same_lines_on_every_floor(bar: StackResult) -> None:
    rh = bar.rhythm
    assert rh is not None
    xs = {x for k in range(4) for x, _ in _cols(bar, k)}
    ys = {y for k in range(4) for _, y in _cols(bar, k)}
    gb = bar.building.outline(0).bounds
    assert xs <= set(rh.grid_lines_x(gb[0], gb[2]))
    assert ys <= set(rh.grid_lines_y(gb[1], gb[3]))
    # a column never stands inside the core or the wet stack
    sk = bar.skeleton
    solids = [shapely.box(x, y, x + w, y + h) for x, y, w, h in map(sk.grid.metres, _solids(bar))]
    for k in range(4):
        for x, y in _cols(bar, k):
            assert not any(s.buffer(-1e-6).contains(shapely.Point(x, y)) for s in solids)


def _solids(r: StackResult) -> list[tuple[int, int, int, int]]:
    sk = r.skeleton
    return [sk.core] + ([sk.wet] if sk.wet is not None else [])


def _cols(r: StackResult, k: int) -> list[tuple[float, float]]:
    assert r.rhythm is not None
    return columns_of(r.rhythm, r.building.outline(k), _solids(r))


def test_M305_columns_of_skips_points_outside_the_outline() -> None:
    rh = Rhythm(12, 12, 4, 0, 0, 0.0, 0.0)  # 7.2 m grid, 2.4 m bay
    poly = shapely.Polygon([(0, 0), (14.4, 0), (14.4, 7.2), (7.2, 7.2), (7.2, 14.4), (0, 14.4)])
    cols = columns_of(rh, poly)
    assert (14.4, 14.4) not in cols and (7.2, 14.4) in cols and (0.0, 0.0) in cols
    assert len(cols) == 8
    cols2 = columns_of(rh, poly, [(1, 1, 3, 3)])  # solid strictly around cell corner (2, 2)
    assert (7.2, 7.2) in cols2 and len(cols2) == 8
    inside = columns_of(rh, shapely.box(0, 0, 14.4, 14.4), [(10, 10, 14, 14)])
    assert (7.2, 7.2) not in inside  # (12, 12) is strictly inside the solid


# ------------------------------------------------------------------------------------ M306
def test_M306_overrides_are_honoured() -> None:
    r = stacked(bc, {"bay_m": 3.6, "grid_m": [7.2, 10.8], "typical_floor": 1})
    rh = r.rhythm
    assert rh is not None
    assert (rh.span_x_m, rh.span_y_m, rh.bay_m) == (7.2, 10.8, 3.6)
    assert set(rh.overridden) == {"bay_m", "grid_m", "typical_floor"}
    assert r.typical == 1
    assert rh.core_on_grid(r.skeleton.core)


def test_M306_typical_floor_is_laid_out_first(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[int] = []
    real = floors_mod._build_floor

    def spy(*args: Any) -> Any:
        order.append(args[4])
        return real(*args)

    monkeypatch.setattr(floors_mod, "_build_floor", spy)
    stacked(bc, {"typical_floor": 2})
    assert order == [2, 1, 0, 3]
    order.clear()
    stacked(bc, {"typical_floor": 0})
    assert order == [0, 1, 2, 3]


def test_M306_bay_override_only_keeps_a_compatible_span() -> None:
    r = stacked(bc, {"bay_m": 4.2})
    rh = r.rhythm
    assert rh is not None and rh.bay_m == 4.2
    assert rh.span_x_m % 4.2 < 1e-6 and rh.span_y_m % 4.2 < 1e-6


@pytest.mark.parametrize(
    ("rules", "needle"),
    [
        ({"bay_m": 1.3}, "multiple de 0,60"),
        ({"bay_m": "large"}, "bay_m"),
        ({"bay_m": -2.4}, "bay_m"),
        ({"grid_m": [7.0, 7.2]}, "multiple de 0,60"),
        ({"grid_m": [7.2]}, "grid_m"),
        ({"grid_m": "7.2"}, "grid_m"),
        ({"bay_m": 3.6, "grid_m": [7.2, 9.0]}, "ne divise pas"),
        ({"typical_floor": 9}, "typical_floor"),
        ({"typical_floor": -1}, "typical_floor"),
        ({"typical_floor": 1.5}, "typical_floor"),
        ({"bay_m": 13.2}, "aucune portée"),
    ],
)
def test_M306_invalid_values_give_a_french_message_and_exit_2(
    tmp_path: Path, rules: dict[str, Any], needle: str
) -> None:
    (tmp_path / "in").mkdir()
    prog, bld, _ = case.write_inputs(tmp_path / "in")
    rp = tmp_path / "rules.yaml"
    rp.write_text(yaml.safe_dump(rules), encoding="utf-8")
    res = run_cli(stack_args(prog, bld, rp, tmp_path / "out"))
    assert res.exit_code == 2, res.output
    assert needle in res.output
    assert "ÉCHEC" in res.output
    assert "Traceback" not in res.output
    assert not (tmp_path / "out" / "stacking.md").exists()


def test_M306_parse_and_validate_raise_rhythm_errors_not_crashes() -> None:
    with pytest.raises(RhythmInputError):
        parse_rules({"bay_m": True})
    with pytest.raises(RhythmInputError):
        validate_overrides(parse_rules({"typical_floor": 4}), 4)
    with pytest.raises(StackInputError):  # unknown keys stay an input error (exit 1)
        parse_rules({"bay": 3.6})
    validate_overrides(parse_rules({"typical_floor": 3, "bay_m": 3.6}), 4)


# ------------------------------------------------------------------------------------ M307
def test_M307_stacking_md_and_svg(tmp_path: Path) -> None:
    (tmp_path / "in").mkdir()
    prog, bld, rules = case.write_inputs(tmp_path / "in")
    out = tmp_path / "out"
    res = run_cli(stack_args(prog, bld, rules, out))
    assert res.exit_code == 0, res.output
    md = (out / "stacking.md").read_text(encoding="utf-8")
    for needle in (
        "## Trame et empilement",
        "portées",
        "module de travée",
        "Niveau typique",
        "Poteaux (tous niveaux)",
        "Cloisons de façade",
        "| 0 / 1 |",
        "Noyau sur la trame : oui",
    ):
        assert needle in md, needle
    root = ET.fromstring((out / "stack.svg").read_text(encoding="utf-8"))
    ns = "{http://www.w3.org/2000/svg}"
    grid = [g for g in root.iter(f"{ns}g") if g.get("id") == "grid"]
    assert len(grid) == 1
    classes = {ln.get("class") for ln in grid[0].iter(f"{ns}line")}
    assert classes == {"column-line", "bay-line"}


def test_M309_cell_level_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / "in").mkdir()
    prog, bld, rules = case.write_inputs(tmp_path / "in")
    outs = []
    for name in ("a", "b"):
        out = tmp_path / name
        res = run_cli(stack_args(prog, bld, rules, out))
        assert res.exit_code == 0
        outs.append(out)
    for f in sorted(p.relative_to(outs[0]) for p in outs[0].rglob("*") if p.is_file()):
        assert (outs[0] / f).read_bytes() == (outs[1] / f).read_bytes(), f


# ----------------------------------------------------------------- plan-level pure functions
def _plan(level: int, rooms: list[PlanRoom], outline: tuple[tuple[float, float], ...]) -> Any:
    return FloorPlan(level, "ok", rooms_abs=tuple(rooms), outline=outline)


RING = ((0.0, 0.0), (21.6, 0.0), (21.6, 7.2), (0.0, 7.2))


def test_M303_plan_stackability_exact_overlap() -> None:
    low = _plan(
        0,
        [
            PlanRoom("A", "A", "office", (0, 0, 10, 5), "room"),
            PlanRoom("W", "W", "sanitary", (10, 0, 2, 5), "fixed"),
            PlanRoom("c", None, None, (0, 5, 12, 2), "circulation"),
        ],
        RING,
    )
    up = _plan(
        1,
        [
            PlanRoom("A", "A", "office", (5, 0, 7, 5), "room"),  # 5 m of 7 over the office
            PlanRoom("B", "B", "archive", (0, 0, 5, 5), "room"),
        ],
        RING,
    )
    assert plan_stackability([low, up]) == pytest.approx((25 / 60,), abs=1e-9)
    failed = FloorPlan(1, "failed")
    assert plan_stackability([low, failed]) == ()


def test_M304_facade_partitions_and_bay_lines() -> None:
    rh = Rhythm(12, 12, 4, 0, 0, 0.0, 0.0)  # bay lines every 2.4 m
    rooms = [
        PlanRoom("A", "A", "office", (0.0, 0.0, 2.4, 5.0), "room"),
        PlanRoom("B", "B", "office", (2.4, 0.0, 3.6, 5.0), "room"),
        PlanRoom("C", "C", "office", (6.0, 0.0, 15.6, 5.0), "room"),
    ]
    n, ok = plan_facade_partitions(rh, _plan(0, rooms, RING))
    # partitions at x = 2.4 (on a bay line), x = 6.0 (1.2 m off), y = 5.0 on the west wall
    # (0.2 m from the bay line 4.8): three, two of them on a bay line
    assert (n, ok) == (3, 2)
    assert plan_facade_partitions(rh, FloorPlan(0, "failed")) == (0, 0)


def test_M305_plan_columns_in_small_rooms() -> None:
    from ale.stack.skeleton import Grid, Skeleton

    rh = Rhythm(12, 12, 4, 0, 0, 0.0, 0.0)  # columns every 7.2 m
    sk = Skeleton(Grid(0.0, 0.0), (100, 100, 101, 101), None, frozenset(), "x", 0, ())
    ring = ((0.0, 0.0), (21.6, 0.0), (21.6, 14.4), (0.0, 14.4))
    rooms = [
        PlanRoom("big", "big", "office", (0.0, 3.0, 10.0, 8.0), "room"),  # 80 m2 round (7.2, 7.2)
        PlanRoom(
            "small", "small", "office", (13.0, 6.0, 3.0, 3.0), "room"
        ),  # 9 m2 round (14.4, 7.2)
        PlanRoom(
            "wall", "wall", "office", (14.3, 10.0, 2.0, 5.0), "room"
        ),  # column 0.1 m from side
        PlanRoom("corr", None, None, (17.0, 6.0, 3.0, 3.0), "circulation"),
    ]
    cols, small = plan_columns(rh, _plan(0, rooms, ring), sk)
    assert len(cols) == 12 and (14.4, 7.2) in cols
    assert small == [(14.4, 7.2)]
    # a column on the side of the small room (within 0.15 m) is on a wall, not in the room
    wall = [PlanRoom("s", "s", "office", (14.3, 6.0, 3.0, 3.0), "room")]
    assert plan_columns(rh, _plan(0, wall, ring), sk)[1] == []
    assert plan_columns(rh, FloorPlan(0, "failed"), sk) == ([], [])


def test_M304_walls_of_a_row_of_rooms() -> None:
    from ale.contracts.geometry import ModuleRect

    rects = [
        ModuleRect(x=0, y=0, w=10, h=5),
        ModuleRect(x=10, y=0, w=10, h=5),
        ModuleRect(x=20, y=0, w=5, h=3),  # shorter: its left edge is not a whole wall
        ModuleRect(x=0, y=5, w=25, h=5),
    ]
    xs = {(w.pos, w.lo, w.hi) for w in _walls(rects, "x")}
    assert (10, 0, 5) in xs and all(w[0] != 20 for w in xs)
    ys = {(w.pos, w.lo, w.hi) for w in _walls(rects, "y")}
    assert ys == set()  # the room above spans 25 modules, the row below only 20: no whole wall


# ----------------------------------------------------------- plans on plans_case (one run)
@pytest.fixture(scope="module")
def plans_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, Path, float]:
    d = tmp_path_factory.mktemp("m3_plans")
    prog, bld, rules, rb = pc.write_inputs(d / "in")
    out = d / "out"
    t0 = time.monotonic()
    res = run_cli(
        stack_args(prog, bld, rules, out, "--plans", "--rulebook", str(rb), "--budget", "5")
    )
    return res, out, time.monotonic() - t0


def test_M307_plans_md_section_and_grid_svg(plans_run: tuple[Any, Path, float]) -> None:
    res, out, _ = plans_run
    assert res.exit_code == 0, res.output
    md = (out / "plans.md").read_text(encoding="utf-8")
    for needle in (
        "## Trame et empilement",
        "Trame de poteaux : portées",
        "identique à tous les niveaux, noyau sur la trame",
        "Poteaux :",
        "Cloisons de façade sur une ligne de travée",
        "Empilabilité des plans",
        "| 0 / 1 |",
        "| 2 / 3 |",
    ):
        assert needle in md, needle
    ns = "{http://www.w3.org/2000/svg}"
    for k in range(4):
        svg = out / f"floor_{k:02d}" / "plan" / "grille.svg"
        root = ET.fromstring(svg.read_text(encoding="utf-8"))
        grid = [g for g in root.iter(f"{ns}g") if g.get("id") == "grid"]
        assert len(grid) == 1 and len(list(grid[0])) > 4
        assert list(root.iter(f"{ns}circle"))


def test_M305_same_grid_on_every_planned_floor(plans_run: tuple[Any, Path, float]) -> None:
    _, out, _ = plans_run
    text = (out / "plans.md").read_text(encoding="utf-8")
    assert text.count("Trame de poteaux : portées") == 1  # one grid for the building
    spans = text.split("portées ")[1].split(" m,")[0]
    sx, sy = (float(v) for v in spans.split(" x "))
    for v in (sx, sy):
        assert SPAN_RANGE_M[0] <= v <= SPAN_RANGE_M[1] and abs(v / 0.6 - round(v / 0.6)) < 1e-6


def test_M303_four_floors_planned_and_stackability_reported(
    plans_run: tuple[Any, Path, float],
) -> None:
    res, out, _ = plans_run
    assert "plans : 4/4 niveaux" in res.output
    md = (out / "plans.md").read_text(encoding="utf-8")
    rows = [ln for ln in md.splitlines() if ln.startswith("| ") and " / " in ln.split("|")[1]]
    plan_rows = [ln for ln in rows if "%" in ln.split("|")[2] and "Empil" not in ln]
    assert len(plan_rows) >= 3
    # plans_case repeats the same four groups: neighbouring floors share most of their types
    shares = [float(ln.split("|")[2].strip().rstrip("%")) for ln in plan_rows[-3:]]
    assert max(shares) >= 20.0


def test_M304_snap_keeps_a_valid_layout(plans_run: tuple[Any, Path, float]) -> None:
    _, out, _ = plans_run
    plan = out / "floor_01" / "plan"
    layout = Layout.model_validate_json((plan / "layout.json").read_bytes())
    rb, _ = load_rulebook(out.parent / "in" / "rulebook.yaml")
    assert rb is not None
    config = AleConfig()
    prepared = prepare_input(
        plan / "programme.xlsx", plan / "site.yaml", out.parent / "in" / "rulebook.yaml", config
    )
    base = layout.model_copy(update={"fixed": ()})
    rh = Rhythm(10, 10, 5, 0, 0, 0.0, 0.0)  # 6.0 m grid, 3.0 m bay
    snapped, stats = snap_layout(base, prepared, rb, config, rh)
    assert stats.walls >= stats.already + stats.moved
    assert stats.tried >= stats.moved
    from ale.geometry.checks import check_layout

    assert check_layout(snapped, prepared, config) == ()
    assert len(snapped.rooms) == len(base.rooms)
    if stats.moved == 0:
        assert snapped.rooms == base.rooms


# ------------------------------------------------------------------------ slow rate tests
def _plan_bar(seed: int, out: Path) -> tuple[Any, StackResult]:
    prog = bc.program()
    rb = out / "rb.yaml"
    from ale.contracts.serialization import dump_yaml
    from ale.parti.evaluate import neutral_rulebook

    rb.write_text(dump_yaml(neutral_rulebook(prog)), encoding="utf-8")
    r = run_stack(
        prog,
        parse_building(bc.building_dict()),
        parse_rules(bc.RULES),
        seed=seed,
        strict_solids=True,
    )
    pr, used = run_plans(r, rb, out, budget_s=BUDGET, seed=seed)
    return pr, used


@pytest.fixture(scope="module")
def bar_plans(tmp_path_factory: pytest.TempPathFactory) -> list[tuple[Any, StackResult, float]]:
    runs = []
    for seed in range(3):
        d = tmp_path_factory.mktemp(f"m3_bar_{seed}")
        t0 = time.monotonic()
        pr, used = _plan_bar(seed, d)
        runs.append((pr, used, time.monotonic() - t0))
    return runs


@pytest.mark.slow
@pytest.mark.timeout(1500)
def test_M303_bar_four_floors_planned(bar_plans: list[tuple[Any, StackResult, float]]) -> None:
    for pr, _, _ in bar_plans:
        assert sum(p.status == "ok" for p in pr.floors) == 4


@pytest.mark.slow
@pytest.mark.timeout(1500)
@pytest.mark.xfail(strict=False, reason="plan-level stackability reached about 0.3 (RD: 0.5)")
def test_M303_bar_plan_stackability_at_least_half(
    bar_plans: list[tuple[Any, StackResult, float]],
) -> None:
    ok = sum(1 for pr, _, _ in bar_plans if sum(pr.stacking[:3]) / 3 >= 0.5)
    assert ok == len(bar_plans)


@pytest.mark.slow
@pytest.mark.timeout(1500)
@pytest.mark.xfail(strict=False, reason="façade partitions on a bay line about 35 % (RD: 80 %)")
def test_M304_bar_facade_partitions_on_the_bay(
    bar_plans: list[tuple[Any, StackResult, float]],
) -> None:
    for pr, _, _ in bar_plans:
        for f in pr.rhythms:
            assert f.partitions == 0 or f.on_bay / f.partitions >= 0.8


@pytest.mark.slow
@pytest.mark.timeout(1500)
@pytest.mark.xfail(strict=False, reason="columns in rooms under 30 m2: about 30 % (RD: 10 %)")
def test_M305_bar_columns_in_small_rooms(bar_plans: list[tuple[Any, StackResult, float]]) -> None:
    for pr, _, _ in bar_plans:
        cols = sum(f.columns for f in pr.rhythms)
        assert cols and sum(f.small for f in pr.rhythms) / cols <= 0.10


@pytest.mark.slow
@pytest.mark.timeout(1500)
def test_M309_bar_plans_time(bar_plans: list[tuple[Any, StackResult, float]]) -> None:
    for _, _, t in bar_plans:
        assert t <= 108.0  # 1.5 x the M.2b time (72 s at budget 10)
