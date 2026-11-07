"""Write (or ``--check``) the JSON Schemas of the contract models.

Usage: ``python -m ale.contracts.export_schemas [--check]``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from ale.contracts.corridor_plan import CorridorPlan
from ale.contracts.footprint import FootprintPieces
from ale.contracts.models import Layout, PlanGeometry, Program, RoomSpec, Rulebook, SiteSpec
from ale.contracts.taxonomy import Taxonomy

__all__ = ["SCHEMA_DIR", "SCHEMA_MODELS", "export", "main", "render_schemas"]

SCHEMA_DIR = Path(__file__).with_name("schemas")
SCHEMA_MODELS: tuple[type[BaseModel], ...] = (
    RoomSpec,
    Program,
    SiteSpec,
    Layout,
    PlanGeometry,
    Rulebook,
    Taxonomy,
    CorridorPlan,
    FootprintPieces,
)


def render_schemas() -> dict[str, str]:
    """Map ``<Name>.schema.json`` → file content (``indent=2, sort_keys=True`` + newline)."""
    return {
        f"{m.__name__}.schema.json": json.dumps(m.model_json_schema(), indent=2, sort_keys=True)
        + "\n"
        for m in SCHEMA_MODELS
    }


def export(schema_dir: Path, check: bool) -> int:
    """Write the schemas into ``schema_dir``, or with ``check`` compare them; return exit code."""
    status = 0
    for name, content in render_schemas().items():
        path = schema_dir / name
        if check:
            current = path.read_text(encoding="utf-8") if path.is_file() else None
            if current != content:
                print(f"schema out of date: {path}")
                status = 1
        else:
            schema_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    return status


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(prog="python -m ale.contracts.export_schemas")
    parser.add_argument("--check", action="store_true", help="exit 1 if any schema file differs")
    args = parser.parse_args(argv)
    return export(SCHEMA_DIR, args.check)


if __name__ == "__main__":
    sys.exit(main())
