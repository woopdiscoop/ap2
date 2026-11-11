"""Ticket A.4 eval A402 (site.yaml), A403, A404, A405, A406 (files), A407 (gates)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fixtures import load_program, load_site
from program_helpers import (
    HEADERS,
    good_row,
    program_to_xlsx,
    site_to_yaml,
    write_rows,
    write_site_yaml,
)
from typer.testing import CliRunner

from ale.cli import app
from ale.contracts.config import AleConfig
from ale.contracts.models import Program, SiteSpec
from ale.contracts.serialization import canonical_json
from ale.program import InputError, prepare_input, read_program
from ale.program.excel import ANCHOR_LABELS, COL_ANCHOR
from ale.program.site import read_site
from ale.program.template import TEMPLATE_PATH, write_template

openpyxl = pytest.importorskip("openpyxl")  # the 'excel' extra

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = AleConfig()
RECT = [[0, 0], [20, 0], [20, 10], [0, 10]]


def _runner() -> CliRunner:
    try:  # click < 8.2 needs mix_stderr=False to expose result.stderr separately
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


def _site(tmp: Path, **keys: Any) -> tuple[SiteSpec | None, list[tuple[str, str]]]:
    path = write_site_yaml(tmp / "site.yaml", {"footprint": RECT, **keys})
    site, issues = read_site(path)
    return site, [(i.code, i.message) for i in issues]


# ------------------------------------------------------------------------------ A402
def test_A402_site_yaml_valid(tmp_path: Path) -> None:
    site, issues = _site(
        tmp_path,
        entrances=[{"point": [10, 0], "label": "Principale", "main": True}, {"point": [0, 5]}],
        cores=[{"id": "N1", "rect": [0, 0, 3, 3], "kind": "stair"}],
        party_edges=[1],
    )
    assert issues == [] and site is not None
    assert site.entrances[0].label == "Principale" and site.entrances[0].main
    assert site.cores[0].kind == "stair" and site.party_edges == (1,)
    plot, issues = _site(tmp_path, mode="plot", setbacks=[1, 2, 3, 4])
    assert issues == [] and plot is not None
    assert plot.mode == "plot" and plot.setbacks == (1.0, 2.0, 3.0, 4.0)
    plain, issues = _site(tmp_path)
    assert issues == [] and plain is not None
    assert plain.entrances == () and plain.mode == "footprint" and plain.setbacks is None


@pytest.mark.parametrize(
    ("keys", "named"),
    [
        ({"entrances": [{"point": [10, 5]}]}, "entrances[0]"),  # off the boundary
        (
            {"entrances": [{"point": [0, 0], "main": True}, {"point": [20, 0], "main": True}]},
            "entrances",
        ),
        ({"entrances": [{"point": "x"}]}, "entrances[0].point"),
        ({"entrances": [{"point": [0, 0], "colour": 1}]}, "colour"),
        ({"entrances": "porte"}, "entrances"),
        ({"cores": [{"id": "C", "rect": [18, 0, 5, 3], "kind": "stair"}]}, "cores[0]"),
        (
            {
                "cores": [
                    {"id": "A", "rect": [0, 0, 4, 4], "kind": "stair"},
                    {"id": "B", "rect": [3, 3, 4, 4], "kind": "lift"},
                ]
            },
            "chevauche",
        ),
        ({"cores": [{"id": "C", "rect": [0, 0, 2, 2], "kind": "garage"}]}, "cores[0].kind"),
        ({"cores": [{"id": "C", "rect": [0, 0, 2], "kind": "core"}]}, "cores[0].rect"),
        ({"mode": "parcelle"}, "mode"),
        ({"mode": "plot", "setbacks": [1, 2, 3]}, "setbacks"),  # wrong count
        ({"setbacks": [1, 2, 3, 4]}, "setbacks"),  # mode footprint
        ({"mode": "plot", "setbacks": "x"}, "setbacks"),
        ({"party_edges": [4]}, "party_edges"),
        ({"party_edges": [1.5]}, "party_edges"),
    ],
)
def test_A402_site_yaml_invalid(tmp_path: Path, keys: dict[str, Any], named: str) -> None:
    site, issues = _site(tmp_path, **keys)
    assert site is None and issues
    assert all(code == "E_SITE_SCHEMA" for code, _ in issues)
    assert any(named in message for _, message in issues), issues


def test_A402_site_yaml_edges_follow_normalisation(tmp_path: Path) -> None:
    # Clockwise input with a collinear vertex: input edge i is remapped to the normalised ring
    # (CCW from the lowest-leftmost vertex), as access_edge is.
    cw = [[0, 0], [0, 10], [10, 10], [20, 10], [20, 0]]
    path = write_site_yaml(
        tmp_path / "s.yaml",
        {"footprint": cw, "access_edge": 3, "party_edges": [0, 1, 2], "mode": "plot"}
        | {"setbacks": [5, 4, 4, 3, 2]},
    )
    site, issues = read_site(path)
    assert issues == () and site is not None
    assert site.footprint.exterior == ((0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0))
    # input edges: 0 left, 1-2 top (merged), 3 right, 4 bottom
    assert site.access_edge == 1  # right
    assert site.party_edges == (2, 3)  # top and left
    assert site.setbacks == (2.0, 3.0, 4.0, 5.0)  # bottom, right, top, left
    bad = write_site_yaml(
        tmp_path / "t.yaml",
        {"footprint": cw, "mode": "plot", "setbacks": [5, 4, 9, 3, 2]},
    )
    none, issues = read_site(bad)
    assert none is None and "setbacks" in issues[0].message


# ------------------------------------------------------------------------------ A403
def _read(tmp: Path, cell: Any) -> Any:
    return read_program(write_rows(tmp / "p.xlsx", [good_row("R01", Ancrage=cell)]))


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("coin", "corner"),
        ("Coin", "corner"),
        ("  COIN ", "corner"),
        ("Entrée", "entrance"),
        ("entrée", "entrance"),
        ("ENTREE", "entrance"),
        ("Entree", "entrance"),
        (None, None),
        ("  ", None),
    ],
)
def test_A403_room_anchor_parsed(tmp_path: Path, cell: Any, expected: str | None) -> None:
    program, report = _read(tmp_path, cell)
    assert program is not None, report.issues
    assert program.rooms[0].anchor == expected


@pytest.mark.parametrize("cell", ["milieu", "coins", 3, True])
def test_A403_room_anchor_error_has_row(tmp_path: Path, cell: Any) -> None:
    program, report = read_program(
        write_rows(tmp_path / "p.xlsx", [good_row("R01"), good_row("R02", Ancrage=cell)])
    )
    assert program is None
    (issue,) = report.issues
    assert (issue.code, issue.row, issue.column) == ("E_ANCHOR", 3, "Ancrage")
    assert "coin" in issue.message and "entrée" in issue.message


def test_A403_column_optional_and_template(tmp_path: Path) -> None:
    # A workbook without the column (the 16 headers of before A.4) still loads.
    old = [h for h in HEADERS if h != "Ancrage"]
    full = good_row("R01")
    legacy = [v for h, v in zip(HEADERS, full, strict=True) if h != "Ancrage"]
    program, report = read_program(write_rows(tmp_path / "o.xlsx", [legacy], headers=old))
    assert program is not None, report.issues
    assert program.rooms[0].anchor is None

    for path in (write_template(tmp_path / "t.xlsx"), TEMPLATE_PATH):
        wb = openpyxl.load_workbook(path)
        ws = wb["Programme"]
        headers = [c.value for c in ws[1]]
        assert COL_ANCHOR in headers and headers == HEADERS
        letter = openpyxl.utils.get_column_letter(headers.index(COL_ANCHOR) + 1)
        dvs = [
            dv
            for dv in ws.data_validations.dataValidation
            if f"{letter}2:{letter}500" in str(dv.sqref)
        ]
        assert len(dvs) == 1 and dvs[0].type == "list"
        assert dvs[0].formula1 == '"Coin,Entrée"'
        assert list(ANCHOR_LABELS.values()) == ["Coin", "Entrée"]
        assert "Ancrage" in [r[0] for r in wb["Aide"].iter_rows(min_row=2, values_only=True)]


# ------------------------------------------------------------------------------ A404
def _floor_files(tmp: Path, floors: list[int]) -> tuple[Path, Path]:
    program = load_program("program_08")
    rooms = tuple(
        r.model_copy(update={"floor": floors[k % len(floors)]}) for k, r in enumerate(program.rooms)
    )
    xlsx = program_to_xlsx(Program(rooms=rooms), tmp / "p.xlsx")
    return xlsx, site_to_yaml(load_site("site_rect_small"), tmp / "s.yaml")


def test_A404_floors(tmp_path: Path, rulebook_path: Path) -> None:
    # Contract and Excel accept levels >= 0.
    program, report = read_program(
        write_rows(tmp_path / "f.xlsx", [good_row("R01", Niveau=2), good_row("R02", Niveau="1")])
    )
    assert program is not None, report.issues
    assert [r.floor for r in program.rooms] == [2, 1]
    for bad in (-1, 1.5, "rez"):
        none, report = read_program(write_rows(tmp_path / "b.xlsx", [good_row("R01", Niveau=bad)]))
        assert none is None
        assert [(i.code, i.row, i.column) for i in report.issues] == [("E_FLOOR", 2, "Niveau")]
    # Several floors: refused by prepare_input with a French error naming the levels.
    xlsx, yml = _floor_files(tmp_path, [0, 1])
    with pytest.raises(InputError) as info:
        prepare_input(xlsx, yml, rulebook_path, CONFIG)
    issue = next(i for i in info.value.issues if i.code == "E_FLOORS_MULTIPLE")
    assert issue.column == "Niveau" and issue.row is not None
    assert "plusieurs niveaux (0, 1)" in issue.message and "un seul niveau" in issue.message
    # Single-floor programmes are unchanged.
    xlsx, yml = _floor_files(tmp_path, [0])
    prepared = prepare_input(xlsx, yml, rulebook_path, CONFIG)
    assert prepared.instances == load_program("program_08").instances()
    assert all(r.floor == 0 for r in prepared.program.rooms)


# ------------------------------------------------------------------------------ A405
def _anchored(tmp: Path, anchors: dict[str, str], **site: Any) -> list[str]:
    program = load_program("program_08")
    rooms = tuple(r.model_copy(update={"anchor": anchors.get(r.id)}) for r in program.rooms)
    xlsx = program_to_xlsx(Program(rooms=rooms), tmp / "p.xlsx")
    base = {"footprint": [[0, 0], [10, 0], [10, 10], [0, 10]], "access_edge": 0, **site}
    yml = write_site_yaml(tmp / "s.yaml", base)
    rb = Path(__file__).parent / "data" / "rulebook_test.yaml"
    args = ["program", "check", "--program", str(xlsx), "--site", str(yml), "--rulebook", str(rb)]
    result = _runner().invoke(app, args)
    assert result.exit_code == 0, result.output
    return result.stdout.splitlines()


def test_A405_check_lists_anchors(tmp_path: Path) -> None:
    lines = _anchored(tmp_path, {"R01": "entrance", "R03": "corner", "R04": "corner"})
    text = "\n".join(lines)
    assert "Ancrages (3) :" in text
    assert "R01 (Hall d'entrée) : entrée" in text
    assert "R03" in text and "coin" in text
    # An entrance room but no entrance in the site: warning (the run still succeeds).
    assert "W_ANCHOR_NO_ENTRANCE" in text and "R01" in text
    assert "W_ANCHOR_CORNERS" not in text  # two corners of the four of a rectangle: fine
    assert "entrées du site : 0" in text

    with_entrance = _anchored(
        tmp_path, {"R01": "entrance"}, entrances=[{"point": [5, 0], "main": True}]
    )
    text = "\n".join(with_entrance)
    assert "W_ANCHOR_NO_ENTRANCE" not in text and "entrées du site : 1" in text

    # More corner rooms than corners.
    crowded = "\n".join(_anchored(tmp_path, {f"R0{k}": "corner" for k in (1, 2, 3, 4, 5)}))
    assert "W_ANCHOR_CORNERS" in crowded and "4 coins" in crowded

    plain = "\n".join(_anchored(tmp_path, {}))
    assert "Ancrages (0) :" in plain and "W_ANCHOR" not in plain


def test_A405_plot_mode_warning(tmp_path: Path) -> None:
    lines = _anchored(tmp_path, {}, mode="plot", setbacks=[1, 1, 1, 1])
    assert any("W_SITE_PLOT_MODE" in line for line in lines)


# ------------------------------------------------------------------------------ A406
def test_A406_round_trip_files(tmp_path: Path) -> None:
    site, issues = _site(
        tmp_path,
        entrances=[{"point": [10, 0], "label": "Principale", "main": True}, {"point": [0, 5]}],
        cores=[{"id": "N1", "rect": [1, 1, 2.5, 3], "kind": "stair"}],
        mode="plot",
        setbacks=[1, 2, 3, 4],
        party_edges=[2],
    )
    assert issues == [] and site is not None
    again, issues = read_site(site_to_yaml(site, tmp_path / "again.yaml"))
    assert issues == () and again == site
    assert canonical_json(again) == canonical_json(site)

    program = load_program("program_08")
    anchors = ["entrance", "corner", None, "corner", None, None, None]
    assert len(anchors) == len(program.rooms)
    rooms = tuple(
        r.model_copy(update={"anchor": a, "floor": 3})
        for r, a in zip(program.rooms, anchors, strict=True)
    )
    full = Program(rooms=rooms)
    back, report = read_program(program_to_xlsx(full, tmp_path / "full.xlsx"))
    assert back is not None, report.issues
    assert back == full and canonical_json(back) == canonical_json(full)

    # The template writer round-trips anchors too (Exemple sheet).
    wb = openpyxl.load_workbook(write_template(tmp_path / "t.xlsx"))
    assert wb["Exemple"].max_column == len(HEADERS)


# ------------------------------------------------------------------------------ A407
PATHS = ["src", "tests/contracts", "tests/program"]


@pytest.mark.timeout(600)
def test_A407_gates() -> None:
    def run(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", *argv],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=550,
            check=False,
        )

    assert run("ale.contracts.lock", "--check").returncode == 0
    assert run("ale.contracts.export_schemas", "--check").returncode == 0
    if importlib.util.find_spec("ruff") is None:  # pragma: no cover - dev extra installed
        pytest.skip("ruff not installed")
    for argv in (("ruff", "check", *PATHS), ("ruff", "format", "--check", *PATHS)):
        proc = run(*argv)
        assert proc.returncode == 0, proc.stdout + proc.stderr
    if importlib.util.find_spec("mypy") is None:  # pragma: no cover - dev extra installed
        pytest.skip("mypy not installed")
    proc = run("mypy", "src")
    assert proc.returncode == 0, proc.stdout + proc.stderr
