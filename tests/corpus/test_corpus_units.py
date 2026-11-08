"""Ticket 1.1: unit tests of the corpus building blocks (edge cases behind C05-C10)."""

from __future__ import annotations

import os
import types
from pathlib import Path
from typing import Any

import pytest
from corpus_helpers import (
    HAS_FITZ,
    dwg_bytes,
    pdf_one_page,
    png_bytes,
    query,
    units_of,
    write,
)

import ale.corpus.classify as classify
from ale.contracts.enums import FileStatus, SourceKind
from ale.corpus.classify import Family, classify_file, detect_family, load_fitz
from ale.corpus.ingest import ingest
from ale.corpus.meta import parse_meta, parse_meta_text
from ale.corpus.scan import is_inside, scan, sha256_file
from ale.workspace import Workspace


def _classify(path: Path, ext: str, dwg: bool = False, n: int = 200) -> classify.Classification:
    return classify_file(path, ext, pdf_vector_min_paths=n, dwg_tool_available=dwg)


# --- detection -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("head", "family"),
    [
        (b"AC1015" + bytes(10), Family.DWG),
        (b"AC10x5", None),
        (b"999\ncomment\n  0\nSECTION\n", Family.DXF),
        (b"\xef\xbb\xbf  0\r\nSECTION\r\n", Family.DXF),
        (b"  0\nTABLE\n", None),
        (b"MM\x00*\x00\x00\x00\x08", Family.RASTER),
        (b"II+\x00\x08\x00\x00\x00", Family.RASTER),
        (b"junk\n%PDF-1.4\n", Family.PDF),
        (b"GIF89a", None),
    ],
)
def test_detect_family(head: bytes, family: Family | None) -> None:
    assert detect_family(head) is family


def test_raster_checks(tmp_path: Path) -> None:
    big_tiff = b"II+\x00\x08\x00\x00\x00" + (16).to_bytes(8, "little") + bytes(16)
    cases = {
        "ok_big.tif": (big_tiff, None),
        "big_bad.tif": (b"II+\x00\x08\x00\x00\x00" + bytes(8), "corrupt TIFF"),
        "be.tif": (b"MM\x00*" + (8).to_bytes(4, "big") + bytes(6), None),
        "noihdr.png": (b"\x89PNG\r\n\x1a\n" + bytes(40), "missing IHDR"),
    }
    for name, (data, problem) in cases.items():
        unit = _classify(write(tmp_path / name, data), name.rsplit(".", 1)[1]).units[0]
        if problem is None:
            assert unit.status is FileStatus.NEW, name
        else:
            assert unit.status is FileStatus.FAILED and problem in (unit.reason or ""), name


def test_large_raster_tail_is_read(tmp_path: Path) -> None:
    good = png_bytes(200, 200)
    # A big valid PNG: IEND only found in the tail block.
    data = good[:-12] + bytes(10_000) + good[-12:]
    unit = _classify(write(tmp_path / "big.png", data), "png").units[0]
    assert unit.status is FileStatus.NEW
    unit = _classify(write(tmp_path / "big_cut.png", data[:-12]), "png").units[0]
    assert unit.status is FileStatus.FAILED


def test_unknown_extension_and_mismatch(tmp_path: Path) -> None:
    cls = _classify(write(tmp_path / "plan.bin", dwg_bytes()), "bin", dwg=True)
    assert cls.kind_mismatch
    assert cls.units[0].kind is SourceKind.DWG
    assert cls.units[0].status is FileStatus.NEW
    cls = _classify(write(tmp_path / "noext", b"garbage"), "")
    assert cls.units[0].kind is SourceKind.RASTER
    assert cls.units[0].reason == "unrecognised content for file without extension"
    assert not cls.kind_mismatch


def test_unreadable_file(tmp_path: Path) -> None:
    cls = _classify(tmp_path / "gone.png", "png")
    assert cls.units[0].status is FileStatus.FAILED
    assert (cls.units[0].reason or "").startswith("cannot read file")


# --- PDF analysis with a fake PyMuPDF (runs without the pdf extra) ----------------------


class _Rect:
    def __init__(self, w: float, h: float) -> None:
        self.x0, self.y0, self.x1, self.y1 = 0.0, 0.0, w, h


class _Page:
    def __init__(self, paths: int, images: list[tuple[float, ...]], w: float = 100.0) -> None:
        self.rect = _Rect(w, 100.0)
        self._paths = paths
        self._images = images

    def get_drawings(self) -> list[int]:
        return list(range(self._paths))

    def get_image_info(self) -> list[dict[str, Any]]:
        return [{"bbox": b} for b in self._images]


class _Doc:
    def __init__(self, pages: list[Any], needs_pass: bool = False) -> None:
        self.pages = pages
        self.needs_pass = needs_pass
        self.page_count = len(pages)

    def load_page(self, index: int) -> Any:
        page = self.pages[index]
        if isinstance(page, Exception):
            raise page
        return page

    def close(self) -> None:
        pass


