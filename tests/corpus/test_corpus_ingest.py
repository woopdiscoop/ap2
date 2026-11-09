"""Ticket 1.1 eval: corpus ingestion and classification (C01-C15)."""

from __future__ import annotations

import json
import os
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path

import pytest
from corpus_helpers import (
    HAS_FITZ,
    Invoke,
    count,
    dwg_bytes,
    encrypted_pdf,
    events,
    fake_pdf_bytes,
    pdf_three_pages,
    png_bytes,
    query,
    set_config,
    snapshot,
    units_of,
    write,
)

from ale.corpus.classify import DWG_NEEDS_TOOL_REASON, PDF_NEEDS_TOOL_REASON
from ale.corpus.db import migrate, read_status
from ale.corpus.ingest import ingest
from ale.workspace import Workspace, WorkspaceError, open_workspace

needs_fitz = pytest.mark.skipif(not HAS_FITZ, reason="pdf extra (PyMuPDF) not installed")


def test_C01_read_only(tmp_workspace: Workspace, input_dir: Path) -> None:
    write(input_dir / "broken.png", png_bytes()[:20])
    write(input_dir / "dup" / "a copy.png", png_bytes())
    write(input_dir / "pack.zip", b"PK\x03\x04")
    if HAS_FITZ:
        write(input_dir / "plans.pdf", pdf_three_pages())
    before = snapshot(input_dir)
    meta = input_dir.parent / "meta.csv"
    meta.write_text("filename,exclude\nb.jpg,1\n", encoding="utf-8")
    ingest(tmp_workspace, input_dir, meta=meta)
    ingest(tmp_workspace, input_dir, meta=meta)
    assert snapshot(input_dir) == before


def test_C02_idempotent(tmp_workspace: Workspace, input_dir: Path, db: Path) -> None:
    write(input_dir / "copy" / "a.png", png_bytes())  # a duplicate inside the input
    first = ingest(tmp_workspace, input_dir)
    assert first.files_seen == 6
    assert first.files_new == 5
    assert first.duplicates == 1
    assert first.units_new == 5
    files, units, paths = count(db, "files"), count(db, "units"), count(db, "file_paths")
    second = ingest(tmp_workspace, input_dir)
    assert second.files_new == 0
    assert second.units_new == 0
    assert second.duplicates == 0
    assert second.files_unchanged == second.files_seen == 6
    assert (count(db, "files"), count(db, "units"), count(db, "file_paths")) == (
        files,
        units,
        paths,
    )
    assert count(db, "inputs") == 1


def test_C02_touched_file_is_unchanged(tmp_workspace: Workspace, input_dir: Path, db: Path) -> None:
    ingest(tmp_workspace, input_dir)
    target = input_dir / "a.png"
    st = target.stat()
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    report = ingest(tmp_workspace, input_dir)
    assert report.files_unchanged == report.files_seen
    assert report.units_new == 0
    (mtime,) = query(db, "SELECT mtime_ns FROM file_paths WHERE rel_path = 'a.png'")[0]
    assert mtime == st.st_mtime_ns + 5_000_000_000


def test_C03_rename_move(tmp_workspace: Workspace, input_dir: Path, db: Path) -> None:
    ingest(tmp_workspace, input_dir)
    units_before = query(db, "SELECT id, sha256, page, kind, status FROM units ORDER BY id")
    (input_dir / "a.png").rename(input_dir / "renamed.png")
    (input_dir / "moved").mkdir()
    (input_dir / "b.jpg").rename(input_dir / "moved" / "b.jpg")
    report = ingest(tmp_workspace, input_dir)
    assert report.units_new == 0
    assert report.files_new == 0
    assert report.duplicates == 2
    assert query(db, "SELECT id, sha256, page, kind, status FROM units ORDER BY id") == units_before
    rels = {r[0] for r in query(db, "SELECT rel_path FROM file_paths")}
    assert {"renamed.png", "moved/b.jpg", "a.png", "b.jpg"} <= rels
    sha = query(db, "SELECT sha256 FROM file_paths WHERE rel_path = 'a.png'")[0][0]
    assert query(db, "SELECT sha256 FROM file_paths WHERE rel_path = 'renamed.png'")[0][0] == sha
    dup_paths = {json.loads(e[2])["rel_path"] for e in events(db, "duplicate")}
    assert dup_paths == {"renamed.png", "moved/b.jpg"}


