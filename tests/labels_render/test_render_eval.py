"""Ticket I.2 V202-V204: plan images and extents per source kind (mock VLM, no network)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
pymupdf = pytest.importorskip("pymupdf")
pytest.importorskip("PIL")

import cad_helpers  # noqa: E402
import pdf_helpers  # noqa: E402
import raster_helpers  # noqa: E402
from labels_helpers import FakeProvider, vlm_config, vlm_json  # noqa: E402

from ale.cad import read_cad  # noqa: E402
from ale.cad.layers import LayerMap, LayerRole  # noqa: E402
from ale.contracts.config import AleConfig  # noqa: E402
from ale.contracts.enums import Frame, LabelSource  # noqa: E402
from ale.contracts.models import PlanGeometry  # noqa: E402
from ale.labels import label_plan  # noqa: E402
from ale.labels.bbox import Extent, native_to_normalized, normalized_to_native  # noqa: E402
from ale.labels.cache import VlmCache  # noqa: E402
from ale.labels.label import plan_extent  # noqa: E402
from ale.labels.providers import prepare_image  # noqa: E402
from ale.labels.render import CAD_LONG_SIDE, CAD_MARGIN, plan_image  # noqa: E402
from ale.raster import read_raster  # noqa: E402

CONFIG = AleConfig()


def _bounds(plan: PlanGeometry, room_id: str) -> tuple[float, float, float, float]:
    room = next(r for r in plan.rooms if r.id == room_id)
    xs = [p[0] for p in room.polygon.exterior]
    ys = [p[1] for p in room.polygon.exterior]
    return (min(xs), min(ys), max(xs), max(ys))


def _pixel(
    point: tuple[float, float], size: tuple[int, int], extent: Extent, frame: Frame
) -> tuple[int, int]:
    """Pixel ``(column, row)`` where the rendering model draws a native point."""
    ny, nx, _, _ = native_to_normalized(
        (*point, *point), image_size=size, extent=extent, frame=frame
    )
    return int(nx * size[0] / 1000), int(ny * size[1] / 1000)


def _decode(png: bytes) -> Any:
    return cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)


def _dark_near(img: Any, col: int, row: int, radius: int = 2) -> bool:
    patch = img[max(0, row - radius) : row + radius + 1, max(0, col - radius) : col + radius + 1]
    return bool(patch.min() < 128)


def _assert_vlm_labels_room(
    plan: PlanGeometry, png: bytes, extent: Extent, room_id: str, tmp_path: Path
) -> None:
    """The mock VLM boxes ``room_id`` on the prepared image; label_plan types that room."""
    prepared = prepare_image(png)
    box = _bounds(plan, room_id)
    frame = Frame(plan.frame)
    norm = native_to_normalized(box, image_size=prepared.size, extent=extent, frame=frame)
    back = normalized_to_native(norm, image_size=prepared.size, extent=extent, frame=frame)
    assert back == pytest.approx(box, abs=1e-9)  # box -> native round trip exact
    bbox = [round(v) for v in norm]
    provider = FakeProvider([vlm_json(("Bureau", bbox, 0.9))])
    result = label_plan(
        plan,
        image=prepared.png,
        provider=provider,
        cache=VlmCache(tmp_path / "cache"),
        config=vlm_config(),
        extent=extent,
    )
    assert len(provider.calls) == 1
    typed = {r.id: (r.type, r.label_source) for r in result.plan.rooms}
    assert typed[room_id] == ("office", LabelSource.VLM)
    assert all(t == (None, None) for rid, t in typed.items() if rid != room_id), typed
    assert not result.warnings


# ---------------------------------------------------------------------- V202


def test_V202_raster_extent(tmp_path: Path) -> None:
    image = raster_helpers.plan_image()
    raster = read_raster(image, source_sha256=raster_helpers.SHA, config=CONFIG)
    plan = raster.plans[0]
    assert Frame(plan.frame) is Frame.Y_DOWN and len(plan.rooms) == 3

    png, extent = plan_image(plan, config=CONFIG, bitmap=image)

    h, w = image.shape
    assert extent == (0.0, 0.0, float(w), float(h))
    assert np.array_equal(_decode(png), image)  # the bitmap the reader traced
    # R1 (right-top) and R3 (right-bottom) share their x range: rows must not be flipped.
    for room_id in ("R1", "R3"):
        _assert_vlm_labels_room(plan, png, extent, room_id, tmp_path / room_id)


def test_V202_raster_extent_from_source_file(tmp_path: Path) -> None:
    image = raster_helpers.plan_image()
    path = tmp_path / "plan.png"
    path.write_bytes(cv2.imencode(".png", image)[1].tobytes())
    plan = read_raster(path, source_sha256=raster_helpers.SHA, config=CONFIG).plans[0]

    png, extent = plan_image(plan, config=CONFIG, source=path)

    assert np.array_equal(_decode(png), image)
    _assert_vlm_labels_room(plan, png, extent, "R2", tmp_path)


# ---------------------------------------------------------------------- V203


def _unlabelled_pdf(path: Path) -> Path:
    def build(page: Any) -> None:
        pdf_helpers.draw_plan_lines(page)
        pdf_helpers.draw_door(page)
        pdf_helpers.draw_title(page)

    return pdf_helpers.save_page(path, build)


def test_V203_pdf_extent(tmp_path: Path) -> None:
    path = _unlabelled_pdf(tmp_path / "plan.pdf")
    plan = pdf_helpers.read(path).plans[0]
    assert len(plan.rooms) == 2 and all(r.type is None for r in plan.rooms)

    png, extent = plan_image(plan, config=CONFIG, source=path)

    assert extent == (0.0, 0.0, 595.0, 842.0)  # page box in points
    dpi = CONFIG.extract.raster_dpi
    size = (math.ceil(595 * dpi / 72), math.ceil(842 * dpi / 72))  # PyMuPDF rounds up
    img = _decode(png)
    assert (img.shape[1], img.shape[0]) == size
    prepared = prepare_image(png)
    small = _decode(prepared.png)
    for wall in plan.walls:  # every wall centreline lands between its drawn faces
        (xa, ya), (xb, yb) = wall.centerline.coords[0], wall.centerline.coords[-1]
        mid = ((xa + xb) / 2, (ya + yb) / 2)
        col, row = _pixel(mid, prepared.size, extent, Frame.Y_DOWN)
        assert _dark_near(small, col, row, radius=8), (wall, col, row)  # faces ±0.1 m
    for room in plan.rooms:
        _assert_vlm_labels_room(plan, png, extent, room.id, tmp_path / room.id)


def test_V203_pdf_extent_rotated_page(tmp_path: Path) -> None:
    path = _unlabelled_pdf(tmp_path / "plan.pdf")
    with pymupdf.open(path) as doc:
        doc[0].set_rotation(90)
        doc.save(tmp_path / "rotated.pdf")
    rotated = tmp_path / "rotated.pdf"
    plan = pdf_helpers.read(rotated).plans[0]

    png, extent = plan_image(plan, config=CONFIG, source=rotated, dpi=72)

    assert extent == (0.0, 0.0, 595.0, 842.0)  # unrotated page box, like the reader
    _assert_vlm_labels_room(plan, png, extent, plan.rooms[0].id, tmp_path)


# ---------------------------------------------------------------------- V204


def _cad_plan(tmp_path: Path) -> PlanGeometry:
    doc = cad_helpers.new_doc()
    cad_helpers.add_plan_width(doc.modelspace(), extra_partition=True)
    doc.modelspace().add_text(
        "SALLE", dxfattribs={"layer": "TEXTE", "height": 200.0}
    ).set_placement((500.0, 4500.0))
    path = cad_helpers.save(doc, tmp_path / "plan.dxf")
    layers = LayerMap(layers={"MUR": LayerRole.WALL, "TEXTE": LayerRole.ROOM_LABEL})
    return read_cad(path, source_sha256=raster_helpers.SHA, layer_map=layers, config=CONFIG).plans[
        0
    ]


def test_V204_dxf_render(tmp_path: Path) -> None:
    plan = _cad_plan(tmp_path)
    assert Frame(plan.frame) is Frame.Y_UP and len(plan.rooms) == 3

    png, extent = plan_image(plan, config=CONFIG)

    prepared = prepare_image(png)
    assert prepared.png == png  # already within the provider limit: no second downscale
    assert max(prepared.size) == CAD_LONG_SIDE == 1568
    ext = plan_extent(plan)
    assert ext is not None
    mx, my = (ext[2] - ext[0]) * CAD_MARGIN, (ext[3] - ext[1]) * CAD_MARGIN
    assert extent == pytest.approx((ext[0] - mx, ext[1] - my, ext[2] + mx, ext[3] + my))
    img = _decode(png)
    # Y_UP: the top wall (largest y) is drawn near the top image row.
    top = max(plan.walls, key=lambda wl: min(p[1] for p in wl.centerline.coords))
    (xa, ya), (xb, yb) = top.centerline.coords[0], top.centerline.coords[-1]
    col, row = _pixel(((xa + xb) / 2, (ya + yb) / 2), prepared.size, extent, Frame.Y_UP)
    assert row < prepared.size[1] * 0.1 and _dark_near(img, col, row)
    # r001 (top-right) and r003 (bottom-right) differ only in y.
    for room_id in ("r001", "r003"):
        _assert_vlm_labels_room(plan, png, extent, room_id, tmp_path / room_id)
