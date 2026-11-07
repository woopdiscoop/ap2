"""``ale ingest`` (stub, Ticket 1.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ale.cli.commands._common import (
    WorkspaceOption,
    not_implemented,
    open_workspace_or_exit,
    require_workspace,
)

DEFAULT_INCLUDE = "jpg,jpeg,png,tif,tiff,pdf,dwg,dxf"


def parse_include(value: str) -> list[str]:
    """Split the comma list into lower-case extensions without leading dots."""
    items = [part.strip().lstrip(".").lower() for part in value.split(",")]
    items = [item for item in items if item]
    if not items:
        raise typer.BadParameter("expected a comma-separated list of extensions")
    return items


def _validate_include(value: str) -> str:
    parse_include(value)
    return value


def ingest(
    ctx: typer.Context,
    input_dir: Annotated[
        Path,
        typer.Option(
            "--input",
            exists=True,
            file_okay=False,
            dir_okay=True,
            help="Folder to ingest (must exist).",
        ),
    ],
    workspace: WorkspaceOption = None,
    recursive: Annotated[
        bool, typer.Option("--recursive/--no-recursive", help="Descend into sub-folders.")
    ] = True,
    include: Annotated[
        str,
        typer.Option(
            "--include", callback=_validate_include, help="Comma list of file extensions."
        ),
    ] = DEFAULT_INCLUDE,
    meta: Annotated[
        Path | None,
        typer.Option("--meta", exists=True, help="Optional metadata file (must exist)."),
    ] = None,
) -> None:
    """Register source drawings into the corpus."""
    open_workspace_or_exit(ctx, require_workspace(workspace))
    not_implemented("ingest", "1.1")
