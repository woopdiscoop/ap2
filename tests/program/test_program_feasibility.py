"""Ticket 3.1 section 3: feasibility pre-check with the test rulebook (Z01-Z07)."""

from __future__ import annotations

import math
import statistics
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest
from fixtures import load_program, load_site
from program_helpers import good_row, site_to_yaml, write_rows

from ale.contracts.config import AleConfig
from ale.contracts.enums import MacroZone
from ale.contracts.footprint import decompose_footprint
from ale.contracts.geometry import ModulePolygon
from ale.contracts.lock import main as lock_main
from ale.contracts.models import GridSpec, Program, Quantiles, RoomSpec, Rulebook
from ale.program.feasibility import (
    band_estimate,
    check_feasibility,
    facade_usable_mm,
    narrowest_width,
    room_fit,
)
from ale.program.models import ModuleFootprint
from ale.program.prepare import check_inputs
from ale.program.site import to_module_footprint

CONFIG = AleConfig()
GRID = GridSpec()


def footprint(name: str):  # type: ignore[no-untyped-def]
    return to_module_footprint(load_site(name), GRID)  # type: ignore[arg-type]


def with_office_aspect(rulebook: Rulebook, p10: float, p50: float, p90: float) -> Rulebook:
    office = rulebook.types["office"]
    aspect = Quantiles(p10=p10, p50=p50, p90=p90)
    types = dict(rulebook.types, office=office.model_copy(update={"aspect": aspect}))
    return rulebook.model_copy(update={"types": types})


