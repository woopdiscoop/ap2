"""``ale init``: create a workspace."""

from __future__ import annotations

import logging

import typer

from ale.cli.commands._common import EXIT_WORKSPACE, RequiredWorkspaceOption
from ale.logging_setup import attach_workspace_log
from ale.paths import display
from ale.workspace import InitResult, WorkspaceError, init_workspace

log = logging.getLogger(__name__)


def init(workspace: RequiredWorkspaceOption) -> None:
    """Create a workspace (idempotent on an existing workspace)."""
    try:
        root, result = init_workspace(workspace)
    except WorkspaceError as exc:
        for line in exc.lines:
            typer.echo(f"error: {line}", err=True)
        raise typer.Exit(EXIT_WORKSPACE) from exc
    attach_workspace_log(root / "logs")
    log.debug("ale init: %s", result.value, extra={"event": "cli.init", "result": result.value})
    if result is InitResult.ALREADY_INITIALISED:
        typer.echo(f"workspace already initialised: {display(root)}")
    else:
        typer.echo(f"workspace created: {display(root)}")
