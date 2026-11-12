"""Tests M207, M209 and M210 (Ticket M.2): exact per-floor plans around the vertical skeleton.

Synthetic data only (``plans_case``: the M.1 programme in a 4-floor block with a central core).
"""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path
from typing import Any

import plans_case as pc
import pytest
import shapely
import stack_case as case
from typer.testing import CliRunner

from ale.cli import app
from ale.config import AleConfig
from ale.contracts.models import GridSpec, Layout, Program
from ale.geometry.checks import check_layout
from ale.program import prepare_input
from ale.program.models import PreparedInput
from ale.program.site import to_module_footprint
from ale.stack import StackResult, parse_building, parse_rules, run_stack
from ale.stack.plans import (
    FloorPlan,
    PlansResult,
    _fixed_rooms,
    _gap_rects,
    _plan_site,
    _vertical,
    build_skeleton_strict,
    plans_misses,
    render_plans_markdown,
    run_plans,
)
from ale.stack.skeleton import CELL_M, rect_cells

BUDGET = 10.0


def run_cli(args: list[str]) -> Any:
    return CliRunner().invoke(app, args)


def stack_args(d: Path, out: Path, *extra: str) -> list[str]:
    """``ale stack`` arguments for the inputs written by ``plans_case.write_inputs(d)``."""
    prog, bld, rules, _ = pc.write_inputs(d)
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


@pytest.fixture(scope="module")
def stacked() -> StackResult:
    return run_stack(
        pc.program(), parse_building(pc.building_dict()), parse_rules(pc.RULES), strict_solids=True
    )


@pytest.fixture(scope="module")
def cli_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, Path, float]:
    d = tmp_path_factory.mktemp("m2_cli")
    prog, bld, rules, rb = pc.write_inputs(d / "in")
    out = d / "out"
    t0 = time.monotonic()
    res = run_cli(
        [
            "stack",
            "--program",
            str(prog),
            "--building",
            str(bld),
            "--rules",
            str(rules),
            "--out",
            str(out),
            "--plans",
            "--rulebook",
            str(rb),
            "--budget",
            str(BUDGET),
        ]
    )
    return res, out, time.monotonic() - t0


def load_plan(out: Path, level: int) -> tuple[Layout, PreparedInput]:
    plan = out / f"floor_{level:02d}" / "plan"
    layout = Layout.model_validate_json((plan / "layout.json").read_bytes())
    rb = out.parent / "in" / "rulebook.yaml"
    prepared = prepare_input(plan / "programme.xlsx", plan / "site.yaml", rb, AleConfig())
    return layout, prepared


def absolute(layout: Layout, prepared: PreparedInput, r: Any) -> tuple[float, float, float, float]:
    m = layout.grid.module_mm / 1000
    ox, oy = prepared.footprint.origin_m
    return (
        round(ox + r.x * m, 3),
        round(oy + r.y * m, 3),
        round(r.w * m, 3),
        round(r.h * m, 3),
    )


# ------------------------------------------------------------------------------------ M207
def test_M207_one_plan_per_floor_passing_check_layout(cli_run: tuple[Any, Path, float]) -> None:
    res, out, _ = cli_run
    assert res.exit_code == 0, res.output
    for level in range(4):
        plan = out / f"floor_{level:02d}" / "plan"
        for name in ("layout.json", "layout.dxf", "preview.svg", "report.md"):
            assert (plan / name).is_file(), (level, name)
        layout, prepared = load_plan(out, level)
        assert check_layout(layout, prepared, AleConfig()) == ()
        assert layout.fixed, level
        assert layout.footprint.solids, level


def test_M207_core_and_wet_rooms_identical_on_every_floor(
    cli_run: tuple[Any, Path, float],
) -> None:
    _, out, _ = cli_run
    cores: set[tuple[float, float, float, float]] = set()
    solids: set[tuple[tuple[float, float], ...]] = set()
    stacks: set[tuple[float, float, float, float]] = set()
    for level in range(4):
        layout, prepared = load_plan(out, level)
        fixed = {p.instance_id: absolute(layout, prepared, p.rect) for p in layout.fixed}
        cores.add(fixed["C1"])
        wet = [r for i, r in fixed.items() if i != "C1" and not i.startswith("reserve_technique_g")]
        assert wet, level
        x0 = min(r[0] for r in wet)
        y0 = min(r[1] for r in wet)
        stacks.add((x0, y0, max(r[0] + r[2] for r in wet) - x0, max(r[1] + r[3] for r in wet) - y0))
        ox, oy = prepared.footprint.origin_m
        m = layout.grid.module_mm / 1000
        solids.add(
            tuple(
                (round(ox + x * m, 3), round(oy + y * m, 3)) for x, y in layout.footprint.solids[0]
            )
        )
        # wet rooms of the floor sit inside the stack, names from M.1's tiling
        assert any(i.startswith(("WC01", "NET01", "TEC01")) for i in fixed), level
    assert len(cores) == len(stacks) == len(solids) == 1


