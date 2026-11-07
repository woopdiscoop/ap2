"""``ale layers`` (stub, Ticket 1.2)."""

from __future__ import annotations

import typer

from ale.cli.commands._common import (
    WorkspaceOption,
    not_implemented,
    open_workspace_or_exit,
    require_workspace,
)


def layers(ctx: typer.Context, workspace: WorkspaceOption = None) -> None:
    """Propose CAD layer roles in layer_map.yaml."""
    open_workspace_or_exit(ctx, require_workspace(workspace))
    not_implemented("layers", "1.2")
