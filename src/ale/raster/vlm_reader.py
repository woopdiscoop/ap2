"""Claude reads the room geometry of a raster plan (Ticket R.7).

One call per plan image (the prepared PNG of Ticket I.2). The answer is a list of rooms
``{label, polygon: [[x, y], ...] normalised 0..1000, top-left origin, confidence}``.
Polygons are mapped to native coordinates with the :mod:`ale.labels.bbox` rendering model
(pixel-edge extent), repaired with ``shapely.make_valid``, clipped to the image and kept
when at least :data:`MIN_AREA_PX2` px². Raw answers are cached under (image hash, prompt
version :data:`GEOMETRY_PROMPT_VERSION`, model id); only a parsed answer is cached.

:func:`read_rooms_vlm` never raises: a provider error, refusal or unusable answer becomes
:attr:`VlmRooms.error`. Providers able to read geometry expose ``read_geometry(png, prompt)``;
:class:`~ale.labels.providers.AnthropicVlmProvider` is adapted by :func:`geometry_caller`
(same client and request as the labelling call, with the geometry schema). Any other
provider (labelling only) is not asked and geometry stays classical.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

import shapely

from ale.contracts.config import AleConfig
from ale.contracts.enums import Frame
from ale.contracts.models import LabelledPolygon
from ale.labels.bbox import Extent, normalized_to_native, png_size
from ale.labels.cache import VlmCache, cache_key
from ale.labels.providers.anthropic_provider import (
    AnthropicVlmProvider,
    VlmProviderError,
    _answer_text,
)

__all__ = [
    "GEOMETRY_PROMPT_VERSION",
    "GEOMETRY_SCHEMA",
    "MAX_ROOMS",
    "MIN_AREA_PX2",
    "VlmRoom",
    "VlmRooms",
    "build_geometry_prompt",
    "geometry_caller",
    "read_rooms_vlm",
    "to_labelled_polygons",
]

#: Version of the geometry prompt; part of the cache key.
GEOMETRY_PROMPT_VERSION: Final = "geom-v1"
#: Rooms kept from one answer.
MAX_ROOMS: Final = 60
#: Polygons smaller than this (native px²) are dropped.
MIN_AREA_PX2: Final = 4.0

GEOMETRY_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "rooms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "polygon": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "number"}},
                    },
                    "confidence": {"type": "number"},
                },
                "required": ["label", "polygon", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["rooms"],
    "additionalProperties": False,
}

GeometryCall = Callable[[bytes, str], str]


@dataclass(frozen=True)
class VlmRoom:
    """One room of the VLM in native coordinates."""

    label: str
    polygon: shapely.Polygon
    confidence: float


@dataclass(frozen=True)
class VlmRooms:
    """Result of :func:`read_rooms_vlm`."""

    rooms: tuple[VlmRoom, ...]
    warnings: tuple[str, ...] = ()
    #: Failure message (provider error, refusal, unusable answer); rooms are then empty.
    error: str | None = None
    #: The answer came from the cache (no provider call).
    cached: bool = False


def build_geometry_prompt() -> str:
    """The geometry prompt (version :data:`GEOMETRY_PROMPT_VERSION`), French then English."""
    return "\n".join(
        [
            f"[ale prompt {GEOMETRY_PROMPT_VERSION}]",
            "FR : Ceci est un plan d'étage. Pour chaque pièce visible, donne son nom tel "
            "qu'écrit sur le plan (ou son type) et le contour de la pièce (intérieur des "
            "murs) sous forme de polygone orthogonal. Au plus 60 pièces.",
            "EN: This is a floor plan. For each visible room give its name as written on the "
            "plan (or its type) and the room outline (inside the walls) as an orthogonal "
            "polygon. At most 60 rooms.",
            "",
            "Réponds uniquement en JSON / Answer with JSON only, no other text:",
            '{"rooms": [{"label": "<name>", "polygon": [[x, y], ...], "confidence": <0..1>}]}',
            "polygon: sommets [x, y] normalisés 0-1000 par rapport à l'image, origine en haut "
            "à gauche / vertices [x, y] normalised 0-1000 relative to the image, origin at "
            "the top-left corner.",
        ]
    )


def geometry_caller(provider: object) -> GeometryCall | None:
    """The function asking ``provider`` for a geometry answer, or ``None`` if it cannot."""
    reader = getattr(provider, "read_geometry", None)
    if callable(reader):
        return reader  # type: ignore[no-any-return]
    if isinstance(provider, AnthropicVlmProvider):
        return lambda png, prompt: _anthropic_geometry(provider, png, prompt)
    return None


def _anthropic_geometry(provider: AnthropicVlmProvider, png: bytes, prompt: str) -> str:
    """Sibling of ``label_image``: same client and request, geometry schema."""
    request = provider.build_request(png, prompt)
    request["output_config"] = {
        "effort": "low",
        "format": {"type": "json_schema", "schema": GEOMETRY_SCHEMA},
    }
    try:
        message = provider._client.beta.messages.create(**request)
    except Exception as exc:
        raise VlmProviderError(f"Anthropic API error: {type(exc).__name__}: {exc}") from exc
    return _answer_text(message)


def _strip_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        nl = s.find("\n")
        s = s[nl + 1 :] if nl >= 0 else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def _parse(raw: str) -> list[Any] | None:
    try:
        data = json.loads(_strip_fences(raw))
    except (ValueError, RecursionError):
        return None
    rooms = data.get("rooms") if isinstance(data, dict) else None
    return rooms if isinstance(rooms, list) else None


def _largest(geom: shapely.Geometry) -> shapely.Polygon | None:
    parts = [g for g in getattr(geom, "geoms", [geom]) if isinstance(g, shapely.Polygon)]
    parts = [g for g in parts if not g.is_empty]
    return max(parts, key=lambda g: g.area) if parts else None


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _room(
    item: Any,
    index: int,
    mapping: dict[str, Any],
    image_box: shapely.Polygon,
    warnings: list[str],
) -> VlmRoom | None:
    tag = f"pièce VLM {index + 1}"
    if not isinstance(item, dict) or not isinstance(item.get("polygon"), list):
        warnings.append(f"{tag} ignorée : forme invalide")
        return None
    pts: list[tuple[float, float]] = []
    for pt in item["polygon"]:
        if not (isinstance(pt, list | tuple) and len(pt) == 2 and all(_number(c) for c in pt)):
            warnings.append(f"{tag} ignorée : sommet invalide")
            return None
        nx, ny = float(pt[0]), float(pt[1])
        x, y, _, _ = normalized_to_native((ny, nx, ny, nx), **mapping)
        pts.append((x, y))
    if len(pts) < 3:
        warnings.append(f"{tag} ignorée : moins de 3 sommets")
        return None
    poly = shapely.Polygon(pts)
    if not poly.is_valid:
        fixed = _largest(shapely.make_valid(poly))
        if fixed is None:
            warnings.append(f"{tag} ignorée : polygone dégénéré")
            return None
        warnings.append(f"{tag} : polygone réparé")
        poly = fixed
    if not image_box.contains(poly):
        clipped = _largest(poly.intersection(image_box))
        if clipped is None:
            warnings.append(f"{tag} ignorée : hors de l'image")
            return None
        warnings.append(f"{tag} : polygone découpé à l'image")
        poly = clipped
    if poly.area < MIN_AREA_PX2:
        warnings.append(f"{tag} ignorée : surface < {MIN_AREA_PX2:g} px²")
        return None
    label = item.get("label")
    conf = item.get("confidence")
    confidence = float(conf) if isinstance(conf, int | float) and _number(conf) else 0.0
    return VlmRoom(
        label=label if isinstance(label, str) else "",
        polygon=shapely.Polygon(poly.exterior),
        confidence=min(1.0, max(0.0, confidence)),
    )


def read_rooms_vlm(
    png: bytes,
    extent: Extent,
    frame: Frame,
    provider: object,
    cache: VlmCache | None,
    config: AleConfig,
) -> VlmRooms:
    """Room polygons of the plan image ``png`` read by the VLM; never raises."""
    del config  # reserved: no tunable of AleConfig applies to geometry reading yet
    try:
        return _read(png, extent, frame, provider, cache)
    except Exception as exc:
        return VlmRooms((), error=f"géométrie VLM : {type(exc).__name__}: {exc}")


def _read(
    png: bytes, extent: Extent, frame: Frame, provider: object, cache: VlmCache | None
) -> VlmRooms:
    size = png_size(png)
    if size is None:
        return VlmRooms((), error="géométrie VLM : image PNG invalide")
    call = geometry_caller(provider)
    if call is None:
        return VlmRooms((), error="géométrie VLM : fournisseur sans lecture de géométrie")
    key = cache_key(
        source_sha256="",
        page=0,
        plan_index=0,
        prompt_version=GEOMETRY_PROMPT_VERSION,
        model_id=str(getattr(provider, "model_id", "")),
        image=png,
    )
    raw = cache.get(key) if cache is not None else None
    items = _parse(raw) if raw is not None else None
    cached = items is not None
    if items is None:
        try:
            raw = call(png, build_geometry_prompt())
        except Exception as exc:
            return VlmRooms((), error=f"géométrie VLM : {exc}")
        items = _parse(raw)
        if items is None:
            return VlmRooms((), error="géométrie VLM : réponse invalide")
        if cache is not None:
            cache.put(key, raw)
    warnings: list[str] = []
    if len(items) > MAX_ROOMS:
        warnings.append(f"{len(items) - MAX_ROOMS} pièce(s) VLM ignorée(s) (maximum {MAX_ROOMS})")
        items = items[:MAX_ROOMS]
    mapping = {"image_size": size, "extent": extent, "frame": frame}
    x0, y0, x1, y1 = extent
    image_box = shapely.box(x0, y0, x1, y1)
    rooms = [r for i, it in enumerate(items) if (r := _room(it, i, mapping, image_box, warnings))]
    return VlmRooms(tuple(rooms), tuple(warnings), cached=cached)


def to_labelled_polygons(rooms: tuple[VlmRoom, ...]) -> list[LabelledPolygon]:
    """Contract rooms (ids ``R1``..) from VLM rooms; the label is kept as ``raw_label``."""
    out: list[LabelledPolygon] = []
    for room in rooms:
        ring = [(float(x), float(y)) for x, y in room.polygon.exterior.coords[:-1]]
        out.append(
            LabelledPolygon.model_validate(
                {
                    "id": f"R{len(out) + 1}",
                    "polygon": {"exterior": ring},
                    "raw_label": room.label or None,
                }
            )
        )
    return out
