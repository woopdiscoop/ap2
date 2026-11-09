"""I.1 N1-N4, N6-N9: generated inputs through the public corpus/CLI APIs."""

from __future__ import annotations

import json
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from extract_helpers import Invoke, execute, plan_doc, query, save_doc, unit_of

from ale.contracts.enums import LabelSource, ScaleMethod
from ale.contracts.models import PlanGeometry
from ale.corpus.db import connect, migrate
from ale.corpus.extract import plan_path, run_extract
from ale.corpus.ingest import ingest
from ale.workspace import Workspace


def load_plan(ws: Workspace, name: str) -> PlanGeometry:
    sha, page, *_ = unit_of(ws, name)
    return PlanGeometry.model_validate_json(plan_path(ws, sha, page, 0).read_bytes())


def png_plan(path: Path) -> Path:
    cv2 = pytest.importorskip("cv2")
    from raster_helpers import plan_image

    path.parent.mkdir(parents=True, exist_ok=True)
    image = plan_image()
    # Close the two generated door gaps: no physical scale anchor in this fixture.
    image[200:240, 500:508] = 0
    image[396:404, 780:830] = 0
    ok, data = cv2.imencode(".png", image)
    assert ok
    path.write_bytes(data.tobytes())
    return path


def test_N1_pdf_vector(tmp_workspace: Workspace, tmp_path: Path) -> None:
    fitz = pytest.importorskip("pymupdf")
    from pdf_helpers import reference_page, text_page

    inp = tmp_path / "input"
    inp.mkdir()
    with fitz.open() as doc:
        reference_page()(doc.new_page(width=595, height=842))
        page = doc.new_page(width=595, height=842)
        text_page(page)
        # A decorative path classifies the text page as vector without making it a plan.
        page.draw_line((20, 20), (500, 20))
        doc.save(inp / "mixed.pdf")
    ingest(tmp_workspace, inp)
    report = run_extract(tmp_workspace)
    rows = query(tmp_workspace, "SELECT sha256, page, status, reason FROM units ORDER BY page")
    assert report.extracted == 1 and report.excluded == 1
    assert rows[0][2:] == ("EXTRACTED", None)
    assert rows[1][2] == "EXCLUDED" and rows[1][3].startswith("not a plan (score ")
    plan = PlanGeometry.model_validate_json(plan_path(tmp_workspace, rows[0][0], 0, 0).read_bytes())
    assert plan.scale_method is ScaleMethod.TITLE_BLOCK
    assert len(plan.rooms) == 2
    assert all(r.type and r.label_source is LabelSource.PDF_TEXT for r in plan.rooms)
    assert report.by_kind == {"PDF_VECTOR": 1}


def test_N2_scanned_and_raster(tmp_workspace: Workspace, tmp_path: Path) -> None:
    fitz = pytest.importorskip("pymupdf")
    inp = tmp_path / "input"
    png = png_plan(inp / "plan.png")
    with fitz.open() as doc:
        # 288 x 192 pt at default 300 dpi renders exactly 1200 x 800 pixels.
        page = doc.new_page(width=288, height=192)
        page.insert_image(page.rect, stream=png.read_bytes())
        doc.save(inp / "scan.pdf")
    ingest(tmp_workspace, inp)
    report = run_extract(tmp_workspace)
    assert report.extracted == 2 and report.failed == 0
    assert report.by_kind == {"PDF_SCANNED": 1, "RASTER": 1}
    for name in ("plan.png", "scan.pdf"):
        plan = load_plan(tmp_workspace, name)
        assert plan.scale_method is ScaleMethod.UNKNOWN
        assert plan.scale_m_per_unit is None
        assert ("scale_unknown",) in query(
            tmp_workspace, "SELECT flag FROM review_flags WHERE sha256 = ?", (plan.source_sha256,)
        )


def test_N3_meta_scale(tmp_workspace: Workspace, tmp_path: Path) -> None:
    inp = tmp_path / "input"
    png_plan(inp / "plan.png")
    meta = tmp_path / "plans_meta.csv"
    meta.write_text(
        "filename,page,scale_1_to,dpi,north_angle_deg\n"
        "plan.png,,200,300,12.5\nplan.png,0,100,150,37.5\n",
        encoding="utf-8",
    )
    ingest(tmp_workspace, inp, meta=meta)
    run_extract(tmp_workspace)
    plan = load_plan(tmp_workspace, "plan.png")
    assert plan.scale_method is ScaleMethod.META_CSV
    assert plan.scale_m_per_unit == pytest.approx(100 * 0.0254 / 150)
    stored = json.loads(query(tmp_workspace, "SELECT meta_json FROM files")[0][0])
    assert stored["north_angle_deg"] == 12.5
    assert stored["pages"]["0"]["north_angle_deg"] == 37.5
    assert stored["pages"]["0"]["dpi"] == 150


