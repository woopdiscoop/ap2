"""``ale program template`` / ``ale program check`` (Ticket 3.1).

``ale.program`` (openpyxl) is imported lazily so that the CLI starts without the
``excel`` extra.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

from ale.cli.commands._common import (
    EXIT_OK,
    EXIT_RUNTIME,
    WorkspaceOption,
    open_workspace_or_exit,
)
from ale.config import AleConfig

if TYPE_CHECKING:
    from ale.program.models import FeasibilityReport, Issue

app = typer.Typer(
    name="program",
    help="Program (programme.xlsx) and site (site.yaml) tools.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
)

_EXTRA_HINT = "the 'excel' extra is required: pip install \"ale[excel]\""


@app.command("template")
def template(
    out: Annotated[Path, typer.Option("--out", dir_okay=False, help="Output .xlsx file.")],
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False,
) -> None:
    """Write the program template (French headers, drop-down lists)."""
    if out.exists() and not force:
        typer.echo(f"{out}: file exists (use --force to overwrite)", err=True)
        raise typer.Exit(EXIT_RUNTIME)
    from ale.program.template import TEMPLATE_PATH

    out.parent.mkdir(parents=True, exist_ok=True)
    if TEMPLATE_PATH.is_file():
        shutil.copyfile(TEMPLATE_PATH, out)
    else:  # pragma: no cover - the template is packaged
        try:
            from ale.program.template import write_template
        except ImportError as exc:
            typer.echo(_EXTRA_HINT, err=True)
            raise typer.Exit(EXIT_RUNTIME) from exc
        write_template(out)
    typer.echo(f"template written: {out}")


def _where(issue: Issue) -> str:
    parts = []
    if issue.row is not None:
        parts.append(f"ligne {issue.row}")
    if issue.column is not None:
        parts.append(f"colonne « {issue.column} »")
    return ", ".join(parts)


def _issue_line(issue: Issue) -> str:
    where = _where(issue)
    text = f"  [{issue.code}]"
    if where:
        text += f" {where}"
    text += f" : {issue.message}"
    if issue.value is not None:
        text += f" (valeur : {issue.value})"
    return text


def _summary(f: FeasibilityReport) -> list[str]:
    return [
        "Faisabilité :",
        f"  surface nette      {f.net_m2:.2f} m²",
        f"  circulation        {f.circulation_m2:.2f} m²",
        f"  surplus rectangles {f.overshoot_m2:.2f} m²",
        f"  requis             {f.required_m2:.2f} m²",
        f"  disponible         {f.available_m2:.2f} m² (emprise {f.footprint_m2:.2f} m²)",
        f"  fill ratio         {f.fill_ratio:.4f}",
        f"  façade requise     {f.facade_required_m:.2f} m (périmètre {f.perimeter_m:.2f} m)",
    ]


@app.command("check")
def check(
    ctx: typer.Context,
    program: Annotated[
        Path,
        typer.Option("--program", exists=True, dir_okay=False, help="programme.xlsx (must exist)."),
    ],
    site: Annotated[
        Path, typer.Option("--site", exists=True, dir_okay=False, help="site.yaml (must exist).")
    ],
    rulebook: Annotated[
        Path,
        typer.Option("--rulebook", exists=True, dir_okay=False, help="Rulebook (must exist)."),
    ],
    workspace: WorkspaceOption = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Validate a program, a site and a rulebook, then run the feasibility pre-check."""
    config = open_workspace_or_exit(ctx, workspace).config if workspace is not None else AleConfig()
    if importlib.util.find_spec("openpyxl") is None:  # pragma: no cover - extra in tests
        typer.echo(_EXTRA_HINT, err=True)
        raise typer.Exit(EXIT_RUNTIME)
    from ale.program.prepare import check_inputs

    result = check_inputs(program, site, rulebook, config)
    errors, warnings = result.errors, result.warnings
    if as_json:
        payload: dict[str, Any] = {
            "ok": not errors,
            "issues": [i.model_dump(mode="json") for i in result.issues],
            "feasibility": (
                None if result.feasibility is None else result.feasibility.model_dump(mode="json")
            ),
        }
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        lines = [f"Erreurs ({len(errors)}) :", *(_issue_line(i) for i in errors)]
        lines += [f"Avertissements ({len(warnings)}) :", *(_issue_line(i) for i in warnings)]
        if result.feasibility is not None:
            lines += _summary(result.feasibility)
        lines.append("OK" if not errors else "ÉCHEC : corrigez les erreurs ci-dessus.")
        typer.echo("\n".join(lines))
    raise typer.Exit(EXIT_OK if not errors else EXIT_RUNTIME)
