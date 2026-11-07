"""Validate a contract file.

Usage: ``python -m ale.contracts.validate {rulebook|program|site|layout|plan|taxonomy} FILE``.
Loads YAML (``.yaml``/``.yml``) or JSON (other extensions), prints ``OK`` or one line per
error as ``<dotted.path>: <message>``; exit code 0 / 1.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from ale.contracts.enums import TypeCategory
from ale.contracts.models import Layout, PlanGeometry, Program, Rulebook, SiteSpec
from ale.contracts.serialization import load_yaml
from ale.contracts.taxonomy import Taxonomy, load_taxonomy

__all__ = ["KINDS", "format_errors", "main", "validate_file"]

KINDS: dict[str, type[BaseModel]] = {
    "rulebook": Rulebook,
    "program": Program,
    "site": SiteSpec,
    "layout": Layout,
    "plan": PlanGeometry,
    "taxonomy": Taxonomy,
}
_ROOT = "<root>"


def format_errors(exc: ValidationError) -> list[str]:
    """One ``<dotted.path>: <message>`` line per validation error."""
    lines = []
    for err in exc.errors():
        path = ".".join(str(p) for p in err["loc"]) or _ROOT
        lines.append(f"{path}: {err['msg']}")
    return lines


def _load(cls: type[BaseModel], path: Path) -> BaseModel:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        return load_yaml(cls, text)
    data: Any = json.loads(text)
    return cls.model_validate(data)


def validate_file(kind: str, path: Path) -> tuple[int, list[str]]:
    """Validate ``path`` as ``kind``; return ``(exit_code, output_lines)``."""
    cls = KINDS[kind]
    try:
        model = _load(cls, path)
    except ValidationError as exc:
        return 1, format_errors(exc)
    except (OSError, UnicodeDecodeError, yaml.YAMLError, json.JSONDecodeError) as exc:
        return 1, [f"{_ROOT}: cannot read {path}: {exc}"]
    lines = ["OK"]
    if isinstance(model, Rulebook):
        tax = load_taxonomy()
        needed = [
            t.key for t in tax.types if t.category in (TypeCategory.ROOM, TypeCategory.VERTICAL)
        ]
        missing = model.missing_types(needed)
        lines.append(
            "info: taxonomy room types absent from rulebook: "
            + (", ".join(missing) if missing else "(none)")
        )
    return 0, lines


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(prog="python -m ale.contracts.validate")
    parser.add_argument("kind", choices=sorted(KINDS))
    parser.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    code, lines = validate_file(args.kind, args.file)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