def test_N4_cad_also_labelled(tmp_workspace: Workspace, tmp_path: Path) -> None:
    pytest.importorskip("ezdxf")
    from ale.cad import propose_layer_map, read_cad
    from ale.join import resolve_scale, review_flags
    from ale.labels import VlmCache, label_plan

    inp = tmp_path / "input"
    path = save_doc(plan_doc(labels=True), inp / "plan.dxf")
    ingest(tmp_workspace, inp)
    sha = unit_of(tmp_workspace, "plan.dxf")[0]
    raw = read_cad(
        path,
        source_sha256=sha,
        layer_map=propose_layer_map(["MUR", "TEXTE LOCAUX"]),
        config=tmp_workspace.config,
    ).plans[0]
    expected = label_plan(
        resolve_scale(raw, meta={}, config=tmp_workspace.config),
        image=None,
        provider=None,
        cache=VlmCache.for_workspace(tmp_workspace),
        config=tmp_workspace.config,
    ).plan
    report = run_extract(tmp_workspace)
    assert report.extracted == 1
    actual = load_plan(tmp_workspace, "plan.dxf")
    assert actual == expected
    assert actual.walls == raw.walls and actual.texts == raw.texts
    assert [r.polygon for r in actual.rooms] == [r.polygon for r in raw.rooms]
    assert {r[0] for r in query(tmp_workspace, "SELECT flag FROM review_flags")} == set(
        review_flags(actual)
    )
    assert any(r.label_source is LabelSource.CAD_TEXT for r in actual.rooms)


def test_N6_migration(tmp_workspace: Workspace) -> None:
    with closing(connect(tmp_workspace.path("corpus.sqlite"))) as conn:
        migrate(conn)
        # Restore a genuine v1 table set with existing content, including ale_meta.
        conn.execute("DROP TABLE review_flags")
        conn.execute("PRAGMA user_version = 1")
        conn.execute("INSERT INTO inputs (root, added_at) VALUES ('input', 'old')")
        conn.commit()
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        before = {t: conn.execute(f'SELECT * FROM "{t}"').fetchall() for t in tables}
        assert migrate(conn) == 1
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert conn.execute("SELECT * FROM review_flags").fetchall() == []
        assert {t: conn.execute(f'SELECT * FROM "{t}"').fetchall() for t in tables} == before
        changes = conn.total_changes
        assert migrate(conn) == 2
        assert conn.total_changes == changes


def test_N7_idempotent(tmp_workspace: Workspace, tmp_path: Path) -> None:
    inp = tmp_path / "input"
    png_plan(inp / "plan.png")
    ingest(tmp_workspace, inp)
    assert run_extract(tmp_workspace).extracted == 1
    paths = [
        *tmp_workspace.path("extracted").rglob("plan.json"),
        tmp_workspace.path("corpus.sqlite"),
    ]
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    assert run_extract(tmp_workspace, only_new=True).selected == 0
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths] == before
    execute(tmp_workspace, "UPDATE units SET status='NEW'")
    run_extract(tmp_workspace)
    assert len(query(tmp_workspace, "SELECT * FROM review_flags")) == 2


def test_N8_stubs(tmp_workspace: Workspace, invoke: Invoke) -> None:
    result = invoke(["review", "--workspace", str(tmp_workspace.root), "--json"])
    assert result.exit_code == 0 and "not implemented" not in result.output
    assert json.loads(result.stdout)["plans"] == []
    repo = Path(__file__).resolve().parents[2]
    assert '"review": "1.6"' not in (repo / "tests/cli/test_cli_surface.py").read_text(
        encoding="utf-8"
    )


@pytest.mark.timeout(180)
def test_N9_gates() -> None:
    """Executable static gates; full-suite and corpus coverage measured in the report."""
    for extra in ("ezdxf", "pymupdf", "cv2", "PIL", "pandas", "openpyxl"):
        pytest.importorskip(extra)
    repo = Path(__file__).resolve().parents[2]
    for args in (
        ("ale.contracts.lock", "--check"),
        ("ruff", "check", "."),
        ("ruff", "format", "--check", "."),
        ("mypy",),
    ):
        result = subprocess.run(
            [sys.executable, "-m", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
