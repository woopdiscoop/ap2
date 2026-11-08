"""``SourceKind`` detection by content (Ticket 1.1 RD section 4).

The content decides; the extension is only a tie-break (the ``kind`` recorded for a
``FAILED`` unit whose content is not recognised). PyMuPDF (``fitz``, extra ``pdf``) is
imported lazily for the page analysis of PDFs.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from ale.contracts.enums import FileStatus, SourceKind

__all__ = [
    "DWG_NEEDS_TOOL_REASON",
    "PDF_NEEDS_TOOL_REASON",
    "Classification",
    "Family",
    "UnitResult",
    "classify_file",
    "detect_family",
    "expected_family",
    "load_fitz",
]

log = logging.getLogger(__name__)

DWG_NEEDS_TOOL_REASON = "DWG needs ODA File Converter or accoreconsole"
PDF_NEEDS_TOOL_REASON = "pdf extra not installed"
SCANNED_IMAGE_COVERAGE = 0.5
HEAD_SIZE = 4096
TAIL_SIZE = 4096

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_TIFF_MAGICS = (b"II*\x00", b"MM\x00*")
_BIGTIFF_MAGICS = (b"II+\x00", b"MM\x00+")
_BINARY_DXF = b"AutoCAD Binary DXF"
_PDF_MAGIC = b"%PDF-"


class Family(StrEnum):
    """Content family detected from the first bytes of a file."""

    DWG = "DWG"
    DXF = "DXF"
    RASTER = "RASTER"
    PDF = "PDF"


_EXT_FAMILY: dict[str, Family] = {
    "dwg": Family.DWG,
    "dxf": Family.DXF,
    "pdf": Family.PDF,
    "png": Family.RASTER,
    "jpg": Family.RASTER,
    "jpeg": Family.RASTER,
    "tif": Family.RASTER,
    "tiff": Family.RASTER,
}

#: ``kind`` of a unit whose content could not be analysed (tie-break by family).
_FALLBACK_KIND: dict[Family, SourceKind] = {
    Family.DWG: SourceKind.DWG,
    Family.DXF: SourceKind.DXF,
    Family.PDF: SourceKind.PDF_SCANNED,
    Family.RASTER: SourceKind.RASTER,
}


@dataclass(frozen=True)
class UnitResult:
    page: int
    kind: SourceKind
    status: FileStatus
    reason: str | None = None


@dataclass(frozen=True)
class Classification:
    #: Family recognised from the content (None = not recognised).
    content: Family | None
    #: Family implied by the extension (None = unknown extension).
    expected: Family | None
    units: tuple[UnitResult, ...]

    @property
    def kind_mismatch(self) -> bool:
        return self.content is not None and self.content != self.expected


def expected_family(ext: str) -> Family | None:
    return _EXT_FAMILY.get(ext.lower().lstrip("."))


def _is_dxf_text(head: bytes) -> bool:
    text = head.removeprefix(b"\xef\xbb\xbf").decode("latin-1")
    tokens = [line.strip() for line in text.splitlines() if line.strip()]
    while len(tokens) >= 2 and tokens[0] == "999":  # leading comment groups
        tokens = tokens[2:]
    return tokens[:2] == ["0", "SECTION"]


def detect_family(head: bytes) -> Family | None:
    """Family of a file from its first bytes, or None if not recognised."""
    if len(head) >= 6 and head[:4] == b"AC10" and head[4:6].isdigit():
        return Family.DWG
    if head.startswith(_BINARY_DXF):
        return Family.DXF
    if head.startswith(_PNG_MAGIC) or head.startswith(_JPEG_MAGIC):
        return Family.RASTER
    if head[:4] in _TIFF_MAGICS or head[:4] in _BIGTIFF_MAGICS:
        return Family.RASTER
    if _PDF_MAGIC in head[:1024]:
        return Family.PDF
    if _is_dxf_text(head):
        return Family.DXF
    return None


def _raster_problem(head: bytes, tail: bytes, size: int) -> str | None:
    """None if the raster looks structurally complete, else the reason."""
    if head.startswith(_PNG_MAGIC):
        if len(head) < 33 or head[12:16] != b"IHDR":
            return "corrupt PNG (missing IHDR)"
        if b"IEND" not in tail:
            return "truncated PNG (missing IEND)"
        return None
    if head.startswith(_JPEG_MAGIC):
        if b"\xff\xd9" not in tail:
            return "truncated JPEG (missing end-of-image marker)"
        return None
    big = head[:4] in _BIGTIFF_MAGICS
    order: Literal["little", "big"] = "little" if head[:2] == b"II" else "big"
    raw = head[8:16] if big else head[4:8]
    offset = int.from_bytes(raw, order) if len(raw) == (8 if big else 4) else 0
    if not (8 <= offset < size):
        return "corrupt TIFF (invalid IFD offset)"
    return None


def load_fitz() -> Any | None:
    """The PyMuPDF module, or None when the ``pdf`` extra is not installed."""
    for name in ("pymupdf", "fitz"):  # "fitz" is the legacy name of the same package
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    return None


def _image_coverage(page: Any) -> float:
    """Fraction of the page area covered by the union of its image rectangles."""
    from shapely.geometry import box  # lazy: keeps `ale` start-up light
    from shapely.ops import unary_union

    rect = page.rect
    page_box = box(rect.x0, rect.y0, rect.x1, rect.y1)
    if page_box.area <= 0:
        return 0.0
    shapes = []
    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        shape = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        shapes.append(shape.intersection(page_box))
    if not shapes:
        return 0.0
    return float(unary_union(shapes).area / page_box.area)


def _page_kind(page: Any, min_paths: int) -> SourceKind:
    paths = len(page.get_drawings())
    if paths >= min_paths:
        return SourceKind.PDF_VECTOR
    if _image_coverage(page) >= SCANNED_IMAGE_COVERAGE:
        return SourceKind.PDF_SCANNED
    return SourceKind.PDF_VECTOR if paths >= 1 else SourceKind.PDF_SCANNED


def _failed_pdf(reason: str) -> tuple[UnitResult, ...]:
    return (UnitResult(0, SourceKind.PDF_SCANNED, FileStatus.FAILED, reason),)


def _classify_pdf(path: Path, min_paths: int) -> tuple[UnitResult, ...]:
    fitz = load_fitz()
    if fitz is None:
        return (
            UnitResult(0, SourceKind.PDF_SCANNED, FileStatus.NEEDS_TOOL, PDF_NEEDS_TOOL_REASON),
        )
    fitz.TOOLS.mupdf_display_errors(False)
    with path.open("rb") as fh:
        data = fh.read()
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        return _failed_pdf(f"unreadable PDF ({exc})")
    try:
        if doc.needs_pass:
            return _failed_pdf("encrypted PDF (password required)")
        if doc.page_count == 0:
            return _failed_pdf("PDF has no pages")
        units: list[UnitResult] = []
        for index in range(doc.page_count):
            try:
                kind = _page_kind(doc.load_page(index), min_paths)
            except Exception as exc:
                units.append(
                    UnitResult(
                        index,
                        SourceKind.PDF_SCANNED,
                        FileStatus.FAILED,
                        f"unreadable PDF page ({exc})",
                    )
                )
                continue
            units.append(UnitResult(index, kind, FileStatus.NEW))
        return tuple(units)
    finally:
        doc.close()


def _read_head_tail(path: Path, size: int) -> tuple[bytes, bytes]:
    with path.open("rb") as fh:
        head = fh.read(HEAD_SIZE)
        if size > TAIL_SIZE:
            fh.seek(size - TAIL_SIZE)
            tail = fh.read(TAIL_SIZE)
        else:
            tail = head
    return head, tail


def classify_file(
    path: Path,
    ext: str,
    *,
    pdf_vector_min_paths: int,
    dwg_tool_available: bool,
) -> Classification:
    """Classify one file into its units. Never raises for bad content (``FAILED`` units)."""
    expected = expected_family(ext)
    fallback = _FALLBACK_KIND[expected] if expected is not None else SourceKind.RASTER
    try:
        size = path.stat().st_size
        head, tail = _read_head_tail(path, size)
    except OSError as exc:
        reason = f"cannot read file ({exc.strerror or exc})"
        return Classification(None, expected, (UnitResult(0, fallback, FileStatus.FAILED, reason),))
    if not head:
        return Classification(
            None, expected, (UnitResult(0, fallback, FileStatus.FAILED, "empty file"),)
        )
    family = detect_family(head)
    units: tuple[UnitResult, ...]
    if family is None:
        label = f".{ext}" if ext else "file without extension"
        reason = f"unrecognised content for {label}"
        units = (UnitResult(0, fallback, FileStatus.FAILED, reason),)
    elif family is Family.DWG:
        if dwg_tool_available:
            units = (UnitResult(0, SourceKind.DWG, FileStatus.NEW),)
        else:
            units = (UnitResult(0, SourceKind.DWG, FileStatus.NEEDS_TOOL, DWG_NEEDS_TOOL_REASON),)
    elif family is Family.DXF:
        units = (UnitResult(0, SourceKind.DXF, FileStatus.NEW),)
    elif family is Family.RASTER:
        problem = _raster_problem(head, tail, size)
        status = FileStatus.NEW if problem is None else FileStatus.FAILED
        units = (UnitResult(0, SourceKind.RASTER, status, problem),)
    else:
        try:
            units = _classify_pdf(path, pdf_vector_min_paths)
        except OSError as exc:
            units = _failed_pdf(f"cannot read file ({exc.strerror or exc})")
    return Classification(family, expected, units)
