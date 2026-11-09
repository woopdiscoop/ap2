"""PNG image of a plan for the VLM, with the native extent drawn into it (Ticket I.2).

:func:`plan_image` returns ``(png, extent)``: the image follows the rendering model of
:mod:`ale.labels.bbox` (uniform scale ``min(W / ew, H / eh)``, centred, top image row
``y1`` for ``Frame.Y_UP`` and ``y0`` for ``Frame.Y_DOWN``), so a VLM box drawn on the image
maps back to the plan with :func:`ale.labels.bbox.normalized_to_native`.

Per source kind:

* ``RASTER`` / ``PDF_SCANNED``: the bitmap the raster reader traced (``bitmap``, or
  reloaded from ``source``), ``extent = (0, 0, W, H)``, plan frame ``Y_DOWN``.
* ``PDF_VECTOR``: the page rendered with PyMuPDF at ``dpi`` (default
  ``config.extract.raster_dpi``), ``extent`` = the page box in points.
* ``DXF`` / ``DWG``: drawn with Pillow from the plan geometry (walls black 2 px, doors red,
  room outlines grey, texts black at their insertion points, white background), long side
  :data:`CAD_LONG_SIDE` px, ``extent`` = :func:`ale.labels.label.plan_extent` plus a
  :data:`CAD_MARGIN` margin on each side.

The caller downscales with :func:`ale.labels.providers.prepare_image` before labelling;
the extent is unchanged by a uniform downscale. Failures raise :class:`RenderError`.
"""

from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any, Final

from ale.contracts.config import AleConfig
from ale.contracts.enums import Frame, OpeningKind, SourceKind
from ale.contracts.models import PlanGeometry
from ale.labels.bbox import Extent
from ale.labels.label import plan_extent

__all__ = [
    "CAD_LONG_SIDE",
    "CAD_MARGIN",
    "RenderError",
    "bitmap_image",
    "cad_image",
    "pdf_page_image",
    "plan_image",
]

#: Long side (pixels) of a CAD plan drawing.
CAD_LONG_SIDE: Final = 1568
#: Margin added to each side of a CAD plan extent, as a share of that axis' size.
CAD_MARGIN: Final = 0.02

_WALL_PX: Final = 2
_WHITE: Final = (255, 255, 255)
_BLACK: Final = (0, 0, 0)
_RED: Final = (255, 0, 0)
_GREY: Final = (150, 150, 150)
_BITMAP_KINDS: Final = frozenset({SourceKind.RASTER, SourceKind.PDF_SCANNED})
_CAD_KINDS: Final = frozenset({SourceKind.DXF, SourceKind.DWG})


class RenderError(ValueError):
    """The plan image cannot be produced."""


# --------------------------------------------------------------------------- bitmaps


def bitmap_image(bitmap: Any) -> tuple[bytes, Extent]:
    """PNG of a ``uint8``/``uint16`` array (grey, BGR or BGRA) and ``(0, 0, W, H)``."""
    import cv2
    import numpy as np

    arr = np.asarray(bitmap)
    if arr.ndim not in (2, 3) or arr.shape[0] == 0 or arr.shape[1] == 0:
        raise RenderError(f"empty or unsupported bitmap of shape {arr.shape}")
    ok, data = cv2.imencode(".png", arr)
    if not ok:  # pragma: no cover - cv2 encodes any 8/16-bit grey or colour array
        raise RenderError("cannot encode the bitmap as PNG")
    height, width = int(arr.shape[0]), int(arr.shape[1])
    return bytes(data.tobytes()), (0.0, 0.0, float(width), float(height))


def _load_bitmap(source: Path, kind: SourceKind, page: int, dpi: int) -> Any:
    """The bitmap the raster reader traces for ``source`` (same decoder as the reader)."""
    if kind is SourceKind.PDF_SCANNED:
        from ale.raster import rasterize_pdf_page

        return rasterize_pdf_page(source, page, dpi=dpi)
    from ale.raster.read import _load

    arr, reason = _load(Path(source), page)
    if arr is None:
        raise RenderError(reason or "cannot read image")
    return arr


# --------------------------------------------------------------------------- vector PDF


