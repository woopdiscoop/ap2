"""Drawing scale from title-block texts (``1/100``, ``1:50``, ``Ech. 1/200``, ``ÉCHELLE 1:100``).

Texts are canonicalised (NFKD, accents removed, upper case) before matching. A token is
``1 : N`` or ``1 / N`` not glued to other digits, slashes or decimals:

* preceded by a scale keyword (``ECHELLE``, ``ECH``, ``ECH.``, ``SCALE``): any N in 2..100 000;
* bare: only the usual architectural scales (``STANDARD_SCALES``) — a bare ``1/12`` is far
  more often a sheet number or a date than a scale.

One distinct N → that scale, confidence 0.9. Several distinct N → the candidate whose
text box is nearest to the walls' bounding box (ties: first in reading order),
confidence 0.6. None → ``UNKNOWN``. With ``1:N`` the scale is
``N x 0.0254 / 72`` metres per PDF point (method ``TITLE_BLOCK``).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from ale.contracts.enums import ScaleMethod

__all__ = [
    "CONFIDENCE_MULTIPLE",
    "CONFIDENCE_SINGLE",
    "STANDARD_SCALES",
    "ScaleResult",
    "ScaleText",
    "find_scale",
    "m_per_pt",
    "scale_tokens",
]

Box = tuple[float, float, float, float]

CONFIDENCE_SINGLE = 0.9
CONFIDENCE_MULTIPLE = 0.6
STANDARD_SCALES = frozenset(
    {10, 20, 25, 50, 75, 100, 125, 150, 200, 250, 300, 400, 500, 750, 1000, 1250, 1500,
     2000, 2500, 5000, 10000}
)  # fmt: skip
_KEYWORD_RANGE = (2, 100_000)
_TOKEN_RE = re.compile(
    r"(?P<kw>\b(?:ECHELLE|ECH|SCALE)\b\.?\s*:?\s*)?"
    r"(?<![\d/.,])1\s*[:/]\s*(?P<n>\d{1,6})(?![\d/]|[.,]\d)"
)


@dataclass(frozen=True)
class ScaleText:
    """A line of text and its box ``(x0, y0, x1, y1)`` in points."""

    text: str
    bbox: Box


@dataclass(frozen=True)
class ScaleResult:
    """Scale found on a page; ``m_per_unit`` is ``None`` when unknown."""

    m_per_unit: float | None
    method: ScaleMethod
    confidence: float
    denominator: int | None
    candidates: tuple[int, ...]


def m_per_pt(denominator: int) -> float:
    """Metres per PDF point at scale ``1:denominator``."""
    return denominator * 0.0254 / 72.0


def _canonical(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).upper()


def scale_tokens(text: str) -> tuple[int, ...]:
    """Scale denominators written in ``text``, in order of appearance."""
    out: list[int] = []
    for m in _TOKEN_RE.finditer(_canonical(text)):
        n = int(m.group("n"))
        if m.group("kw"):
            if _KEYWORD_RANGE[0] <= n <= _KEYWORD_RANGE[1]:
                out.append(n)
        elif n in STANDARD_SCALES:
            out.append(n)
    return tuple(out)


def _box_distance(a: Box, b: Box) -> float:
    dx = max(b[0] - a[2], a[0] - b[2], 0.0)
    dy = max(b[1] - a[3], a[1] - b[3], 0.0)
    return math.hypot(dx, dy)


def find_scale(texts: Sequence[ScaleText], walls_bbox: Box | None) -> ScaleResult:
    """Scale of a page from its texts (see module docstring)."""
    found: list[tuple[int, Box]] = [(n, t.bbox) for t in texts for n in scale_tokens(t.text)]
    if not found:
        return ScaleResult(None, ScaleMethod.UNKNOWN, 0.0, None, ())
    distinct = tuple(dict.fromkeys(n for n, _ in found))
    if len(distinct) == 1:
        n = distinct[0]
        confidence = CONFIDENCE_SINGLE
    else:
        ref = walls_bbox
        n = found[0][0] if ref is None else min(found, key=lambda f: _box_distance(f[1], ref))[0]
        confidence = CONFIDENCE_MULTIPLE
    return ScaleResult(m_per_pt(n), ScaleMethod.TITLE_BLOCK, confidence, n, distinct)
