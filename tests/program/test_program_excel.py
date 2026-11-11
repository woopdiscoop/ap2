"""Ticket 3.1 section 1: reading ``programme.xlsx`` (X01-X10) plus edge cases."""

from __future__ import annotations

import datetime as dt
import random
from pathlib import Path
from typing import Any

import pytest
from fixtures import load_program
from program_helpers import (
    HEADERS,
    X07_ROWS,
    good_row,
    program_to_xlsx,
    row,
    write_rows,
    write_x07,
)
from pydantic import ValidationError

from ale.contracts.enums import Bearing, MacroZone
from ale.contracts.models import RoomSpec
from ale.program.excel import canon_header, issues_from_validation_error, read_program
from ale.program.models import ERROR_CODES, WARNING_CODES, ProgramReport

openpyxl = pytest.importorskip("openpyxl")  # the 'excel' extra

#: The frozen code list of RD 3.1 section 4 (site codes included), written out here.
FROZEN_CODES = {
    "E_MISSING_COLUMN",
    "E_NO_ROOMS",
    "E_EMPTY_ID",
    "E_BAD_ID",
    "E_DUP_ID",
    "E_EMPTY_NAME",
    "E_UNKNOWN_TYPE",
    "E_FORBIDDEN_TYPE",
    "E_AREA",
    "E_QUANTITY",
    "E_ZONE",
    "E_FACADE",
    "E_ORIENTATION",
    "E_MIN_WIDTH",
    "E_REF_UNKNOWN",
    "E_SELF_REF",
    "E_REQ_AVOID_CONFLICT",
    "E_FLOOR",
    "E_ROOM_INFEASIBLE",
    "E_TYPE_NOT_IN_RULEBOOK",
    "E_NOT_FEASIBLE",
    "E_FACADE_INSUFFICIENT",
    "E_SITE_DXF",
    "E_SITE_UNITS",
    "E_SITE_DWG",
    "E_SITE_INVALID",
    "E_SITE_NOT_ORTHOGONAL",
    "E_SITE_TOO_SMALL",
    "E_SITE_ACCESS_EDGE",
    "W_SHEET_NAME",
    "W_UNKNOWN_COLUMN",
    "W_ZONE_DEFAULTED",
    "W_FACADE_TIGHT",  # Q.2a
    "E_ANCHOR",  # A.4
    "E_FLOORS_MULTIPLE",  # A.4
    "W_ANCHOR_NO_ENTRANCE",  # A.4
    "W_ANCHOR_CORNERS",  # A.4
    "W_SITE_PLOT_MODE",  # A.4
}


def codes(report: ProgramReport) -> list[tuple[str, int | None]]:
    return [(i.code, i.row) for i in report.issues]


def read_rows(tmp_path: Path, rows: list[list[Any]], **kw: Any) -> tuple[Any, ProgramReport]:
    path = write_rows(tmp_path / "p.xlsx", rows, **kw)
    return read_program(path)


# --------------------------------------------------------------------------- X01


@pytest.mark.parametrize("name", ["program_08", "program_25", "program_60"])
def test_X01_roundtrip_fixtures(tmp_path: Path, name: str) -> None:
    fixture = load_program(name)  # type: ignore[arg-type]
    program, report = read_program(program_to_xlsx(fixture, tmp_path / f"{name}.xlsx"))
    assert report.errors == ()
    assert program == fixture


# --------------------------------------------------------------------------- X02


def test_X02_type_resolution(tmp_path: Path) -> None:
    ok_rows = [
        good_row("A1", Type="meeting_room"),
        good_row("A2", Type="Salle de réunion"),
        good_row("A3", Type="S. REUNION"),
    ]
    program, report = read_rows(tmp_path, ok_rows)
    assert report.errors == ()
    assert [r.type for r in program.rooms] == ["meeting_room"] * 3

    bad_rows = [
        good_row("B1", Type="Bureau paysager nord"),
        good_row("B2", Type="Circulation"),
        good_row("B3", Type="Terrasse"),
    ]
    program, report = read_rows(tmp_path, bad_rows)
    assert program is None
    assert codes(report) == [
        ("E_UNKNOWN_TYPE", 2),
        ("E_FORBIDDEN_TYPE", 3),
        ("E_FORBIDDEN_TYPE", 4),
    ]
    message = report.issues[0].message
    assert "open_office" in message
    assert "Plateau de bureaux" in message


# --------------------------------------------------------------------------- X03


