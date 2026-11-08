"""Scale reconciliation of a ``PlanGeometry`` (ticket 1.6).

:func:`resolve_scale` picks the metres-per-native-unit scale of a plan from the first
available source of this hierarchy:

1. ``DRAWING_UNITS`` already set by the CAD reader (kept as is, confidence included);
2. ``plans_meta.csv`` (the ``meta`` mapping) → ``META_CSV``, confidence 1.0;
3. ``TITLE_BLOCK`` (or ``SCALE_BAR``) already set by the PDF reader (kept as is);
4. dimension texts paired with parallel walls → ``DIMENSION_TEXT``, confidence 0.7;
5. median door width (0.90 m) → ``DOOR_MEDIAN``, confidence 0.5;
6. otherwise ``UNKNOWN``.

Once a scale is known every opening gets ``width_m = width_native * scale``; all other
geometry stays in native units. The function never raises: problems become plan warnings.
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from ale.contracts.config import AleConfig
from ale.contracts.enums import OpeningKind, ScaleMethod, SourceKind
from ale.contracts.models import PlanGeometry, TextItem

__all__ = [
    "CONF_DIMENSION_TEXT",
    "CONF_DOOR_MEDIAN",
    "CONF_META_CSV",
    "DOOR_WIDTH_M",
    "resolve_scale",
]

INCH_M = 0.0254
PT_PER_INCH = 72.0

CONF_META_CSV = 1.0
CONF_DIMENSION_TEXT = 0.7
CONF_DOOR_MEDIAN = 0.5

#: Reference door width, metres.
DOOR_WIDTH_M = 0.90
#: Minimum number of doors (after outlier rejection) for the door-median estimate.
DOOR_MIN_COUNT = 3
#: Doors whose width is outside ``[lo, hi] x median`` are rejected.
DOOR_REJECT_LO = 0.5
DOOR_REJECT_HI = 2.0

#: A dimension text pairs with a wall segment at most this many text heights away.
DIM_MAX_DIST_HEIGHTS = 3.0
#: Maximum angle between a text's direction and a "parallel" wall segment, degrees.
DIM_PARALLEL_TOL_DEG = 10.0
#: Minimum size of the consistent cluster of candidate scales.
DIM_MIN_CLUSTER = 3
#: Relative spread (max / min - 1) of a consistent cluster.
DIM_CLUSTER_REL = 0.03

# Plausible ranges of a scale derived from dimension texts, per native unit kind.
# Paper scales 1:10 .. 1:5000; raster resolutions 50 .. 1200 dpi.
_DENOM_MIN, _DENOM_MAX = 10.0, 5000.0
_DPI_MIN, _DPI_MAX = 50.0, 1200.0
_PLAUSIBLE: dict[str, tuple[float, float]] = {
    "pt": (_DENOM_MIN * INCH_M / PT_PER_INCH, _DENOM_MAX * INCH_M / PT_PER_INCH),
    "px": (_DENOM_MIN * INCH_M / _DPI_MAX, _DENOM_MAX * INCH_M / _DPI_MIN),
    "cad": (1e-4, 10.0),
}

_CAD_UNITS: dict[str, float] = {
    "m": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "metre": 1.0,
    "metres": 1.0,
    "dm": 0.1,
    "cm": 0.01,
    "mm": 0.001,
    "km": 1000.0,
    "in": INCH_M,
    "inch": INCH_M,
    "inches": INCH_M,
    "ft": 0.3048,
    "foot": 0.3048,
    "feet": 0.3048,
}

# Unit interpretations of a dimension value: (name, metres per unit).
_DIM_UNITS: tuple[tuple[str, float], ...] = (("m", 1.0), ("cm", 0.01), ("mm", 0.001))

_NUMBER_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*$")

_CAD_KINDS = (SourceKind.DWG, SourceKind.DXF)


@dataclass(frozen=True)
class _Scale:
    value: float
    method: ScaleMethod
    confidence: float


# --------------------------------------------------------------------------- helpers


def _native_kind(plan: PlanGeometry) -> str:
    """``"cad"``, ``"pt"`` (PDF points) or ``"px"`` (pixels) for the plan's native unit."""
    if plan.source_kind in _CAD_KINDS:
        return "cad"
    label = (plan.units_label or "").strip().lower()
    if label in ("pt", "px"):
        return label
    return "pt" if plan.source_kind is SourceKind.PDF_VECTOR else "px"


def _meta_number(meta: Mapping[str, Any], key: str, warnings: list[str]) -> float | None:
    """Positive finite number under ``key`` (numbers or numeric strings), else ``None``."""
    raw = meta.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    value: float | None = None
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        value = float(raw)
    elif isinstance(raw, str):
        try:
            value = float(raw.strip().replace(",", "."))
        except ValueError:
            value = None
    if value is None or not math.isfinite(value) or value <= 0.0:
        warnings.append(f"scale: meta {key}={raw!r} is not a positive number (ignored)")
        return None
    return value


