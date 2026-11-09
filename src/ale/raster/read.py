"""``read_raster``: one raster image (or scanned PDF page) → ``RasterReadResult``.

Classical computer vision, no learned model (v1). Pipeline: :mod:`~ale.raster.preprocess`
(grey, memory cap, deskew, denoise, binarise, crop) → :mod:`~ale.raster.walls`
(axis-parallel walls) → :mod:`~ale.raster.openings` (door gaps, bridged) →
:mod:`~ale.raster.rooms` (free-space components).

Output geometry is in the native pixels of the input image (pixel centres on integer
coordinates), frame ``Y_DOWN``, scale ``UNKNOWN``. ``read_raster`` and
``rasterize_pdf_page`` never raise on bad input: problems become warnings (or, for
``rasterize_pdf_page``, an empty array and a logged warning).

``plan_score`` (0..1) estimates how much the image looks like a floor plan. All shares
are measured on the cropped working image::

    plan_score = s_ink * s_extent * (0.3 * s_wall + 0.3 * s_rooms + 0.2 * s_straight
                                     + 0.2 * s_long)

* ``s_extent``: bounding-box area of the largest dark component (the crop) over the
  image area, ramped from 0 at 1 % to 1 at 10 % (a text page crops to one word).
* ``s_ink``: 1 while ink covers at most 30 % of the image, falling linearly to 0 at 50 %
  (noise and photographs binarise to about half ink).
* ``s_wall``: wall-pixel share ``f`` as a trapezoid: 0 below 0.5 %, rising linearly to 1
  at 2 %, 1 up to 25 %, falling linearly to 0 at 50 %.
* ``s_rooms = min(1, rooms / 3) * c``, with ``c`` the room-area share ramped from 0 at
  5 % to 1 at 30 %.
* ``s_straight``: share of the long straight strokes (the union of the two line-opened
  masks) explained by accepted wall segments.
* ``s_long``: share of the total wall length in walls at least 10 % of the short side.
"""

from __future__ import annotations

import io
import logging
import math
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field

from ale.contracts.config import AleConfig
from ale.contracts.enums import Frame, OpeningKind, SourceKind
from ale.contracts.geometry import LineString, Point2
from ale.contracts.models import LabelledPolygon, Opening, PlanGeometry, Wall

if TYPE_CHECKING:
    from ale.raster.preprocess import Transform

__all__ = [
    "LONG_WALL_SHARE",
    "MAX_FILE_BYTES",
    "MAX_PDF_PIXELS",
    "RasterReadResult",
    "plan_score",
    "rasterize_pdf_page",
    "read_raster",
]

log = logging.getLogger(__name__)

#: Image files larger than this are not read.
MAX_FILE_BYTES = 512 * 1024 * 1024
#: Pixel cap of a rendered PDF page; the DPI is lowered to fit.
MAX_PDF_PIXELS = 60_000_000
#: Walls at least this share of the short side count as long in ``plan_score``.
LONG_WALL_SHARE = 0.10
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ROUND = 3