def test_X03_numbers_fr(tmp_path: Path) -> None:
    program, report = read_rows(
        tmp_path,
        [
            good_row("A1", Surface="12,5"),
            good_row("A2", Surface=12),
            good_row("A3", Quantite=3.0),
        ],
    )
    assert report.errors == ()
    areas = [r.target_area_m2 for r in program.rooms]
    assert areas == [12.5, 12.0, 12.0]
    assert all(isinstance(a, float) for a in areas)
    assert program.rooms[2].quantity == 3

    bad = [
        good_row("B1", Surface="abc"),
        good_row("B2", Surface=0),
        good_row("B3", Surface=-3),
        good_row("B4", Surface=10001),
        good_row("C1", Quantite=3.5),
        good_row("C2", Quantite=0),
        good_row("C3", Quantite=501),
    ]
    program, report = read_rows(tmp_path, bad)
    assert program is None
    assert codes(report) == [("E_AREA", n) for n in (2, 3, 4, 5)] + [
        ("E_QUANTITY", n) for n in (6, 7, 8)
    ]


# --------------------------------------------------------------------------- X04


def test_X04_zone_and_facade(tmp_path: Path) -> None:
    rows = [
        good_row("Z1", Zone="administratif"),
        good_row("Z2", Zone="ADMINISTRATIVE"),
        good_row("Z3", Zone=None, Type="office"),
        good_row("F1", Facade="Oui"),
        good_row("F2", Facade="o"),
        good_row("F3", Facade="X"),
        good_row("F4", Facade=1),
        good_row("F5", Facade="Vrai"),
        good_row("G1", Facade=None),
        good_row("G2", Facade="Non"),
        good_row("G3", Facade=0),
    ]
    program, report = read_rows(tmp_path, rows)
    assert report.errors == ()
    by_id = {r.id: r for r in program.rooms}
    for rid in ("Z1", "Z2", "Z3"):
        assert by_id[rid].macro_zone is MacroZone.ADMINISTRATIVE
    assert codes(report) == [("W_ZONE_DEFAULTED", 4)]
    assert report.issues[0].column == "Zone"
    assert all(by_id[f"F{k}"].needs_facade is True for k in range(1, 6))
    assert all(by_id[f"G{k}"].needs_facade is False for k in range(1, 4))

    program, report = read_rows(
        tmp_path, [good_row("Z9", Zone="Bureaux"), good_row("F9", Facade="peut-être")]
    )
    assert program is None
    assert codes(report) == [("E_ZONE", 2), ("E_FACADE", 3)]


# --------------------------------------------------------------------------- X05


def test_X05_orientation(tmp_path: Path) -> None:
    program, report = read_rows(
        tmp_path, [good_row("A1", S=1), good_row("A2"), good_row("A3", O=-0.5)]
    )
    assert report.errors == ()
    a1, a2, a3 = program.rooms
    assert a1.orientation_override == {
        Bearing.N: 0.0,
        Bearing.E: 0.0,
        Bearing.S: 1.0,
        Bearing.W: 0.0,
    }
    assert a2.orientation_override is None
    assert a3.orientation_override is not None
    assert a3.orientation_override[Bearing.W] == -0.5  # the O (Ouest) column

    program, report = read_rows(tmp_path, [good_row("B1", N=1.5)])
    assert program is None
    assert codes(report) == [("E_ORIENTATION", 2)]
    assert report.issues[0].column == "Orientation N"


# --------------------------------------------------------------------------- X06


def test_X06_refs(tmp_path: Path) -> None:
    rows = [
        good_row("R01", Adjacent="R02; R03 ,R04"),
        good_row("R02"),
        good_row("R03"),
        good_row("R04"),
    ]
    program, report = read_rows(tmp_path, rows)
    assert report.errors == ()
    assert program.rooms[0].adjacent_to == ("R02", "R03", "R04")

    program, report = read_rows(
        tmp_path, [good_row("R01", Adjacent="R99"), good_row("R02", Eviter="R02")]
    )
    assert program is None
    assert codes(report) == [("E_REF_UNKNOWN", 2), ("E_SELF_REF", 3)]

    program, report = read_rows(
        tmp_path, [good_row("R01", Adjacent="R02"), good_row("R02", Eviter="R01")]
    )
    assert program is None
    assert codes(report) == [("E_REQ_AVOID_CONFLICT", 2)]

    program, report = read_rows(
        tmp_path, [good_row("R01", Adjacent="R02", Eviter="R02"), good_row("R02")]
    )
    assert codes(report) == [("E_REQ_AVOID_CONFLICT", 2)]


# --------------------------------------------------------------------------- X07