def pdf_page_image(source: Path, page: int, dpi: int) -> tuple[bytes, Extent]:
    """Page ``page`` of the PDF rendered at ``dpi`` and the page box ``(0, 0, w, h)`` (pt).

    The page is rendered unrotated (the vector reader's coordinates ignore ``/Rotate``)
    and the DPI is lowered when the page would exceed the raster reader's pixel cap.
    """
    import pymupdf

    from ale.raster.read import MAX_PDF_PIXELS

    if isinstance(dpi, bool) or not isinstance(dpi, int | float) or not dpi > 0:
        raise RenderError(f"invalid dpi {dpi!r}")
    try:
        with pymupdf.open(Path(source)) as doc:  # type: ignore[no-untyped-call]
            if isinstance(page, bool) or not 0 <= page < len(doc):
                raise RenderError(f"page {page!r} out of range ({len(doc)} page(s))")
            pg = doc[page]
            if pg.rotation:
                pg.set_rotation(0)
            rect = pg.rect
            width, height = float(rect.width), float(rect.height)
            if not (width > 0 and height > 0):
                raise RenderError(f"empty page box {width} x {height}")
            zoom = float(dpi) / 72.0
            pixels = width * height * zoom * zoom
            if pixels > MAX_PDF_PIXELS:
                zoom *= math.sqrt(MAX_PDF_PIXELS / pixels)
            pix = pg.get_pixmap(
                matrix=pymupdf.Matrix(zoom, zoom),  # type: ignore[no-untyped-call]
                alpha=False,
            )
            data = bytes(pix.tobytes("png"))
    except RenderError:
        raise
    except Exception as exc:
        raise RenderError(f"cannot render PDF page: {type(exc).__name__}: {exc}") from exc
    return data, (0.0, 0.0, width, height)


# --------------------------------------------------------------------------- CAD drawing


def _cad_extent(plan: PlanGeometry) -> Extent:
    ext = plan_extent(plan)
    if ext is None:
        raise RenderError("plan has no usable native extent")
    x0, y0, x1, y1 = ext
    mx, my = (x1 - x0) * CAD_MARGIN, (y1 - y0) * CAD_MARGIN
    return (x0 - mx, y0 - my, x1 + mx, y1 + my)


def cad_image(plan: PlanGeometry, *, long_side: int = CAD_LONG_SIDE) -> tuple[bytes, Extent]:
    """Pillow drawing of a CAD plan and its extent (see module docstring)."""
    from PIL import Image, ImageDraw

    x0, y0, x1, y1 = extent = _cad_extent(plan)
    ew, eh = x1 - x0, y1 - y0
    if ew >= eh:
        size = (long_side, max(1, round(long_side * eh / ew)))
    else:
        size = (max(1, round(long_side * ew / eh)), long_side)
    w, h = size
    s = min(w / ew, h / eh)
    off_x, off_y = (w - ew * s) / 2.0, (h - eh * s) / 2.0
    y_up = Frame(plan.frame) is Frame.Y_UP

    def px(p: tuple[float, float]) -> tuple[float, float]:
        d = (y1 - p[1]) if y_up else (p[1] - y0)
        return (off_x + (p[0] - x0) * s, off_y + d * s)

    img = Image.new("RGB", size, _WHITE)
    draw = ImageDraw.Draw(img)
    for room in plan.rooms:
        for ring in (room.polygon.exterior, *room.polygon.holes):
            pts = [px(p) for p in ring]
            draw.line([*pts, pts[0]], fill=_GREY, width=1)
    for wall in plan.walls:
        draw.line([px(p) for p in wall.centerline.coords], fill=_BLACK, width=_WALL_PX)
    for opening in plan.openings:
        if opening.kind is OpeningKind.DOOR:
            draw.line([px(p) for p in opening.segment.coords], fill=_RED, width=_WALL_PX)
    for item in plan.texts:
        draw.text(px(item.insert), item.text, fill=_BLACK)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue(), extent


# --------------------------------------------------------------------------- entry point


def plan_image(
    plan: PlanGeometry,
    *,
    config: AleConfig,
    source: Path | None = None,
    bitmap: Any | None = None,
    dpi: int | None = None,
) -> tuple[bytes, Extent]:
    """``(png, extent)`` of ``plan`` for the VLM (see module docstring).

    ``source`` is the source file (needed for PDF pages, and for bitmaps when ``bitmap``
    is not given); ``bitmap`` is the array the raster reader traced; ``dpi`` defaults to
    ``config.extract.raster_dpi``. Raises :class:`RenderError`.
    """
    kind = SourceKind(plan.source_kind)
    resolution = config.extract.raster_dpi if dpi is None else dpi
    if kind in _CAD_KINDS:
        return cad_image(plan)
    if kind in _BITMAP_KINDS:
        if bitmap is None:
            if source is None:
                raise RenderError(f"{kind.value} plan image needs the source file or bitmap")
            bitmap = _load_bitmap(source, kind, plan.page, resolution)
        return bitmap_image(bitmap)
    if kind is SourceKind.PDF_VECTOR:
        if source is None:
            raise RenderError("PDF_VECTOR plan image needs the source file")
        return pdf_page_image(source, plan.page, resolution)
    raise RenderError(f"no plan image for source kind {kind.value}")  # pragma: no cover
