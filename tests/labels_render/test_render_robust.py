"""Ticket I.2: ``ale.labels.render`` edge cases and failures."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
pymupdf = pytest.importorskip("pymupdf")
pytest.importorskip("PIL")

import raster_helpers  # noqa: E402
from labels_helpers import SHA, rect, room, text  # noqa: E402

from ale.contracts.config import AleConfig  # noqa: E402
from ale.contracts.enums import Frame, OpeningKind, SourceKind  # noqa: E402
from ale.contracts.geometry import LineString, Polygon  # noqa: E402
from ale.contracts.models import Opening, PlanGeometry, Wall  # noqa: E402
from ale.labels.bbox import png_size  # noqa: E402
from ale.labels.render import (  # noqa: E402
    CAD_LONG_SIDE,
    RenderError,
    bitmap_image,
    cad_image,
    pdf_page_image,
    plan_image,
)

CONFIG = AleConfig()


def _plan(kind: SourceKind, *, frame: Frame = Frame.Y_UP, **fields: object) -> PlanGeometry:
    return PlanGeometry.model_validate(
        {
            "source_sha256": SHA,
            "page": 0,
            "plan_index": 0,
            "source_kind": kind,
            "frame": frame,
            **fields,
        }
    )


def _decode_rgb(png: bytes) -> np.ndarray:
    return np.asarray(cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR))


def _tall_cad_plan(kind: SourceKind = SourceKind.DWG, frame: Frame = Frame.Y_UP) -> PlanGeometry:
    holed = Polygon(
        exterior=((0, 0), (10, 0), (10, 40), (0, 40)), holes=(((4, 4), (6, 4), (6, 6), (4, 6)),)
    )
    return _plan(
        kind,
        frame=frame,
        rooms=(room("A", holed), room("B", rect(0, 40, 10, 50))),
        walls=(Wall(centerline=LineString(coords=((0.0, 0.0), (0.0, 50.0)))),),
        openings=(
            Opening(
                kind=OpeningKind.DOOR,
                segment=LineString(coords=((10.0, 1.0), (10.0, 3.0))),
                width_native=2.0,
            ),
            Opening(
                kind=OpeningKind.WINDOW,
                segment=LineString(coords=((10.0, 20.0), (10.0, 30.0))),
                width_native=10.0,
            ),
        ),
        texts=(text("WC", 5, 45, source="CAD"),),
    )


def test_cad_tall_plan_colours_and_size() -> None:
    plan = _tall_cad_plan()
    png, extent = plan_image(plan, config=CONFIG)
    size = png_size(png)
    assert size is not None and size[1] == CAD_LONG_SIDE and size[0] < size[1]
    assert extent == pytest.approx((-0.2, -1.0, 10.2, 51.0))
    img = _decode_rgb(png)  # BGR
    red = (img[:, :, 2] > 200) & (img[:, :, 1] < 60) & (img[:, :, 0] < 60)
    rows = np.nonzero(red)[0]
    assert rows.size and rows.min() > 0.9 * size[1]  # the door near y = 2, at the bottom (Y_UP)
    grey = (img[:, :, 0] == 150) & (img[:, :, 1] == 150)
    assert grey.any()  # room outlines (the hole included)
    assert (img == 0).all(axis=2).any()  # black walls and text


def test_cad_y_down_flips_rows() -> None:
    up = _decode_rgb(cad_image(_tall_cad_plan(frame=Frame.Y_UP))[0])
    down = _decode_rgb(cad_image(_tall_cad_plan(frame=Frame.Y_DOWN))[0])
    red_up = np.nonzero(up[:, :, 2] - up[:, :, 1] > 150)[0]
    red_down = np.nonzero(down[:, :, 2] - down[:, :, 1] > 150)[0]
    assert red_up.min() > red_down.max()


def test_cad_without_geometry_raises() -> None:
    with pytest.raises(RenderError, match="extent"):
        plan_image(_plan(SourceKind.DXF), config=CONFIG)


def test_bitmap_requires_source_or_array() -> None:
    with pytest.raises(RenderError, match="source file or bitmap"):
        plan_image(_plan(SourceKind.RASTER, frame=Frame.Y_DOWN), config=CONFIG)


def test_bitmap_empty_raises() -> None:
    with pytest.raises(RenderError, match="empty"):
        bitmap_image(np.zeros((0, 0), dtype=np.uint8))


def test_bitmap_unreadable_source_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    with pytest.raises(RenderError, match="cannot decode"):
        plan_image(_plan(SourceKind.RASTER, frame=Frame.Y_DOWN), config=CONFIG, source=bad)


def test_scanned_pdf_reloaded_at_dpi(tmp_path: Path) -> None:
    png = cv2.imencode(".png", raster_helpers.plan_image())[1].tobytes()
    path = tmp_path / "scan.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=288, height=192)
        page.insert_image(page.rect, stream=png)
        doc.save(path)
    plan = _plan(SourceKind.PDF_SCANNED, frame=Frame.Y_DOWN)
    data, extent = plan_image(plan, config=CONFIG, source=path, dpi=150)
    assert extent == (0.0, 0.0, 600.0, 400.0)
    assert png_size(data) == (600, 400)


def test_pdf_vector_requires_source() -> None:
    with pytest.raises(RenderError, match="needs the source"):
        plan_image(_plan(SourceKind.PDF_VECTOR, frame=Frame.Y_DOWN), config=CONFIG)


@pytest.mark.parametrize("dpi", [0, -5, True])
def test_pdf_invalid_dpi(tmp_path: Path, dpi: int) -> None:
    with pytest.raises(RenderError, match="invalid dpi"):
        pdf_page_image(tmp_path / "x.pdf", 0, dpi)


def test_pdf_page_out_of_range_and_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "one.pdf"
    with pymupdf.open() as doc:
        doc.new_page(width=100, height=50)
        doc.save(path)
    assert pdf_page_image(path, 0, 72)[1] == (0.0, 0.0, 100.0, 50.0)
    with pytest.raises(RenderError, match="out of range"):
        pdf_page_image(path, 3, 72)
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-garbage")
    with pytest.raises(RenderError, match="cannot render PDF page"):
        pdf_page_image(bad, 0, 72)


def test_pdf_pixel_cap_lowers_dpi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import ale.raster.read as raster_read

    path = tmp_path / "one.pdf"
    with pymupdf.open() as doc:
        doc.new_page(width=100, height=50)
        doc.save(path)
    monkeypatch.setattr(raster_read, "MAX_PDF_PIXELS", 5000)
    data, extent = pdf_page_image(path, 0, 300)
    size = png_size(data)
    assert size is not None and size[0] * size[1] <= 5200
    assert extent == (0.0, 0.0, 100.0, 50.0)