def test_C04_modified(tmp_workspace: Workspace, input_dir: Path, db: Path) -> None:
    ingest(tmp_workspace, input_dir)
    old_sha = query(db, "SELECT sha256 FROM file_paths WHERE rel_path = 'a.png'")[0][0]
    old_units = query(db, "SELECT * FROM units WHERE sha256 = ?", (old_sha,))
    target = input_dir / "a.png"
    st = target.stat()
    target.write_bytes(png_bytes(4, 4, 200))
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    report = ingest(tmp_workspace, input_dir)
    assert report.files_new == 1
    assert report.units_new == 1
    new_sha = query(db, "SELECT sha256 FROM file_paths WHERE rel_path = 'a.png'")[0][0]
    assert new_sha != old_sha
    assert count(db, "files") == 6
    assert query(db, "SELECT * FROM units WHERE sha256 = ?", (old_sha,)) == old_units
    assert units_of(db, "a.png") == [(0, "RASTER", "NEW", None)]
    modified = events(db, "modified")
    assert len(modified) == 1
    assert json.loads(modified[0][2])["previous_sha256"] == old_sha


def test_C05_kinds(tmp_workspace: Workspace, input_dir: Path, db: Path) -> None:
    write(input_dir / "really_pdf.png", pdf_three_pages() if HAS_FITZ else fake_pdf_bytes())
    write(input_dir / "binary.dxf", b"AutoCAD Binary DXF\r\n\x1a\x00" + bytes(32))
    write(input_dir / "upper.PNG", png_bytes(3, 3))
    ingest(tmp_workspace, input_dir)
    assert units_of(db, "a.png") == [(0, "RASTER", "NEW", None)]
    assert units_of(db, "b.jpg") == [(0, "RASTER", "NEW", None)]
    assert units_of(db, "c.tif") == [(0, "RASTER", "NEW", None)]
    assert units_of(db, "upper.PNG") == [(0, "RASTER", "NEW", None)]
    assert units_of(db, "sub/d.dxf") == [(0, "DXF", "NEW", None)]
    assert units_of(db, "binary.dxf") == [(0, "DXF", "NEW", None)]
    assert [u[1] for u in units_of(db, "sub/e.dwg")] == ["DWG"]
    pdf_units = units_of(db, "really_pdf.png")
    assert pdf_units
    assert all(kind.startswith("PDF_") for _, kind, _, _ in pdf_units)
    if HAS_FITZ:
        assert len(pdf_units) == 3
    else:
        assert pdf_units == [(0, "PDF_SCANNED", "NEEDS_TOOL", PDF_NEEDS_TOOL_REASON)]
    mismatches = events(db, "kind_mismatch")
    assert len(mismatches) == 1
    detail = json.loads(mismatches[0][2])
    assert detail == {"rel_path": "really_pdf.png", "extension": "RASTER", "content": "PDF"}


@needs_fitz
def test_C06_pdf_pages(tmp_workspace: Workspace, tmp_path: Path, db: Path) -> None:
    root = tmp_path / "pdfs"
    write(root / "plans.pdf", pdf_three_pages())
    ingest(tmp_workspace, root)
    assert units_of(db, "plans.pdf") == [
        (0, "PDF_VECTOR", "NEW", None),
        (1, "PDF_SCANNED", "NEW", None),
        (2, "PDF_SCANNED", "NEW", None),
    ]

    ws = set_config(tmp_workspace, "extract", "pdf_vector_min_paths", "500")
    other = tmp_path / "pdfs500"
    write(other / "plans500.pdf", pdf_three_pages() + b"\n% other bytes\n")
    ingest(ws, other)
    assert [u[1] for u in units_of(db, "plans500.pdf")] == [
        "PDF_VECTOR",
        "PDF_SCANNED",
        "PDF_SCANNED",
    ]


