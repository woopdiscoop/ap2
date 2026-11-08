"""CAD layer roles: the ``LayerMap`` model, keyword proposal and YAML load/save (unitless).

The YAML format is the one of ``templates/layer_map.yaml`` (Ticket 0.1)::

    version: 1
    layers:
      MUR: wall
      PORTES: door

Role values are written in lower case; reading accepts any letter case.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

__all__ = [
    "LayerMap",
    "LayerRole",
    "canon_layer",
    "canon_layer_tokens",
    "load_layer_map",
    "propose_layer_map",
    "propose_role",
    "save_layer_map",
]


class LayerRole(StrEnum):
    """Role of a CAD layer (values are the lower-case names used in ``layer_map.yaml``)."""

    WALL = "wall"
    DOOR = "door"
    WINDOW = "window"
    ROOM_LABEL = "room_label"
    AREA_LABEL = "area_label"
    ZONE = "zone"
    FURNITURE = "furniture"
    IGNORE = "ignore"


class LayerMap(BaseModel):
    """Mapping exact layer name → role."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    layers: dict[str, LayerRole] = {}

    @field_validator("layers", mode="before")
    @classmethod
    def _roles_any_case(cls, v: Any) -> Any:
        if isinstance(v, Mapping):
            return {k: (r.lower() if isinstance(r, str) else r) for k, r in v.items()}
        return v

    def role(self, layer: str) -> LayerRole:
        """Role of ``layer`` (``IGNORE`` when the layer is not in the map)."""
        return self.layers.get(layer, LayerRole.IGNORE)


_NON_ALNUM = re.compile(r"[^A-Z0-9]+")


def canon_layer_tokens(name: str) -> tuple[str, ...]:
    """Canonical tokens: NFKC, accents stripped, upper case, non ``A-Z0-9`` → space, split."""
    text = unicodedata.normalize("NFD", unicodedata.normalize("NFKC", name))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return tuple(_NON_ALNUM.sub(" ", text).split())


def canon_layer(name: str) -> str:
    """Canonical layer name: the canonical tokens joined by single spaces."""
    return " ".join(canon_layer_tokens(name))


Keyword = tuple[str, ...]


def _kw(*words: str) -> tuple[Keyword, ...]:
    return tuple(canon_layer_tokens(w) for w in words)


_ZONE_KW = _kw("ZONE", "LOCAL", "ROOM", "A AREA", "ESPACE")
_HACHURE = _kw("HACHURE")

# (keywords, role) in priority order (RD 1.2 section 3, amended); first match wins.
_RULES: tuple[tuple[tuple[Keyword, ...], LayerRole], ...] = (
    (_kw("COTE", "COTATION", "DIM", "DIMENSION", "AXE", "DEFPOINTS", "VIEWPORT"), LayerRole.IGNORE),
    (_HACHURE, LayerRole.IGNORE),  # only when the name has no zone keyword
    (_kw("MOBILIER", "EQUIPEMENT", "FURN", "A FURN"), LayerRole.FURNITURE),
    (_kw("SURFACE", "AREA", "M2"), LayerRole.AREA_LABEL),
    (_kw("TEXTE", "TEXT", "NOM", "LIBELLE", "A ANNO", "ETIQUETTE"), LayerRole.ROOM_LABEL),
    (_ZONE_KW, LayerRole.ZONE),
    (_kw("PORTE", "DOOR", "A DOOR"), LayerRole.DOOR),
    (_kw("FENETRE", "MENUISERIE", "WINDOW", "A GLAZ", "CHASSIS", "BAIE"), LayerRole.WINDOW),
    (
        _kw("MUR", "CLOISON", "WALL", "A WALL", "VOILE", "MACONNERIE", "BETON", "PORTEUR"),
        LayerRole.WALL,
    ),
)


def _token_matches(name_tok: str, kw_tok: str) -> bool:
    """Equal, or a plural: keyword + ``S`` / ``X``, or French ``-AL`` → ``-AUX``."""
    if name_tok in (kw_tok, kw_tok + "S", kw_tok + "X"):
        return True
    return kw_tok.endswith("AL") and name_tok == kw_tok[:-2] + "AUX"


def _has_keyword(tokens: tuple[str, ...], keyword: Keyword) -> bool:
    n, k = len(tokens), len(keyword)
    return any(
        all(_token_matches(tokens[i + j], keyword[j]) for j in range(k)) for i in range(n - k + 1)
    )


def _has_any(tokens: tuple[str, ...], keywords: tuple[Keyword, ...]) -> bool:
    return any(_has_keyword(tokens, kw) for kw in keywords)


def propose_role(layer_name: str) -> LayerRole:
    """Whole-word keyword proposal for one layer name (RD 1.2 section 3, first match wins)."""
    tokens = canon_layer_tokens(layer_name)
    has_zone = _has_any(tokens, _ZONE_KW)
    for keywords, role in _RULES:
        if keywords is _HACHURE and has_zone:
            continue
        if _has_any(tokens, keywords):
            return role
    return LayerRole.IGNORE


def propose_layer_map(layer_names: Iterable[str], existing: LayerMap | None = None) -> LayerMap:
    """Propose roles for ``layer_names``; entries of ``existing`` are kept unchanged."""
    layers: dict[str, LayerRole] = dict(existing.layers) if existing is not None else {}
    for name in layer_names:
        if name not in layers:
            layers[name] = propose_role(name)
    return LayerMap(layers=dict(sorted(layers.items())))


_HEADER = (
    "# Map CAD layer names to roles. Proposed by `ale layers`; edit and keep.\n"
    "# Roles: wall, door, window, room_label, area_label, zone, furniture, ignore\n"
)


def save_layer_map(layer_map: LayerMap, path: Path) -> None:
    """Write ``layer_map`` as YAML (UTF-8, LF line endings)."""
    data = {
        "version": layer_map.version,
        "layers": {k: str(v) for k, v in layer_map.layers.items()},
    }
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    path.write_text(_HEADER + body, encoding="utf-8", newline="\n")


def load_layer_map(path: Path) -> LayerMap:
    """Read a ``layer_map.yaml`` file (``layers: {}`` or missing ``layers`` = empty map)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if data is None:
        data = {}
    if isinstance(data, dict) and data.get("layers") is None:
        data = {**data, "layers": {}}
    return LayerMap.model_validate(data)