def test_X07_error_catalogue(tmp_path: Path) -> None:
    program, report = read_program(write_x07(tmp_path / "x07.xlsx"))
    assert program is None
    expected = sorted((code, n) for n, (code, _) in enumerate(X07_ROWS, start=2))
    assert sorted(codes(report)) == expected
    assert len(report.issues) == 12
    for issue in report.issues:
        assert issue.severity == "error"
        assert issue.message
        assert issue.column is not None


# --------------------------------------------------------------------------- X08


def test_X08_headers(tmp_path: Path) -> None:
    headers = ["id", "NOM", " type ", "Surface (m2)", "quantite"]
    program, report = read_rows(tmp_path, [["R01", "Bureau", "Bureau", 12, 2]], headers=headers)
    assert report.errors == ()
    assert program.rooms[0].quantity == 2
    assert program.rooms[0].target_area_m2 == 12.0

    no_area = [h for h in HEADERS if h != "Surface (m²)"]
    program, report = read_rows(
        tmp_path, [["R01", "Bureau", "Bureau", "x"], [None, None, "Truc"]], headers=no_area
    )
    assert program is None
    assert codes(report) == [("E_MISSING_COLUMN", 1)]
    assert report.issues[0].column == "Surface (m²)"

    program, report = read_rows(tmp_path, [[*good_row(), 1000]], headers=[*HEADERS, "Budget"])
    assert program is not None
    assert codes(report) == [("W_UNKNOWN_COLUMN", 1)]
    assert report.issues[0].column == "Budget"

    program, report = read_rows(tmp_path, [good_row()], sheet="Feuil1")
    assert program is not None
    assert codes(report) == [("W_SHEET_NAME", None)]
    assert report.sheet == "Feuil1"


# --------------------------------------------------------------------------- X09


def test_X09_comments_blank(tmp_path: Path) -> None:
    rows = [
        good_row("R01"),
        [None] * 17,
        row(ID="#note", Nom=None, Surface="pas un nombre"),
        ["", "  ", None],
        good_row("R05", Surface=-1),
    ]
    program, report = read_rows(tmp_path, rows)
    assert program is None
    assert codes(report) == [("E_AREA", 6)]


# --------------------------------------------------------------------------- X10


def _random_cell(rng: random.Random) -> Any:
    kind = rng.randrange(10)
    if kind == 0:
        return None
    if kind == 1:
        return rng.randint(-1000, 20000)
    if kind == 2:
        return rng.uniform(-5, 15000)
    if kind == 3:
        return rng.choice([True, False])
    if kind == 4:
        return dt.datetime(2020, 1, 1) + dt.timedelta(days=rng.randrange(1000))
    if kind == 5:
        return rng.choice(["Bureau", "Circulation", "Oui", "non", "R01", "R02; R03", "#x", "12,5"])
    if kind == 6:
        return rng.choice(["Public", "Services", "ADMINISTRATIVE", "-0.5", "1.5", "", "  "])
    alphabet = "abcAZ019 _-;,#éèàçÉ²."
    return "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 12)))


def test_X10_never_raises(tmp_path: Path) -> None:
    rng = random.Random(20261107)
    allowed = FROZEN_CODES
    assert allowed == ERROR_CODES | WARNING_CODES
    seen: set[str] = set()
    for k in range(50):
        if rng.random() < 0.8:
            headers: list[Any] = list(HEADERS)
            rng.shuffle(headers)
            headers = headers[: rng.randint(4, 17)]
            if rng.random() < 0.3:
                headers.append(_random_cell(rng))
        else:
            headers = [_random_cell(rng) for _ in range(rng.randint(0, 8))]
        rows = [
            [_random_cell(rng) for _ in range(rng.randint(0, len(headers) + 2))]
            for _ in range(rng.randint(0, 15))
        ]
        sheet = "Programme" if rng.random() < 0.8 else "Feuil1"
        path = write_rows(tmp_path / f"fuzz{k}.xlsx", rows, headers=headers, sheet=sheet)
        program, report = read_program(path)
        assert (program is None) == bool(report.errors)
        for issue in report.issues:
            assert issue.code in allowed, issue
            assert issue.value is None or len(issue.value) <= 80
            seen.add(issue.code)
    assert len(seen) >= 8  # the fuzz exercises many paths


# --------------------------------------------------------------------------- extra cases


def test_canon_header() -> None:
    assert canon_header("  Surface   (m²) ") == "surface"
    assert canon_header("LARGEUR MIN (M)") == "largeur min"
    assert canon_header("Éviter") == "eviter"


