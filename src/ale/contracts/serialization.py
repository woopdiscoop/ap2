"""Canonical JSON and YAML (de)serialisation of contract models (unit-preserving)."""

from __future__ import annotations

import json
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel

__all__ = ["canonical_json", "dump_yaml", "load_yaml", "round_floats"]

M = TypeVar("M", bound=BaseModel)

_SIG_DIGITS = 9


def round_floats(obj: Any) -> Any:
    """Recursively round every float to 9 significant digits (ints, bools untouched)."""
    if isinstance(obj, float):
        return float(f"{obj:.{_SIG_DIGITS}g}")
    if isinstance(obj, dict):
        return {k: round_floats(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [round_floats(v) for v in obj]
    return obj


def canonical_json(model: BaseModel) -> bytes:
    """Canonical UTF-8 JSON bytes of a model.

    ``model_dump(mode="json")``, floats rounded to 9 significant digits, keys sorted,
    compact separators, no ASCII escaping, NaN/Infinity rejected, trailing newline.
    """
    data = round_floats(model.model_dump(mode="json"))
    text = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return text.encode("utf-8") + b"\n"


class _Loader(yaml.SafeLoader):
    """Safe loader that keeps ISO dates (``2026-11-07``) as strings instead of ``date``."""


_Loader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def dump_yaml(model: BaseModel) -> str:
    """YAML text of a model, keys in model field order, Unicode kept."""
    return yaml.safe_dump(model.model_dump(mode="json"), sort_keys=False, allow_unicode=True)


def load_yaml(cls: type[M], text: str) -> M:
    """Parse YAML (safe loader; timestamps stay strings) and validate it as ``cls``."""
    return cls.model_validate(yaml.load(text, Loader=_Loader))
