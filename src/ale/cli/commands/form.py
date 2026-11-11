"""``ale form`` (Ticket G.3): the building's outline by cell growth on the plot.

For candidates k = 1..K: grow a form, simplify its outline, score it; write ``form_kk.svg``,
``form_kk.yaml`` (the outline as a site in mode ``footprint``) and ``forms.md`` (ranking).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from xml.sax.saxutils import escape

import typer

from ale.cli.commands._common import EXIT_OK, EXIT_RUNTIME
from ale.contracts.geometry import Polygon
from ale.contracts.models import Entrance, Program, SiteSpec
from ale.contracts.serialization import dump_yaml
from ale.export.diagram import PALETTE
from ale.form.grow import COURT, PARTY, FormResult, grow_form
from ale.form.metrics import FormMetrics, compute_metrics, rank_key
from ale.form.outline import Outline, outline_from_cells
from ale.topology.cellgrow import CORE_CELL, FREE, OUTSIDE

__all__ = ["Candidate", "build_candidates", "candidate_site", "form", "form_svg", "forms_md"]

_PX = 10
_FILLS = {
    "street": "#e8eef5",
    "setback": "#f6efd9",
    "free": "#ffffff",
    "court": "#dff0d8",
    "party": "#555555",
    "circulation": "#cccccc",
}


@dataclass(frozen=True)
class Candidate:
    k: int
    result: FormResult
    outline: Outline
    metrics: FormMetrics


def build_candidates(
    program: Program, site: SiteSpec, count: int, *, courtyard: bool = False
) -> list[Candidate]:
    """Candidates 1..count (seed k): grow, simplify the outline, score."""
    out: list[Candidate] = []
    for k in range(1, count + 1):
        res = grow_form(program, site, seed=k, courtyard=courtyard)
        core_cells = frozenset(res.xy(i) for _, cs in res.cores for i in cs)
        outline = outline_from_cells(
            {res.xy(i) for i in res.built_cells()},
            res.origin,
            res.cell_m,
            core_cells,
            frozenset(res.xy(i) for i in res.court_cells),
        )
        out.append(Candidate(k, res, outline, compute_metrics(res, outline)))
    return out


# ---------------------------------------------------------------------- yaml
def candidate_site(site: SiteSpec, cand: Candidate) -> SiteSpec:
    """The outline as a site in mode ``footprint``; cores carried over, entrances snapped to
    the outline (they lie on the plot edge, the building stands back by the setback)."""
    from shapely import LineString, Point
    from shapely.ops import nearest_points

    poly = max(cand.outline.polygons, key=lambda p: p.area())
    ext = poly.exterior
    line = LineString([*ext, ext[0]])
    entrances = []
    for e in site.entrances:
        near = nearest_points(line, Point(e.point))[0]
        entrances.append(
            Entrance(point=(round(near.x, 6), round(near.y, 6)), label=e.label, main=e.main)
        )
    main = next(
        (e for e in site.entrances if e.main), site.entrances[0] if site.entrances else None
    )
    ref = Point(main.point) if main is not None else Point(cand.result.entrance)
    edges = [LineString([ext[i], ext[(i + 1) % len(ext)]]) for i in range(len(ext))]
    access = min(range(len(edges)), key=lambda i: (round(edges[i].distance(ref), 9), i))
    return SiteSpec(
        footprint=Polygon(exterior=ext, holes=poly.holes),
        north_angle_deg=site.north_angle_deg,
        access_edge=access,
        entrances=tuple(entrances),
        cores=site.cores,
        mode="footprint",
    )


# ---------------------------------------------------------------------- svg
def form_svg(site: SiteSpec, cand: Candidate) -> str:
    """Cell diagram of one candidate: rooms by type, outline, outside, setbacks, party wall,
    entrance and cores. Cell ``(cx, cy)`` is drawn at ``(cx, -cy - 1)`` (y up)."""
    res = cand.result
    w, h = res.width + 2, res.height + 2
    types = sorted({t for t in res.types.values() if t != "circulation"})
    colour = {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(types)} | {
        "circulation": _FILLS["circulation"]
    }
    ox, oy = -1, -1
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{ox} {-h - oy} {w} {h}" '
        f'width="{w * _PX}" height="{h * _PX}">',
        '<defs><pattern id="core-hatch" width="0.4" height="0.4" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><rect width="0.4" height="0.4" fill="#ffffff"/>'
        '<line x1="0" y1="0" x2="0" y2="0.4" stroke="#444444" stroke-width="0.12"/>'
        "</pattern></defs>",
        f'<rect x="{ox}" y="{-h - oy}" width="{w}" height="{h}" fill="{_FILLS["street"]}"/>',
    ]
    for cy in range(res.height):
        for cx in range(res.width):
            i = res.idx(cx, cy)
            v = res.owner[i]
            if v == CORE_CELL:
                fill = "url(#core-hatch)"
            elif v >= 0:
                fill = colour[res.types[res.rooms[v]]]
            elif v == PARTY:
                fill = _FILLS["party"]
            elif v == COURT:
                fill = _FILLS["court"]
            elif v == FREE:
                fill = _FILLS["free"]
            elif v == OUTSIDE and res.in_plot[i]:
                fill = _FILLS["setback"]
            else:
                continue
            out.append(
                f'<rect x="{cx}" y="{-cy - 1}" width="1" height="1" fill="{fill}" '
                'stroke="#ffffff" stroke-width="0.04"/>'
            )
    out += _plot_lines(site, res)
    for poly in cand.outline.polygons:
        for ring in (poly.exterior, *poly.holes):
            pts = " ".join(
                f"{(x - res.origin[0]) / res.cell_m:.2f},{-(y - res.origin[1]) / res.cell_m:.2f}"
                for x, y in ring
            )
            out.append(
                f'<polygon class="outline" points="{pts}" fill="none" stroke="#000000" '
                'stroke-width="0.25"/>'
            )
    ex = (res.entrance[0] - res.origin[0]) / res.cell_m
    ey = (res.entrance[1] - res.origin[1]) / res.cell_m
    out.append(
        f'<circle id="entrance" cx="{ex:.2f}" cy="{-ey:.2f}" r="0.7" fill="#d62728" '
        'stroke="#ffffff" stroke-width="0.15"/>'
    )
    for room in res.rooms:
        cells = res.cells_of(res.rooms.index(room))
        if not cells:
            continue
        xy = [res.xy(i) for i in cells]
        sx = sum(p[0] for p in xy) / len(xy) + 0.5
        sy = sum(p[1] for p in xy) / len(xy) + 0.5
        out.append(
            f'<text x="{sx:.2f}" y="{-sy:.2f}" font-size="0.9" text-anchor="middle" '
            f'font-family="sans-serif">{escape(room)}</text>'
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _plot_lines(site: SiteSpec, res: FormResult) -> list[str]:
    ext = site.footprint.exterior
    n = len(ext)
    lines = []
    for k in range(n):
        a, b = ext[k], ext[(k + 1) % n]
        x1, y1 = (a[0] - res.origin[0]) / res.cell_m, -(a[1] - res.origin[1]) / res.cell_m
        x2, y2 = (b[0] - res.origin[0]) / res.cell_m, -(b[1] - res.origin[1]) / res.cell_m
        party = k in site.party_edges
        style = (
            'stroke="#000000" stroke-width="0.5"'
            if party
            else 'stroke="#7a7a7a" stroke-width="0.12" stroke-dasharray="0.6 0.4"'
        )
        cls = "party" if party else "plot"
        lines.append(
            f'<line class="{cls}" x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" {style}/>'
        )
    return lines


# ---------------------------------------------------------------------- ranking
def _ranked(cands: list[Candidate]) -> list[Candidate]:
    return sorted(cands, key=lambda c: (rank_key(c.metrics), c.k))


def forms_md(cands: list[Candidate]) -> str:
    """``forms.md``: the candidates ranked by the RD section 5 key (French)."""
    lines = [
        "# Recherche de forme : candidats",
        "",
        "Classement par : pièces sous leur surface, pièces à façade sans façade, pièces hors "
        "circulation, sommets du contour, compacité (ordre croissant, le plus petit est le "
        "meilleur).",
        "",
        "| Rang | Candidat | Pièces courtes | Sans façade | Hors circulation | Sommets | "
        "Compacité | Emprise (m²) | Façade (m) | Couverture | Cour | Taille cour (cellules) | "
        "Part façade | Part circulation |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for rank, c in enumerate(_ranked(cands), start=1):
        m = c.metrics
        lines.append(
            f"| {rank} | form_{c.k:02d} | {m.short} | {m.facade_missing} | {m.off_circulation} | "
            f"{m.vertices} | {m.compactness:.3f} | {m.footprint_m2:.1f} | {m.facade_m:.1f} | "
            f"{m.coverage:.3f} | {_COURT_FR[m.courtyard]} | {m.courtyard_cells} | "
            f"{m.facade_share:.2f} | {m.circulation_share:.2f} |"
        )
    lines += ["", "## Notes", ""]
    for c in sorted(cands, key=lambda c: c.k):
        o = c.outline
        lines.append(
            f"- form_{c.k:02d} : contour {o.vertices_before} sommets avant, "
            f"{o.vertices_after} après simplification ({o.cells_filled} cellules comblées, "
            f"{o.cells_cut} retirées) ; circulation : {c.result.circ_extra} cellules en plus."
        )
    return "\n".join(lines) + "\n"


_COURT_FR = {"none": "aucune", "open": "ouverte", "enclosed": "fermée"}


def form(
    program: Annotated[
        Path, typer.Option("--program", exists=True, dir_okay=False, help="Programme (.xlsx).")
    ],
    site: Annotated[
        Path,
        typer.Option("--site", exists=True, dir_okay=False, help="Parcelle (.yaml, mode plot)."),
    ],
    out: Annotated[Path, typer.Option("--out", help="Dossier de sortie.")],
    candidates: Annotated[
        int, typer.Option("--candidates", min=1, help="Nombre de candidats.")
    ] = 6,
    courtyard: Annotated[
        bool, typer.Option("--courtyard", help="Réserver une cour (extérieur enclos).")
    ] = False,
) -> None:
    """Find the building's outline by cell growth on the plot."""
    from ale.cli.commands.program import _issue_line
    from ale.program import read_program, read_site

    prog, report = read_program(program)
    spec, site_issues = read_site(site)
    errors = [i for i in (*report.issues, *site_issues) if i.severity == "error"]
    if prog is None or spec is None or errors:
        lines = [f"Erreurs ({len(errors)}) :", *(_issue_line(i) for i in errors)]
        typer.echo("\n".join([*lines, "ÉCHEC : corrigez les erreurs ci-dessus."]), err=True)
        raise typer.Exit(EXIT_RUNTIME)
    if spec.mode != "plot":
        typer.echo("ÉCHEC : le site doit être en mode « plot » (parcelle).", err=True)
        raise typer.Exit(EXIT_RUNTIME)
    out.mkdir(parents=True, exist_ok=True)
    cands = build_candidates(prog, spec, candidates, courtyard=courtyard)
    for c in cands:
        stem = f"form_{c.k:02d}"
        (out / f"{stem}.svg").write_text(form_svg(spec, c), encoding="utf-8", newline="\n")
        (out / f"{stem}.yaml").write_text(
            dump_yaml(candidate_site(spec, c)), encoding="utf-8", newline="\n"
        )
        m = c.metrics
        typer.echo(
            f"{stem} : {m.footprint_m2:.1f} m², {m.vertices} sommets, compacité "
            f"{m.compactness:.3f}, pièces courtes {m.short}"
        )
    (out / "forms.md").write_text(forms_md(cands), encoding="utf-8", newline="\n")
    typer.echo(f"classement : {out / 'forms.md'}")
    raise typer.Exit(EXIT_OK)
