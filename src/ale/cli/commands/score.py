"""``ale score``: score an existing scheme (PDF/DXF/DWG) against a programme (Ticket R.10)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

import typer

from ale.cli.commands._common import EXIT_OK, EXIT_RUNTIME, EXIT_USAGE
from ale.contracts.config import AleConfig
from ale.contracts.models import PlanGeometry, Program

__all__ = ["score"]


def _fail(message: str, code: int = EXIT_RUNTIME) -> typer.Exit:
    typer.echo(f"ale score : {message}", err=True)
    return typer.Exit(code)


def _load_program(programme: Path | None, annexe: Path | None, building: str | None) -> Program:
    from ale.program import read_program
    from ale.program.annexe import AnnexeError, read_annexe

    if (programme is None) == (annexe is None):
        raise _fail("donner exactement un de --programme ou --annexe.", EXIT_USAGE)
    if programme is not None:
        program, report = read_program(programme)
        if program is None:
            for issue in report.issues:
                typer.echo(f"{issue.code} : {issue.message}", err=True)
            raise _fail("programme illisible.")
        return program
    assert annexe is not None
    try:
        result = read_annexe(annexe)
    except AnnexeError as exc:
        raise _fail(f"annexe illisible : {exc}") from exc
    for item in result.unmatched:
        typer.echo(f"Avertissement : espace sans règle ignoré : {item.espace}", err=True)
    buildings = result.buildings
    if building is not None:
        buildings = [b for b in buildings if b.slug == building]
    if not buildings:
        raise _fail("aucun bâtiment importable dans l'annexe.")
    if len(buildings) > 1:
        slugs = ", ".join(b.slug for b in buildings)
        raise _fail(f"plusieurs bâtiments ({slugs}) : choisir avec --building.", EXIT_USAGE)
    return buildings[0].program()


def _read_plans(plan: Path, page: int) -> tuple[tuple[PlanGeometry, ...], str]:
    from ale.cad import convert_dwg, propose_layer_map, read_cad
    from ale.cad.convert import file_sha256
    from ale.pdfread import read_pdf_page

    config = AleConfig()
    sha = file_sha256(plan)
    suffix = plan.suffix.lower()
    if suffix == ".pdf":
        res = read_pdf_page(plan, page - 1, source_sha256=sha, config=config)
        for w in res.warnings:
            typer.echo(f"Avertissement : {w}", err=True)
        return res.plans, sha
    if suffix in (".dxf", ".dwg"):
        from ezdxf.filemanagement import readfile

        from ale.contracts.enums import SourceKind

        kind = SourceKind.DXF
        dxf = plan
        with tempfile.TemporaryDirectory() as tmp:
            if suffix == ".dwg":
                conv = convert_dwg(plan, Path(tmp), config)
                if not conv.ok or conv.dxf_path is None:
                    raise _fail(f"conversion DWG impossible : {conv.message}")
                dxf, kind = conv.dxf_path, SourceKind.DWG
            try:
                doc = readfile(dxf)
                names = {str(e.dxf.layer) for e in doc.modelspace()}
                names.update(str(layer.dxf.name) for layer in doc.layers)
            except Exception as exc:
                raise _fail(f"DXF illisible : {exc}") from exc
            cad = read_cad(
                dxf,
                source_sha256=sha,
                layer_map=propose_layer_map(sorted(names)),
                config=config,
                source_kind=kind,
            )
        for w in cad.warnings:
            typer.echo(f"Avertissement : {w}", err=True)
        return cad.plans, sha
    raise _fail(f"format de plan non pris en charge : {plan.suffix or plan.name}", EXIT_USAGE)


def score(
    plan: Annotated[Path, typer.Option("--plan", help="Plan existant (PDF vectoriel, DXF, DWG).")],
    programme: Annotated[
        Path | None, typer.Option("--programme", help="Programme (programme.xlsx).")
    ] = None,
    annexe: Annotated[
        Path | None, typer.Option("--annexe", help="Annexe « programme physique » (import P.2).")
    ] = None,
    building: Annotated[
        str | None, typer.Option("--building", help="Bâtiment de l'annexe (si plusieurs).")
    ] = None,
    page: Annotated[int, typer.Option("--page", min=1, help="Page du PDF (à partir de 1).")] = 1,
    out: Annotated[Path, typer.Option("--out", help="Dossier de sortie.")] = Path("score_out"),
    tolerance_pct: Annotated[
        float, typer.Option("--tolerance-pct", min=0.0, help="Tolérance d'esquisse (%).")
    ] = 5.0,
) -> None:
    """Score an existing scheme against a programme (areas, façade, stairs; advisory)."""
    from ale.score import build_score, extract_sheet, lines_from_program, write_outputs

    if not plan.is_file():
        raise _fail(f"plan introuvable : {plan}")
    program = _load_program(programme, annexe, building)
    plans, sha = _read_plans(plan, page)
    if not plans:
        raise _fail("aucun plan lisible dans le fichier.")
    sheet = extract_sheet(plans)
    if not sheet.rooms:
        raise _fail("aucune pièce lue sur le plan.")
    source = programme if programme is not None else annexe
    assert source is not None
    result = build_score(
        sheet,
        lines_from_program(program),
        tolerance_pct=tolerance_pct,
        plan_name=plan.name,
        plan_sha256=sha,
        page=page,
        programme_name=source.name,
    )
    written = write_outputs(result, out)
    cov = result.data["coverage"]
    typer.echo(
        f"Score : {cov['matched']}/{cov['programme_lines']} ligne(s) appariée(s). "
        f"Ouvrir : {written[0]}"
    )
    raise typer.Exit(EXIT_OK)
