"""Ticket 1.4 evaluation R1-R8 (images rendered from a declared ground truth)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

import shapely  # noqa: E402
from raster_helpers import (  # noqa: E402
    GT_DOOR_WIDTHS,
    GT_ROOMS,
    SHA,
    H,
    W,
    gt_wall_mask,
    iou_masks,
    iou_polygons,
    noisy_skewed,
    plan_image,
    walls_mask,
)

from ale.contracts.config import AleConfig  # noqa: E402
from ale.contracts.enums import Frame, OpeningKind, ScaleMethod, SourceKind  # noqa: E402
from ale.contracts.lock import main as lock_main  # noqa: E402
from ale.contracts.models import PlanGeometry  # noqa: E402
from ale.raster import RasterReadResult, rasterize_pdf_page, read_raster  # noqa: E402

CONFIG = AleConfig()


def _read(image: object, **kw: object) -> RasterReadResult:
    return read_raster(image, source_sha256=SHA, config=CONFIG, **kw)  # type: ignore[arg-type]


def test_R1_synthetic_plan() -> None:
    res = _read(plan_image())
    assert len(res.plans) == 1, res.warnings
    plan = res.plans[0]
    assert len(plan.rooms) == 3
    assert iou_masks(walls_mask(plan, (H, W)), gt_wall_mask()) >= 0.85
    for gt in GT_ROOMS:
        box = shapely.box(*gt)
        best = max(iou_polygons(shapely.Polygon(r.polygon.exterior), box) for r in plan.rooms)
        assert best >= 0.9, (gt, best)
    assert len(plan.openings) == 2
    assert all(o.kind is OpeningKind.DOOR for o in plan.openings)
    widths = sorted(o.width_native for o in plan.openings)
    for got, want in zip(widths, sorted(GT_DOOR_WIDTHS), strict=True):
        assert abs(got - want) <= 3.0
    for o in plan.openings:
        assert o.host_wall is not None and 0 <= o.host_wall < len(plan.walls)
    assert all(w.thickness is not None and abs(w.thickness - 8.0) <= 1.0 for w in plan.walls)
    assert res.plan_score >= 0.8


def test_R2_noise_and_skew() -> None:
    img, gt = noisy_skewed(2.0)
    res = _read(img)
    assert len(res.plans) == 1, res.warnings
    plan = res.plans[0]
    assert len(plan.rooms) == 3
    assert iou_masks(walls_mask(plan, (H, W)), gt) >= 0.75
    assert any(w.startswith("deskewed by") for w in res.warnings)


def test_R2_skew_both_directions() -> None:
    for angle in (-2.0, 2.0, 5.0):
        img, gt = noisy_skewed(angle, seed=11)
        res = _read(img)
        assert len(res.plans) == 1 and len(res.plans[0].rooms) == 3, (angle, res.warnings)
        assert iou_masks(walls_mask(res.plans[0], (H, W)), gt) >= 0.75, angle


def test_R3_scanned_pdf(tmp_path: Path) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    ok, png = cv2.imencode(".png", plan_image())
    assert ok
    pdf = tmp_path / "scan é.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=W * 72 / 150, height=H * 72 / 150)
        page.insert_image(page.rect, stream=png.tobytes())
        doc.save(pdf)
    arr = rasterize_pdf_page(pdf, 0, 150)
    assert arr.dtype == np.uint8 and arr.ndim == 2
    assert abs(arr.shape[0] - H) <= 2 and abs(arr.shape[1] - W) <= 2
    res = _read(arr, source_kind=SourceKind.PDF_SCANNED)
    assert len(res.plans) == 1, res.warnings
    assert len(res.plans[0].rooms) == len(_read(plan_image()).plans[0].rooms) == 3
    assert res.plans[0].source_kind is SourceKind.PDF_SCANNED


def _photo_like(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = cv2.GaussianBlur(rng.normal(0.0, 1.0, (H, W)), (0, 0), 4.0)
    n = (n - n.min()) / (n.max() - n.min()) * 255.0
    grad = np.linspace(-40.0, 40.0, W)[None, :]
    return np.clip(n + grad, 0, 255).astype(np.uint8)


def _text_page(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = np.full((1100, 850), 255, np.uint8)
    words = [
        "Lorem",
        "ipsum",
        "dolor",
        "sit",
        "amet",
        "consectetur",
        "adipiscing",
        "elit",
        "sed",
        "do",
        "eiusmod",
    ]
    for y in range(60, 1060, 24):
        x = 50
        for _ in range(40):  # bounded
            word = words[int(rng.integers(len(words)))]
            (tw, _th), _ = cv2.getTextSize(word + " ", cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
            if x + tw > 800:
                break
            cv2.putText(img, word, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 0, 1, cv2.LINE_AA)
            x += tw
    return img


@pytest.mark.parametrize("kind", ["photo", "white_noise", "text"])
def test_R4_not_a_plan(kind: str) -> None:
    rng = np.random.default_rng(3)
    img = {
        "photo": lambda: _photo_like(5),
        "white_noise": lambda: rng.integers(0, 256, (H, W)).astype(np.uint8),
        "text": lambda: _text_page(9),
    }[kind]()
    res = _read(img)
    assert res.plans == () or res.plan_score < 0.3, (res.plan_score, res.warnings)


def test_R5_robustness() -> None:
    cases = {
        "blank": np.full((H, W), 255, np.uint8),
        "black": np.zeros((H, W), np.uint8),
        "1x1": np.zeros((1, 1), np.uint8),
        "1x1 white": np.full((1, 1), 255, np.uint8),
        "empty": np.zeros((0, 0), np.uint8),
    }
    for name, img in cases.items():
        t0 = time.monotonic()
        res = _read(img)
        assert time.monotonic() - t0 < 10.0, name
        assert res.plans == (), name
        assert res.warnings, name


def test_R5_huge_image_downscaled() -> None:
    big = np.full((10_000, 10_000), 255, np.uint8)
    big[1000:9000, :] = cv2.resize(plan_image(), (10_000, 8000), interpolation=cv2.INTER_NEAREST)
    t0 = time.monotonic()
    res = _read(big)
    assert time.monotonic() - t0 < 30.0
    assert any("downscaled" in w for w in res.warnings)
    assert len(res.plans) == 1 and len(res.plans[0].rooms) == 3
    # Geometry stays in the input's native pixels: the 40 px door gap (vertical, y x 10)
    # and the 50 px one (horizontal, x x 10000/1200).
    widths = sorted(o.width_native for o in res.plans[0].openings)
    assert widths == pytest.approx([40 * 10.0, 50 * 10_000 / 1200], abs=12.0)
    del big


def test_R6_contract() -> None:
    plan = _read(plan_image()).plans[0]
    again = PlanGeometry.model_validate_json(plan.model_dump_json())
    assert again == plan
    assert plan.frame is Frame.Y_DOWN
    assert plan.scale_method is ScaleMethod.UNKNOWN and plan.scale_m_per_unit is None
    assert plan.source_kind is SourceKind.RASTER and plan.source_sha256 == SHA
    assert all(r.type is None and r.label_source is None for r in plan.rooms)
    assert len({r.id for r in plan.rooms}) == len(plan.rooms)
    assert _read(plan_image()) == _read(plan_image())  # deterministic


def test_R7_real_corpus_smoke() -> None:
    corpus = os.environ.get("ALE_CORPUS_DIR", "")
    if not corpus:
        pytest.skip("ALE_CORPUS_DIR not set (optional smoke test, never in CI)")
    root = Path(corpus) / "floor_plan_images"
    exts = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
    images = sorted(
        (p for p in root.rglob("*") if p.suffix.lower() in exts),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    if not images:
        pytest.skip(f"no images under {root}")
    step = max(1, len(images) // 20)
    picked = images[::step][:20]
    print(f"\nR7: {len(picked)} of {len(images)} images under {root}")
    for p in picked:
        t0 = time.monotonic()
        res = read_raster(p, source_sha256=SHA, config=CONFIG)
        walls = sum(len(pl.walls) for pl in res.plans)
        rooms = sum(len(pl.rooms) for pl in res.plans)
        doors = sum(len(pl.openings) for pl in res.plans)
        print(
            f"  {p.name}: plans={len(res.plans)} walls={walls} rooms={rooms} doors={doors} "
            f"score={res.plan_score:.2f} t={time.monotonic() - t0:.1f}s"
        )


def test_R8_gates() -> None:
    """Contracts untouched (lock --check); ruff/mypy/coverage run as commands (eval_report)."""
    assert lock_main(["--check"]) == 0
