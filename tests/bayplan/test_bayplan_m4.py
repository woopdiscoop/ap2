"""Tests M400-M412 (Ticket M.4): bay-first planning of office bars, one floor at a time.

Cases A, B, C go through ``run_stack`` + ``run_plans(planner="bay")`` (session fixture ``runs``);
E and F (a clean section, the kernel called directly) are built in ``bay_cases``. The shapes of
RD 4.5 are recomputed by ``bay_cases.catalogue`` (the tests never import the planner's own).
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import bay_cases as bc
import pytest
from bay_cases import CaseRun

from ale.bayplan import NotEligible, choose_facade_depth, plan_bar
from ale.contracts.geometry import ModuleRect
from ale.contracts.models import Quantiles, RoomSpec
from ale.geometry.blocks import Consts
from ale.geometry.checks import check_layout, exterior_contacts
from ale.program.models import PreparedInput
from ale.stack.assign import default_group
from ale.stack.plans import FloorPlan

REPO = Path(__file__).resolve().parents[2]
CASES = ("A", "B", "C")
HARD = ("ASPECT", "MIN_WIDTH", "NO_FACADE", "NO_CIRCULATION_ACCESS", "SOLID_NO_ACCESS")
HARD += ("REQUIRED_ADJ", "AVOID_ADJ")
BAY = 2.4


def _group(spec_id: str) -> str:
    return default_group(spec_id)


def floors_of(run: CaseRun) -> Iterator[tuple[FloorPlan, PreparedInput]]:
    for p in run.plans.floors:
        yield p, bc.prepared_floor(run.out, run.rulebook, p.level)


def plate_depth(prep: PreparedInput) -> float:
    xs = [q[0] for q in prep.footprint.polygon.exterior]
    ys = [q[1] for q in prep.footprint.polygon.exterior]
    return min(max(xs) - min(xs), max(ys) - min(ys)) / 10


def shapes_kw(prep: PreparedInput) -> dict[str, float]:
    return {"plate": plate_depth(prep)}


def rooms_of(p: FloorPlan, prep: PreparedInput) -> list[tuple[Any, Any]]:
    """``(PlacedRoom, spec or None)`` of every room of the layout."""
    assert p.layout is not None
    specs = dict(prep.instances)
    return [(r, specs.get(r.instance_id)) for r in p.layout.rooms]


# --------------------------------------------------------------------------------- M400
def test_M400_diagnosis_is_in_the_report() -> None:
    text = (REPO / "specs/tickets/M.4_bay-first/eval_report.md").read_text(encoding="utf-8")
    assert "## Diagnosis" in text
    assert "check_layout" in text and "export_run" in text


def test_M400_smoke_layout_exports_four_files(tmp_path: Path) -> None:
    """Circulation only plus reserve cells (the diagnosis smoke) is a valid, exportable layout:
    here the planner's own layout of the clean section, exported."""
    from ale.export import export_run

    prep, rb, rh = bc.build_bar(tmp_path / "e")
    res = plan_bar(
        prep, rb, bc.SKETCH, rh, df=48, corridor_m=1.8, group_of=lambda i, s: _group(s.id)
    )
    assert check_layout(res.layout, prep, bc.SKETCH) == ()
    export_run(
        res.layout,
        prep,
        tmp_path / "out",
        rulebook_version=prep.rulebook_version,
        run_id="m400",
        config=bc.SKETCH,
        rulebook=rb,
    )
    assert sorted(f.name for f in (tmp_path / "out").iterdir()) == [
        "layout.dxf",
        "layout.json",
        "preview.svg",
        "report.md",
    ]


# --------------------------------------------------------------------------------- M401
@pytest.mark.parametrize("name", CASES)
def test_M401_every_floor_is_bay_planned_and_valid(runs: dict[str, CaseRun], name: str) -> None:
    run = runs[name]
    assert len(run.plans.floors) == 4
    for p, prep in floors_of(run):
        assert p.status == "ok" and p.planner == "bay", (name, p.level, p.why)
        assert p.layout is not None
        assert check_layout(p.layout, prep, bc.SKETCH) == ()
        assert p.problems == ()
    assert run.plans.vertical_ok


# --------------------------------------------------------------------------------- M402
def _share(p: FloorPlan, prep: PreparedInput) -> float:
    target = sum(s.target_area_m2 for _, s in prep.instances)
    placed = sum(s.target_area_m2 for r, s in rooms_of(p, prep) if s is not None)
    return placed / target


