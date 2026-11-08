"""``ale layers``: propose CAD layer roles in ``layer_map.yaml`` (Ticket 1.2c)."""

from __future__ import annotations

import typer

from ale.cli.commands._common import (
    EXIT_OK,
    EXIT_WORKSPACE,
    WorkspaceOption,
    open_workspace_or_exit,
    require_workspace,
)
from ale.corpus.extract import LayersReport, run_layers
from ale.workspace import WorkspaceError


def format_layers(report: LayersReport) -> str:
    """French table printed by ``ale layers``."""
    lines = [f"avertissement : {w}" for w in report.warnings]
    if not report.rows:
        lines.append("Aucun calque à proposer : aucun fichier DXF/DWG lisible dans le corpus.")
        return "\n".join(lines)
    header = ("CALQUE", "RÔLE", "FICHIERS", "")
    rows = [header] + [
        (r.layer, r.role, str(r.files), "nouveau" if r.new else "") for r in report.rows
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    for row in rows:
        cells = [row[0].ljust(widths[0]), row[1].ljust(widths[1]), row[2].rjust(widths[2])]
        lines.append("  ".join([*cells, row[3]]).rstrip())
    lines.append("")
    lines.append(
        f"layer_map.yaml mis à jour : {len(report.rows)} calques dans {report.files_read} "
        f"fichier(s), {report.new_count} nouveau(x)"
    )
    return "\n".join(lines)


def layers(ctx: typer.Context, workspace: WorkspaceOption = None) -> None:
    """Propose CAD layer roles in layer_map.yaml."""
    ws = open_workspace_or_exit(ctx, require_workspace(workspace))
    try:
        report = run_layers(ws)
    except WorkspaceError as exc:
        for line in exc.lines:
            typer.echo(line, err=True)
        raise typer.Exit(EXIT_WORKSPACE) from exc
    typer.echo(format_layers(report))
    raise typer.Exit(EXIT_OK)
