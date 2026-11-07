"""``ale rulebook build`` (stub, Ticket 2.2)."""

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

app = typer.Typer(
    name="rulebook",
    help="Rulebook commands.",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


@app.command("build")
def build(
    ctx: typer.Context,
    workspace: WorkspaceOption = None,
    seed_rulebook: Annotated[
        Path | None,
        typer.Option("--seed-rulebook", exists=True, help="Optional seed rulebook (must exist)."),
    ] = None,
    min_support: Annotated[
        int | None,
        typer.Option("--min-support", min=1, help="Minimum support (>= 1; default from config)."),
    ] = None,
) -> None:
    """Build the rulebook from the extracted corpus."""
    open_workspace_or_exit(ctx, require_workspace(workspace))
    not_implemented("rulebook build", "2.2")
