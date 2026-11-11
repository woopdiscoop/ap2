"""Stacking rules (Ticket M.1, RD section 3): groups, pins, soft pairs, circulation share."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "CIRCULATION_SHARE",
    "WET_TYPES",
    "StackInputError",
    "StackRules",
    "load_rules",
    "parse_rules",
]

#: Room types that form the wet stack instead of being stacked with their group (RD 4).
WET_TYPES: frozenset[str] = frozenset({"sanitary", "cleaning_room", "technical_room"})
CIRCULATION_SHARE = 0.25
_RULE_KEYS = {"groups", "pins", "together", "keep_whole", "circulation_share"}


class StackInputError(Exception):
    """Unusable stacking input (rules or building); ``lines`` are French messages."""

    def __init__(self, *lines: str) -> None:
        self.lines: tuple[str, ...] = tuple(lines)
        super().__init__("\n".join(lines))


@dataclass(frozen=True)
class StackRules:
    """Parsed ``rules.yaml``. ``pins`` values are ``"top"``, ``"ground"`` or a level."""

    groups: dict[str, tuple[str, ...]] = field(default_factory=dict)
    pins: dict[str, str | int] = field(default_factory=dict)
    together: tuple[tuple[str, str], ...] = ()
    keep_whole: bool = False
    circulation_share: float = CIRCULATION_SHARE


def _parse_groups(data: dict[str, Any], errors: list[str]) -> dict[str, tuple[str, ...]]:
    groups: dict[str, tuple[str, ...]] = {}
    raw = data.get("groups") or {}
    if not isinstance(raw, dict):
        errors.append("Règles d'empilement : « groups » doit être un dictionnaire.")
        return groups
    for name, members in raw.items():
        if isinstance(members, str):
            members = [members]
        if not isinstance(members, list) or not members:
            errors.append(f"Groupe « {name} » : liste d'identifiants ou de préfixes attendue.")
            continue
        groups[str(name)] = tuple(str(m) for m in members)
    return groups


def _parse_pins(data: dict[str, Any], errors: list[str]) -> dict[str, str | int]:
    pins: dict[str, str | int] = {}
    raw = data.get("pins") or {}
    if not isinstance(raw, dict):
        errors.append("Règles d'empilement : « pins » doit être un dictionnaire.")
        return pins
    for name, where in raw.items():
        if where in ("top", "ground"):
            pins[str(name)] = where
        elif isinstance(where, int) and not isinstance(where, bool) and where >= 0:
            pins[str(name)] = where
        else:
            errors.append(
                f"Épingle « {name} » : « top », « ground » ou un niveau entier ≥ 0 attendu "
                f"(reçu {where!r})."
            )
    return pins


def parse_rules(data: Any) -> StackRules:
    """Validate a decoded YAML mapping; every problem is reported at once (French)."""
    if data is None:
        return StackRules()
    if not isinstance(data, dict):
        raise StackInputError("Règles d'empilement : le fichier doit contenir un dictionnaire.")
    errors: list[str] = []
    for key in sorted(str(k) for k in data if k not in _RULE_KEYS):
        errors.append(f"Règles d'empilement : clé inconnue « {key} ».")
    groups = _parse_groups(data, errors)
    pins = _parse_pins(data, errors)
    together: list[tuple[str, str]] = []
    raw_together = data.get("together") or []
    if not isinstance(raw_together, list):
        errors.append("Règles d'empilement : « together » doit être une liste de paires.")
        raw_together = []
    for pair in raw_together:
        if not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(p, str) for p in pair)):
            errors.append(f"Paire « together » invalide : {pair!r} (deux noms de groupes).")
            continue
        together.append((pair[0], pair[1]))
    keep = data.get("keep_whole", False)
    if not isinstance(keep, bool):
        errors.append("« keep_whole » doit valoir true ou false.")
        keep = False
    share = data.get("circulation_share", CIRCULATION_SHARE)
    if isinstance(share, bool) or not isinstance(share, int | float) or not 0.0 <= share < 1.0:
        errors.append(f"« circulation_share » doit être un nombre dans [0, 1) (reçu {share!r}).")
        share = CIRCULATION_SHARE
    if errors:
        raise StackInputError(*errors)
    return StackRules(
        groups=groups,
        pins=pins,
        together=tuple(together),
        keep_whole=keep,
        circulation_share=float(share),
    )


def load_rules(path: Path | None) -> StackRules:
    """Read ``rules.yaml`` (``None`` = defaults)."""
    if path is None:
        return StackRules()
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
        data = yaml.safe_load(text)
    except (OSError, UnicodeDecodeError) as exc:
        raise StackInputError(f"Règles d'empilement illisibles : {exc}.") from None
    except yaml.YAMLError as exc:
        raise StackInputError(f"Règles d'empilement : YAML invalide ({exc}).") from None
    return parse_rules(data)
