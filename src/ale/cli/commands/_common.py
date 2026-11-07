"""Shared CLI pieces: option types, workspace opening, stub behaviour, exit codes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from ale.logging_setup import attach_workspace_log, set_console_level
from ale.workspace import Workspace, WorkspaceError, open_workspace

# Exit codes (frozen, RD 0.1 section 5).
EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2
EXIT_NOT_IMPLEMENTED = 3
EXIT_WORKSPACE = 4

WORKSPACE_ENV = "ALE_WORKSPACE"
_WORKSPACE_HELP = f"Workspace folder (default: ${WORKSPACE_ENV}; the flag wins)."
LOG_LEVEL_EXPLICIT_KEY = "ale.log_level_explicit"

RequiredWorkspaceOption = Annotated[
    Path,
    typer.Option("--workspace", envvar=WORKSPACE_ENV, show_envvar=False, help=_WORKSPACE_HELP),
]
WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", envvar=WORKSPACE_ENV, show_envvar=False, help=_WORKSPACE_HELP),
]


def require_workspace(path: Path | None) -> Path:
    """Usage error (exit 2) when no workspace was given by flag or environment."""
    if path is None:
        raise typer.BadParameter(
            f"no workspace given (use --workspace or set {WORKSPACE_ENV})",
            param_hint="'--workspace'",
        )
    return path


def open_workspace_or_exit(ctx: typer.Context, path: Path) -> Workspace:
    """Open and validate the workspace; on failure print the problem(s) and exit 4.

    On success the JSON-lines log file in ``logs/`` is attached and, unless
    ``--log-level`` was given explicitly, ``[logging].level`` sets the console level.
    """
    try:
        ws = open_workspace(path)
    except WorkspaceError as exc:
        for line in exc.lines:
            typer.echo(line, err=True)
        raise typer.Exit(EXIT_WORKSPACE) from exc
    if not ctx.meta.get(LOG_LEVEL_EXPLICIT_KEY, False):
        set_console_level(ws.config.logging.level)
    attach_workspace_log(ws.path("logs"))
    return ws


def not_implemented(command: str, ticket: str) -> NoReturn:
    """Stub behaviour: message on stderr, exit 3."""
    typer.echo(f"ale {command}: not implemented yet (Ticket {ticket})", err=True)
    raise typer.Exit(EXIT_NOT_IMPLEMENTED)
