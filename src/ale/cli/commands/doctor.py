"""``ale doctor``: environment check (runs no external program, no network)."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from ale.cli.commands._common import (
    EXIT_OK,
    EXIT_RUNTIME,
    RequiredWorkspaceOption,
    open_workspace_or_exit,
)
from ale.doctor import DoctorReport, run_checks


def _table(report: DoctorReport) -> str:
    headers = ("CHECK", "STATUS", "REQUIRED", "DETAIL")
    rows = [(c.name, c.status, "yes" if c.required else "no", c.detail) for c in report.checks]
    widths = [max(len(r[i]) for r in [headers, *rows]) for i in range(3)]
    lines = []
    for row in [headers, *rows]:
        cells = [row[i].ljust(widths[i]) for i in range(3)]
        lines.append("  ".join([*cells, row[3]]).rstrip())
    lines.append("")
    lines.append("ok" if report.ok else "FAILED: a required check did not pass")
    return "\n".join(lines)


def doctor(
    ctx: typer.Context,
    workspace: RequiredWorkspaceOption,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Check Python, the workspace, optional extras, CAD tools and the VLM key."""
    ws = open_workspace_or_exit(ctx, workspace)
    report = run_checks(ws)
    if as_json:
        typer.echo(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        typer.echo(_table(report))
    raise typer.Exit(EXIT_OK if report.ok else EXIT_RUNTIME)