class RasterReadResult(BaseModel):
    """Result of :func:`read_raster`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plans: tuple[PlanGeometry, ...]
    warnings: tuple[str, ...]
    plan_score: float = Field(ge=0.0, le=1.0)


def _trapezoid(f: float, a: float, b: float, c: float, d: float) -> float:
    """0 at or below ``a``, linear to 1 at ``b``, 1 up to ``c``, linear to 0 at ``d``."""
    if f <= a or f >= d:
        return 0.0
    if f < b:
        return (f - a) / (b - a)
    if f <= c:
        return 1.0
    return (d - f) / (d - c)


def _clamp01(v: float) -> float:
    return min(1.0, max(0.0, v))


def plan_score(
    *,
    extent_share: float,
    ink_share: float,
    wall_share: float,
    n_rooms: int,
    room_share: float,
    straight_share: float,
    long_share: float,
) -> float:
    """The documented plan score (see the module docstring), rounded to 4 decimals."""
    s_ink = _trapezoid(ink_share, -1.0, 0.0, 0.3, 0.5)
    s_wall = _trapezoid(wall_share, 0.005, 0.02, 0.25, 0.5)
    s_rooms = min(1.0, max(0, n_rooms) / 3.0) * _clamp01((room_share - 0.05) / 0.25)
    s_extent = _clamp01((extent_share - 0.01) / 0.09)
    score = (
        s_ink
        * s_extent
        * (
            0.3 * s_wall
            + 0.3 * s_rooms
            + 0.2 * _clamp01(straight_share)
            + 0.2 * _clamp01(long_share)
        )
    )
    return round(_clamp01(score), 4)


# --------------------------------------------------------------------------- loading


def _decode_pillow(data: bytes, page: int) -> tuple[NDArray[Any] | None, str | None]:
    try:
        from PIL import Image
    except ImportError:
        return None, "cannot decode image (Pillow not installed)"
    try:
        with Image.open(io.BytesIO(data)) as img:
            n_frames = int(getattr(img, "n_frames", 1))
            if page >= n_frames:
                return None, f"page {page} out of range ({n_frames} frame(s))"
            img.seek(page)
            frame = img.convert("RGBA") if "A" in img.getbands() else img.convert("L")
            arr = np.asarray(frame)
    except Exception as exc:  # any decoder failure (incl. decompression bomb) is a warning
        return None, f"cannot decode image: {type(exc).__name__}: {exc}"
    if arr.ndim == 3:  # RGBA → BGRA for to_gray
        arr = arr[:, :, [2, 1, 0, 3]]
    return arr, None


def _load(path: Path, page: int) -> tuple[NDArray[Any] | None, str | None]:
    import cv2

    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, f"cannot read image file: {exc.strerror or exc}"
    if size > MAX_FILE_BYTES:
        return None, f"image file too large ({size} bytes > {MAX_FILE_BYTES})"
    try:
        data = path.read_bytes()
    except OSError as exc:
        return None, f"cannot read image file: {exc.strerror or exc}"
    if page == 0:
        try:  # imdecode (not imread) works with any path on Windows
            arr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        except cv2.error:
            arr = None
        if arr is not None:
            return np.asarray(arr), None
    return _decode_pillow(data, page)


# --------------------------------------------------------------------------- assembly


def _pt(p: NDArray[np.float64]) -> Point2:
    return (round(float(p[0]), _ROUND) + 0.0, round(float(p[1]), _ROUND) + 0.0)


def _line(tr: Transform, a: tuple[float, float], b: tuple[float, float]) -> LineString | None:
    pts = tr.to_native(np.array([a, b], dtype=np.float64))
    p0, p1 = _pt(pts[0]), _pt(pts[1])
    if p0 == p1:
        return None
    return LineString(coords=(p0, p1))


def _native_polygon(tr: Transform, coords: list[tuple[float, float]]) -> Any:
    import shapely

    pts = tr.to_native(np.array(coords, dtype=np.float64))
    ring: list[Point2] = []
    for p in pts:
        q = _pt(p)
        if not ring or ring[-1] != q:
            ring.append(q)
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    if len(ring) < 3:
        return None
    poly = shapely.Polygon(ring)
    if not poly.is_valid or poly.area <= 0.0:
        return None
    return ring


def _run(gray: NDArray[np.uint8], warnings: list[str]) -> tuple[dict[str, Any] | None, float]:
    from ale.raster.openings import bridge_gaps, doors_from_gaps, find_gaps, max_gap_px
    from ale.raster.preprocess import preprocess
    from ale.raster.rooms import trace_rooms
    from ale.raster.walls import extract_walls

    pre = preprocess(gray)
    if pre is None:
        warnings.append("no dark content")
        return None, 0.0
    warnings.extend(pre.warnings)
    if pre.oblique_lines:
        warnings.append(
            f"{pre.oblique_lines} oblique line(s) ignored (only axis-parallel walls in v1)"
        )
    ext = extract_walls(pre.binary)
    warnings.extend(ext.warnings)
    if not ext.segments:
        warnings.append("no walls found")
        return None, 0.0
    h, w = pre.binary.shape
    gaps = find_gaps(ext.segments, ext.wall_mask, max_gap_px(ext.median_thickness, min(h, w)))
    sealed = bridge_gaps(ext.wall_mask, gaps)
    regions, room_warnings = trace_rooms(sealed, ext.median_thickness)
    warnings.extend(room_warnings)
    doors = doors_from_gaps(gaps)
    area = float(h * w)
    total_len = sum(s.length for s in ext.segments)
    long_len = sum(s.length for s in ext.segments if s.length >= LONG_WALL_SHARE * min(h, w))
    score = plan_score(
        extent_share=pre.content_share,
        ink_share=float(np.count_nonzero(pre.binary)) / area,
        wall_share=float(np.count_nonzero(ext.wall_mask)) / area,
        n_rooms=len(regions),
        room_share=sum(r.area_px for r in regions) / area,
        straight_share=ext.explained_pixels / ext.line_pixels if ext.line_pixels else 0.0,
        long_share=long_len / total_len if total_len > 0 else 0.0,
    )
    tr = pre.transform
    walls: list[Wall] = []
    index: dict[int, int] = {}
    for i, s in enumerate(ext.segments):
        a, b = s.endpoints()
        line = _line(tr, a, b)
        if line is None:  # pragma: no cover - walls are >= 1.5 % of the short side long
            continue
        index[i] = len(walls)
        walls.append(
            Wall(centerline=line, thickness=round(tr.length_to_native(s.thickness), _ROUND))
        )
    openings: list[Opening] = []
    for g in doors:
        a, b = g.endpoints()
        seg = _line(tr, a, b)
        width = round(tr.length_to_native(g.length), _ROUND)
        if seg is None or width <= 0.0:  # pragma: no cover - a gap has >= 1 free pixel
            continue
        openings.append(
            Opening(
                kind=OpeningKind.DOOR, segment=seg, width_native=width, host_wall=index.get(g.host)
            )
        )
    rooms: list[LabelledPolygon] = []
    for r in regions:
        coords = [(float(x), float(y)) for x, y in r.polygon.exterior.coords[:-1]]
        ring = _native_polygon(tr, coords)
        if ring is None:
            warnings.append("room polygon degenerate after mapping: skipped")
            continue
        rooms.append(
            LabelledPolygon.model_validate(
                {"id": f"R{len(rooms) + 1}", "polygon": {"exterior": ring}}
            )
        )
    if not rooms:
        warnings.append("no rooms found")
    return {"walls": walls, "openings": openings, "rooms": rooms}, score


def read_raster(
    image: Path | str | NDArray[Any],
    *,
    source_sha256: str,
    page: int = 0,
    source_kind: SourceKind = SourceKind.RASTER,
    config: AleConfig,
) -> RasterReadResult:
    """Read one floor-plan image (a file path or a ``uint8`` array, BGR(A) or grey)."""
    del config  # reserved: no tunable of AleConfig applies to raster reading yet
    warnings: list[str] = []

    def fail(reason: str) -> RasterReadResult:
        return RasterReadResult(plans=(), warnings=(*warnings, reason), plan_score=0.0)

    if not isinstance(source_sha256, str) or not _SHA_RE.match(source_sha256):
        return fail("invalid source_sha256 (64 lowercase hex characters expected)")
    if isinstance(page, bool) or not isinstance(page, int) or page < 0:
        return fail(f"invalid page {page!r}")
    try:
        kind = SourceKind(source_kind)
    except ValueError:
        return fail(f"invalid source_kind {source_kind!r}")
    try:
        import cv2  # noqa: F401
    except ImportError:
        return fail("raster extra not installed (opencv-python-headless)")
    from ale.raster.preprocess import to_gray

    try:
        if isinstance(image, str | Path):
            arr, reason = _load(Path(image), page)
            if arr is None:
                return fail(reason or "cannot read image")
        else:
            arr = image
        gray, reason = to_gray(arr)
        if gray is None:
            return fail(reason or "unsupported image")
        parts, score = _run(gray, warnings)
        if parts is None:
            return RasterReadResult(plans=(), warnings=tuple(warnings), plan_score=0.0)
        if score < 0.3:
            warnings.append(f"low plan score {score:.2f}")
        plan = PlanGeometry(
            source_sha256=source_sha256,
            page=page,
            plan_index=0,
            source_kind=kind,
            frame=Frame.Y_DOWN,
            units_label="px",
            walls=tuple(parts["walls"]),
            openings=tuple(parts["openings"]),
            rooms=tuple(parts["rooms"]),
            warnings=tuple(warnings),
        )
    except Exception as exc:  # the reader never raises on bad input
        log.warning("raster read failed: %s: %s", type(exc).__name__, exc)
        return fail(f"raster pipeline error: {type(exc).__name__}: {exc}")
    return RasterReadResult(plans=(plan,), warnings=tuple(warnings), plan_score=score)


def rasterize_pdf_page(path: Path, page: int, dpi: int) -> NDArray[np.uint8]:
    """Render one PDF page to a grey ``uint8`` array (PyMuPDF, extra ``pdf``).

    The DPI is lowered when the page would exceed ``MAX_PDF_PIXELS``. On any failure
    (missing extra, unreadable file, page out of range, bad DPI) a warning is logged and
    an empty ``(0, 0)`` array is returned, which :func:`read_raster` reports as
    ``empty image``.
    """
    empty = np.zeros((0, 0), dtype=np.uint8)
    try:
        import pymupdf
    except ImportError:
        log.warning("rasterize_pdf_page: pdf extra not installed (pymupdf)")
        return empty
    if isinstance(dpi, bool) or not isinstance(dpi, int | float) or not dpi > 0:
        log.warning("rasterize_pdf_page: invalid dpi %r", dpi)
        return empty
    try:
        with pymupdf.open(Path(path)) as doc:  # type: ignore[no-untyped-call]
            if isinstance(page, bool) or not isinstance(page, int) or not 0 <= page < len(doc):
                log.warning("rasterize_pdf_page: page %r out of range (%d)", page, len(doc))
                return empty
            pg = doc[page]
            zoom = float(dpi) / 72.0
            rect = pg.rect
            pixels = rect.width * rect.height * zoom * zoom
            if pixels > MAX_PDF_PIXELS:
                zoom *= math.sqrt(MAX_PDF_PIXELS / pixels)
                log.warning("rasterize_pdf_page: dpi lowered to %.1f (pixel cap)", zoom * 72.0)
            pix = pg.get_pixmap(
                matrix=pymupdf.Matrix(zoom, zoom),  # type: ignore[no-untyped-call]
                colorspace=pymupdf.csGRAY,
                alpha=False,
            )
            buf = np.frombuffer(pix.samples, dtype=np.uint8)
            arr = buf.reshape(pix.height, pix.stride)[:, : pix.width].copy()
    except Exception as exc:
        log.warning("rasterize_pdf_page failed: %s: %s", type(exc).__name__, exc)
        return empty
    return np.asarray(arr, dtype=np.uint8)
