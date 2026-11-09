"""``ale rulebook build`` (Ticket 2.2): mine the extracted corpus into ``rulebook/``."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ale.cli.commands._common import (
    WorkspaceOption,
    open_workspace_or_exit,
    require_workspace,
)
from ale.paths import display

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
    ws = open_workspace_or_exit(ctx, require_workspace(workspace))
    from ale.rulebook import SeedError, load_seed, run_build

    seed = None
    if seed_rulebook is not None:
        try:
            seed = load_seed(seed_rulebook)
        except SeedError as exc:
            raise typer.BadParameter(str(exc), param_hint="'--seed-rulebook'") from exc
    run = run_build(ws, seed=seed, min_support=min_support)
    rb = run.result.rulebook
    typer.echo(f"rulebook {rb.kind} {rb.version} : {run.used} plan(s) utilisé(s)")
    for label, reason in run.skipped:
        typer.echo(f"  ignoré : {label} ({reason})")
    for path in run.files:
        typer.echo(f"  écrit : {display(path)}")
