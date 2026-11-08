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


_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def canon_layer(name: str) -> str:
    """Canonical layer name: NFKC, accents stripped, upper case, every non ``A-Z0-9`` removed."""
    text = unicodedata.normalize("NFD", unicodedata.normalize("NFKC", name))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return _NON_ALNUM.sub("", text)


def _kw(*words: str) -> tuple[str, ...]:
    return tuple(canon_layer(w) for w in words)


_ZONE_KW = _kw("ZONE", "LOCAUX", "ROOM", "A-AREA", "ESPACE")

# (keywords, role) in priority order; the first group with a substring match wins.
_RULES: tuple[tuple[tuple[str, ...], LayerRole], ...] = (
    (_kw("COTE", "DIM"), LayerRole.IGNORE),
    (_kw("HACH"), LayerRole.IGNORE),  # only when no zone keyword matches (see propose_role)
    (_kw("AXE"), LayerRole.IGNORE),
    (_kw("MOBILIER"), LayerRole.FURNITURE),
    (_kw("DEFPOINTS", "VIEWPORT"), LayerRole.IGNORE),
    (_ZONE_KW, LayerRole.ZONE),
    (_kw("SURFACE", "AREA", "M2"), LayerRole.AREA_LABEL),
    (_kw("TEXTE", "TEXT", "NOM", "A-ANNO", "LIBELLE"), LayerRole.ROOM_LABEL),
    (_kw("PORTE", "DOOR", "A-DOOR"), LayerRole.DOOR),
    (_kw("FENETRE", "MENUISERIE", "WINDOW", "A-GLAZ", "CHASSIS"), LayerRole.WINDOW),
    (_kw("MUR", "CLOISON", "WALL", "A-WALL", "VOILE", "MACONNERIE", "BETON"), LayerRole.WALL),
)
_HACH = canon_layer("HACH")


def propose_role(layer_name: str) -> LayerRole:
    """Keyword proposal for one layer name (RD 1.2 section 3, first match wins)."""
    c = canon_layer(layer_name)
    has_zone = any(k in c for k in _ZONE_KW)
    for keywords, role in _RULES:
        if keywords == (_HACH,) and has_zone:
            continue
        if any(k in c for k in keywords):
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
