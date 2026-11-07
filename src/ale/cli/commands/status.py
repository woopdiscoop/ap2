"""``ale status`` (stub, Ticket 1.1)."""

from __future__ import annotations

from typing import Annotated

import typer

from ale.cli.commands._common import (
    WorkspaceOption,
    not_implemented,
    open_workspace_or_exit,
    require_workspace,
)


def status(
    ctx: typer.Context,
    workspace: WorkspaceOption = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Show the state of the workspace corpus."""
    open_workspace_or_exit(ctx, require_workspace(workspace))
    not_implemented("status", "1.1")
