"""Ticket 1.4 unit tests: loading, preprocessing, walls, openings, rooms, plan score."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

import shapely  # noqa: E402
from raster_helpers import SHA, H, W, plan_image  # noqa: E402

from ale.contracts.config import AleConfig  # noqa: E402
from ale.contracts.enums import SourceKind  # noqa: E402
from ale.raster import RasterReadResult, plan_score, rasterize_pdf_page, read_raster  # noqa: E402
from ale.raster import read as read_mod  # noqa: E402
from ale.raster import rooms as rooms_mod  # noqa: E402
from ale.raster import walls as walls_mod  # noqa: E402
from ale.raster.openings import Gap, doors_from_gaps, find_gaps, max_gap_px  # noqa: E402
from ale.raster.preprocess import (  # noqa: E402
    Transform,
    binarise,
    estimate_skew,
    preprocess,
    to_gray,
)
from ale.raster.rooms import trace_rooms  # noqa: E402
from ale.raster.walls import WallSeg, draw_segments, extract_walls  # noqa: E402

CONFIG = AleConfig()


def _read(image: object, **kw: object) -> RasterReadResult:
    return read_raster(image, source_sha256=SHA, config=CONFIG, **kw)  # type: ignore[arg-type]


def _rooms(res: RasterReadResult) -> int:
    return len(res.plans[0].rooms) if res.plans else -1


# --------------------------------------------------------------------------- arguments


def test_bad_arguments_are_warnings() -> None:
    img = plan_image()
    bad = read_raster(img, source_sha256="XYZ", config=CONFIG)
    assert bad.plans == () and "invalid source_sha256" in bad.warnings[-1]
    assert "invalid page" in _read(img, page=-1).warnings[-1]
    assert "invalid page" in _read(img, page=True).warnings[-1]
    assert "invalid source_kind" in _read(img, source_kind="NOPE").warnings[-1]
    assert _read(img, source_kind="PDF_SCANNED").plans[0].source_kind is SourceKind.PDF_SCANNED


def test_missing_raster_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "cv2", None)
    res = _read(plan_image())
    assert res.plans == () and "raster extra not installed" in res.warnings[-1]


def test_pipeline_error_is_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_binary: object) -> None:
        raise RuntimeError("kaputt")

    monkeypatch.setattr(walls_mod, "extract_walls", boom)
    res = _read(plan_image())
    assert res.plans == () and res.warnings[-1] == "raster pipeline error: RuntimeError: kaputt"


# --------------------------------------------------------------------------- to_gray


def test_to_gray_variants() -> None:
    plan = plan_image()
    assert to_gray(plan)[0] is not None
    assert to_gray(plan > 128)[0] is not None
    g16, _ = to_gray(plan.astype(np.uint16) * 257)
    assert g16 is not None and np.array_equal(g16, plan)
    gf, _ = to_gray(plan.astype(np.float64) / 255.0)
    assert gf is not None and np.array_equal(gf, plan)
    big = plan.astype(np.float32) * 2.0
    big[0, 0] = np.nan
    assert to_gray(big)[0] is not None
    assert to_gray(plan.astype(np.int32) - 5)[0] is not None
    bgr = np.dstack([plan, plan, plan])
    assert np.array_equal(to_gray(bgr)[0], plan)
    assert np.array_equal(to_gray(plan[:, :, None])[0], plan)
    bgra = np.dstack([np.zeros_like(plan)] * 3 + [255 - plan])  # black ink, transparent paper
    assert np.array_equal(to_gray(bgra)[0], plan)
    assert to_gray(np.zeros((0, 3)))[1] == "empty image"
    assert "unsupported image shape" in str(to_gray(np.zeros((4, 4, 2)))[1])
    assert "unsupported image dtype" in str(to_gray(np.zeros((4, 4), dtype=np.complex64))[1])
    assert "unsupported image shape" in _read(np.zeros((3, 3, 3, 3), np.uint8)).warnings[-1]


def test_transparent_png_plan_is_read() -> None:
    plan = plan_image()
    bgra = np.dstack([np.zeros_like(plan)] * 3 + [255 - plan])
    assert _rooms(_read(bgra)) == 3


# --------------------------------------------------------------------------- files


def test_read_from_files(tmp_path: Path) -> None:
    folder = tmp_path / "plans é ü"
    folder.mkdir()
    png = folder / "plan ü.png"
    ok, buf = cv2.imencode(".png", plan_image())
    assert ok
    png.write_bytes(buf.tobytes())
    assert _rooms(_read(png)) == 3
    assert _rooms(_read(str(png))) == 3
    missing = _read(folder / "missing.png")
    assert missing.plans == () and "cannot read image file" in missing.warnings[-1]
    junk = folder / "junk.png"
    junk.write_bytes(b"not an image at all")
    assert "cannot decode image" in _read(junk).warnings[-1]
    assert "cannot read image file" in _read(folder).warnings[-1]


def test_multipage_tiff(tmp_path: Path) -> None:
    from PIL import Image

    blank = Image.fromarray(np.full((H, W), 255, np.uint8))
    plan = Image.fromarray(plan_image())
    tif = tmp_path / "pages.tif"
    blank.save(tif, save_all=True, append_images=[plan])
    assert _read(tif).plans == ()
    second = _read(tif, page=1)
    assert _rooms(second) == 3 and second.plans[0].page == 1
    assert "out of range" in _read(tif, page=5).warnings[-1]
    rgba = tmp_path / "rgba.png"
    p = plan_image()
    Image.fromarray(np.dstack([p, p, p, np.full_like(p, 255)]), mode="RGBA").save(rgba)
    multi = tmp_path / "rgba.tif"
    Image.open(rgba).save(multi, save_all=True, append_images=[Image.open(rgba)])
    assert _rooms(_read(multi, page=1)) == 3


def test_file_size_cap_and_missing_pillow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    png = tmp_path / "p.png"
    _ok, buf = cv2.imencode(".png", plan_image())
    png.write_bytes(buf.tobytes())
    monkeypatch.setattr(read_mod, "MAX_FILE_BYTES", 10)
    assert "too large" in _read(png).warnings[-1]
    monkeypatch.setattr(read_mod, "MAX_FILE_BYTES", 1 << 30)
    monkeypatch.setitem(sys.modules, "PIL", None)
    assert "Pillow not installed" in _read(png, page=1).warnings[-1]


def test_read_bytes_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    png = tmp_path / "p.png"
    png.write_bytes(b"x")

    def fail(_self: Path) -> bytes:
        raise PermissionError(13, "denied")

    monkeypatch.setattr(Path, "read_bytes", fail)
    assert "cannot read image file: denied" in _read(png).warnings[-1]


# --------------------------------------------------------------------------- PDF


def test_rasterize_pdf_page_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    pdf = tmp_path / "a.pdf"
    with pymupdf.open() as doc:
        doc.new_page(width=200, height=100)
        doc.save(pdf)
    caplog.set_level(logging.WARNING)
    assert rasterize_pdf_page(pdf, 0, 72).shape == (100, 200)
    assert rasterize_pdf_page(pdf, 3, 72).shape == (0, 0)
    assert rasterize_pdf_page(pdf, 0, 0).shape == (0, 0)
    assert rasterize_pdf_page(tmp_path / "none.pdf", 0, 72).shape == (0, 0)
    monkeypatch.setattr(read_mod, "MAX_PDF_PIXELS", 5000)
    capped = rasterize_pdf_page(pdf, 0, 300)
    assert 0 < capped.size <= 5200
    assert any("dpi lowered" in r.message for r in caplog.records)
    monkeypatch.setitem(sys.modules, "pymupdf", None)
    assert rasterize_pdf_page(pdf, 0, 72).shape == (0, 0)
    assert "empty image" in _read(rasterize_pdf_page(pdf, 0, 72)).warnings[-1]


# --------------------------------------------------------------------------- preprocess


def test_transform_maps_back() -> None:
    m = np.vstack([cv2.getRotationMatrix2D((50.0, 40.0), 3.0, 1.0), [0.0, 0.0, 1.0]])
    tr = Transform(scale=0.5, rotation=m, offset=(10, -4))
    work = np.array([[20.0, 30.0]])
    rot = work + np.array([10.0, -4.0])
    scaled = np.linalg.solve(m, np.array([rot[0, 0], rot[0, 1], 1.0]))[:2]
    assert tr.to_native(work)[0] == pytest.approx((scaled + 0.5) / 0.5 - 0.5)
    assert tr.length_to_native(3.0) == 6.0


def test_skew_sign_and_oblique() -> None:
    plan = plan_image()
    m = cv2.getRotationMatrix2D(((W - 1) / 2, (H - 1) / 2), 4.0, 1.0)
    rotated = cv2.warpAffine(plan, m, (W, H), borderValue=255)
    angle, _ = estimate_skew(rotated)
    assert angle == pytest.approx(-4.0, abs=0.3)
    assert estimate_skew(np.full((50, 50), 255, np.uint8)) == (0.0, 0)
    diag = np.full((400, 400), 255, np.uint8)
    cv2.line(diag, (20, 20), (380, 380), 0, 3)
    cv2.line(diag, (20, 380), (380, 20), 0, 3)
    angle, oblique = estimate_skew(diag)
    assert angle == 0.0 and oblique >= 2


def test_oblique_warning_in_read() -> None:
    img = plan_image()
    cv2.line(img, (120, 120), (480, 680), 0, 4)
    res = _read(img)
    assert any("oblique line(s) ignored" in w for w in res.warnings)


def test_inverted_and_non_uniform_background() -> None:
    inverted = 255 - plan_image()
    res = _read(inverted)
    assert "dark background: image inverted" in res.warnings and _rooms(res) == 3
    shade = np.linspace(110.0, 255.0, W)[None, :]
    shaded = np.clip(plan_image().astype(np.float64) * shade / 255.0, 0, 255).astype(np.uint8)
    _, adaptive = binarise(shaded)
    assert adaptive
    res = _read(shaded)
    assert any("adaptive threshold" in w for w in res.warnings) and _rooms(res) == 3


def test_preprocess_pads_content_at_the_edge() -> None:
    img = np.full((300, 400), 255, np.uint8)
    img[0:8, :] = 0
    img[:, 0:8] = 0
    pre = preprocess(img)
    assert pre is not None and pre.transform.offset[0] < 0 and pre.transform.offset[1] < 0
    assert preprocess(np.full((20, 20), 255, np.uint8)) is None


# --------------------------------------------------------------------------- walls / gaps


def test_extract_walls_thin_lines_merge_and_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    ink = np.zeros((400, 600), np.uint8)
    ink[100:110, 50:250] = 255
    ink[100:110, 252:550] = 255  # a 2 px break: merged
    ink[300:301, 50:550] = 255  # 1 px drawing line: dropped as thin
    ext = extract_walls(ink)
    horizontal = [s for s in ext.segments if s.horizontal]
    assert len(horizontal) == 1
    assert horizontal[0].start == 50 and horizontal[0].end == 549
    assert any("thin line(s) ignored" in w for w in ext.warnings)
    monkeypatch.setattr(walls_mod, "MAX_COMPONENTS", 1)
    capped = extract_walls(ink)
    assert any("skipped (cap 1)" in w for w in capped.warnings)
    empty = extract_walls(np.zeros((50, 50), np.uint8))
    assert empty.segments == [] and empty.median_thickness == 0.0


def test_wallseg_and_draw() -> None:
    v = WallSeg(False, 20.0, 5.0, 45.0, 4.0)
    assert v.endpoints() == ((20.0, 5.0), (20.0, 45.0)) and v.length == 40.0
    mask = draw_segments((60, 60), [v])
    assert np.count_nonzero(mask) == 4 * 41


def test_gaps_and_doors() -> None:
    segs = [WallSeg(True, 10.0, 0.0, 19.0, 4.0), WallSeg(True, 10.0, 40.0, 59.0, 4.0)]
    mask = draw_segments((30, 80), segs)
    gaps = find_gaps(segs, mask, 30)
    assert len(gaps) == 1 and gaps[0].length == 20.0
    assert find_gaps(segs, mask, 10) == []
    off = [WallSeg(True, 100.0, 0.0, 19.0, 4.0)]
    assert find_gaps(off, mask, 30) == []
    assert doors_from_gaps([]) == []
    g = [Gap(0, True, 0.0, 0.0, n, 1.0) for n in (10.0, 11.0, 40.0)]
    assert [x.length for x in doors_from_gaps(g)] == [10.0, 11.0]
    v = Gap(0, False, 5.0, 1.0, 3.0, 1.0)
    assert v.endpoints() == ((5.0, 1.0), (5.0, 3.0))
    assert max_gap_px(8.0, 1000) == 80 and max_gap_px(0.0, 1000) == 1


# --------------------------------------------------------------------------- rooms / score


def test_rooms_cap_and_simplify(monkeypatch: pytest.MonkeyPatch) -> None:
    walls = 255 - plan_image()
    walls[200:240, 500:508] = 255
    walls[396:404, 780:830] = 255
    rooms, warnings = trace_rooms(walls, 8.0)
    assert len(rooms) == 3 and warnings == []
    monkeypatch.setattr(rooms_mod, "MAX_ROOMS", 1)
    rooms, warnings = trace_rooms(walls, 8.0)
    assert len(rooms) == 1 and any("skipped (cap 1)" in w for w in warnings)
    assert rooms_mod._simplify(np.zeros((10, 10), np.uint8)) is None
    two = np.zeros((40, 40), np.uint8)
    two[5:20, 5:20] = 255
    two[20:35, 20:35] = 255  # touches the first square at one corner
    poly = rooms_mod._simplify(two)
    assert poly is not None and poly.is_valid
    line = np.zeros((10, 10), np.uint8)
    line[5, 2:8] = 255
    assert rooms_mod._simplify(line) is None


def test_native_polygon_degenerate() -> None:
    tr = Transform(scale=1.0, rotation=np.eye(3), offset=(0, 0))
    assert read_mod._native_polygon(tr, [(0.0, 0.0), (0.0, 0.0), (1.0, 1.0)]) is None
    bow = [(0.0, 0.0), (2.0, 2.0), (2.0, 0.0), (0.0, 2.0)]
    assert read_mod._native_polygon(tr, bow) is None
    assert read_mod._native_polygon(tr, [(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 0.0)]) == [
        (0.0, 0.0),
        (4.0, 0.0),
        (4.0, 3.0),
    ]
    assert read_mod._line(tr, (1.0, 1.0), (1.0, 1.0)) is None
    assert shapely.Polygon([(0, 0), (1, 0), (0, 1)]).is_valid


def test_plan_score_formula() -> None:
    perfect = dict(
        extent_share=0.5,
        ink_share=0.1,
        wall_share=0.1,
        n_rooms=5,
        room_share=0.6,
        straight_share=1.0,
        long_share=1.0,
    )
    assert plan_score(**perfect) == 1.0  # type: ignore[arg-type]
    assert plan_score(**{**perfect, "ink_share": 0.6}) == 0.0  # type: ignore[arg-type]
    assert plan_score(**{**perfect, "ink_share": 0.4}) == 0.5  # type: ignore[arg-type]
    assert plan_score(**{**perfect, "extent_share": 0.005}) == 0.0  # type: ignore[arg-type]
    low_wall = {**perfect, "wall_share": 0.0125}
    assert plan_score(**low_wall) == pytest.approx(0.85)  # type: ignore[arg-type]
    high_wall = {**perfect, "wall_share": 0.375}
    assert plan_score(**high_wall) == pytest.approx(0.85)  # type: ignore[arg-type]
    no_rooms = {**perfect, "n_rooms": 0}
    assert plan_score(**no_rooms) == pytest.approx(0.7)  # type: ignore[arg-type]


def test_low_score_plan_kept_with_warning() -> None:
    img = np.full((H, W), 255, np.uint8)
    img[400:410, 100:1100] = 0  # one lonely wall: no rooms
    res = _read(img)
    assert len(res.plans) == 1 and res.plans[0].rooms == ()
    assert "no rooms found" in res.warnings
    assert any(w.startswith("low plan score") for w in res.warnings)
    assert res.plans[0].warnings == res.warnings


def test_gap_seen_from_both_sides_once() -> None:
    a = WallSeg(True, 10.4, 0.0, 19.0, 4.0)
    b = WallSeg(True, 11.6, 40.0, 59.0, 4.0)  # slightly offset centreline (skew residue)
    mask = draw_segments((30, 80), [a, b])
    assert len(find_gaps([a, b], mask, 30)) == 1


def test_room_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    walls = 255 - plan_image()
    walls[200:240, 500:508] = 255
    walls[396:404, 780:830] = 255
    monkeypatch.setattr(rooms_mod, "_TIME_BUDGET_S", 1e-9)
    rooms, warnings = trace_rooms(walls, 8.0)
    assert len(rooms) < 3 and any("time budget" in w for w in warnings)
    monkeypatch.setattr(rooms_mod, "_TIME_BUDGET_S", 60.0)
    monkeypatch.setattr(rooms_mod, "_simplify", lambda _c: None)
    rooms, warnings = trace_rooms(walls, 8.0)
    assert rooms == [] and sum("no valid polygon" in w for w in warnings) == 3


def test_simplify_repairs_invalid_ring(monkeypatch: pytest.MonkeyPatch) -> None:
    bow = np.array([[[0, 0]], [[10, 10]], [[10, 0]], [[0, 10]]], dtype=np.int32)
    monkeypatch.setattr(cv2, "approxPolyDP", lambda *_a, **_k: bow)
    square = np.zeros((20, 20), np.uint8)
    square[2:18, 2:18] = 255
    poly = rooms_mod._simplify(square)
    assert poly is not None and poly.is_valid and poly.area == pytest.approx(25.0)
    flat = np.array([[[0, 0]], [[5, 0]], [[10, 0]], [[5, 0]]], dtype=np.int32)
    monkeypatch.setattr(cv2, "approxPolyDP", lambda *_a, **_k: flat)
    assert rooms_mod._simplify(square) is None


def test_reader_fallbacks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dots = np.full((H, W), 255, np.uint8)
    for x in range(100, 1100, 50):
        cv2.circle(dots, (x, 400), 3, 0, -1)
    res = _read(dots)
    assert res.plans == () and res.warnings[-1] == "no walls found"
    monkeypatch.setattr(read_mod, "_native_polygon", lambda *_a: None)
    res = _read(plan_image())
    assert res.plans[0].rooms == ()
    assert "room polygon degenerate after mapping: skipped" in res.warnings
    png = tmp_path / "p.png"
    _ok, buf = cv2.imencode(".png", plan_image())
    png.write_bytes(buf.tobytes())

    def broken(*_a: object) -> None:
        raise cv2.error("decoder")

    monkeypatch.setattr(cv2, "imdecode", broken)
    assert len(_read(png).plans) == 1  # Pillow fallback
