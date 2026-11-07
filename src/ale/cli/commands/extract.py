"""``ale extract`` (stub, Tickets 1.2-1.4)."""

from __future__ import annotations

import enum
from typing import Annotated

import typer

from ale.cli.commands._common import (
    WorkspaceOption,
    not_implemented,
    open_workspace_or_exit,
    require_workspace,
)


class SourceKind(enum.StrEnum):
    dwg = "dwg"
    dxf = "dxf"
    pdf = "pdf"
    raster = "raster"


def extract(
    ctx: typer.Context,
    workspace: WorkspaceOption = None,
    only_new: Annotated[
        bool, typer.Option("--only-new", help="Only sources not extracted yet.")
    ] = False,
    kind: Annotated[
        SourceKind | None, typer.Option("--kind", help="Only this kind of source.")
    ] = None,
) -> None:
    """Extract geometry and labels from ingested sources."""
    open_workspace_or_exit(ctx, require_workspace(workspace))
    not_implemented("extract", "1.2\u20131.4")
