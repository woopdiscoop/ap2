"""I.1 N5: offline review, database selection, escaped markup and previews."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import pytest
from extract_helpers import execute, plan_doc, query, save_doc
from typer.testing import CliRunner

from ale.cli import app
from ale.corpus.extract import run_extract
from ale.corpus.ingest import ingest
from ale.corpus.review import run_review
from ale.workspace import Workspace, WorkspaceError


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows = 0
        self.svgs = 0
        self.scripts = 0
        self.external: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self.rows += tag == "tr" and values.get("class") == "plan"
        self.svgs += tag == "svg"
        self.scripts += tag == "script"
        self.external.extend(v for k, v in attrs if k in ("src", "href") and v)


def corpus(ws: Workspace, inp: Path) -> None:
    pytest.importorskip("ezdxf")
    flagged = plan_doc(labels=True)
    flagged.modelspace().add_arc((0, 2000), 900, 0, 90, dxfattribs={"layer": "PORTES"})
    save_doc(flagged, inp / "flagged.dxf")
    doc = plan_doc(labels=True)
    doc.modelspace().add_text(
        "BUREAU", dxfattribs={"layer": "TEXTE LOCAUX", "height": 200}
    ).set_placement((7000, 2500))
    save_doc(doc, inp / "clean.dxf")
    ingest(ws, inp)
    assert run_extract(ws).extracted == 2


def test_N5_review_page(tmp_workspace: Workspace, tmp_path: Path) -> None:
    corpus(tmp_workspace, tmp_path / "input")
    flags = query(tmp_workspace, "SELECT sha256, page, plan_index, flag FROM review_flags")
    assert flags
    runner = CliRunner()
    args = ["review", "--workspace", str(tmp_workspace.root)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    target = tmp_workspace.path("review", "index.html")
    assert str(target) in result.stdout
    parsed = PageParser()
    parsed.feed(target.read_text(encoding="utf-8"))
    assert parsed.rows == parsed.svgs == len({r[:3] for r in flags}) == 1
    assert parsed.scripts == 0 and not parsed.external
    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["path"] == str(target)
    for row in data["plans"]:
        assert row["flags"] == sorted(
            r[3] for r in flags if r[:3] == (row["sha256"], row["page"], row["plan_index"])
        )
        assert row["typed"] + row["untyped"] == row["room_count"]
        assert 'data-frame="Y_UP"' in row["preview_svg"]
        assert 'stroke="black"' in row["preview_svg"]
        assert 'stroke="red"' in row["preview_svg"]
        assert 'fill="#bdbdbd"' in row["preview_svg"]
    result = runner.invoke(app, [*args, "--all", "--json"])
    assert result.exit_code == 0, result.output
    all_rows = json.loads(result.stdout)["plans"]
    assert len(all_rows) == 2
    assert sum(not r["flags"] for r in all_rows) == 1
    parsed = PageParser()
    parsed.feed(target.read_text(encoding="utf-8"))
    assert parsed.rows == parsed.svgs == 2
    before = (target.read_bytes(), target.stat().st_mtime_ns)
    assert runner.invoke(app, [*args, "--all"]).exit_code == 0
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before


def test_review_escapes_metadata(tmp_workspace: Workspace, tmp_path: Path) -> None:
    corpus(tmp_workspace, tmp_path / "input")
    execute(
        tmp_workspace,
        "UPDATE file_paths SET rel_path = ? WHERE rel_path = 'flagged.dxf'",
        ('<script>alert("bad")</script>&.dxf',),
    )
    report = run_review(tmp_workspace)
    text = report.path.read_text(encoding="utf-8")
    assert "&lt;script&gt;" in text and "&amp;.dxf" in text
    parser = PageParser()
    parser.feed(text)
    assert parser.scripts == 0


def test_review_empty_and_missing_plan(tmp_workspace: Workspace, tmp_path: Path) -> None:
    report = run_review(tmp_workspace)
    assert not report.plans and report.path.is_file()
    corpus(tmp_workspace, tmp_path / "input")
    for path in tmp_workspace.path("extracted").rglob("plan.json"):
        path.unlink()
    with pytest.raises(WorkspaceError, match=r"No extracted plan\.json"):
        run_review(tmp_workspace)
    result = CliRunner().invoke(app, ["review", "--workspace", str(tmp_workspace.root)])
    assert result.exit_code == 4


def test_review_corrupt_and_mismatched_plan(tmp_workspace: Workspace, tmp_path: Path) -> None:
    corpus(tmp_workspace, tmp_path / "input")
    path = next(tmp_workspace.path("extracted").rglob("plan.json"))
    original = path.read_bytes()
    path.write_bytes(b"invalid")
    with pytest.raises(WorkspaceError, match="Cannot review"):
        run_review(tmp_workspace)
    value = json.loads(original)
    value["plan_index"] = 99
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(WorkspaceError, match="identity"):
        run_review(tmp_workspace)


def test_review_y_down(tmp_workspace: Workspace, tmp_path: Path) -> None:
    from test_integration_eval import png_plan

    png_plan(tmp_path / "input/plan.png")
    ingest(tmp_workspace, tmp_path / "input")
    assert run_extract(tmp_workspace).extracted == 1
    report = run_review(tmp_workspace)
    svg = report.plans[0]["preview_svg"]
    assert 'data-frame="Y_UP"' in svg and 'transform="scale(1,-1)"' in svg
    assert ",-" in svg  # raster native y is positive, y-up geometry is negative
