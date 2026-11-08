"""``read_pdf_page``: one page of a vector PDF → ``PdfReadResult``.

Geometry stays in PDF points in PyMuPDF page space (frame ``Y_DOWN``, ``units_label``
``"pt"``, ``source_kind PDF_VECTOR``). Paths come from ``page.get_drawings()``, texts
from ``page.get_text("dict")`` spans (``TextItem(source="PDF")``, insert = span origin,
height = font size, rotation = direction of the line).

Pipeline: walls (:mod:`ale.pdfread.walls`) → scale (:mod:`ale.pdfread.scale`, nearest
to the walls' bounding box) → door arcs → rooms (:mod:`ale.pdfread.rooms`) →
plan-likeness. One page gives at most one plan (``plan_index`` 0).

Plan-likeness: with ``W`` walls, ``R`` rooms, ``L`` the total wall centreline length and
``D`` the page diagonal (points)::

    likely     = W >= 8 and R >= 2 and L >= 0.2 * D * 3
    plan_score = (min(1, W / 8) + min(1, R / 2) + min(1, L / (0.6 * D))) / 3

so ``plan_score`` ∈ [0, 1] and equals 1 exactly when the page is plan-likely. A page
that is not plan-likely returns ``plans == ()``.

``read_pdf_page`` never raises: unreadable, encrypted or corrupt files, a bad page index
and internal errors become warnings.
"""

from __future__ import annotations

import importlib
import logging
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from ale.contracts.config import AleConfig
from ale.contracts.enums import Frame, ScaleMethod, SourceKind
from ale.contracts.models import Opening, PlanGeometry, TextItem, Wall
from ale.pdfread.rooms import RoomText, label_rooms, polygonize_rooms
from ale.pdfread.scale import ScaleResult, ScaleText, find_scale
from ale.pdfread.walls import (
    Bezier,
    FilledShape,
    Pt,
    StrokeSeg,
    build_doors,
    door_closures,
    extract_walls,
)

__all__ = [
    "MAX_PATH_ITEMS",
    "PLAN_LENGTH_DIAGONALS",
    "PLAN_MIN_ROOMS",
    "PLAN_MIN_WALLS",
    "PdfReadResult",
    "plan_likeness",
    "read_pdf_page",
]

log = logging.getLogger(__name__)

