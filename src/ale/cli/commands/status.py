"""``ale status``: units of the corpus by kind and status (Ticket 1.1)."""

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
from ale.contracts.enums import FileStatus, SourceKind
from ale.corpus.db import CorpusDbError, CorpusStatus, read_status
from ale.workspace import CORPUS_FILENAME


def format_status(st: CorpusStatus) -> str:
    """Kind x status table plus the number of inputs and the last ingest time."""
    counts = {(k, s): c for k, s, c in st.units}
    kinds = [k.value for k in SourceKind]
    kinds += sorted({k for k, _ in counts} - set(kinds))
    statuses = [s.value for s in FileStatus]
    statuses += sorted({s for _, s in counts} - set(statuses))
    header = ["TYPE", *statuses, "TOTAL"]
    rows = [header]
    for kind in kinds:
        values = [counts.get((kind, s), 0) for s in statuses]
        rows.append([kind, *(str(v) for v in values), str(sum(values))])
    totals = [sum(counts.get((k, s), 0) for k in kinds) for s in statuses]
    rows.append(["TOTAL", *(str(v) for v in totals), str(st.total_units)])
    widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
    lines = [
        f"entrées : {st.inputs}",
        f"fichiers : {st.files}",
        f"dernière ingestion : {st.last_ingest or 'jamais'}",
        "",
    ]
    for row in rows:
        cells = [row[0].ljust(widths[0])] + [
            c.rjust(w) for c, w in zip(row[1:], widths[1:], strict=True)
        ]
        lines.append("  ".join(cells))
    return "\n".join(lines)


def status(
    ctx: typer.Context,
    workspace: WorkspaceOption = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Show the state of the workspace corpus."""
    ws = open_workspace_or_exit(ctx, require_workspace(workspace))
    try:
        st = read_status(ws.path(CORPUS_FILENAME))
    except CorpusDbError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_WORKSPACE) from exc
    if as_json:
        typer.echo(json.dumps(st.to_dict(), indent=2, ensure_ascii=False))
    else:
        typer.echo(format_status(st))
    raise typer.Exit(EXIT_OK)
