"""``ale review`` (stub, Ticket 1.6)."""

from __future__ import annotations

import typer

from ale.cli.commands._common import (
    WorkspaceOption,
    not_implemented,
    open_workspace_or_exit,
    require_workspace,
)


def review(ctx: typer.Context, workspace: WorkspaceOption = None) -> None:
    """Review low-confidence extractions."""
    open_workspace_or_exit(ctx, require_workspace(workspace))
    not_implemented("review", "1.6")