def _meta_scale(
    plan: PlanGeometry, meta: Mapping[str, Any] | None, config: AleConfig, warnings: list[str]
) -> float | None:
    """Level 2: scale from the ``plans_meta.csv`` row, or ``None``."""
    if not meta:
        return None
    kind = _native_kind(plan)
    if kind == "cad":
        raw = meta.get("units")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None
        factor = _CAD_UNITS.get(str(raw).strip().lower())
        if factor is None:
            warnings.append(f"scale: meta units={raw!r} is not a known unit (ignored)")
        return factor
    n = _meta_number(meta, "scale_1_to", warnings)
    if n is None:
        return None
    if kind == "pt":
        return n * INCH_M / PT_PER_INCH
    dpi = _meta_number(meta, "dpi", warnings)
    if dpi is None and plan.source_kind is SourceKind.PDF_SCANNED:
        # A scanned PDF page is rendered by ALE itself at the configured resolution.
        dpi = float(config.extract.raster_dpi)
    if dpi is None:
        warnings.append("scale: meta scale_1_to given but a raster plan also needs dpi (ignored)")
        return None
    return n * INCH_M / dpi


def _segments(plan: PlanGeometry) -> np.ndarray:
    """Wall segments as an ``(n, 4)`` array ``ax, ay, bx, by`` (zero-length ones dropped)."""
    rows = [
        (a[0], a[1], b[0], b[1])
        for wall in plan.walls
        for a, b in zip(wall.centerline.coords, wall.centerline.coords[1:], strict=False)
    ]
    arr = np.asarray(rows, dtype=float).reshape(-1, 4)
    if arr.size == 0:
        return arr
    lengths = np.hypot(arr[:, 2] - arr[:, 0], arr[:, 3] - arr[:, 1])
    keep = np.isfinite(lengths) & (lengths > 0.0)
    return np.asarray(arr[keep])


def _unit_preferences(token: str) -> dict[str, int]:
    """Tie-break rank (0 = most likely) of each unit interpretation of a number token."""
    if "." in token or "," in token:
        return {"m": 0, "cm": 1, "mm": 2}
    if len(token.lstrip("0")) >= 4:
        return {"mm": 0, "cm": 1, "m": 2}
    return {"cm": 0, "mm": 1, "m": 2}


def _nearest_parallel_length(text: TextItem, segs: np.ndarray) -> float | None:
    """Length of the nearest wall segment parallel to ``text`` within reach, or ``None``."""
    height = text.height
    if height is None or not math.isfinite(height) or height <= 0.0 or segs.size == 0:
        return None
    ax, ay, bx, by = segs[:, 0], segs[:, 1], segs[:, 2], segs[:, 3]
    dx, dy = bx - ax, by - ay
    lengths = np.hypot(dx, dy)
    seg_angle = np.degrees(np.arctan2(dy, dx))
    diff = np.abs((seg_angle - text.rotation_deg) % 180.0)
    diff = np.minimum(diff, 180.0 - diff)
    px, py = text.insert
    t = np.clip(((px - ax) * dx + (py - ay) * dy) / (lengths * lengths), 0.0, 1.0)
    dist = np.hypot(ax + t * dx - px, ay + t * dy - py)
    ok = (diff <= DIM_PARALLEL_TOL_DEG) & (dist <= DIM_MAX_DIST_HEIGHTS * height)
    if not bool(ok.any()):
        return None
    idx = np.flatnonzero(ok)
    best = int(idx[int(np.argmin(dist[idx]))])  # first of the nearest on ties
    return float(lengths[best])


def _dimension_scale(plan: PlanGeometry) -> float | None:
    """Level 4: median of the largest consistent cluster of dimension-text scales."""
    segs = _segments(plan)
    if segs.size == 0:
        return None
    lo, hi = _PLAUSIBLE[_native_kind(plan)]
    candidates: list[tuple[float, int]] = []  # (scale, unit preference rank)
    for text in plan.texts:
        match = _NUMBER_RE.match(text.text)
        if match is None:
            continue
        token = match.group(1)
        value = float(token.replace(",", "."))
        if value <= 0.0:
            continue
        length = _nearest_parallel_length(text, segs)
        if length is None:
            continue
        prefs = _unit_preferences(token)
        for unit, factor in _DIM_UNITS:
            scale = value * factor / length
            if lo <= scale <= hi:
                candidates.append((scale, prefs[unit]))
    if len(candidates) < DIM_MIN_CLUSTER:
        return None
    candidates.sort()
    best: tuple[int, int, int] | None = None  # (-count, preference sum, start)
    best_window: tuple[int, int] = (0, 0)
    j = 0
    n = len(candidates)
    for i in range(n):
        j = max(j, i)
        limit = candidates[i][0] * (1.0 + DIM_CLUSTER_REL)
        while j + 1 < n and candidates[j + 1][0] <= limit:
            j += 1
        count = j - i + 1
        if count < DIM_MIN_CLUSTER:
            continue
        key = (-count, sum(p for _, p in candidates[i : j + 1]), i)
        if best is None or key < best:
            best, best_window = key, (i, j + 1)
    if best is None:
        return None
    return float(statistics.median(s for s, _ in candidates[best_window[0] : best_window[1]]))