def office(rid: str, area: float, **kw: object) -> RoomSpec:
    return RoomSpec(
        id=rid,
        name="Bureau",
        type="office",
        target_area_m2=area,
        macro_zone=MacroZone.ADMINISTRATIVE,
        **kw,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- Z01


@pytest.mark.parametrize(
    ("program", "site", "required", "available", "overshoot", "fill"),
    [
        ("program_08", "site_rect_small", 88.5, 95.0, 0.0, 0.885),
        ("program_25", "site_rect", 394.12, 410.4, 0.0, 0.9123),
        ("program_60", "site_L", 1135.16, 1162.8, 0.0, 0.9274),
    ],
)
def test_Z01_fixtures_fit(
    rulebook: Rulebook,
    program: str,
    site: str,
    required: float,
    available: float,
    overshoot: float,
    fill: float,
) -> None:
    report = check_feasibility(load_program(program), footprint(site), rulebook, CONFIG)  # type: ignore[arg-type]
    # Q.2a: program_60 on site_L now carries the W_FACADE_TIGHT warning (eval F3); no error.
    expected_warnings = ["W_FACADE_TIGHT"] if program == "program_60" else []
    assert [i.code for i in report.issues] == expected_warnings
    assert report.required_m2 == pytest.approx(required, abs=1e-3)
    assert report.available_m2 == pytest.approx(available, abs=1e-3)
    assert report.overshoot_m2 == pytest.approx(overshoot, abs=1e-3)
    assert report.fill_ratio == pytest.approx(fill, abs=1e-3)
    assert report.circulation_m2 == pytest.approx(report.net_m2 * 0.18, abs=1e-9)


# --------------------------------------------------------------------------- Z02


def test_Z02_not_feasible(rulebook: Rulebook) -> None:
    report = check_feasibility(
        load_program("program_25"), footprint("site_rect_small"), rulebook, CONFIG
    )
    assert [i.code for i in report.issues] == [
        "E_NOT_FEASIBLE",
        "W_FACADE_TIGHT",
    ]  # Q.2a warning appended
    message = report.issues[0].message
    assert "il manque 299.12 m²" in message
    assert message.startswith("Programme trop grand : il manque 299.12 m² (requis ")


# --------------------------------------------------------------------------- Z03


def test_Z03_room_infeasible(tmp_path: Path, rulebook_path: Path) -> None:
    pytest.importorskip("openpyxl")  # the 'excel' extra
    xlsx = write_rows(
        tmp_path / "p.xlsx",
        [good_row("R01"), good_row("R02", Surface=4, Largeur=3.0)],
    )
    site = site_to_yaml(load_site("site_rect"), tmp_path / "site.yaml")
    result = check_inputs(xlsx, site, rulebook_path, CONFIG)
    assert [(i.code, i.row) for i in result.errors] == [("E_ROOM_INFEASIBLE", 3)]
    assert result.feasibility is not None
    assert "R02" not in result.feasibility.per_room
    assert "R01" in result.feasibility.per_room


# --------------------------------------------------------------------------- Z04


def test_Z04_rulebook_coverage(rulebook: Rulebook) -> None:
    types = {k: v for k, v in rulebook.types.items() if k != "storage"}
    reduced = rulebook.model_copy(update={"types": types})
    report = check_feasibility(
        load_program("program_08"), footprint("site_rect_small"), reduced, CONFIG
    )
    missing = [i for i in report.issues if i.code == "E_TYPE_NOT_IN_RULEBOOK"]
    assert len(missing) == 1
    assert "storage" in missing[0].message
    assert [i.code for i in report.issues] == ["E_TYPE_NOT_IN_RULEBOOK"]


# --------------------------------------------------------------------------- Z05


def test_Z05_facade(rulebook: Rulebook) -> None:
    program = Program(rooms=(office("B", 4.0, quantity=20, needs_facade=True),))
    report = check_feasibility(program, footprint("site_rect_small"), rulebook, CONFIG)
    assert [i.code for i in report.issues] == ["E_FACADE_INSUFFICIENT", "W_FACADE_TIGHT"]  # Q.2a
    assert report.facade_required_m == pytest.approx(48.0)
    assert report.perimeter_m == pytest.approx(40.0)
    assert report.required_m2 == pytest.approx(94.4, abs=1e-3)
    assert report.required_m2 <= report.available_m2


# --------------------------------------------------------------------------- Z06


def test_Z06_band_fallback(rulebook: Rulebook) -> None:
    narrow = with_office_aspect(rulebook, 1.5, 1.55, 1.6)
    program = Program(rooms=(office("A", 12.0), office("B", 12.0, min_width_m=3.0)))
    report = check_feasibility(program, footprint("site_rect"), narrow, CONFIG)
    assert report.issues == ()
    a, b = report.per_room["A"], report.per_room["B"]
    assert (a.short, a.long) == (28, 43)
    assert a.overshoot_m2 == pytest.approx(0.04, abs=1e-9)
    assert (b.short, b.long) == (30, 40)
    assert b.overshoot_m2 == 0.0


# --------------------------------------------------------------------------- Z07


def test_Z07_exact_arithmetic(rulebook: Rulebook) -> None:
    program = load_program("program_60")
    report = check_feasibility(program, footprint("site_L"), rulebook, CONFIG)
    net = sum((Decimal(str(spec.target_area_m2)) for _, spec in program.instances()), Decimal(0))
    module_m2 = Decimal(GRID.module_mm) ** 2 / Decimal(1_000_000)
    over = sum(
        (
            max(
                Decimal(0),
                Decimal(report.per_room[spec.id].short * report.per_room[spec.id].long) * module_m2
                - Decimal(str(spec.target_area_m2)),
            )
            for _, spec in program.instances()
        ),
        Decimal(0),
    )
    expected = net * (1 + Decimal(str(CONFIG.circulation.ratio))) + over
    assert report.required_m2 == float(expected)
    assert expected == Decimal("1135.16")


# --------------------------------------------------------------------------- extra


def test_room_fit_missing_type_and_empty_band(rulebook: Rulebook) -> None:
    # Type absent from the rulebook → straight to the fallback band.
    types = {k: v for k, v in rulebook.types.items() if k != "office"}
    reduced = rulebook.model_copy(update={"types": types})
    assert room_fit(office("A", 12.0), GRID, reduced, CONFIG) == (30, 40)
    # Rulebook band entirely above shape.aspect_max → empty band → fallback.
    steep = with_office_aspect(rulebook, 3.0, 3.5, 4.0)
    assert room_fit(office("A", 12.0), GRID, steep, CONFIG) == (30, 40)


def test_overshoot_counted(rulebook: Rulebook) -> None:
    narrow = with_office_aspect(rulebook, 1.5, 1.55, 1.6)
    program = Program(rooms=(office("A", 12.0, quantity=3),))
    report = check_feasibility(program, footprint("site_rect"), narrow, CONFIG)
    assert report.overshoot_m2 == pytest.approx(0.12, abs=1e-9)
    assert report.required_m2 == pytest.approx(36 * 1.18 + 0.12, abs=1e-9)


# --------------------------------------------------------------------------- Q.2a

S_MOD = 12  # spine width: ceil(circulation.min_width_m 1.2 m / 0.1 m)


def _n0(depth: int, program: Program) -> int:
    """RD 3.2 band estimate, recomputed independently: max(1, round((P-s)/(2·D_t+s)))."""
    cells = sorted(
        Fraction(Decimal(str(spec.target_area_m2))) * 100 for _, spec in program.instances()
    )
    median = Fraction(statistics.median(cells))
    d_t = math.isqrt(math.floor(median * Fraction(7, 5)))
    while d_t * d_t < median * Fraction(7, 5):
        d_t += 1
    return max(1, round(Fraction(depth - S_MOD, 2 * d_t + S_MOD)))


def test_F1_rect(rulebook: Rulebook) -> None:
    program = load_program("program_25")
    report = check_feasibility(program, footprint("site_rect"), rulebook, CONFIG)
    # 24 x 18 m, spine X: both 24 m edges count, minus s per band at each of the 2 ends.
    n0 = _n0(180, program)
    assert n0 == 2
    expected = 2 * 24.0 - 2 * n0 * 1.2
    assert report.facade_usable_m == pytest.approx(expected, abs=1e-9)
    assert report.facade_usable_m == pytest.approx(43.2, abs=1e-9)


def test_F2_L(rulebook: Rulebook) -> None:
    program = load_program("program_60")
    fp = footprint("site_L")
    pieces = decompose_footprint(fp.polygon)
    # J2: primary 30 x 30 m (spine X), secondary 18 x 18 m (spine X), vertical cut x = 30 m.
    assert pieces.junction == "J2"
    assert [(p.rect.x, p.rect.y, p.rect.w, p.rect.h, p.spine_axis) for p in pieces.pieces] == [
        (0, 0, 300, 300, "X"),
        (300, 0, 180, 180, "X"),
    ]
    assert pieces.cut == ((300, 0), (300, 180))
    report = check_feasibility(program, fp, rulebook, CONFIG)
    # Edges parallel to X: 30 + 30 (primary) + 18 + 18 (secondary); short edges on the cut
    # (primary east, secondary west) excluded, one exterior end per piece.
    n_primary, n_secondary = _n0(300, program), _n0(180, program)
    assert (n_primary, n_secondary) == (3, 2)
    expected = (30.0 + 30.0 + 18.0 + 18.0) - 1.2 * (n_primary + n_secondary)
    assert report.facade_usable_m == pytest.approx(expected, abs=1e-9)
    assert report.facade_usable_m == pytest.approx(90.0, abs=1e-9)
    assert report.facade_usable_m < report.perimeter_m


def test_F2_J1_cut_on_long_edge() -> None:
    # J1: primary (0,0,300,500) spine Y, its east edge shares 200 modules with the cut;
    # secondary (300,0,200,200) spine X, west short edge on the cut.
    poly = ModulePolygon(exterior=((0, 0), (500, 0), (500, 200), (300, 200), (300, 500), (0, 500)))
    assert decompose_footprint(poly).junction == "J1"
    targets = [Fraction(1200)]  # one 12 m² room → D_t = 41
    n_p = round(Fraction(300 - S_MOD, 2 * 41 + S_MOD))  # 3
    n_s = round(Fraction(200 - S_MOD, 2 * 41 + S_MOD))  # 2
    expected = (500 + (500 - 200) + 200 + 200) - S_MOD * (2 * n_p + n_s)
    assert facade_usable_mm(poly, targets, S_MOD, 100) == expected * 100 == 110_400


def test_F2_helpers() -> None:
    assert band_estimate(180, [], S_MOD) == 1
    assert band_estimate(10_000, [Fraction(100)], S_MOD) == 6  # capped at MAX_BANDS
    # 12 m², tol -3 % / +1.2 m², 2:1 → 2.5 m x ≥ 4.66 m (25 x 47 cells).
    assert narrowest_width(office("A", 12.0), GRID, CONFIG) == 25
    assert narrowest_width(office("A", 12.0, min_width_m=3.0), GRID, CONFIG) == 30
    # A width larger than any compliant rectangle allows → None.
    assert narrowest_width(office("A", 4.0, min_width_m=3.0), GRID, CONFIG) is None


def test_F3_tight_warning(rulebook: Rulebook) -> None:
    program = load_program("program_60")
    report = check_feasibility(program, footprint("site_L"), rulebook, CONFIG)
    tight = [i for i in report.issues if i.code == "W_FACADE_TIGHT"]
    assert len(tight) == 1
    assert tight[0].severity == "warning"
    assert [i for i in report.issues if i.severity == "error"] == []
    # Demand Σ max(2.4 m, w_est) over needs_facade instances exceeds the usable façade.
    demand = sum(
        (
            max(Decimal("2.4"), Decimal(narrowest_width(spec, GRID, CONFIG) or 0) / 10)
            for _, spec in program.instances()
            if spec.needs_facade
        ),
        Decimal(0),
    )
    assert demand > Decimal(str(report.facade_usable_m))
    assert f"{float(demand)} m" in tight[0].message

    small = check_feasibility(
        load_program("program_08"), footprint("site_rect_small"), rulebook, CONFIG
    )
    assert small.issues == ()
    assert small.facade_usable_m == pytest.approx(17.6, abs=1e-9)


def test_F3_non_grammar_footprint_falls_back_to_perimeter(rulebook: Rulebook) -> None:
    # A footprint outside decompose_footprint (G.1: one needing more than 12 pieces, here a
    # staircase of 14 steps; a U is decomposable since G.1): no raise, usable = perimeter.
    steps: list[tuple[int, int]] = [(0, 0), (140, 0)]
    for k in range(14):
        steps += [(140 - 10 * k, 10 * (k + 1)), (130 - 10 * k, 10 * (k + 1))]
    u_shape = ModulePolygon(exterior=tuple(steps))
    fp = ModuleFootprint(polygon=u_shape, origin_m=(0.0, 0.0), access_edge=0, sliver_loss_m2=0.0)
    report = check_feasibility(load_program("program_08"), fp, rulebook, CONFIG)
    assert report.facade_usable_m == report.perimeter_m == pytest.approx(56.0)
    assert "W_FACADE_TIGHT" not in [i.code for i in report.issues]


def test_F4_gates() -> None:
    """Contracts untouched; ruff/format/mypy and the whole suite run as commands (eval_report)."""
    assert lock_main(["--check"]) == 0