def test_M207_plans_md_is_french_with_the_vertical_check(cli_run: tuple[Any, Path, float]) -> None:
    res, out, _ = cli_run
    md = (out / "plans.md").read_text(encoding="utf-8")
    for needle in (
        "# Plans exacts par niveau",
        "Violations dures",
        "Façade manquante",
        "Surface cible",
        "## Contrôle vertical (dur)",
        "Noyau : identique sur 4 niveau(x)",
        "Colonne humide : identique sur 4 niveau(x)",
        "## Manques durs",
    ):
        assert needle in md, needle
    assert "plans : 4/4 niveaux" in res.output
    assert (out / "stacking.md").is_file()  # the M.1 outputs are still there


def test_M207_without_plans_nothing_is_added(tmp_path: Path) -> None:
    res = run_cli(stack_args(tmp_path / "in", tmp_path / "out"))
    assert res.exit_code in (0, 1), res.output
    assert not (tmp_path / "out" / "plans.md").exists()
    assert not (tmp_path / "out" / "floor_00" / "plan").exists()


def test_M207_plans_needs_a_rulebook(tmp_path: Path) -> None:
    res = run_cli(stack_args(tmp_path / "in", tmp_path / "out", "--plans"))
    assert res.exit_code == 2


# ----------------------------------------------------------------------- skeleton and fixed rooms
def test_strict_skeleton_keeps_the_stack_off_the_outline(stacked: StackResult) -> None:
    sk = stacked.skeleton
    assert sk.wet is not None and sk.wet_adjacent()
    cells = sk.wet_cells | sk.core_cells
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    gx1 = round(pc.W / CELL_M)
    gy1 = round(pc.H / CELL_M)
    assert min(xs) >= 1 and min(ys) >= 1 and max(xs) < gx1 - 1 and max(ys) < gy1 - 1
    grid = GridSpec(module_mm=AleConfig().grid.module_mm)
    for f in stacked.floors:
        fp = to_module_footprint(_plan_site(f, sk, stacked.building), grid, strict_cores=True)
        assert len(fp.polygon.solids) == 1


def test_plain_stacking_of_the_m1_bar_is_replanned_strictly(tmp_path: Path) -> None:
    """The M.1 skeleton puts the wet stack against the outline (a solid may not touch it)."""
    plain = run_stack(case.program(), parse_building(case.building_dict()), parse_rules(case.RULES))
    sk = plain.skeleton
    assert sk.wet is not None and min(c[1] for c in sk.wet_cells) == 0  # on the south wall
    strict = run_stack(
        case.program(),
        parse_building(case.building_dict()),
        parse_rules(case.RULES),
        strict_solids=True,
    )
    assert strict.skeleton.wet is not None
    assert min(c[1] for c in strict.skeleton.wet_cells) >= 1
    assert strict.skeleton.wet_adjacent()


def test_gap_rects_tile_the_solid(stacked: StackResult) -> None:
    sk = stacked.skeleton
    from ale.stack.plans import _bbox_cells

    gaps = _gap_rects(sk)
    box = set(rect_cells(_bbox_cells(sk)))
    got: set[tuple[int, int]] = set()
    for g in gaps:
        cells = set(rect_cells(g))
        assert not cells & got
        got |= cells
    assert got | sk.core_cells | sk.wet_cells == box
    assert not got & (sk.core_cells | sk.wet_cells)


def test_fixed_rooms_lie_in_the_solid_on_a_receding_floor() -> None:
    """The M.1 bar has a receding top floor (offset 10 cells): the fixed rooms follow it."""
    result = run_stack(
        case.program(),
        parse_building(case.building_dict()),
        parse_rules(case.RULES),
        strict_solids=True,
    )
    cfg = AleConfig()
    top = result.floors[3]
    assert top.offset == (10, 0)
    for f in (result.floors[0], top):
        site = _plan_site(f, result.skeleton, result.building)
        fp = to_module_footprint(site, GridSpec(module_mm=cfg.grid.module_mm), strict_cores=True)
        (ring,) = fp.polygon.solids
        solid = shapely.Polygon(ring)
        rooms = _fixed_rooms(f, result.skeleton, result.building, cfg.grid.module_mm)
        assert [p.instance_id for p in rooms] == sorted(p.instance_id for p in rooms)
        assert solid.covers(
            shapely.unary_union(
                [shapely.box(p.rect.x, p.rect.y, p.rect.x2(), p.rect.y2()) for p in rooms]
            )
        )
        assert (
            shapely.unary_union(
                [shapely.box(p.rect.x, p.rect.y, p.rect.x2(), p.rect.y2()) for p in rooms]
            ).area
            == solid.area
        )
    with pytest.raises(ValueError, match="trame"):
        _fixed_rooms(top, result.skeleton, result.building, 250)


# ------------------------------------------------------------------------------------ M209
def _oversized(program: Program) -> Program:
    return Program(
        rooms=tuple(r.model_copy(update={"quantity": r.quantity * 6}) for r in program.rooms)
    )


