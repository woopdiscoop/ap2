"""``ale extract``: geometry of the ingested sources (CAD, PDF and raster)."""

from __future__ import annotations

import enum
from typing import Annotated

import typer

from ale.cli.commands._common import (
    EXIT_OK,
    EXIT_WORKSPACE,
    WorkspaceOption,
    open_workspace_or_exit,
    require_workspace,
)
from ale.corpus.extract import ExtractReport, run_extract
from ale.workspace import WorkspaceError


class SourceKind(enum.StrEnum):
    dwg = "dwg"
    dxf = "dxf"
    pdf = "pdf"
    raster = "raster"


def format_extract(report: ExtractReport) -> str:
    """French summary printed by ``ale extract``."""
    lines: list[str] = []
    if report.vlm_warning is not None:
        lines.append(f"avertissement : {report.vlm_warning}")
    if report.proposed_layers is not None:
        lines.append(
            "avertissement : layer_map.yaml ne contient aucun calque ; "
            f"{report.proposed_layers} rôle(s) proposé(s) automatiquement pour cette "
            "extraction, non enregistré(s). Lancez `ale layers` pour les vérifier et les "
            "enregistrer."
        )
    lines += [
        "Extraction terminée",
        f"  unités sélectionnées : {report.selected}",
        f"  extraites : {report.extracted} ({report.plans} plan(s), "
        f"{report.files_written} fichier(s) écrit(s))",
        f"  échecs : {report.failed}",
        f"  outil manquant : {report.needs_tool}",
        f"  exclues : {report.excluded}",
    ]
    if report.vlm_enabled:
        lines.append(
            f"  VLM : {report.vlm_plans} plan(s) envoyé(s), "
            f"{report.vlm_cache_hits} réponse(s) du cache, {report.vlm_errors} erreur(s)"
        )
    lines.extend(
        f"  {kind} : {count} unité(s) extraite(s)" for kind, count in sorted(report.by_kind.items())
    )
    lines.extend(f"    - {name} : {reason}" for name, reason in report.problems)
    return "\n".join(lines)


def extract(
    ctx: typer.Context,
    workspace: WorkspaceOption = None,
    only_new: Annotated[
        bool, typer.Option("--only-new", help="Only sources not extracted yet.")
    ] = False,
    kind: Annotated[
        SourceKind | None, typer.Option("--kind", help="Only this kind of source.")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Re-extract every status, including excluded units.")
    ] = False,
    no_vlm: Annotated[
        bool,
        typer.Option("--no-vlm", help="Label rooms from drawing text only (no VLM call)."),
    ] = False,
) -> None:
    """Extract geometry and labels from ingested sources."""
    if force and only_new:
        raise typer.BadParameter("--force et --only-new sont incompatibles.")
    ws = open_workspace_or_exit(ctx, require_workspace(workspace))
    try:
        report = run_extract(
            ws,
            only_new=only_new,
            kind=None if kind is None else kind.value,
            no_vlm=no_vlm,
            force=force,
        )
    except WorkspaceError as exc:
        for line in exc.lines:
            typer.echo(line, err=True)
        raise typer.Exit(EXIT_WORKSPACE) from exc
    typer.echo(format_extract(report))
    raise typer.Exit(EXIT_OK)