PLAN_MIN_WALLS = 8
PLAN_MIN_ROOMS = 2
PLAN_LENGTH_DIAGONALS = 0.6  # "wall length ≥ 20 % of page diagonal x 3" (0.2 * 3)
MAX_PATH_ITEMS = 1_000_000
MAX_TEXT_SPANS = 100_000
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class PdfReadResult(BaseModel):
    """Result of :func:`read_pdf_page`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plans: tuple[PlanGeometry, ...]
    warnings: tuple[str, ...]
    is_plan_likely: bool
    plan_score: float


@dataclass
class _Page:
    strokes: list[StrokeSeg] = field(default_factory=list)
    filled: list[FilledShape] = field(default_factory=list)
    chains: list[list[Bezier]] = field(default_factory=list)
    texts: list[TextItem] = field(default_factory=list)
    room_texts: list[RoomText] = field(default_factory=list)
    scale_texts: list[ScaleText] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _fail(*warnings: str) -> PdfReadResult:
    return PdfReadResult(plans=(), warnings=tuple(warnings), is_plan_likely=False, plan_score=0.0)


def _load_fitz() -> Any | None:
    for name in ("pymupdf", "fitz"):  # "fitz" is the legacy name of the same package
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    return None  # pragma: no cover - the pdf extra is installed in the test environment


def _pt(p: Any) -> Pt | None:
    try:
        x, y = float(p[0]), float(p[1])
    except (TypeError, ValueError, IndexError):
        return None
    return (x, y) if math.isfinite(x) and math.isfinite(y) else None


def _corners(item: Any) -> list[Pt] | None:
    kind = item[0]
    if kind == "re":
        r = item[1]
        pts = [_pt((r.x0, r.y0)), _pt((r.x1, r.y0)), _pt((r.x1, r.y1)), _pt((r.x0, r.y1))]
    else:  # "qu"
        q = item[1]
        pts = [_pt(q.ul), _pt(q.ur), _pt(q.lr), _pt(q.ll)]
    clean = [p for p in pts if p is not None]
    return clean if len(clean) == 4 else None


def _collect_path(d: dict[str, Any], out: _Page) -> int:
    """Add one drawing path to ``out``; returns its number of items."""
    ptype = str(d.get("type") or "")
    stroked = "s" in ptype
    filled = "f" in ptype and d.get("fill") is not None
    width = d.get("width")
    w = float(width) if isinstance(width, int | float) and math.isfinite(width) else 0.0
    items = d.get("items") or []
    poly: list[Pt] = []  # current subpath of line items
    chain: list[Bezier] = []

    def flush_poly() -> None:
        if filled and len(poly) >= 3:
            out.filled.append(FilledShape(tuple(poly)))
        if stroked and d.get("closePath") and len(poly) >= 3 and poly[0] != poly[-1]:
            out.strokes.append(StrokeSeg((poly[-1], poly[0]), w))
        poly.clear()

    def flush_chain() -> None:
        if stroked and chain:
            out.chains.append(list(chain))
        chain.clear()

    for item in items:
        kind = item[0] if item else None
        if kind == "l":
            a, b = _pt(item[1]), _pt(item[2])
            flush_chain()
            if a is None or b is None:
                flush_poly()
                continue
            if poly and poly[-1] != a:
                flush_poly()
            if not poly:
                poly.append(a)
            if b != poly[-1]:
                poly.append(b)
            if stroked and a != b:
                out.strokes.append(StrokeSeg((a, b), w))
        elif kind == "c":
            flush_poly()
            pts = [_pt(p) for p in item[1:5]]
            if len(pts) != 4 or any(p is None for p in pts):
                flush_chain()
                continue
            bz: Bezier = (pts[0], pts[1], pts[2], pts[3])  # type: ignore[assignment]
            if chain and chain[-1][3] != bz[0]:
                flush_chain()
            chain.append(bz)
        elif kind in ("re", "qu"):
            flush_poly()
            flush_chain()
            corners = _corners(item)
            if corners is None:
                continue
            if filled:
                out.filled.append(FilledShape(tuple(corners)))
            if stroked:
                for i in range(4):
                    a, b = corners[i], corners[(i + 1) % 4]
                    if a != b:
                        out.strokes.append(StrokeSeg((a, b), w))
        else:
            flush_poly()
            flush_chain()
    flush_poly()
    flush_chain()
    return len(items)


def _collect_drawings(drawings: Iterable[dict[str, Any]], out: _Page) -> None:
    total = 0
    for d in drawings:
        try:
            total += _collect_path(d, out)
        except Exception as exc:  # a malformed path never stops the page
            out.warnings.append(f"path skipped: {type(exc).__name__}: {exc}")
            total += 1
        if total > MAX_PATH_ITEMS:
            out.warnings.append(f"drawing truncated after {MAX_PATH_ITEMS} path items")
            break


def _collect_texts(text_dict: dict[str, Any], out: _Page) -> None:
    n = 0
    for block in text_dict.get("blocks", []):
        for line in block.get("lines", []) or []:
            dx, dy = line.get("dir", (1.0, 0.0))
            rotation = math.degrees(math.atan2(float(dy), float(dx))) + 0.0
            parts: list[str] = []
            boxes: list[tuple[float, float, float, float]] = []
            for span in line.get("spans", []) or []:
                text = str(span.get("text", ""))
                origin = _pt(span.get("origin", (math.nan, math.nan)))
                bbox = tuple(float(v) for v in span.get("bbox", (0.0, 0.0, 0.0, 0.0)))
                if not text.strip() or origin is None or len(bbox) != 4:
                    continue
                if not all(math.isfinite(v) for v in bbox):
                    continue
                n += 1
                if n > MAX_TEXT_SPANS:
                    out.warnings.append(f"texts truncated after {MAX_TEXT_SPANS} spans")
                    return
                size = float(span.get("size", 0.0))
                out.texts.append(
                    TextItem(
                        text=text,
                        insert=origin,
                        height=size if math.isfinite(size) and size > 0.0 else None,
                        rotation_deg=rotation,
                        source="PDF",
                    )
                )
                center = ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
                out.room_texts.append(RoomText(text, center))
                parts.append(text)
                boxes.append((bbox[0], bbox[1], bbox[2], bbox[3]))
            if not boxes:
                continue
            lbox = (
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            )
            joined = "".join(parts)
            out.scale_texts.append(ScaleText(joined, lbox))
            if len(parts) > 1:
                center = ((lbox[0] + lbox[2]) / 2.0, (lbox[1] + lbox[3]) / 2.0)
                out.room_texts.append(RoomText(joined, center))


def plan_likeness(
    n_walls: int, n_rooms: int, wall_length: float, diagonal: float
) -> tuple[bool, float]:
    """``(is_plan_likely, plan_score)`` (see module docstring)."""
    need = PLAN_LENGTH_DIAGONALS * diagonal
    length_term = 1.0 if need <= 0.0 else min(1.0, wall_length / need)
    score = (
        min(1.0, n_walls / PLAN_MIN_WALLS) + min(1.0, n_rooms / PLAN_MIN_ROOMS) + length_term
    ) / 3.0
    likely = n_walls >= PLAN_MIN_WALLS and n_rooms >= PLAN_MIN_ROOMS and wall_length >= need
    return likely, min(1.0, max(0.0, score))


def _walls_bbox(walls: list[Wall]) -> tuple[float, float, float, float] | None:
    if not walls:
        return None
    xs = [p[0] for w in walls for p in w.centerline.coords]
    ys = [p[1] for w in walls for p in w.centerline.coords]
    return (min(xs), min(ys), max(xs), max(ys))


def _with_width_m(openings: list[Opening], scale: float | None) -> list[Opening]:
    if scale is None:
        return openings
    return [o.model_copy(update={"width_m": o.width_native * scale}) for o in openings]


def _analyse(
    col: _Page, diagonal: float, *, source_sha256: str, page: int
) -> tuple[PlanGeometry | None, bool, float, list[str]]:
    warnings = list(col.warnings)
    wr = extract_walls(col.strokes, col.filled)
    warnings.extend(wr.warnings)
    walls = wr.walls
    scale: ScaleResult = find_scale(col.scale_texts, _walls_bbox(walls))
    if scale.method is ScaleMethod.UNKNOWN:
        warnings.append("scale unknown: no scale text found")
    elif len(scale.candidates) > 1:
        warnings.append(f"several scales {list(scale.candidates)}: chose 1:{scale.denominator}")
    openings = _with_width_m(build_doors(col.chains, walls), scale.m_per_unit)
    lines = [*wr.face_lines, *door_closures(openings, walls)]
    faces = polygonize_rooms(lines, wr.material, scale.m_per_unit, warnings)
    rooms = label_rooms(faces, col.room_texts, warnings)
    wall_length = sum(math.dist(w.centerline.coords[0], w.centerline.coords[-1]) for w in walls)
    likely, score = plan_likeness(len(walls), len(rooms), wall_length, diagonal)
    if not likely:
        warnings.append(
            f"not a plan: {len(walls)} walls, {len(rooms)} rooms, "
            f"wall length {wall_length:.1f} pt (score {score:.3f})"
        )
        return None, False, score, warnings
    plan = PlanGeometry(
        source_sha256=source_sha256,
        page=page,
        plan_index=0,
        source_kind=SourceKind.PDF_VECTOR,
        frame=Frame.Y_DOWN,
        units_label="pt",
        scale_m_per_unit=scale.m_per_unit,
        scale_method=scale.method,
        scale_confidence=scale.confidence,
        walls=tuple(walls),
        openings=tuple(openings),
        rooms=tuple(rooms),
        texts=tuple(col.texts),
        warnings=tuple(dict.fromkeys(warnings)),
    )
    return plan, True, score, warnings


def read_pdf_page(path: Path, page: int, *, source_sha256: str, config: AleConfig) -> PdfReadResult:
    """Read page ``page`` (0-based) of the vector PDF at ``path`` (see module docstring)."""
    del config  # reserved: no tunable of AleConfig applies to vector-PDF reading yet
    if not isinstance(source_sha256, str) or not _SHA_RE.match(source_sha256):
        return _fail("invalid source_sha256 (expected 64 lowercase hex characters)")
    if not isinstance(page, int) or isinstance(page, bool) or page < 0:
        return _fail(f"invalid page index {page!r}")
    fitz = _load_fitz()
    if fitz is None:  # pragma: no cover - the pdf extra is installed in the test environment
        return _fail("PyMuPDF is not installed (extra 'pdf')")
    try:
        fitz.TOOLS.mupdf_display_errors(False)
        data = Path(path).read_bytes()
    except Exception as exc:
        return _fail(f"cannot read file: {type(exc).__name__}: {exc}")
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        return _fail(f"unreadable PDF: {type(exc).__name__}: {exc}")
    try:
        if doc.needs_pass:
            return _fail("encrypted PDF (password required)")
        if page >= doc.page_count:
            return _fail(f"page {page} out of range (document has {doc.page_count} pages)")
        col = _Page()
        try:
            pg = doc.load_page(page)
            rect = pg.rect
            diagonal = math.hypot(float(rect.width), float(rect.height))
            _collect_drawings(pg.get_drawings(), col)
            _collect_texts(pg.get_text("dict"), col)
        except Exception as exc:
            return _fail(f"cannot parse page {page}: {type(exc).__name__}: {exc}")
        try:
            plan, likely, score, warnings = _analyse(
                col, diagonal, source_sha256=source_sha256, page=page
            )
        except Exception as exc:  # never raise for a readable page
            log.warning("read_pdf_page: %s: %s", type(exc).__name__, exc)
            return _fail(*col.warnings, f"extraction error: {type(exc).__name__}: {exc}")
        return PdfReadResult(
            plans=() if plan is None else (plan,),
            warnings=tuple(dict.fromkeys(warnings)),
            is_plan_likely=likely,
            plan_score=score,
        )
    finally:
        doc.close()