def test_M209_a_floor_that_cannot_be_generated_is_reported(
    stacked: StackResult, tmp_path: Path
) -> None:
    _, _, _, rb = pc.write_inputs(tmp_path / "in")
    f0, f1 = stacked.floors[0], stacked.floors[1]
    assert f1.program_cells is not None
    bad = dataclasses.replace(f1, program_cells=_oversized(f1.program_cells))
    partial = dataclasses.replace(stacked, floors=(f0, bad))
    plans, used = run_plans(partial, rb, tmp_path / "out", budget_s=BUDGET)
    assert used is partial
    ok, failed = plans.floors
    assert (
        ok.status == "ok" and ok.passes and (tmp_path / "out/floor_00/plan/layout.json").is_file()
    )
    assert failed.status == "failed" and "Programme trop grand" in failed.message
    assert not (tmp_path / "out/floor_01/plan/layout.json").exists()
    assert not plans.ok
    assert any("Niveau 1 : plan impossible" in m for m in plans.misses)
    assert any("Contrôle incomplet" in line for line in plans.vertical)
    md = (tmp_path / "out" / "plans.md").read_text(encoding="utf-8")
    assert "ÉCHEC" in md and "Niveau 1 : plan impossible" in md


def test_M209_exit_code_is_one_with_a_failed_floor(
    stacked: StackResult, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ale stack --plans`` exits 1 and still writes the outputs when a floor fails."""
    import ale.stack.plans as plans_mod

    failed = FloorPlan(1, "failed", "Programme trop grand")
    fake = PlansResult(
        floors=(failed,),
        vertical=("Contrôle incomplet : 1 niveau(x) sans plan sur 1.",),
        vertical_ok=False,
        misses=plans_misses((failed,), False),
    )
    monkeypatch.setattr(plans_mod, "run_plans", lambda *a, **k: (fake, a[0]))
    rb = tmp_path / "in" / "rulebook.yaml"
    res = run_cli(stack_args(tmp_path / "in", tmp_path / "out", "--plans", "--rulebook", str(rb)))
    assert res.exit_code == 1
    assert "MANQUE DUR : Niveau 1 : plan impossible" in res.output
    assert (tmp_path / "out" / "stacking.md").is_file()


def test_vertical_check_and_report_rendering() -> None:
    a = FloorPlan(
        0,
        "ok",
        core=(1.0, 1.0, 2.0, 2.0),
        stack=(3.0, 1.0, 4.0, 2.0),
        solids=((1.0, 1.0, 6.0, 2.0),),
    )
    b = dataclasses.replace(a, level=1, core=(1.0, 1.1, 2.0, 2.0))
    lines, ok = _vertical([a, b], 2)
    assert not ok and any("Noyau : DIFFÉRENT" in x for x in lines)
    lines, ok = _vertical([a, dataclasses.replace(a, level=1)], 2)
    assert ok and all("identique" in x for x in lines[:3])
    empty = FloorPlan(2, "empty", "aucune pièce")
    assert _vertical([a, empty], 1)[1]
    assert plans_misses([a, empty], True) == ()
    md = render_plans_markdown(
        PlansResult(floors=(a, empty), vertical=lines, vertical_ok=True, notes=("note",))
    )
    assert "vide : aucune pièce" in md and "- Remarque : note" in md and "Aucun." in md


def test_build_skeleton_strict_reports_a_wet_stack_that_does_not_fit() -> None:
    bd = pc.building_dict()
    # a top floor too small to hold the wet stack away from its outline
    bd["floors"][3]["footprint"] = pc._rect(11.4, 7.8, 18.6, 14.4)
    building = parse_building(bd)
    wet = [
        (iid, spec)
        for iid, spec in pc.program().instances()
        if spec.type in ("sanitary", "cleaning_room", "technical_room")
    ]
    sk = build_skeleton_strict(building, wet, [100.0] * 4)
    assert sk.wet is None and "Colonne humide : aucun emplacement" in sk.misses[0]
    none = build_skeleton_strict(building, [], [100.0] * 4)
    assert none.wet is None and not none.misses


# ------------------------------------------------------------------------------------ M210
def test_M210_five_seconds_per_floor_stays_within_a_minute(tmp_path: Path) -> None:
    rb = tmp_path / "in" / "rulebook.yaml"
    args = stack_args(tmp_path / "in", tmp_path / "out", "--plans", "--rulebook", str(rb))
    t0 = time.monotonic()
    res = run_cli([*args, "--budget", "5"])
    elapsed = time.monotonic() - t0
    assert elapsed <= 60.0, elapsed
    assert res.exit_code in (0, 1), res.output  # a floor may miss at 5 s: reported, not a crash
    assert (tmp_path / "out" / "plans.md").is_file()
    data = [
        json.loads((p / "plan" / "layout.json").read_text(encoding="utf-8"))
        for p in sorted((tmp_path / "out").glob("floor_*"))
        if (p / "plan" / "layout.json").is_file()
    ]
    assert all(d["fixed"] for d in data)