@needs_fitz
def test_C06_pdf_vector_only_via_path_rule(
    tmp_workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With N = 500 page 0 (300 paths) is below N and has no images: PDF_VECTOR only
    through the >= 1 path rule (the image test is reached and returns 0 %)."""
    import ale.corpus.classify as classify

    calls: list[float] = []
    real = classify._image_coverage

    def spy(page: object) -> float:
        value = real(page)
        calls.append(value)
        return value

    monkeypatch.setattr(classify, "_image_coverage", spy)
    ws = set_config(tmp_workspace, "extract", "pdf_vector_min_paths", "500")
    root = tmp_path / "pdfs"
    write(root / "plans.pdf", pdf_three_pages())
    ingest(ws, root)
    assert calls[0] == 0.0  # page 0 went past the N test into the image test
    assert calls[1] >= 0.99


def test_C06_pdf_without_extra(
    tmp_workspace: Workspace, tmp_path: Path, db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ale.corpus.classify as classify

    monkeypatch.setattr(classify, "load_fitz", lambda: None)
    root = tmp_path / "pdfs"
    write(root / "plans.pdf", fake_pdf_bytes())
    report = ingest(tmp_workspace, root)
    assert units_of(db, "plans.pdf") == [(0, "PDF_SCANNED", "NEEDS_TOOL", PDF_NEEDS_TOOL_REASON)]
    assert report.units_by_status == {"NEEDS_TOOL": 1}


def test_C07_dwg_needs_tool(
    tmp_workspace: Workspace, input_dir: Path, tmp_path: Path, db: Path, invoke: Invoke
) -> None:
    ingest(tmp_workspace, input_dir)
    assert units_of(db, "sub/e.dwg") == [(0, "DWG", "NEEDS_TOOL", DWG_NEEDS_TOOL_REASON)]

    # A converter configured afterwards: the unchanged file is re-classified.
    write(tmp_workspace.path("tools", "ODAFileConverter.exe"), b"dummy")
    ws = set_config(tmp_workspace, "tools", "oda_file_converter", '"tools/ODAFileConverter.exe"')
    report = ingest(ws, input_dir)
    assert units_of(db, "sub/e.dwg") == [(0, "DWG", "NEW", None)]
    assert report.units_new == 1
    assert report.files_new == 0
    assert len(events(db, "reclassified")) == 1

    # A fresh workspace with the converter configured: NEW directly.
    other_root = tmp_path / "ws2"
    assert invoke(["init", "--workspace", other_root]).exit_code == 0
    dummy = tmp_path / "ODA" / "ODAFileConverter.exe"
    write(dummy, b"dummy")
    ws2 = set_config(
        open_workspace(other_root), "tools", "oda_file_converter", json.dumps(str(dummy))
    )
    ingest(ws2, input_dir)
    assert units_of(ws2.path("corpus.sqlite"), "sub/e.dwg") == [(0, "DWG", "NEW", None)]


def test_C07_dwg_tool_on_path(
    tmp_workspace: Workspace,
    input_dir: Path,
    tmp_path: Path,
    db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detection reuses `ale doctor`'s rules: a converter found on PATH counts."""
    bin_dir = tmp_path / "bin"
    exe = write(bin_dir / ("accoreconsole.exe" if os.name == "nt" else "accoreconsole"), b"x")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    ingest(tmp_workspace, input_dir)
    assert units_of(db, "sub/e.dwg") == [(0, "DWG", "NEW", None)]


def test_C08_corrupt_never_fatal(tmp_path: Path, invoke: Invoke) -> None:
    ws_root = tmp_path / "ws"
    assert invoke(["init", "--workspace", ws_root]).exit_code == 0
    root = tmp_path / "input"
    write(root / "good.png", png_bytes())
    write(root / "truncated.png", png_bytes()[:40])
    write(root / "empty.jpg", b"")
    write(root / "garbage.dwg", b"not a drawing at all")
    write(root / "cut.jpg", b"\xff\xd8\xff\xe0" + bytes(64))
    write(root / "bad.tif", b"II*\x00" + b"\xff\xff\xff\x7f" + bytes(8))
    write(root / "broken.pdf", b"%PDF-1.7\n" + bytes(32) if HAS_FITZ else fake_pdf_bytes())
    if HAS_FITZ:
        write(root / "secret.pdf", encrypted_pdf())
    result = invoke(["ingest", "--workspace", ws_root, "--input", root])
    assert result.exit_code == 0, result.output
    db = ws_root / "corpus.sqlite"
    assert units_of(db, "good.png") == [(0, "RASTER", "NEW", None)]
    expected = {
        "truncated.png": ("RASTER", "truncated PNG"),
        "empty.jpg": ("RASTER", "empty file"),
        "garbage.dwg": ("DWG", "unrecognised content"),
        "cut.jpg": ("RASTER", "truncated JPEG"),
        "bad.tif": ("RASTER", "corrupt TIFF"),
    }
    if HAS_FITZ:
        expected["broken.pdf"] = ("PDF_SCANNED", "unreadable PDF")
        expected["secret.pdf"] = ("PDF_SCANNED", "encrypted PDF")
    for rel, (kind, reason) in expected.items():
        units = units_of(db, rel)
        assert len(units) == 1, rel
        assert units[0][1:3] == (kind, "FAILED"), rel
        assert units[0][3] is not None and reason in units[0][3], (rel, units[0][3])
        assert rel in result.stdout
    assert "échecs" in result.stdout


@needs_fitz
def test_C08_encrypted_pdf_report(tmp_workspace: Workspace, tmp_path: Path) -> None:
    root = tmp_path / "input"
    write(root / "secret.pdf", encrypted_pdf())
    write(root / "ok.png", png_bytes())
    report = ingest(tmp_workspace, root)
    assert report.failed == [("secret.pdf", "encrypted PDF (password required)")]
    assert report.units_by_status == {"FAILED": 1, "NEW": 1}


def test_C09_filters(tmp_workspace: Workspace, tmp_path: Path, db: Path) -> None:
    root = tmp_path / "input"
    write(root / "keep.png", png_bytes())
    write(root / "keep.dwg", dwg_bytes())
    write(root / ".hidden.png", png_bytes(5, 5))
    write(root / ".git" / "inside.png", png_bytes(6, 6))
    write(root / "~$x.dwg", dwg_bytes(b"AC1027"))
    write(root / "notes.txt", b"hello")
    write(root / "photo.jpg", b"\xff\xd8\xff\xe0\xff\xd9")
    write(root / "pack.zip", b"PK\x03\x04")
    write(root / "pack.rar", b"Rar!\x1a\x07\x00")
    write(root / "sub" / "deep.png", png_bytes(7, 7))
    write(root / "sub" / "deep.zip", b"PK\x03\x04")
    symlinked = False
    try:
        (root / "link.png").symlink_to(root / "keep.png")
        (root / "linkdir").symlink_to(root / "sub", target_is_directory=True)
        symlinked = True
    except OSError:  # Windows without the symlink privilege
        pass

    report = ingest(tmp_workspace, root, include=["png", "dwg"], recursive=False)
    rels = {r[0] for r in query(db, "SELECT rel_path FROM file_paths")}
    assert rels == {"keep.png", "keep.dwg"}
    assert report.skipped_archives == ["pack.rar", "pack.zip"]
    assert report.files_seen == 2
    assert len(events(db, "skipped_archive")) == 2

    report = ingest(tmp_workspace, root, include=["png", "dwg"], recursive=True)
    rels = {r[0] for r in query(db, "SELECT rel_path FROM file_paths")}
    assert rels == {"keep.png", "keep.dwg", "sub/deep.png"}
    assert report.skipped_archives == ["pack.rar", "pack.zip", "sub/deep.zip"]
    if symlinked:
        assert "link.png" not in rels
        assert not any(r.startswith("linkdir/") for r in rels)


def test_C10_meta_csv(tmp_workspace: Workspace, input_dir: Path, tmp_path: Path, db: Path) -> None:
    write(input_dir / "x" / "dup.png", png_bytes(9, 9))
    write(input_dir / "y" / "dup.png", png_bytes(10, 10))
    meta = tmp_path / "plans_meta.csv"
    text = (
        "filename;page;scale_1_to;units;building_type;floor;exclude\n"
        "a.png;;;;;;oui\n"
        "sub/d.dxf;;100;mm;école;RDC;\n"
        "dup.png;;;;;;x\n"
        "missing.png;;50;;;;\n"
        "b.jpg;;abc;;;;\n"
    )
    meta.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    report = ingest(tmp_workspace, input_dir, meta=meta)

    assert units_of(db, "a.png") == [(0, "RASTER", "EXCLUDED", "plans_meta.csv")]
    sha_a = query(db, "SELECT sha256 FROM file_paths WHERE rel_path = 'a.png'")[0][0]
    assert query(db, "SELECT excluded FROM files WHERE sha256 = ?", (sha_a,)) == [(1,)]

    sha_d = query(db, "SELECT sha256 FROM file_paths WHERE rel_path = 'sub/d.dxf'")[0][0]
    (meta_json,) = query(db, "SELECT meta_json FROM files WHERE sha256 = ?", (sha_d,))[0]
    stored = json.loads(meta_json)
    assert stored["scale_1_to"] == 100
    assert stored == {"scale_1_to": 100, "units": "mm", "building_type": "école", "floor": "RDC"}
    assert units_of(db, "sub/d.dxf") == [(0, "DXF", "NEW", None)]

    for rel in ("x/dup.png", "y/dup.png"):
        assert units_of(db, rel) == [(0, "RASTER", "NEW", None)]
    assert query(db, "SELECT COUNT(*) FROM files WHERE excluded = 1") == [(1,)]
    warnings = "\n".join(report.meta_warnings)
    assert "line 4" in warnings and "ambiguous" in warnings
    assert "missing.png" in warnings
    assert "line 6" in warnings and "scale_1_to" in warnings
    assert len(report.meta_warnings) == 3

    # Idempotent: re-applying the same CSV changes nothing.
    before = query(db, "SELECT sha256, excluded, meta_json FROM files ORDER BY sha256")
    ingest(tmp_workspace, input_dir, meta=meta)
    assert query(db, "SELECT sha256, excluded, meta_json FROM files ORDER BY sha256") == before


@needs_fitz
def test_C10_meta_csv_per_page(tmp_workspace: Workspace, tmp_path: Path, db: Path) -> None:
    root = tmp_path / "input"
    write(root / "plans.pdf", pdf_three_pages())
    meta = tmp_path / "meta.csv"
    meta.write_text(
        "filename,page,scale_1_to,exclude\nplans.pdf,1,50,\nplans.pdf,2,,yes\nplans.pdf,7,,1\n",
        encoding="utf-8",
    )
    report = ingest(tmp_workspace, root, meta=meta)
    assert [u[2] for u in units_of(db, "plans.pdf")] == ["NEW", "NEW", "EXCLUDED"]
    (meta_json,) = query(db, "SELECT meta_json FROM files")[0]
    assert json.loads(meta_json) == {"pages": {"1": {"scale_1_to": 50}}}
    assert query(db, "SELECT excluded FROM files") == [(0,)]
    assert len(report.meta_warnings) == 1 and "page 7" in report.meta_warnings[0]


def test_C11_workspace_inside_input(tmp_path: Path, invoke: Invoke) -> None:
    # Workspace inside the input folder.
    root = tmp_path / "input"
    write(root / "a.png", png_bytes())
    ws_root = root / "ws"
    assert invoke(["init", "--workspace", ws_root]).exit_code == 0
    before = snapshot(root)
    result = invoke(["ingest", "--workspace", ws_root, "--input", root])
    assert result.exit_code == 4, result.output
    assert "inside the input folder" in result.stderr
    assert snapshot(root) == before
    with pytest.raises(WorkspaceError):
        ingest(open_workspace(ws_root), root)
    assert snapshot(root) == before

    # Input inside the workspace.
    ws2 = tmp_path / "ws2"
    assert invoke(["init", "--workspace", ws2]).exit_code == 0
    write(ws2 / "plans" / "a.png", png_bytes())
    before = snapshot(ws2)
    result = invoke(["ingest", "--workspace", ws2, "--input", ws2 / "plans"])
    assert result.exit_code == 4, result.output
    assert snapshot(ws2) == before

    # Same folder for both.
    result = invoke(["ingest", "--workspace", ws2, "--input", ws2])
    assert result.exit_code == 4


def test_C12_unicode_paths(tmp_workspace: Workspace, tmp_path: Path, db: Path) -> None:
    root = tmp_path / "Références" / "Plans 2024"
    write(root / "Façade é.png", png_bytes())
    nfd_dir = unicodedata.normalize("NFD", "Étage")
    nfd_name = unicodedata.normalize("NFD", "Coupe è.png")
    write(root / nfd_dir / nfd_name, png_bytes(3, 3))
    report = ingest(tmp_workspace, root)
    assert report.files_new == 2
    rels = sorted(r[0] for r in query(db, "SELECT rel_path FROM file_paths"))
    assert rels == ["Façade é.png", "Étage/Coupe è.png"]
    assert all(unicodedata.is_normalized("NFC", r) for r in rels)
    (stored_root,) = query(db, "SELECT root FROM inputs")[0]
    assert unicodedata.is_normalized("NFC", stored_root)
    assert Path(stored_root).is_absolute()
    assert units_of(db, "Façade é.png") == [(0, "RASTER", "NEW", None)]


def test_C13_migration(tmp_workspace: Workspace, input_dir: Path, db: Path) -> None:
    meta_before = query(db, "SELECT key, value FROM ale_meta ORDER BY key")
    assert query(db, "PRAGMA user_version") == [(0,)]
    assert read_status(db).total_units == 0  # an un-migrated DB reads as empty
    ingest(tmp_workspace, input_dir)
    assert query(db, "PRAGMA user_version") == [(2,)]
    assert query(db, "SELECT key, value FROM ale_meta ORDER BY key") == meta_before
    schema = query(db, "SELECT type, name, sql FROM sqlite_master ORDER BY name")
    with closing(sqlite3.connect(db)) as conn:
        assert migrate(conn) == 2  # re-opening: no-op
    assert query(db, "SELECT type, name, sql FROM sqlite_master ORDER BY name") == schema
    assert {r[1] for r in schema} >= {"inputs", "files", "file_paths", "units", "events"}


def test_C13_newer_schema_refused(tmp_workspace: Workspace, input_dir: Path, db: Path) -> None:
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("PRAGMA user_version = 99")
    with pytest.raises(WorkspaceError, match="newer"):
        ingest(tmp_workspace, input_dir)


def test_C14_cli(tmp_path: Path, input_dir: Path, invoke: Invoke) -> None:
    ws_root = tmp_path / "ws"
    assert invoke(["init", "--workspace", ws_root]).exit_code == 0
    result = invoke(["status", "--workspace", ws_root, "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["last_ingest"] is None

    write(input_dir / "pack.zip", b"PK")
    meta = tmp_path / "meta.csv"
    meta.write_text("filename,exclude\nb.jpg,1\nnope.png,1\n", encoding="utf-8")
    result = invoke(["ingest", "--workspace", ws_root, "--input", input_dir, "--meta", meta])
    assert result.exit_code == 0, result.output
    assert "Ingestion terminée" in result.stdout
    assert "fichiers vus : 5" in result.stdout
    assert "pack.zip" in result.stdout
    assert "nope.png" in result.stdout

    result = invoke(["status", "--workspace", ws_root, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    db = ws_root / "corpus.sqlite"
    expected = query(db, "SELECT kind, status, COUNT(*) FROM units GROUP BY kind, status")
    assert sorted((u["kind"], u["status"], u["count"]) for u in data["units"]) == sorted(expected)
    assert data["inputs"] == 1
    assert data["files"] == 5
    assert data["total_units"] == 5
    assert data["last_ingest"].endswith("Z")

    result = invoke(["status", "--workspace", ws_root])
    assert result.exit_code == 0
    assert "TOTAL" in result.stdout
    assert "entrées : 1" in result.stdout

    # --include parsing goes through the CLI too.
    result = invoke(
        ["ingest", "--workspace", ws_root, "--input", input_dir, "--include", ".PNG, dxf"]
    )
    assert result.exit_code == 0
    assert "fichiers vus : 2" in result.stdout


def test_C14_status_bad_db(tmp_path: Path, invoke: Invoke) -> None:
    ws_root = tmp_path / "ws"
    assert invoke(["init", "--workspace", ws_root]).exit_code == 0
    with closing(sqlite3.connect(ws_root / "corpus.sqlite")) as conn:
        conn.execute("PRAGMA user_version = 1")  # claims v1 without the tables
    result = invoke(["status", "--workspace", ws_root])
    assert result.exit_code == 4
    assert "corpus.sqlite" in result.stderr


@pytest.mark.timeout(1800)
def test_C15_real_corpus_smoke(tmp_workspace: Workspace) -> None:
    corpus = os.environ.get("ALE_CORPUS_DIR", "")
    if not corpus or not Path(corpus).is_dir():
        pytest.skip("ALE_CORPUS_DIR not set")
    before = sum(1 for _ in Path(corpus).rglob("*"))
    report = ingest(tmp_workspace, Path(corpus))
    print(json.dumps({k: v for k, v in report.to_dict().items() if k != "failed"}, indent=2))
    print(f"failed: {len(report.failed)}")
    for rel, reason in report.failed:
        print(f"  {rel}: {reason}")
    assert report.files_seen > 0
    assert sum(1 for _ in Path(corpus).rglob("*")) == before
    again = ingest(tmp_workspace, Path(corpus))
    assert again.units_new == 0
    assert again.files_unchanged == again.files_seen
