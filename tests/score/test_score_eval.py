"""Ticket R.10 evaluation S1001-S1008 (synthetic PDFs, DXFs and workbooks only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from score_helpers import (
    SHA,
    area_text,
    grid_of,
    save_annexe,
    save_dxf_sheet,
    save_programme,
    save_sheet,
    spec,
)
from typer.testing import CliRunner

from ale.cli import app
from ale.contracts.config import AleConfig
from ale.contracts.lock import main as lock_main
from ale.pdfread import read_pdf_page
from ale.program.annexe import read_annexe
from ale.program.annexe import write_outputs as annexe_outputs
from ale.score import (
    Line,
    assign,
    build_score,
    extract_sheet,
    lines_from_program,
    match_lines,
    render_markdown,
)
from ale.score.report import classify

pytest.importorskip("openpyxl")


def _run(*args: str) -> Any:
    try:  # click < 8.2 needs mix_stderr=False
        runner = CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        runner = CliRunner()
    return runner.invoke(app, ["score", *args])


def _score(tmp: Path, pdf: Path, prog: Path, *extra: str, name: str = "out") -> dict[str, Any]:
    out = tmp / name
    res = _run("--plan", str(pdf), "--programme", str(prog), "--out", str(out), *extra)
    assert res.exit_code == 0, res.output + str(res.stderr)
    data: dict[str, Any] = json.loads((out / "score.json").read_text(encoding="utf-8"))
    return data


def _statuses(data: dict[str, Any]) -> dict[str, str]:
    return {m["line"]: m["status"] for m in data["matches"]}


def test_S1001_match(tmp_path: Path) -> None:
    targets = [10.0, 13.0, 17.0, 22.0, 28.0, 36.0, 47.0, 61.0, 79.0, 103.0, 134.0, 174.0]
    devs = [0.0, 0.03, -0.05, 0.08, -0.08, 0.02, -0.03, 0.05, 0.0, -0.02, 0.04, -0.06]
    drawn = [t * (1 + d) for t, d in zip(targets, devs, strict=True)]
    pdf = save_sheet(tmp_path / "sheet.pdf", [grid_of(drawn[:6], 3), grid_of(drawn[6:], 3)])
    prog = save_programme(
        tmp_path / "prog.xlsx",
        [spec(f"R{i:02d}", f"Pièce {i}", t) for i, t in enumerate(targets, start=1)],
    )
    data = _score(tmp_path, pdf, prog)
    assert data["coverage"]["matched"] == 12
    assert data["coverage"]["unmatched_lines"] == [] and data["coverage"]["unmatched_rooms"] == []
    by_line = {m["line"]: m for m in data["matches"]}
    for i, a in enumerate(drawn, start=1):
        m = by_line[f"R{i:02d}"]
        assert m["area_m2"] == pytest.approx(a, abs=0.01)  # the right room
        assert m["plan"] == (1 if i <= 6 else 2)  # plan index reported
        assert m["area_source"] == "texte"
    assert [p["plan"] for p in data["totals"]["plans"]] == [1, 2]
    assert data["totals"]["building"]["matched"] == 12


def test_S1002_tolerance(tmp_path: Path) -> None:
    targets = {"A": 20.0, "B": 40.0, "C": 60.0, "D": 80.0}
    drawn = [20.0 * 0.97, 40.0 * 0.92, 60.0 * 1.12, 80.0]
    pdf = save_sheet(tmp_path / "s.pdf", [grid_of(drawn, 2)])
    prog = save_programme(
        tmp_path / "p.xlsx", [spec(k, f"Bureau {k}", v) for k, v in targets.items()]
    )
    st = _statuses(_score(tmp_path, pdf, prog, name="d5"))
    assert st == {
        "A": "a_ajuster",
        "B": "sous_programme",
        "C": "au_dessus",
        "D": "conforme",
    }
    md = (tmp_path / "d5" / "score.md").read_text(encoding="utf-8")
    assert "« à ajuster »" in md and "« sous le programme »" in md
    assert "« au-dessus de la tolérance »" in md
    st10 = _statuses(_score(tmp_path, pdf, prog, "--tolerance-pct", "10", name="d10"))
    assert st10["B"] == "a_ajuster" and st10["C"] == "au_dessus"
    assert classify(0.07, 5.0) == "a_ajuster"  # between the tolerance and +10 %
    assert classify(0.0, 5.0) == "conforme"


def test_S1003_unmatched(tmp_path: Path) -> None:
    pdf = save_sheet(tmp_path / "s.pdf", [grid_of([20.0, 40.0, 300.0], 3)])
    prog = save_programme(
        tmp_path / "p.xlsx",
        [
            spec("A", "Bureau A", 20.0),
            spec("B", "Bureau B", 40.0),
            spec("C", "Grande salle", 100.0),
        ],
    )
    data = _score(tmp_path, pdf, prog)
    cov = data["coverage"]
    assert [x["line"] for x in cov["unmatched_lines"]] == ["C"]
    assert [x["area_m2"] for x in cov["unmatched_rooms"]] == [300.0]
    md = (tmp_path / "out" / "score.md").read_text(encoding="utf-8")
    assert "Grande salle" in md and "300,0 m²" in md


def test_S1004_facade(tmp_path: Path) -> None:
    areas = [11.0, 12.0, 25.0, 14.0, 55.0, 16.0, 17.0, 18.0, 19.0]  # centre cell = 55 m²
    pdf = save_sheet(tmp_path / "s.pdf", [grid_of(areas, 3)])
    prog = save_programme(
        tmp_path / "p.xlsx",
        [
            spec("INT", "Salle intérieure", 55.0, facade=True),
            spec("EDG", "Bureau d'angle", 25.0, facade=True),
            spec("FREE", "Archive", 17.0, facade=False),
        ],
    )
    data = _score(tmp_path, pdf, prog)
    rows = {m["line"]: m for m in data["matches"]}
    assert rows["INT"]["facade"] == "signale"
    assert rows["EDG"]["facade"] == "ok"
    assert rows["FREE"]["facade"] is None
    md = (tmp_path / "out" / "score.md").read_text(encoding="utf-8")
    assert "façade manquante" in md


def test_S1005_stairs(tmp_path: Path) -> None:
    prog = save_programme(tmp_path / "p.xlsx", [spec("A", "Bureau A", 20.0)])

    def sheet(stairs: set[int], name: str) -> dict[str, Any]:
        cells = grid_of([20.0, 12.0, 30.0, 33.0, 12.0, 41.0], 3)
        cells = [
            [(a, "ESCALIER" if 3 * j + i in stairs else None) for i, (a, _) in enumerate(row)]
            for j, row in enumerate(cells)
        ]
        pdf = save_sheet(tmp_path / f"{name}.pdf", [cells])
        return _score(tmp_path, pdf, prog, name=name)

    one = sheet({1}, "one")["stairs"]
    assert one["stair_rooms"] == 1
    assert one["plans"] == [{"plan": 1, "cores": 1, "status": "ok"}]
    two_same_core = sheet({1, 4}, "same")["stairs"]  # two stairs stacked in one core (U-14)
    assert two_same_core["stair_rooms"] == 2
    assert two_same_core["plans"][0] == {"plan": 1, "cores": 1, "status": "ok"}
    apart = sheet({0, 2}, "apart")["stairs"]
    assert apart["plans"][0]["cores"] == 2 and apart["plans"][0]["status"] == "a_verifier"
    none = sheet(set(), "none")["stairs"]
    assert none["plans"][0] == {"plan": 1, "cores": 0, "status": "absente"}
    md = (tmp_path / "one" / "score.md").read_text(encoding="utf-8")
    assert "une seule cage requise" in md
    assert "Pièces d'escalier repérées : 1" in md


def test_S1006_annexe(tmp_path: Path) -> None:
    annexe = save_annexe(
        tmp_path / "annexe.xlsx",
        [
            ("ACCUEIL", "Loge gardien", 1, 12),
            ("ACCUEIL", "Bureau d'ordre", 1, 16),
            ("ESPACE COMMUN", "Salle de prière", 1, 30),
        ],
    )
    pdf = save_sheet(tmp_path / "s.pdf", [grid_of([12.5, 15.5, 29.0], 3)])
    res = _run("--plan", str(pdf), "--annexe", str(annexe), "--out", str(tmp_path / "a"))
    assert res.exit_code == 0, res.output + str(res.stderr)
    via_annexe = json.loads((tmp_path / "a" / "score.json").read_text(encoding="utf-8"))
    assert via_annexe["coverage"]["matched"] == 3
    written = annexe_outputs(read_annexe(annexe).buildings, tmp_path / "imp")
    xlsx = next(p for p in written if p.suffix == ".xlsx")
    via_prog = _score(tmp_path, pdf, xlsx, name="b")
    for key in ("coverage", "matches", "totals", "stairs"):
        assert via_annexe[key] == via_prog[key]
    # usage errors
    assert _run("--plan", str(pdf), "--out", str(tmp_path / "x")).exit_code == 2
    both = _run("--plan", str(pdf), "--annexe", str(annexe), "--programme", str(xlsx))
    assert both.exit_code == 2
    assert _run("--plan", str(pdf), "--annexe", str(annexe), "--building", "nope").exit_code == 1


def test_S1007_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = save_sheet(tmp_path / "s.pdf", [grid_of([20.0, 40.0, 60.0], 3)])
    prog = save_programme(
        tmp_path / "p.xlsx", [spec("A", "Bureau A", 21.0), spec("B", "Bureau B", 40.0)]
    )
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    before = {p for p in tmp_path.rglob("*")}
    _score(tmp_path, pdf, prog, name="one")
    _score(tmp_path, pdf, prog, name="two")
    new = {p for p in tmp_path.rglob("*")} - before
    outside = [
        p
        for p in new
        if not any(d in p.parents or p == d for d in (tmp_path / "one", tmp_path / "two"))
    ]
    assert outside == []
    assert sorted(p.name for p in (tmp_path / "one").iterdir()) == ["score.json", "score.md"]
    for name in ("score.md", "score.json"):
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()
    md = (tmp_path / "one" / "score.md").read_text(encoding="utf-8")
    for heading in (
        "## Couverture du programme",
        "## Surfaces",
        "## Façade",
        "## Circulation verticale",
        "## Limites",
    ):
        assert heading in md
    data = json.loads((tmp_path / "one" / "score.json").read_text(encoding="utf-8"))
    assert data["schema"] == "ale.score/1" and str(tmp_path) not in json.dumps(data)


def test_S1008_gates() -> None:
    """Contracts untouched (lock --check); ruff/mypy/coverage run as commands (eval_report)."""
    assert lock_main(["--check"]) == 0


# --------------------------------------------------------------------------- units (coverage)


def test_assign_rectangular_and_empty() -> None:
    assert assign([]) == []
    cost = [[4.0, 1.0, 3.0], [2.0, 0.0, 5.0]]
    pairs = assign(cost)
    assert sum(cost[i][j] for i, j in pairs) == 3.0  # optimal: 1 + 2
    tall = [[4.0, 2.0], [1.0, 0.0], [3.0, 5.0]]
    pairs = assign(tall)
    assert len(pairs) == 2
    assert sum(tall[i][j] for i, j in pairs) == 3.0


def test_name_halves_the_cost(tmp_path: Path) -> None:
    pdf = save_sheet(
        tmp_path / "s.pdf",
        [
            [
                [(area_text(20.0), "BUREAU"), (area_text(21.0), "SALLE DE REUNION"), (None, None)],
                [(None, None), (None, None), (None, None)],
            ]
        ],
    )
    res = read_pdf_page(pdf, 0, source_sha256=SHA, config=AleConfig())
    sheet = extract_sheet(res.plans)
    assert {r.type for r in sheet.rooms} == {"office", "meeting_room", None}
    lines = [
        Line("M", "Salle de réunion", "meeting_room", 20.5, False),
        Line("O", "Bureau", "office", 20.5, False),
    ]
    rooms = [r for r in sheet.rooms if r.type is not None]
    got = {lines[m.line].key: rooms[m.room].type for m in match_lines(lines, rooms)}
    assert got == {"M": "meeting_room", "O": "office"}  # the names break the area tie


def test_quantity_expands(tmp_path: Path) -> None:
    from ale.contracts.models import Program

    prog = Program(
        rooms=(spec("B", "Bureau", 16.0, qty=2), spec("S", "Escalier", 10.0, type_="stair"))
    )
    lines = lines_from_program(prog)
    assert [ln.key for ln in lines] == ["B.1", "B.2"]  # the stair line is scored apart


def test_dxf_plan(tmp_path: Path) -> None:
    dxf = save_dxf_sheet(tmp_path / "plan.dxf", [])
    prog = save_programme(tmp_path / "p.xlsx", [spec("A", "Bureau A", 18.7), spec("B", "B", 18.2)])
    res = _run("--plan", str(dxf), "--programme", str(prog), "--out", str(tmp_path / "o"))
    assert res.exit_code == 0, res.output + str(res.stderr)
    data = json.loads((tmp_path / "o" / "score.json").read_text(encoding="utf-8"))
    assert data["coverage"]["matched"] == 2
    assert {m["area_source"] for m in data["matches"]} == {"géométrie"}


def test_cli_errors(tmp_path: Path) -> None:
    prog = save_programme(tmp_path / "p.xlsx", [spec("A", "Bureau A", 20.0)])
    assert _run("--plan", str(tmp_path / "none.pdf"), "--programme", str(prog)).exit_code == 1
    txt = tmp_path / "plan.txt"
    txt.write_text("x", encoding="utf-8")
    assert _run("--plan", str(txt), "--programme", str(prog)).exit_code == 2
    dwg = tmp_path / "plan.dwg"
    dwg.write_bytes(b"AC1018 not a drawing")
    assert _run("--plan", str(dwg), "--programme", str(prog)).exit_code == 1
    bad_dxf = tmp_path / "bad.dxf"
    bad_dxf.write_text("not a dxf", encoding="utf-8")
    assert _run("--plan", str(bad_dxf), "--programme", str(prog)).exit_code == 1
    empty = tmp_path / "empty.pdf"
    import pymupdf

    doc = pymupdf.open()
    doc.new_page()
    doc.save(empty)
    doc.close()
    assert _run("--plan", str(empty), "--programme", str(prog)).exit_code == 1
    bad_prog = tmp_path / "bad.xlsx"
    bad_prog.write_text("nope", encoding="utf-8")
    pdf = save_sheet(tmp_path / "s.pdf", [grid_of([20.0], 1)])
    assert _run("--plan", str(pdf), "--programme", str(bad_prog)).exit_code == 1
    bad_annexe = tmp_path / "bad_annexe.xlsx"
    bad_annexe.write_text("nope", encoding="utf-8")
    assert _run("--plan", str(pdf), "--annexe", str(bad_annexe)).exit_code == 1


def test_no_scale_uses_text_only(tmp_path: Path) -> None:
    import pymupdf
    from score_helpers import draw_grid_plan

    doc = pymupdf.open()
    page = doc.new_page(width=900, height=500)
    draw_grid_plan(page, 1.0, [[(area_text(20.0), None), (None, None)]])  # no scale title
    pdf = tmp_path / "noscale.pdf"
    doc.save(pdf)
    doc.close()
    res = read_pdf_page(pdf, 0, source_sha256=SHA, config=AleConfig())
    sheet = extract_sheet(res.plans)
    assert [r.area_m2 for r in sheet.rooms] == [20.0]
    assert len(sheet.skipped) == 1 and any("échelle inconnue" in w for w in sheet.warnings)
    lines = [Line("A", "Bureau", "office", 20.0, False)]
    result = build_score(
        sheet, lines, plan_name="n.pdf", plan_sha256=SHA, page=1, programme_name="p.xlsx"
    )
    md = render_markdown(result.data)
    assert "sans surface exploitable" in md
    assert Path(result.data["plan"]["file"]).name == "n.pdf"