def test_unreadable_workbook(tmp_path: Path) -> None:
    bad = tmp_path / "pas_un_classeur.xlsx"
    bad.write_text("ceci n'est pas un zip", encoding="utf-8")
    program, report = read_program(bad)
    assert program is None
    assert [i.code for i in report.issues] == ["E_FILE_UNREADABLE"]
    program, report = read_program(tmp_path / "absent.xlsx")
    assert [i.code for i in report.issues] == ["E_FILE_UNREADABLE"]


def test_empty_sheet_and_no_rooms(tmp_path: Path) -> None:
    wb = openpyxl.Workbook()
    wb.active.title = "Programme"
    wb.save(tmp_path / "empty.xlsx")
    program, report = read_program(tmp_path / "empty.xlsx")
    assert program is None
    assert [i.code for i in report.issues] == ["E_MISSING_COLUMN"] * 4

    program, report = read_rows(tmp_path, [[None] * 17, row(ID="# seulement un commentaire")])
    assert program is None
    assert codes(report) == [("E_NO_ROOMS", None)]


def test_cell_type_variants(tmp_path: Path) -> None:
    rows = [
        good_row(101, Facade=True, Niveau="0", Largeur="2,5", Adjacent=102),  # type: ignore[arg-type]
        good_row(102.0, Facade=False, Quantite="4", Nom=12345),  # type: ignore[arg-type]
        good_row("R03", Facade=1.0, Zone=" services ", Remarques="libre"),
    ]
    program, report = read_rows(tmp_path, rows)
    assert report.errors == (), report.issues
    r1, r2, r3 = program.rooms
    assert (r1.id, r1.needs_facade, r1.min_width_m, r1.adjacent_to) == ("101", True, 2.5, ("102",))
    assert (r2.id, r2.needs_facade, r2.quantity, r2.name) == ("102", False, 4, "12345")
    assert (r3.needs_facade, r3.macro_zone) == (True, MacroZone.SERVICES)
    assert report.rows == {"101": 2, "102": 3, "R03": 4}
    assert report.types == ("office",)


def test_bad_cell_types(tmp_path: Path) -> None:
    when = dt.datetime(2024, 5, 1)
    rows = [
        good_row(1.5),  # type: ignore[arg-type]
        good_row("R02", Type=42, Facade=2, Zone=7),
        good_row("R03", Nom="x" * 121, Quantite=True, Largeur="abc"),
        good_row("R04", Adjacent=when, N="haut", Niveau="rez"),
        good_row("R05", Surface=float("nan")),
    ]
    program, report = read_rows(tmp_path, rows)
    assert program is None
    assert codes(report) == [
        ("E_BAD_ID", 2),
        ("E_UNKNOWN_TYPE", 3),
        ("E_ZONE", 3),
        ("E_FACADE", 3),
        ("E_EMPTY_NAME", 4),
        ("E_QUANTITY", 4),
        ("E_MIN_WIDTH", 4),
        ("E_ORIENTATION", 5),
        ("E_REF_UNKNOWN", 5),
        ("E_FLOOR", 5),
        ("E_AREA", 6),
    ]
    assert len(report.issues[4].value or "") <= 80


def test_duplicate_header_and_blank_header(tmp_path: Path) -> None:
    headers = [*HEADERS[:4], None, "id"]
    program, report = read_rows(tmp_path, [[*good_row()[:4], "ignoré", "R99"]], headers=headers)
    assert program is not None
    assert program.rooms[0].id == "R01"
    assert codes(report) == [("W_UNKNOWN_COLUMN", 1), ("W_ZONE_DEFAULTED", 2)]


def test_issues_from_validation_error() -> None:
    with pytest.raises(ValidationError) as info:
        RoomSpec.model_validate(
            {
                "id": "R1",
                "name": "x",
                "type": "office",
                "target_area_m2": -1.0,
                "macro_zone": "PUBLIC",
                "adjacent_to": ("R1",),
            }
        )
    issues = issues_from_validation_error(info.value, row=7)
    assert {i.code for i in issues} <= {"E_AREA", "E_REF_UNKNOWN"}
    assert all(i.row == 7 for i in issues)
    with pytest.raises(ValidationError) as info2:
        from ale.contracts.models import Program

        Program.model_validate({"rooms": [{"id": "A", "name": "a", "type": "office"}]})
    issues = issues_from_validation_error(info2.value, rows=[9])
    by_code = {i.code: i.row for i in issues}
    assert by_code["E_AREA"] == 9
    assert by_code["E_ZONE"] == 9
    assert set(by_code) <= {"E_AREA", "E_ZONE", "E_NO_ROOMS"}
    issues = issues_from_validation_error(info2.value, rows=[])
    assert all(i.row is None for i in issues)
