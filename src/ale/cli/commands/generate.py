"""``ale generate`` (stub, Tickets 3.1-3.5)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ale.cli.commands._common import not_implemented


def _require_suffix(value: Path, suffixes: tuple[str, ...]) -> Path:
    if value.suffix.lower() not in suffixes:
        raise typer.BadParameter(f"expected a {' or '.join(suffixes)} file, got {value.name!r}")
    return value


def _program_suffix(value: Path) -> Path:
    return _require_suffix(value, (".xlsx",))


def _site_suffix(value: Path) -> Path:
    return _require_suffix(value, (".yaml", ".yml"))


def generate(
    program: Annotated[
        Path,
        typer.Option(
            "--program",
            exists=True,
            dir_okay=False,
            callback=_program_suffix,
            help="Space program (.xlsx, must exist).",
        ),
    ],
    site: Annotated[
        Path,
        typer.Option(
            "--site",
            exists=True,
            dir_okay=False,
            callback=_site_suffix,
            help="Site description (.yaml/.yml, must exist).",
        ),
    ],
    rulebook: Annotated[
        Path, typer.Option("--rulebook", exists=True, help="Rulebook (must exist).")
    ],
    out: Annotated[Path, typer.Option("--out", help="Output folder.")],
    seed: Annotated[
        int | None,
        typer.Option("--seed", min=0, help="Random seed (default: [determinism].seed)."),
    ] = None,
    variants: Annotated[
        int, typer.Option("--variants", min=1, help="Number of variants (>= 1).")
    ] = 1,
) -> None:
    """Generate layout variants for a program on a site."""
    not_implemented("generate", "3.1\u20133.5")
