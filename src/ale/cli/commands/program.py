"""``ale program template`` / ``check`` (Ticket 3.1) and ``import`` (Ticket P.2).

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
    EXIT_USAGE,
    WorkspaceOption,
    open_workspace_or_exit,
)
from ale.config import AleConfig

if TYPE_CHECKING:
    from ale.program.annexe import AnnexeResult
    from ale.program.models import FeasibilityReport, Issue
    from ale.program.prepare import InputCheck

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


def _anchor_lines(result: InputCheck) -> list[str]:
    """Anchors found in the programme and the site (A.4)."""
    site = result.site
    entrances = () if site is None else site.entrances
    cores = () if site is None else site.cores
    lines = [f"Ancrages ({len(result.anchors)}) :"]
    labels = {"corner": "coin", "entrance": "entrée"}
    lines += [f"  {rid} ({name}) : {labels[a]}" for rid, name, a in result.anchors]
    lines.append(f"  entrées du site : {len(entrances)}, noyaux du site : {len(cores)}")
    return lines


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
        lines += _anchor_lines(result)
        if result.feasibility is not None:
            lines += _summary(result.feasibility)
        lines.append("OK" if not errors else "ÉCHEC : corrigez les erreurs ci-dessus.")
        typer.echo("\n".join(lines))
    raise typer.Exit(EXIT_OK if not errors else EXIT_RUNTIME)


def _import_summary(result: AnnexeResult, written: list[Path]) -> list[str]:
    lines = [f"Bâtiments : {len(result.buildings)}"]
    for b in result.buildings:
        lines.append(
            f"  {b.name} : {len(b.lines)} lignes, {b.instances} instances, "
            f"{float(b.useful_m2):.2f} m² utiles"
        )
    lines.append(f"Lignes ignorées ({len(result.skipped)}) :")
    lines += [f"  {s.building}, ligne {s.row} : {s.espace} ({s.reason})" for s in result.skipped]
    lines.append(f"Contrôle des totaux ({len(result.totals)}) :")
    for t in result.totals:
        verdict = "OK" if t.ok else "ÉCART"
        lines.append(
            f"  {t.building}, ligne {t.row} : déclaré {float(t.stated_m2):.2f} m², "
            f"lu {float(t.computed_m2):.2f} m² : {verdict}"
        )
    lines.append(f"Avertissements ({len(result.warnings)}) :")
    lines += [f"  {w}" for w in result.warnings]
    lines.append("Fichiers écrits :")
    lines += [f"  {p}" for p in written]
    return lines


@app.command("import")
def import_annexe(
    annexe: Annotated[
        Path, typer.Option("--annexe", dir_okay=False, help="Programme physique (.xlsx).")
    ],
    out: Annotated[Path, typer.Option("--out", file_okay=False, help="Output directory.")],
    rules: Annotated[
        Path | None,
        typer.Option("--rules", dir_okay=False, help="Mapping rules YAML (before the defaults)."),
    ] = None,
    building: Annotated[
        str | None, typer.Option("--building", help="Import only this building (name or slug).")
    ] = None,
) -> None:
    """Convert a "programme physique" (Annexe format) into ALE programme templates."""
    if importlib.util.find_spec("openpyxl") is None:  # pragma: no cover - extra in tests
        typer.echo(_EXTRA_HINT, err=True)
        raise typer.Exit(EXIT_RUNTIME)
    from ale.program.annexe import AnnexeError, fold_name, load_rules, read_annexe, write_outputs

    try:
        result = read_annexe(annexe, load_rules(rules))
    except AnnexeError as exc:
        typer.echo(f"ERREUR : {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    if result.unmatched:
        lines = [f"ERREUR : espaces sans règle de correspondance ({len(result.unmatched)}) :"]
        lines += [f"  {u.building}, ligne {u.row} : « {u.espace} »" for u in result.unmatched]
        lines.append("Ajoutez une règle (--rules FICHIER). Aucun fichier écrit.")
        typer.echo("\n".join(lines), err=True)
        raise typer.Exit(EXIT_USAGE)
    if building is not None:
        wanted = fold_name(building)
        chosen = [b for b in result.buildings if wanted in (fold_name(b.name), b.slug)]
        if not chosen:
            names = ", ".join(f"« {b.name} »" for b in result.buildings) or "aucun"
            typer.echo(f"ERREUR : bâtiment « {building} » introuvable (lus : {names}).", err=True)
            raise typer.Exit(EXIT_USAGE)
        result.buildings = chosen
    if not result.buildings:
        typer.echo("ERREUR : aucune ligne de programme importée.", err=True)
        raise typer.Exit(EXIT_USAGE)
    written = write_outputs(result.buildings, out)
    typer.echo("\n".join(_import_summary(result, written)))
    raise typer.Exit(EXIT_OK)