def _fake_fitz(monkeypatch: pytest.MonkeyPatch, doc: _Doc | Exception) -> None:
    def _open(**_: Any) -> _Doc:
        if isinstance(doc, Exception):
            raise doc
        return doc

    module = types.SimpleNamespace(
        open=_open, TOOLS=types.SimpleNamespace(mupdf_display_errors=lambda _: None)
    )
    monkeypatch.setattr(classify, "load_fitz", lambda: module)


def _pdf(tmp_path: Path) -> Path:
    return write(tmp_path / "x.pdf", b"%PDF-1.7\n")


def test_pdf_rules_fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("shapely")
    pages = [
        _Page(250, []),  # >= N paths
        _Page(3, [(0, 0, 100, 60)]),  # few paths, image >= 50 %
        _Page(3, [(0, 0, 100, 30), (0, 10, 100, 40)]),  # union 40 %: vector via >= 1 path
        _Page(0, [(0, 0, 100, 20)]),  # nothing: scanned
        _Page(0, [(-50, -50, 200, 200)], w=0.0),  # degenerate page area
        RuntimeError("bad page"),
        _Page(0, [(100, 100, 0, 0)]),  # reversed bbox, full page
    ]
    _fake_fitz(monkeypatch, _Doc(pages))
    units = _classify(_pdf(tmp_path), "pdf").units
    assert [(u.kind.value, u.status.value) for u in units] == [
        ("PDF_VECTOR", "NEW"),
        ("PDF_SCANNED", "NEW"),
        ("PDF_VECTOR", "NEW"),
        ("PDF_SCANNED", "NEW"),
        ("PDF_SCANNED", "NEW"),
        ("PDF_SCANNED", "FAILED"),
        ("PDF_SCANNED", "NEW"),
    ]
    assert units[5].reason == "unreadable PDF page (bad page)"


@pytest.mark.parametrize(
    ("doc", "reason"),
    [
        (_Doc([], needs_pass=True), "encrypted PDF (password required)"),
        (_Doc([]), "PDF has no pages"),
        (ValueError("broken xref"), "unreadable PDF (broken xref)"),
    ],
)
def test_pdf_failures_fake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, doc: Any, reason: str
) -> None:
    _fake_fitz(monkeypatch, doc)
    units = _classify(_pdf(tmp_path), "pdf").units
    assert units == (classify.UnitResult(0, SourceKind.PDF_SCANNED, FileStatus.FAILED, reason),)


