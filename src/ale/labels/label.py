"""Semantic labelling of a plan's room polygons (Ticket 1.5).

Priority: CAD_TEXT / CAD_ZONE → PDF_TEXT → VLM → MANUAL.

1. Rooms that already have a type are kept as they are.
2. Untyped rooms are labelled from ``plan.texts``: a text item inside the polygon whose
   label normalises to a taxonomy key types the room (``CAD`` texts → ``CAD_TEXT``,
   ``PDF`` and ``OCR`` texts → ``PDF_TEXT``).
3. Remaining untyped rooms go to the VLM only when a provider is given **and**
   ``config.vlm.provider`` is set (and a PNG image is given); otherwise they stay untyped.

:func:`label_plan` never raises: every problem becomes a warning of the result.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Sequence
from typing import Any

import shapely
from pydantic import BaseModel, ConfigDict, NonNegativeInt, StrictStr

from ale.contracts.config import AleConfig
from ale.contracts.enums import Frame, LabelSource
from ale.contracts.geometry import Polygon
from ale.contracts.models import LabelledPolygon, PlanGeometry, TextItem
from ale.contracts.taxonomy import UNKNOWN, canon, load_taxonomy
from ale.labels import provider as _provider_mod
from ale.labels.bbox import Extent, normalized_to_native, png_size
from ale.labels.cache import VlmCache, cache_key
from ale.labels.provider import VlmProvider, VlmResponse, build_prompt, parse_response

__all__ = [
    "MIN_OVERLAP",
    "LabelResult",
    "assign_one_to_one",
    "label_plan",
    "plan_extent",
]

#: Minimum ``area(bbox ∩ polygon) / area(bbox)`` for a VLM box to match a room.
MIN_OVERLAP = 0.3

_CONFIG = ConfigDict(extra="forbid", frozen=True)

_TEXT_SOURCE: dict[str, LabelSource] = {
    "CAD": LabelSource.CAD_TEXT,
    "PDF": LabelSource.PDF_TEXT,
    "OCR": LabelSource.PDF_TEXT,
}
_CONF_EXACT = 1.0
_CONF_PREFIX = 0.8


class LabelResult(BaseModel):
    """Result of :func:`label_plan`."""

    model_config = _CONFIG

    plan: PlanGeometry
    api_calls: NonNegativeInt
    warnings: tuple[StrictStr, ...]


# --------------------------------------------------------------------------- geometry helpers


def _shape(polygon: Polygon) -> shapely.Geometry:
    geom: shapely.Geometry = shapely.Polygon(polygon.exterior, polygon.holes)
    if not shapely.is_valid(geom):
        geom = shapely.make_valid(geom)
    return geom


def plan_extent(plan: PlanGeometry) -> Extent | None:
    """Native extent ``(xmin, ymin, xmax, ymax)`` of rooms, walls and openings.

    ``None`` when the plan has no geometry or the extent is degenerate.
    """
    xs: list[float] = []
    ys: list[float] = []
    for room in plan.rooms:
        for x, y in room.polygon.exterior:
            xs.append(x)
            ys.append(y)
    for line in (*(w.centerline for w in plan.walls), *(o.segment for o in plan.openings)):
        for x, y in line.coords:
            xs.append(x)
            ys.append(y)
    if not xs:
        return None
    ext = (min(xs), min(ys), max(xs), max(ys))
    if not ext[2] > ext[0] or not ext[3] > ext[1]:
        return None
    return ext


# --------------------------------------------------------------------------- text labelling


def _label_from_texts(room: LabelledPolygon, texts: Sequence[TextItem]) -> LabelledPolygon | None:
    """``room`` typed from the best text inside it, or ``None`` if no text matches."""
    tax = load_taxonomy()
    poly = _shape(room.polygon)
    best: tuple[tuple[int, int], str, TextItem, bool] | None = None
    for t in texts:
        if not shapely.covers(poly, shapely.Point(t.insert)):
            continue
        match = tax.normalize_label(t.text)
        if match.key == UNKNOWN or match.matched_synonym is None:
            continue
        exact = match.rule == "exact"
        rank = (len(canon(match.matched_synonym)), 1 if exact else 0)
        if best is None or rank > best[0]:
            best = (rank, match.key, t, exact)
    if best is None:
        return None
    _, key, text, exact = best
    return room.model_copy(
        update={
            "type": key,
            "label_source": _TEXT_SOURCE[text.source],
            "confidence": _CONF_EXACT if exact else _CONF_PREFIX,
            "raw_label": text.text,
        }
    )


# --------------------------------------------------------------------------- assignment

Solver = Callable[..., Any]


def _scipy_solver() -> Solver | None:
    try:
        mod = importlib.import_module("scipy.optimize")
    except ImportError:
        return None
    solver = getattr(mod, "linear_sum_assignment", None)
    return solver if callable(solver) else None


def _greedy(weights: Sequence[Sequence[float]]) -> list[tuple[int, int]]:
    """Deterministic greedy matching: highest weight first, ties by (row, column)."""
    candidates = sorted(
        ((w, i, j) for i, row in enumerate(weights) for j, w in enumerate(row) if w > 0.0),
        key=lambda c: (-c[0], c[1], c[2]),
    )
    used_rows: set[int] = set()
    used_cols: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _, i, j in candidates:  # bounded: one pass over a finite list
        if i in used_rows or j in used_cols:
            continue
        used_rows.add(i)
        used_cols.add(j)
        pairs.append((i, j))
    return sorted(pairs)


def assign_one_to_one(
    weights: Sequence[Sequence[float]], *, use_scipy: bool = True
) -> list[tuple[int, int]]:
    """One-to-one ``(row, column)`` pairs maximising the total weight; weight 0 = forbidden.

    Uses ``scipy.optimize.linear_sum_assignment`` (Hungarian) when available, else the
    deterministic greedy fallback. Result sorted by row.
    """
    if not weights or not weights[0]:
        return []
    solver = _scipy_solver() if use_scipy else None
    if solver is None:
        return _greedy(weights)
    import numpy as np

    matrix = np.asarray(weights, dtype=float)
    rows, cols = solver(matrix, maximize=True)
    pairs = [
        (int(i), int(j)) for i, j in zip(rows, cols, strict=True) if weights[int(i)][int(j)] > 0.0
    ]
    return sorted(pairs)


# --------------------------------------------------------------------------- VLM stage


def _type_of_label(label: str) -> str:
    """Taxonomy key of a VLM label: an exact key, else ``normalize_label`` (may be unknown)."""
    tax = load_taxonomy()
    stripped = label.strip()
    keys = tax.keys()
    if stripped in keys and stripped != UNKNOWN:
        return stripped
    return tax.normalize_label(label).key


def _call_provider(
    provider: VlmProvider, image: bytes, config: AleConfig, warnings: list[str]
) -> tuple[VlmResponse | None, str | None, int]:
    """``(response, raw, calls)``; one first attempt plus the configured retries."""
    attempts = 1 + config.vlm.max_invalid_json_retries
    prompt = build_prompt()
    calls = 0
    error = "no attempt"
    for _ in range(attempts):  # bounded by config (1 + at most 3)
        calls += 1
        try:
            raw = provider.label_image(image, prompt, temperature=config.vlm.temperature)
        except Exception as exc:
            warnings.append(f"VLM provider call failed: {type(exc).__name__}: {exc}")
            return None, None, calls
        if not isinstance(raw, str):
            error = f"provider returned {type(raw).__name__}, not str"
        else:
            response, err = parse_response(raw)
            if response is not None:
                return response, raw, calls
            error = err or "invalid response"
        prompt = _provider_mod.repair_prompt(error)
    warnings.append(f"VLM response invalid after {calls} call(s); rooms left untyped: {error}")
    return None, None, calls


def _match_rooms(
    plan: PlanGeometry,
    rooms: list[LabelledPolygon],
    untyped: list[int],
    response: VlmResponse,
    image_size: tuple[int, int],
    extent: Extent,
    warnings: list[str],
) -> None:
    shapes = [_shape(rooms[j].polygon) for j in untyped]
    weights: list[list[float]] = []
    for vroom in response.rooms:
        row = [0.0] * len(untyped)
        x0, y0, x1, y1 = normalized_to_native(
            vroom.bbox, image_size=image_size, extent=extent, frame=Frame(plan.frame)
        )
        box = shapely.box(x0, y0, x1, y1)
        area = box.area
        if area > 0.0:
            for col, shp in enumerate(shapes):
                ratio = shapely.intersection(box, shp).area / area
                if ratio >= MIN_OVERLAP:
                    row[col] = ratio
        weights.append(row)
    pairs = assign_one_to_one(weights)
    for k, col in pairs:
        vroom = response.rooms[k]
        overlap = weights[k][col]
        conf = min(1.0, max(0.0, vroom.confidence * overlap))
        j = untyped[col]
        rooms[j] = rooms[j].model_copy(
            update={
                "type": _type_of_label(vroom.label),
                "label_source": LabelSource.VLM,
                "confidence": conf,
                "raw_label": vroom.label,
            }
        )
    unmatched = len(response.rooms) - len(pairs)
    if unmatched:
        warnings.append(f"{unmatched} VLM room(s) matched no untyped room polygon")


def _vlm_stage(
    plan: PlanGeometry,
    rooms: list[LabelledPolygon],
    untyped: list[int],
    *,
    image: bytes,
    provider: VlmProvider,
    cache: VlmCache,
    config: AleConfig,
    extent: Extent | None,
    warnings: list[str],
) -> int:
    """Label ``rooms[untyped]`` with the VLM in place; returns the number of provider calls."""
    size = png_size(image)
    if size is None:
        warnings.append("VLM skipped: image is not a valid PNG")
        return 0
    ext = extent if extent is not None else plan_extent(plan)
    if ext is None or not (ext[2] > ext[0] and ext[3] > ext[1]):
        warnings.append("VLM skipped: plan has no usable native extent")
        return 0
    prompt_version = _provider_mod.PROMPT_VERSION
    if config.vlm.prompt_version != prompt_version:
        warnings.append(
            f"vlm.prompt_version {config.vlm.prompt_version!r} differs from the implemented "
            f"prompt {prompt_version!r}; using {prompt_version!r}"
        )
    model_id = str(getattr(provider, "model_id", ""))
    key = cache_key(
        source_sha256=plan.source_sha256,
        page=plan.page,
        plan_index=plan.plan_index,
        prompt_version=prompt_version,
        model_id=model_id,
        image=image,
    )
    calls = 0
    response: VlmResponse | None = None
    cached = cache.get(key)
    if cached is not None:
        response, err = parse_response(cached)
        if response is None:
            warnings.append(f"cached VLM response ignored ({err})")
    if response is None:
        response, raw, calls = _call_provider(provider, image, config, warnings)
        if response is None or raw is None:
            return calls
        put_err = cache.put(key, raw)
        if put_err is not None:
            warnings.append(put_err)
    _match_rooms(plan, rooms, untyped, response, size, ext, warnings)
    return calls


# --------------------------------------------------------------------------- entry point


def label_plan(
    plan: PlanGeometry,
    *,
    image: bytes | None,
    provider: VlmProvider | None,
    cache: VlmCache,
    config: AleConfig,
    extent: Extent | None = None,
) -> LabelResult:
    """Label the untyped rooms of ``plan`` (text first, then the VLM); never raises.

    ``image`` is the PNG rendering of the plan given to the VLM; ``extent`` is the native
    ``(xmin, ymin, xmax, ymax)`` drawn into it (default: :func:`plan_extent`, see
    :mod:`ale.labels.bbox` for the rendering model).
    """
    warnings: list[str] = []
    calls = 0
    try:
        rooms = list(plan.rooms)
        for i, room in enumerate(rooms):
            if room.type is not None:
                continue
            try:
                labelled = _label_from_texts(room, plan.texts)
            except Exception as exc:  # shapely errors on pathological polygons
                warnings.append(f"room {room.id}: text labelling failed: {exc}")
                continue
            if labelled is not None:
                rooms[i] = labelled
        untyped = [i for i, r in enumerate(rooms) if r.type is None]
        vlm_enabled = provider is not None and bool(config.vlm.provider)
        if untyped and vlm_enabled and provider is not None:
            if image is None:
                warnings.append("VLM skipped: no image given")
            else:
                try:
                    calls = _vlm_stage(
                        plan,
                        rooms,
                        untyped,
                        image=image,
                        provider=provider,
                        cache=cache,
                        config=config,
                        extent=extent,
                        warnings=warnings,
                    )
                except Exception as exc:
                    warnings.append(f"VLM labelling failed: {type(exc).__name__}: {exc}")
        new_plan = plan.model_copy(update={"rooms": tuple(rooms)})
    except Exception as exc:
        warnings.append(f"labelling failed: {type(exc).__name__}: {exc}")
        new_plan = plan
    return LabelResult(plan=new_plan, api_calls=calls, warnings=tuple(warnings))