@pytest.mark.parametrize(("name", "floor_min"), [("A", 1.0), ("B", 0.90), ("C", 0.85)])
def test_M402_completeness(runs: dict[str, CaseRun], name: str, floor_min: float) -> None:
    run = runs[name]
    for p, prep in floors_of(run):
        assert p.bay is not None
        assert _share(p, prep) >= floor_min - 1e-9, (name, p.level, p.bay.unplaced)
        if name == "A":
            assert p.bay.unplaced == ()
        placed_ids = {r.instance_id for r, s in rooms_of(p, prep) if s is not None}
        assert placed_ids | set(p.bay.unplaced) == {i for i, _ in prep.instances}
    text = (run.out / "plans.md").read_text(encoding="utf-8")
    for p in run.plans.floors:
        assert p.bay is not None
        for iid in p.bay.unplaced:
            assert iid in text


# --------------------------------------------------------------------------------- M403
def _merge_runs(rects: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Merge reserve rectangles that touch along x and share y and height."""
    out: list[tuple[int, int, int, int]] = []
    for x, y, w, h in sorted(rects, key=lambda r: (r[1], r[3], r[0])):
        if out and out[-1][1] == y and out[-1][3] == h and out[-1][0] + out[-1][2] == x:
            out[-1] = (out[-1][0], y, out[-1][2] + w, h)
        else:
            out.append((x, y, w, h))
    return out


def _fits(free_w: float, w: float, legal_rest: float) -> bool:
    """A free run of width ``free_w`` takes a room of width ``w`` when what is left is nothing
    or a legal reserve piece (at least ``legal_rest``)."""
    rest = free_w - w
    return rest > -1e-6 and (rest < 1e-6 or rest >= legal_rest - 1e-6)


@pytest.mark.parametrize("name", CASES)
def test_M403_no_degenerate_reserve(runs: dict[str, CaseRun], name: str) -> None:
    run = runs[name]
    for p, prep in floors_of(run):
        assert p.bay is not None and p.layout is not None
        plate_m2 = p.layout.footprint.area_cells() / 100
        reserve = [r for r in p.layout.rooms if r.spec_id is None]
        area = sum(r.area_m2(p.layout.grid) for r in reserve)
        assert p.placed_m2 == pytest.approx(
            sum(r.area_m2(p.layout.grid) for r in p.layout.rooms if r.spec_id is not None)
        )
        if p.bay.unplaced:
            assert area <= 0.08 * plate_m2, (name, p.level, area / plate_m2)
        reliquat = sum(
            c.area_m2(p.layout.grid)
            for c in p.layout.circulation
            if p.bay.kinds[c.instance_id] == "reliquat"
        )
        assert reliquat <= 0.015 * plate_m2
        depth = plate_depth(prep)
        specs = dict(prep.instances)
        rects = [(r.rect.x, r.rect.y, r.rect.w, r.rect.h) for r in reserve]
        facade_free = _merge_runs([r for r in rects if r[3] == 48])
        band = round((depth - 2 * 4.8 - 3.6) * 10)
        band_free = _merge_runs(
            [r for r in rects if r[3] in (band, band // 2) and 66 <= r[1] < 126]
        )
        for iid in p.bay.unplaced:
            spec = specs[iid]
            cat = bc.catalogue(spec.target_area_m2, spec.needs_facade, **shapes_kw(prep))
            options = [("F", s) for s in cat["F"]] + [("B", s) for s in cat["B"] + cat["b"]]
            if not options:
                continue
            for kind, (tag, w, d, _a) in options:
                runs_ = facade_free if kind == "F" else band_free
                for _x, _y, rw, rh in runs_:
                    if kind == "B" and abs(rh / 10 - d) > 1e-6:
                        continue
                    legal = BAY if kind == "F" else d / 2
                    assert not _fits(rw / 10, w, legal), (name, p.level, iid, tag, rw / 10)


# --------------------------------------------------------------------------------- M404
@pytest.mark.parametrize("name", CASES)
def test_M404_hard_violations_and_windows(runs: dict[str, CaseRun], name: str) -> None:
    run = runs[name]
    flagged = placed_n = 0
    for p, prep in floors_of(run):
        assert p.layout is not None and p.bay is not None
        codes = defaultdict(set)
        for v in p.layout.metrics.violations:
            codes[v.code] |= set(v.instance_ids)
        for hard in HARD:
            assert not codes.get(hard), (name, p.level, hard, codes[hard])
        kw = shapes_kw(prep)
        for r, s in rooms_of(p, prep):
            if s is None:
                continue
            placed_n += 1
            lo, hi = bc.window(s.target_area_m2)
            area = r.area_m2(p.layout.grid)
            inside = lo - 1e-6 <= area <= hi + 1e-6
            cat = bc.catalogue(s.target_area_m2, s.needs_facade, **kw)
            kinds = "FDT" if s.needs_facade else "FDBb"
            if any(cat[k_] for k_ in kinds):
                assert inside, (name, p.level, r.instance_id, area)
                assert r.instance_id not in codes.get("AREA_UNDER", set()) | codes.get(
                    "AREA_OVER", set()
                )
                tags = {t[0] for k_ in kinds for t in cat[k_]}
                assert p.bay.tags[r.instance_id] in tags, (r.instance_id, p.bay.tags[r.instance_id])
            else:
                flagged += 1
                tag, _dev = bc.fallback(s.target_area_m2, s.needs_facade, **kw)
                assert p.bay.tags[r.instance_id] == tag
        for code in ("AREA_UNDER", "AREA_OVER"):
            for iid in codes.get(code, ()):
                s = dict(prep.instances)[iid]
                assert bc.no_shape(s.target_area_m2, s.needs_facade, **kw)
    if name == "B":
        assert flagged <= 0.15 * placed_n
        assert flagged >= 1


# --------------------------------------------------------------------------------- M405
def test_M405_large_rooms_are_deep_or_unplaced(runs: dict[str, CaseRun]) -> None:
    run = runs["B"]
    seen = 0
    for p, prep in floors_of(run):
        assert p.bay is not None and p.layout is not None
        for r, s in rooms_of(p, prep):
            if s is None or (s.type != "open_office" and s.target_area_m2 != 150):
                continue
            seen += 1
            assert p.bay.tags[r.instance_id][0] in "DT", (p.level, r.instance_id)
            lo, hi = bc.window(s.target_area_m2)
            assert lo <= r.area_m2(p.layout.grid) <= hi
            assert min(r.rect.w, r.rect.h) >= 60  # a facade room is 4.8 m deep
    assert seen >= 6


# --------------------------------------------------------------------------------- M406
@pytest.mark.parametrize("name", CASES)
def test_M406_facade_and_band(runs: dict[str, CaseRun], name: str) -> None:
    run = runs[name]
    for p, prep in floors_of(run):
        assert p.layout is not None and p.bay is not None
        depth = plate_depth(prep)
        band = round((depth - 9.6 - 3.6) * 10)
        free_band = _merge_runs(
            [
                (r.rect.x, r.rect.y, r.rect.w, r.rect.h)
                for r in p.layout.rooms
                if r.spec_id is None and r.rect.h in (band, band // 2) and 66 <= r.rect.y < 126
            ]
        )
        for r, s in rooms_of(p, prep):
            if s is None:
                continue
            if s.needs_facade:
                contacts = exterior_contacts(r.rect, p.layout.footprint)
                assert sum(c[0] for c in contacts) >= 24, (name, p.level, r.instance_id)
            elif not (r.rect.y >= 66 and r.rect.y2() <= 66 + band):
                cat = bc.catalogue(s.target_area_m2, False, **shapes_kw(prep))
                for tag, w, d, _a in cat["B"] + cat["b"]:
                    for _x, _y, rw, rh in free_band:
                        if abs(rh / 10 - d) < 1e-6:
                            assert not _fits(rw / 10, w, d / 2), (name, p.level, r.instance_id, tag)


# --------------------------------------------------------------------------------- M407
def _half_bay_ok(coord_m: float, phase_cells: int) -> tuple[bool, bool]:
    """``(on a half-bay line, on a whole bay line)`` of an absolute coordinate."""
    rel = (coord_m - phase_cells * 0.6) / BAY
    whole = abs(rel - round(rel)) < 1e-6
    half = abs(rel * 2 - round(rel * 2)) < 1e-6
    return half, whole


@pytest.mark.parametrize("name", CASES)
def test_M407_long_side_partitions_on_half_bay_lines(runs: dict[str, CaseRun], name: str) -> None:
    run = runs[name]
    rh = run.stack.rhythm
    assert rh is not None
    for res_row in run.plans.longside:
        level, n, half, whole = res_row
        assert n > 0 and half == n, (name, level, n, half)
        assert 0 <= whole <= n
    assert len(run.plans.longside) == 4
    for p in run.plans.floors:  # independent recount from the room rectangles
        xs = [q[0] for q in p.outline]
        ys = [q[1] for q in p.outline]
        n = 0
        for r in p.rooms_abs:
            if r.kind != "room":
                continue
            x0, y0, w, h = r.rect
            if abs(y0 - min(ys)) < 1e-3 or abs(y0 + h - max(ys)) < 1e-3:
                for x in (x0, x0 + w):
                    if min(xs) + 1e-3 < x < max(xs) - 1e-3:
                        n += 1
                        assert _half_bay_ok(x, rh.phase_x)[0], (name, p.level, r.iid, x)
        assert n > 0


# --------------------------------------------------------------------------------- M408
def _classify(p: FloorPlan, prep: PreparedInput) -> None:
    """Every circulation rectangle is one of the elements of RD 4.4 (checked on geometry)."""
    assert p.layout is not None and p.bay is not None
    sec = p.bay.section
    df, c, band, dp = (round(sec[k_] * 10) for k_ in ("df", "c", "band", "plate_depth"))
    for circ in p.layout.circulation:
        kind = p.bay.kinds[circ.instance_id]
        r = circ.rect
        assert kind in {
            "couloir",
            "lien",
            "palier",
            "ecrete",
            "flanc",
            "bout",
            "entree",
            "reliquat",
        }
        if kind == "couloir":
            assert r.h <= c and r.y >= df and r.y2() <= dp - df
        elif kind == "lien":
            assert r.w == round(sec["bay"] * 10) and r.y2() <= dp
        elif kind == "bout":
            assert r.w == c and r.y == df + c and r.h == band
        elif kind == "reliquat":
            assert df + c <= r.y and r.y2() <= dp - df - c
        elif kind == "entree":
            assert r.w == round(sec["bay"] * 10)


@pytest.mark.parametrize("name", CASES)
def test_M408_circulation(runs: dict[str, CaseRun], name: str) -> None:
    run = runs[name]
    for p, prep in floors_of(run):
        assert p.layout is not None and p.bay is not None
        plate = p.layout.footprint.area_cells() / 100
        circ = sum(c.area_m2(p.layout.grid) for c in p.layout.circulation)
        assert circ / plate <= 0.37, (name, p.level, circ / plate)
        _classify(p, prep)
        corridors = [c for c in p.layout.circulation if p.bay.kinds[c.instance_id] == "couloir"]
        assert corridors
        for c in corridors:
            assert min(c.rect.w, c.rect.h) >= 12  # circulation.min_width_m beside the solid
        widths = {min(c.rect.w, c.rect.h) for c in corridors if c.rect.w >= 150}
        assert widths <= {18, 12} and 18 in widths  # 1.8 m in the wings; 1.2 m on the top floor
    top = run.plans.floors[3]
    assert top.bay is not None and top.bay.section["narrowed"] == 1.0


# --------------------------------------------------------------------------------- M409
@pytest.mark.parametrize("name", CASES)
def test_M409_entrance_on_circulation(runs: dict[str, CaseRun], name: str) -> None:
    run = runs[name]
    p = run.plans.floors[0]
    ex, ey = run.plans.entrances[0]
    circ = [r.rect for r in p.rooms_abs if r.kind == "circulation"]
    on = any(
        (rx - 1e-6 <= ex <= rx + rw + 1e-6 and ry - 1e-6 <= ey <= ry + rh + 1e-6)
        for rx, ry, rw, rh in circ
    )
    assert on
    text = (run.out / "plans.md").read_text(encoding="utf-8")
    assert "Entrée (" in text
    assert "Pièce d'entrée" in text


# --------------------------------------------------------------------------------- M410
def _stretches(p: FloorPlan) -> dict[str, int]:
    assert p.bay is not None
    sec = p.bay.section
    x_min = min(q[0] for q in p.outline)
    c0, c1 = sec["core0"], sec["core1"]
    spans: dict[str, list[tuple[float, float]]] = defaultdict(list)

    def squash(u: float) -> float:
        return u if u <= c0 else (c0 if u < c1 else u - (c1 - c0))

    for r in p.rooms_abs:
        if r.kind == "room" and r.spec_id is not None:
            u0 = r.rect[0] - x_min
            spans[_group(r.spec_id)].append((squash(u0), squash(u0 + r.rect[2])))
    out = {}
    for g, lst in spans.items():
        n = 0
        end: float | None = None
        for a, b in sorted(lst):
            if end is None or a - end > 2 * BAY + 1e-6:
                n += 1
            end = b if end is None else max(end, b)
        out[g] = n
    return out


@pytest.mark.parametrize("name", CASES)
def test_M410_groups_stay_together(runs: dict[str, CaseRun], name: str) -> None:
    run = runs[name]
    total = single = 0
    for p in run.plans.floors:
        for g, n in _stretches(p).items():
            assert n <= 3, (name, p.level, g, n)
            total += 1
            single += n == 1
    assert single >= 0.5 * total, (name, single, total)


# --------------------------------------------------------------------------------- M411
def _specs(area: float, n: int = 3, facade: bool = True) -> list[RoomSpec]:
    return [
        RoomSpec(
            id=f"X{i}",
            name="x",
            type="office",
            target_area_m2=area,
            macro_zone="ADMINISTRATIVE",
            needs_facade=facade,
        )
        for i in range(n)
    ]


def test_M411_facade_depth_for_case_b(runs: dict[str, CaseRun]) -> None:
    run = runs["B"]
    k = Consts.from_config(bc.SKETCH)
    specs = [s for _, s in run.program.instances() if s.type not in bc.WET]
    df, total = choose_facade_depth(specs, k, 24)
    assert df == 48 and total > 0
    text = (run.out / "plans.md").read_text(encoding="utf-8")
    assert "d_f = 4.8 m" in text


def test_M411_depth_tie_is_broken_by_the_learned_depth(tmp_path: Path) -> None:
    from ale.contracts.models import Program
    from ale.parti.evaluate import neutral_rulebook

    k = Consts.from_config(bc.SKETCH)
    specs = _specs(11.5)
    assert choose_facade_depth(specs, k, 30)[0] == 42  # bay 3.0 m: 3.6 and 4.2 tie, ref 5.4
    rb = neutral_rulebook(Program(rooms=tuple(specs[:1])))
    learned = rb.types["office"].model_copy(
        update={"depth_m": Quantiles(p10=3.0, p50=3.6, p90=4.2, n=10)}
    )
    rb2 = rb.model_copy(update={"types": {"office": learned}})
    assert choose_facade_depth(specs, k, 30, rulebook=rb2)[0] == 36


def _bar(tmp_path: Path, **kw: Any) -> Any:
    return bc.build_bar(tmp_path, **kw)


_SMALL = [bc.stack_case.room("AA01", "Bureau", "office", 12, qty=4, facade=True)]


def _plan(prep: PreparedInput, rb: Any, rh: Any) -> Any:
    return plan_bar(
        prep, rb, bc.SKETCH, rh, df=48, corridor_m=1.8, group_of=lambda i, s: _group(s.id)
    )


def test_M411_rows_of_the_two_plates(tmp_path: Path) -> None:
    prep, rb, rh = _bar(tmp_path / "a")
    r = _plan(prep, rb, rh)
    sec = r.section
    assert (sec["df"], sec["c"], sec["band"], sec["plate_depth"]) == (4.8, 1.8, 6.0, 19.2)
    ys = {
        (c.rect.y, c.rect.y2()) for c in r.layout.circulation if r.kinds[c.instance_id] == "couloir"
    }
    assert (48, 66) in ys and (126, 144) in ys
    prep2, rb2, rh2 = _bar(tmp_path / "b", depth=16.8, solids=((24.0, 6.6, 16.8, 3.6),))
    r2 = _plan(prep2, rb2, rh2)
    assert (r2.section["band"], r2.section["plate_depth"]) == (3.6, 16.8)
    ys2 = {
        (c.rect.y, c.rect.y2())
        for c in r2.layout.circulation
        if r2.kinds[c.instance_id] == "couloir"
    }
    assert (48, 66) in ys2 and (102, 120) in ys2


@pytest.mark.parametrize(
    ("kw", "word"),
    [
        ({"depth": 14.4, "solids": ((24.0, 6.0, 16.8, 2.4),)}, "bande"),
        ({"length": 36.0, "solids": ((10.0, 6.6, 6.0, 6.0),)}, "barre"),
        ({"solids": ((12.0, 6.6, 6.0, 6.0), (40.0, 6.6, 6.0, 6.0))}, "volumes pleins"),
    ],
)
def test_M411_not_eligible_with_a_french_reason(
    tmp_path: Path, kw: dict[str, Any], word: str
) -> None:
    prep, rb, rh = _bar(tmp_path, rooms=_SMALL, **kw)
    with pytest.raises(NotEligible) as exc:
        _plan(prep, rb, rh)
    assert word in exc.value.reason


# ------------------------------------------------------------------------------ catalogue
def test_catalogue_recomputed_from_the_formulas() -> None:
    cat = bc.catalogue
    assert [t[0] for t in cat(12, True)["F"]] == ["F1"]
    assert [t[0] for t in cat(24, True)["F"]] == ["F2"]
    assert [t[0] for t in cat(30, True)["F"]] == ["F2.5"]
    assert [t[0] for t in cat(40, True)["F"]] == ["F3.5"]
    assert bc.no_shape(80, True) and bc.no_shape(15, True)
    assert "D5" in [t[0] for t in cat(150, True)["D"]]
    assert "D5" in [t[0] for t in cat(163.2, True)["D"]]
    big = cat(170, True)
    assert {"D5.5", "D6"} <= {t[0] for t in big["D"]} and "T4" in [t[0] for t in big["T"]]
    f = bc.fallback
    assert f(15, True)[0] in ("F1.5", "F1") and f(80, True)[0] == "D3"
    assert math.isclose(cat(12, True)["F"][0][3], 11.52)


# --------------------------------------------------------------------------------- M412
@pytest.mark.parametrize("name", CASES)
def test_M412_columns_in_small_rooms(runs: dict[str, CaseRun], name: str) -> None:
    pr = runs[name].plans
    cols = sum(f.columns for f in pr.rhythms)
    small = sum(f.small for f in pr.rhythms)
    assert cols > 0 and small <= 0.12 * cols, (name, small, cols)
    assert len(pr.stacking) == 3 and len(pr.bound) == 3
    for s, b in zip(pr.stacking, pr.bound, strict=True):
        assert 0.0 <= s <= b + 1e-9 <= 1.0 + 1e-9


# ------------------------------------------------------------------------------- E and F
@pytest.fixture(scope="module")
def ef(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[Any, Any]]:
    out = {}
    for key, tr in (("E", False), ("F", True)):
        prep, rb, rh = _bar(tmp_path_factory.mktemp(f"m4_{key}"), transposed=tr)
        out[key] = (prep, _plan(prep, rb, rh))
    return out


@pytest.mark.parametrize("key", ["E", "F"])
def test_E_F_valid_complete_and_compact(ef: dict[str, tuple[Any, Any]], key: str) -> None:
    prep, res = ef[key]
    lay = res.layout
    assert check_layout(lay, prep, bc.SKETCH) == ()
    assert res.unplaced == ()
    assert {v.code for v in lay.metrics.violations} == set()
    plate = lay.footprint.area_cells() / 100
    circ = sum(c.area_m2(lay.grid) for c in lay.circulation)
    assert circ / plate <= 0.27
    groups: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for r in lay.rooms:
        if r.spec_id is not None:
            groups[_group(r.spec_id)].append(
                (r.rect.y, r.rect.y2()) if key == "F" else (r.rect.x, r.rect.x2())
            )
    sec = res.section
    c0, c1 = round(sec["core0"] * 10), round(sec["core1"] * 10)
    for g, lst in groups.items():
        sq = [
            (
                (a if a <= c0 else (c0 if a < c1 else a - (c1 - c0))),
                (b if b <= c0 else (c0 if b < c1 else b - (c1 - c0))),
            )
            for a, b in lst
        ]
        n, end = 0, None
        for a, b in sorted(sq):
            if end is None or a - end > 48:
                n += 1
            end = b if end is None else max(end, b)
        assert n <= 2, (key, g, n)


def test_F_is_E_transposed(ef: dict[str, tuple[Any, Any]]) -> None:
    (_pe, re_), (_pf, rf) = ef["E"], ef["F"]
    areas_e = {r.instance_id: r.rect.w * r.rect.h for r in re_.layout.rooms if r.spec_id}
    areas_f = {r.instance_id: r.rect.w * r.rect.h for r in rf.layout.rooms if r.spec_id}
    assert areas_e == areas_f
    assert re_.tags == rf.tags
    for a, b in zip(re_.layout.rooms, rf.layout.rooms, strict=True):
        assert (a.rect.x, a.rect.y, a.rect.w, a.rect.h) == (b.rect.y, b.rect.x, b.rect.h, b.rect.w)
    assert re.fullmatch(r"reserve-\d{3}", re_.reserve_ids[0])
    assert ModuleRect  # contract rectangle type used by the layouts
