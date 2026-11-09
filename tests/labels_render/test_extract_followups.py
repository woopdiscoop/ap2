"""X.1 pixel-edge extent and static acceptance gates."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ale.contracts.config import AleConfig
from ale.contracts.enums import Frame, SourceKind
from ale.contracts.models import PlanGeometry
from ale.labels.bbox import normalized_to_native
from ale.labels.render import plan_image


@pytest.mark.parametrize("kind", [SourceKind.RASTER, SourceKind.PDF_SCANNED])
@pytest.mark.parametrize(
    "width,height,column,top,bottom",
    [
        (100, 50, 7, 3, 14),
        (100, 50, 0, 0, 1),
        (100, 50, 99, 49, 50),
        (1, 1, 0, 0, 1),
        (1000, 500, 127, 100, 400),
    ],
)
def test_X05_extent(
    kind: SourceKind, width: int, height: int, column: int, top: int, bottom: int
) -> None:
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    bitmap = np.full((height, width), 255, dtype=np.uint8)
    bitmap[top:bottom, column] = 0  # a real one-pixel-wide wall in this synthetic image
    plan = PlanGeometry(
        source_sha256="a" * 64, page=0, plan_index=0, source_kind=kind, frame=Frame.Y_DOWN
    )
    png, extent = plan_image(plan, config=AleConfig(), bitmap=bitmap)
    assert extent == (-0.5, -0.5, width - 0.5, height - 0.5)
    assert np.array_equal(cv2.imdecode(np.frombuffer(png, dtype=np.uint8), 0), bitmap)
    # Box from independent image coordinates, not an inverse of normalized_to_native.
    mock_box = (
        top * 1000 / height,
        column * 1000 / width,
        bottom * 1000 / height,
        (column + 1) * 1000 / width,
    )
    native = normalized_to_native(
        mock_box, image_size=(width, height), extent=extent, frame=Frame.Y_DOWN
    )
    assert native == (column - 0.5, top - 0.5, column + 0.5, bottom - 0.5)
    assert native[2] - native[0] == 1.0


@pytest.mark.timeout(180)
def test_X06_gates() -> None:
    """Full-suite/path-coverage results and before/after percentages are in the report."""
    for extra in ("ruff", "mypy", "ezdxf", "pymupdf", "cv2", "PIL", "anthropic"):
        pytest.importorskip(extra)
    root = Path(__file__).resolve().parents[2]
    for args in (
        ("ruff", "check", "."),
        ("ruff", "format", "--check", "."),
        ("mypy", "src"),
        ("ale.contracts.lock", "--check"),
    ):
        proc = subprocess.run(
            [sys.executable, "-m", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
