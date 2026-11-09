"""``ale review``: self-contained static extraction review."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from ale.cli.commands._common import (
    EXIT_OK,
    EXIT_WORKSPACE,
    WorkspaceOption,
    open_workspace_or_exit,
    require_workspace,
)
from ale.corpus.review import run_review
from ale.workspace import WorkspaceError


def review(
    ctx: typer.Context,
    workspace: WorkspaceOption = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    all_plans: Annotated[bool, typer.Option("--all", help="Include plans without flags.")] = False,
) -> None:
    """Review low-confidence extractions in an offline HTML page."""
    ws = open_workspace_or_exit(ctx, require_workspace(workspace))
    try:
        report = run_review(ws, all_plans=all_plans)
    except WorkspaceError as exc:
        for line in exc.lines:
            typer.echo(line, err=True)
        raise typer.Exit(EXIT_WORKSPACE) from exc
    if as_json:
        typer.echo(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    typer.echo(f"Revue : {len(report.plans)} plan(s). Ouvrir : {report.path}", err=as_json)
    raise typer.Exit(EXIT_OK)
