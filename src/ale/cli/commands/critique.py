"""``ale critique``: advisory visual critique of a generated variant (Ticket R.6)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ale.cli.commands._common import (
    EXIT_OK,
    EXIT_RUNTIME,
    WorkspaceOption,
    open_workspace_or_exit,
)
from ale.contracts.config import AleConfig
from ale.critique import CritiqueError, CritiqueUnavailableError, run_critique

#: Exit code when no VLM provider / key is configured.
EXIT_NO_PROVIDER = 3


def critique(
    ctx: typer.Context,
    variant: Annotated[
        Path,
        typer.Option("--variant", help="Variant folder (layout.json, report.md)."),
    ],
    workspace: WorkspaceOption = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Ask Claude for an architect's critique of a variant (advisory, changes nothing)."""
    config = AleConfig()
    cache_dir: Path | None = None
    if workspace is not None:
        ws = open_workspace_or_exit(ctx, workspace)
        config = ws.config
        cache_dir = ws.path("cache", "critique")
    try:
        result = run_critique(variant, config, cache_dir=cache_dir)
    except CritiqueUnavailableError as exc:
        typer.echo(f"ale critique : {exc}", err=True)
        raise typer.Exit(EXIT_NO_PROVIDER) from exc
    except CritiqueError as exc:
        typer.echo(f"ale critique : échec — {exc}", err=True)
        raise typer.Exit(EXIT_RUNTIME) from exc
    crit = result.critique
    if as_json:
        typer.echo(result.critique_json.read_text(encoding="utf-8"), nl=False)
    for warning in crit.warnings:
        typer.echo(f"Avertissement : {warning}", err=True)
    source = "cache" if result.calls == 0 else "appel au modèle"
    typer.echo(
        f"Critique : {len(crit.defects)} défaut(s) ({source}). Ouvrir : {result.critique_md}",
        err=as_json,
    )
    raise typer.Exit(EXIT_OK)