def _door_scale(plan: PlanGeometry, warnings: list[str]) -> float | None:
    """Level 5: 0.90 m over the median native door width (outliers rejected)."""
    widths = [o.width_native for o in plan.openings if o.kind is OpeningKind.DOOR]
    if len(widths) < DOOR_MIN_COUNT:
        return None
    med = statistics.median(widths)
    kept = [w for w in widths if DOOR_REJECT_LO * med <= w <= DOOR_REJECT_HI * med]
    if len(kept) < DOOR_MIN_COUNT:
        return None
    rejected = len(widths) - len(kept)
    if rejected:
        warnings.append(f"scale: door median ignored {rejected} outlier door width(s)")
    return DOOR_WIDTH_M / statistics.median(kept)


_EXISTING_LEVEL: dict[ScaleMethod, int] = {
    ScaleMethod.DRAWING_UNITS: 1,
    ScaleMethod.META_CSV: 2,
    ScaleMethod.TITLE_BLOCK: 3,
    ScaleMethod.SCALE_BAR: 3,
    ScaleMethod.DIMENSION_TEXT: 4,
    ScaleMethod.DOOR_MEDIAN: 5,
}


def _choose(
    plan: PlanGeometry, meta: Mapping[str, Any] | None, config: AleConfig, warnings: list[str]
) -> _Scale | None:
    existing: _Scale | None = None
    existing_level = 0
    if plan.scale_m_per_unit is not None and plan.scale_method is not ScaleMethod.UNKNOWN:
        existing = _Scale(plan.scale_m_per_unit, plan.scale_method, plan.scale_confidence)
        existing_level = _EXISTING_LEVEL.get(plan.scale_method, 0)
    for level in range(1, 6):
        if existing is not None and existing_level == level:
            return existing
        value: float | None = None
        method, conf = ScaleMethod.UNKNOWN, 0.0
        if level == 2:
            value = _meta_scale(plan, meta, config, warnings)
            method, conf = ScaleMethod.META_CSV, CONF_META_CSV
        elif level == 4:
            value = _dimension_scale(plan)
            method, conf = ScaleMethod.DIMENSION_TEXT, CONF_DIMENSION_TEXT
        elif level == 5:
            value = _door_scale(plan, warnings)
            method, conf = ScaleMethod.DOOR_MEDIAN, CONF_DOOR_MEDIAN
        if value is not None and math.isfinite(value) and value > 0.0:
            return _Scale(value, method, conf)
    return existing


def _with_warnings(plan: PlanGeometry, new: list[str]) -> list[str]:
    out = list(plan.warnings)
    for w in new:
        if w not in out:
            out.append(w)
    return out


# --------------------------------------------------------------------------- public API


def resolve_scale(
    plan: PlanGeometry,
    *,
    meta: Mapping[str, Any] | None = None,
    config: AleConfig | None = None,
) -> PlanGeometry:
    """Return a copy of ``plan`` with its scale resolved and ``Opening.width_m`` filled.

    ``meta`` is the plan's ``plans_meta.csv`` row (keys ``scale_1_to``, ``dpi``, ``units``;
    values may be numbers or strings). Never raises: problems are appended to ``warnings``.
    """
    cfg = config if config is not None else AleConfig()
    warnings: list[str] = []
    try:
        chosen = _choose(plan, meta, cfg, warnings)
        if chosen is None:
            warnings.append("scale: unknown (no usable scale source)")
            data: dict[str, Any] = plan.model_dump()
            data.update(
                scale_m_per_unit=None,
                scale_method=ScaleMethod.UNKNOWN,
                scale_confidence=0.0,
                warnings=_with_warnings(plan, warnings),
            )
            return PlanGeometry.model_validate(data)
        s = chosen.value
        openings = [
            o.model_copy(update={"width_m": o.width_native * s}).model_dump() for o in plan.openings
        ]
        data = plan.model_dump()
        data.update(
            scale_m_per_unit=s,
            scale_method=chosen.method,
            scale_confidence=chosen.confidence,
            openings=openings,
            warnings=_with_warnings(plan, warnings),
        )
        return PlanGeometry.model_validate(data)
    except Exception as exc:  # public API never raises (RD 1.6)
        warnings.append(f"scale: resolution failed ({type(exc).__name__}: {exc})")
        return plan.model_copy(update={"warnings": tuple(_with_warnings(plan, warnings))})
