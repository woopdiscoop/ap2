"""Ticket 3.1 section 3: feasibility pre-check with the test rulebook (Z01-Z07)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fixtures import load_program, load_site
from program_helpers import good_row, site_to_yaml, write_rows

from ale.contracts.config import AleConfig
from ale.contracts.enums import MacroZone
from ale.contracts.models import GridSpec, Program, Quantiles, RoomSpec, Rulebook
from ale.program.feasibility import check_feasibility, room_fit
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
    assert report.issues == ()
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
    assert [i.code for i in report.issues] == ["E_NOT_FEASIBLE"]
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
    assert [i.code for i in report.issues] == ["E_FACADE_INSUFFICIENT"]
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