def test_pdf_read_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_fitz(monkeypatch, _Doc([]))
    path = _pdf(tmp_path)
    real_open = Path.open
    calls = {"n": 0}

    def flaky_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == path:
            calls["n"] += 1
            if calls["n"] > 1:  # head read succeeds, the full read fails
                raise PermissionError(13, "Permission denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)
    unit = _classify(path, "pdf").units[0]
    assert unit.status is FileStatus.FAILED
    assert unit.reason == "cannot read file (Permission denied)"


def test_load_fitz_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def only_fitz(name: str) -> object:
        seen.append(name)
        if name == "fitz":
            return types.ModuleType("fitz")
        raise ImportError(name)

    monkeypatch.setattr(classify, "importlib", types.SimpleNamespace(import_module=only_fitz))
    module = load_fitz()
    assert module is not None and seen == ["pymupdf", "fitz"]

    def nothing(name: str) -> object:
        raise ImportError(name)

    monkeypatch.setattr(classify, "importlib", types.SimpleNamespace(import_module=nothing))
    assert load_fitz() is None


@pytest.mark.skipif(not HAS_FITZ, reason="pdf extra (PyMuPDF) not installed")
def test_real_pdf_single_path(tmp_path: Path) -> None:
    units = _classify(write(tmp_path / "one.pdf", pdf_one_page(1)), "pdf").units
    assert [(u.page, u.kind) for u in units] == [(0, SourceKind.PDF_VECTOR)]
    units = _classify(write(tmp_path / "zero.pdf", pdf_one_page(0)), "pdf").units
    assert [(u.page, u.kind) for u in units] == [(0, SourceKind.PDF_SCANNED)]


# --- plans_meta.csv ----------------------------------------------------------------------


def test_meta_parse_rows() -> None:
    parsed = parse_meta_text(
        "﻿filename,page,scale_1_to,units,exclude,colour\n"
        "a.png,,1:100,,non,red\n"
        ",1,,,,\n"
        "b.png,x,,,,\n"
        'c.png,,"12,5",m,peut-être,\n'
        "d.png,2,0,,,\n"
        "e.png,,,,,,extra\n"
        "f.png,,nan,,TRUE,\n"
    )
    assert [r.filename for r in parsed.rows] == ["a.png", "c.png", "d.png", "f.png"]
    a, c, d, f = parsed.rows
    assert a.fields == {} and not a.exclude
    assert c.fields == {"scale_1_to": 12.5, "units": "m"} and not c.exclude
    assert d.page == 2 and d.fields == {}
    assert f.exclude
    joined = "\n".join(parsed.warnings)
    for fragment in (
        "unknown column(s) ignored: colour",
        "line 2: scale_1_to '1:100'",
        "line 3: empty filename",
        "line 4: page 'x'",
        "line 5: exclude 'peut-être'",
        "line 6: scale_1_to '0'",
        "line 7: too many cells",
        "line 8: scale_1_to 'nan'",
    ):
        assert fragment in joined, fragment


def test_meta_parse_header_problems(tmp_path: Path) -> None:
    assert parse_meta_text("").warnings == ["plans_meta.csv: empty file"]
    assert "missing column 'filename'" in parse_meta_text("name;exclude\na;1\n").warnings[-1]
    bad = write(tmp_path / "latin1.csv", "filename\nfaçade.png\n".encode("latin-1"))
    assert "not valid UTF-8" in parse_meta(bad).warnings[0]
    assert "cannot read" in parse_meta(tmp_path / "missing.csv").warnings[0]
    blank_first = parse_meta_text("\n\nfilename;exclude\n\na.png;1\n")
    assert [r.filename for r in blank_first.rows] == ["a.png"]


def test_meta_windows_paths_and_duplicates(
    tmp_workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "input"
    write(root / "Dossier" / "plan.png", png_bytes())
    write(root / "copie" / "plan.png", png_bytes())  # same content, two paths
    meta = write(
        tmp_path / "m.csv",
        b"filename,exclude\nDossier\\plan.png,1\nplan.png,0\n./copie/plan.png,\n",
    )
    report = ingest(tmp_workspace, root, meta=meta)
    assert report.meta_warnings == []
    db = tmp_workspace.path("corpus.sqlite")
    assert units_of(db, "Dossier/plan.png")[0][2] == "EXCLUDED"


# --- scan ----------------------------------------------------------------------------------


def test_scan_errors_and_ordering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "in"
    write(root / "b.png", b"x")
    write(root / "a.PNG", b"x")
    write(root / "locked" / "c.png", b"x")
    write(root / "noext", b"x")
    real_scandir = os.scandir

    def scandir(path: Any) -> Any:
        if Path(path).name == "locked":
            raise PermissionError(13, "Permission denied")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    result = scan(root, ["png", ""])
    assert [f.rel_path for f in result.files] == ["a.PNG", "b.png"]
    assert result.errors == [("locked", "Permission denied")]


def test_scan_stat_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "in"
    write(root / "a.png", b"x")

    class Broken:
        name = "a.png"
        path = str(root / "a.png")

        def is_symlink(self) -> bool:
            return False

        def is_dir(self, follow_symlinks: bool = True) -> bool:
            raise OSError(5, "I/O error")

    class It:
        def __enter__(self) -> list[Broken]:
            return [Broken()]

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(os, "scandir", lambda _: It())
    result = scan(root, ["png"])
    assert result.files == [] and result.errors == [("a.png", "I/O error")]


def test_is_inside_and_hash(tmp_path: Path) -> None:
    assert is_inside(tmp_path / "a" / "b", tmp_path / "a")
    assert is_inside(tmp_path / "a", tmp_path / "a")
    assert not is_inside(tmp_path / "ab", tmp_path / "a")
    data = bytes(range(256)) * 9000  # > 1 MiB: several chunks
    import hashlib

    assert sha256_file(write(tmp_path / "big.bin", data)) == hashlib.sha256(data).hexdigest()


def test_ingest_hash_error_is_reported(
    tmp_workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ale.corpus.ingest as ingest_mod

    root = tmp_path / "in"
    write(root / "ok.png", png_bytes())
    write(root / "locked.png", png_bytes(3, 3))
    real = ingest_mod.sha256_file

    def sha(path: Path) -> str:
        if path.name == "locked.png":
            raise PermissionError(13, "Permission denied")
        return real(path)

    monkeypatch.setattr(ingest_mod, "sha256_file", sha)
    report = ingest(tmp_workspace, root)
    assert report.files_seen == 1
    assert report.failed == [("locked.png", "cannot read file (Permission denied)")]


def test_ingest_input_must_be_folder(tmp_workspace: Workspace, tmp_path: Path) -> None:
    from ale.workspace import WorkspaceError

    with pytest.raises(WorkspaceError, match="input folder not found"):
        ingest(tmp_workspace, tmp_path / "missing")


def test_needs_tool_stays_when_tool_still_missing(tmp_workspace: Workspace, tmp_path: Path) -> None:
    root = tmp_path / "in"
    write(root / "a.dwg", dwg_bytes())
    write(root / "copy" / "a.dwg", dwg_bytes())
    ingest(tmp_workspace, root)
    report = ingest(tmp_workspace, root)
    assert report.units_new == 0
    db = tmp_workspace.path("corpus.sqlite")
    assert query(db, "SELECT status FROM units") == [("NEEDS_TOOL",)]
