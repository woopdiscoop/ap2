"""``ale ingest``: register an input folder into the corpus (Ticket 1.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ale.cli.commands._common import (
    EXIT_OK,
    EXIT_WORKSPACE,
    WorkspaceOption,
    open_workspace_or_exit,
    require_workspace,
)
from ale.corpus.ingest import IngestReport, check_input
from ale.corpus.ingest import ingest as run_ingest
from ale.paths import normalise
from ale.workspace import WorkspaceError

DEFAULT_INCLUDE = "jpg,jpeg,png,tif,tiff,pdf,dwg,dxf"


def parse_include(value: str) -> list[str]:
    """Split the comma list into lower-case extensions without leading dots."""
    items = [part.strip().lstrip(".").lower() for part in value.split(",")]
    items = [item for item in items if item]
    if not items:
        raise typer.BadParameter("expected a comma-separated list of extensions")
    return items


def _validate_include(value: str) -> str:
    parse_include(value)
    return value


def ingest(
    ctx: typer.Context,
    input_dir: Annotated[
        Path,
        typer.Option(
            "--input",
            exists=True,
            file_okay=False,
            dir_okay=True,
            help="Folder to ingest (must exist).",
        ),
    ],
    workspace: WorkspaceOption = None,
    recursive: Annotated[
        bool, typer.Option("--recursive/--no-recursive", help="Descend into sub-folders.")
    ] = True,
    include: Annotated[
        str,
        typer.Option(
            "--include", callback=_validate_include, help="Comma list of file extensions."
        ),
    ] = DEFAULT_INCLUDE,
    meta: Annotated[
        Path | None,
        typer.Option("--meta", exists=True, help="Optional metadata file (must exist)."),
    ] = None,
) -> None:
    """Register source drawings into the corpus."""
    ws_path = require_workspace(workspace)
    try:
        # Before opening the workspace: opening it writes its log file, which must
        # never land inside the (read-only) input folder.
        check_input(normalise(ws_path), normalise(input_dir))
        ws = open_workspace_or_exit(ctx, ws_path)
        report = run_ingest(ws, input_dir, parse_include(include), recursive, meta)
    except WorkspaceError as exc:
        for line in exc.lines:
            typer.echo(line, err=True)
        raise typer.Exit(EXIT_WORKSPACE) from exc
    typer.echo(format_summary(report))
    raise typer.Exit(EXIT_OK)


def _counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key} {value}" for key, value in counts.items()) or "aucune"


def format_summary(report: IngestReport) -> str:
    """French summary printed by ``ale ingest``."""
    lines = [
        f"Ingestion terminée : {report.input_root}",
        f"  fichiers vus : {report.files_seen} (nouveaux : {report.files_new}, "
        f"inchangés : {report.files_unchanged}, doublons : {report.duplicates})",
        f"  unités nouvelles : {report.units_new}",
        f"  unités par type : {_counts(report.units_by_kind)}",
        f"  unités par statut : {_counts(report.units_by_status)}",
        f"  archives ignorées (non ouvertes) : {len(report.skipped_archives)}",
    ]
    lines.extend(f"    - {rel}" for rel in report.skipped_archives)
    lines.append(f"  échecs : {len(report.failed)}")
    lines.extend(f"    - {rel} : {reason}" for rel, reason in report.failed)
    if report.meta_warnings:
        lines.append(f"  avertissements métadonnées : {len(report.meta_warnings)}")
        lines.extend(f"    - {warning}" for warning in report.meta_warnings)
    return "\n".join(lines)
