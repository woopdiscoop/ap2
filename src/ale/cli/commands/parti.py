"""``ale parti`` (Ticket G.2): generate partis, evaluate them jointly, explain each one."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Annotated

import typer
from shapely import Polygon as ShPolygon

from ale.cli.commands._common import EXIT_OK, EXIT_RUNTIME
from ale.contracts.models import SiteSpec
from ale.contracts.serialization import dump_yaml, load_yaml
from ale.parti import (
    Dropped,
    Entry,
    FormMatch,
    Parti,
    build_card,
    card_md,
    match_forms,
    run_partis,
)
from ale.parti.card import FLAG_FR
from ale.parti.evaluate import typical_floor_site

__all__ = ["parse_floors", "parti", "parti_svg", "partis_md"]

_PX = 6.0
_FLOOR_FILLS = ("#c9d6e8", "#aebfd6", "#93a8c4", "#7a91b0", "#627a9c")


def parse_floors(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", text)
    if not m:
        raise typer.BadParameter(f"« {text} » : attendu N ou N-M")
    lo = int(m.group(1))
    hi = int(m.group(2) or lo)
    if lo < 1 or hi < lo:
        raise typer.BadParameter(f"« {text} » : plage de niveaux invalide")
    return lo, hi


def _axis(x1: float, y1: float, x2: float, y2: float) -> str:
    return (
        f'<line class="axis" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        'stroke="#d62728" stroke-width="2"/>'
    )


def _ring_path(coords: Iterable[Sequence[float]], x0: float, y1: float) -> str:
    pts = " ".join(f"{(x - x0) * _PX:.1f},{(y1 - y) * _PX:.1f}" for x, y in coords)
    return pts


def parti_svg(site: SiteSpec, e: Entry) -> str:
    """Plan of one parti: plot, setback zone, floor outlines (one tint per floor), core,
    forecourt, orientation arrows and, beside it, the typical-floor cell diagram."""
    from ale.export.diagram import diagram_svg

    m = e.massing
    ext = site.footprint.exterior
    x0, x1 = min(p[0] for p in ext), max(p[0] for p in ext)
    y0, y1 = min(p[1] for p in ext), max(p[1] for p in ext)
    w, h = (x1 - x0) * _PX, (y1 - y0) * _PX
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w * 2 + 30:.0f}" height="{h:.0f}" '
        f'viewBox="0 0 {w * 2 + 30:.0f} {h:.0f}">',
        f'<rect x="0" y="0" width="{w * 2 + 30:.0f}" height="{h:.0f}" fill="#ffffff"/>',
        f'<polygon class="plot" points="{_ring_path(list(ext), x0, y1)}" fill="#f6efd9" '
        'stroke="#7a7a7a" stroke-dasharray="6 4"/>',
        f'<polygon class="zone" points="{_ring_path(m.zone.exterior.coords, x0, y1)}" '
        'fill="#ffffff" stroke="#999999"/>',
    ]
    if m.forecourt is not None:
        fc_pts = _ring_path(m.forecourt.exterior.coords, x0, y1)
        out.append(
            f'<polygon class="forecourt" points="{fc_pts}" fill="#dff0d8" stroke="#6a9a5a"/>'
        )
    for k, o in enumerate(m.outlines):
        fill = _FLOOR_FILLS[min(k, len(_FLOOR_FILLS) - 1)]
        rings = [o.exterior, *o.interiors]
        d = " ".join("M " + _ring_path(r.coords, x0, y1).replace(" ", " L ") + " Z" for r in rings)
        out.append(
            f'<path class="floor" data-floor="{k}" d="{d}" fill="{fill}" fill-opacity="0.55" '
            'fill-rule="evenodd" stroke="#1f3a5f" stroke-width="1.2"/>'
        )
    cx0, cy0, cx1, cy1 = m.core
    out.append(
        f'<rect class="core" x="{(cx0 - x0) * _PX:.1f}" y="{(y1 - cy1) * _PX:.1f}" '
        f'width="{(cx1 - cx0) * _PX:.1f}" height="{(cy1 - cy0) * _PX:.1f}" fill="#444444"/>'
    )
    # orientation arrows: along each long axis, and north
    bx0, by0, bx1, by1 = m.typical.bounds
    mx, my = (bx0 + bx1) / 2, (by0 + by1) / 2
    ax, ay = (mx - x0) * _PX, (y1 - my) * _PX
    ln = 30.0
    if e.parti.orientation_deg == 0:
        out.append(_axis(ax - ln, ay, ax + ln, ay))
    else:
        out.append(_axis(ax, ay - ln, ax, ay + ln))
    out.append(f'<text x="8" y="16" font-size="12" font-family="sans-serif">{e.parti.key()}</text>')
    diagram = e.evaluation.diagram
    if diagram is not None:
        inner = diagram_svg(diagram).split("\n", 1)[1]
        inner = re.sub(
            r'<svg xmlns="http://www.w3.org/2000/svg" ',
            f'<svg class="cells" x="{w + 30:.0f}" y="0" ',
            inner,
            count=1,
        )
        inner = re.sub(
            r'width="[\d.]+" height="[\d.]+">',
            f'width="{w:.0f}" height="{h:.0f}" preserveAspectRatio="xMinYMin meet">',
            inner,
            count=1,
        )
        out.append(inner.rstrip())
    out.append("</svg>")
    return "\n".join(out) + "\n"


def partis_md(
    entries: list[Entry],
    dropped: list[Dropped],
    north_angle_deg: float,
    matches: list[FormMatch] | None = None,
) -> str:
    n_nd = sum(e.non_dominated for e in entries)
    lines = [
        "# Génération de partis",
        "",
        "Les critères sont évalués ensemble. Classement : ensemble non dominé d'abord, selon "
        "(manques durs, caractère forcé, part de façade mal orientée, compacité), tous à "
        "minimiser.",
        "",
        f"{len(entries)} partis retenus, dont {n_nd} non dominés ; "
        f"{len(dropped)} jeux de gènes écartés.",
        "",
        "| Rang | Parti | Non dominé | Typologie | Niveaux | Manques durs | Forçage | "
        "Exceptions locales | Façade bien orientée | Compacité | Éléments à fonction unique |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    cards = []
    for i, e in enumerate(entries, start=1):
        ev = e.evaluation
        card = build_card(e.massing, ev, north_angle_deg)
        cards.append(card)
        lines.append(
            f"| {i} | parti_{i:02d} | {'oui' if e.non_dominated else 'non'} | {e.parti.typology} | "
            f"{e.parti.floors} | {ev.hard_misses} | {ev.forcedness:.2f} | {ev.exceptions} | "
            f"{ev.good_share:.2f} | {ev.compactness:.3f} | {len(card.flagged)} |"
        )
    if matches:
        lines += [
            "",
            "## Formes G.3 rapprochées",
            "",
            "| Forme | Typologie | IoU |",
            "|---|---|---|",
        ]
        lines += [f"| {mt.name} | {mt.typology} | {mt.iou:.3f} |" for mt in matches]
    lines += ["", "## Partis", ""]
    for i, (e, card) in enumerate(zip(entries, cards, strict=True), start=1):
        ev = e.evaluation
        p = e.parti
        loading = "simple" if p.loading == "single" else "double"
        lines += [
            f"### parti_{i:02d} : {p.typology}, {p.floors} niveaux"
            + (" (non dominé)" if e.non_dominated else ""),
            "",
            f"- gènes : orientation {p.orientation_deg}°, ailes {loading} "
            f"charge ({p.wing_depth_m:.1f} m), noyau « {p.core_position} », circulation "
            f"« {p.circulation} », entrée sur le côté {p.entrance_side}, parvis "
            f"{p.forecourt_m:.1f} m, retrait en terrasse : {'oui' if p.terrace else 'non'}",
            f"- surface : {ev.gross_m2:.0f} m² pour un besoin de {ev.need_m2:.0f} m² "
            f"({ev.gross_m2 / ev.need_m2 - 1:+.1%})",
            f"- façade : {ev.facade_m:.0f} m par niveau, {ev.good_share:.0%} bien orientée ; "
            f"linéaire utile {ev.frontage_capacity_m:.0f} m pour "
            f"{ev.frontage_demand_m:.0f} m demandés",
            f"- prospect de la cour : petit côté {ev.court_short_m:.1f} m, "
            f"{'conforme' if ev.court_ok else 'NON conforme'} ; distance noyau - point le plus "
            f"éloigné : {ev.core_distance_m:.0f} m (indicatif)",
            f"- diagramme de l'étage courant : {len(ev.facade_missing)} pièce(s) à façade sans "
            f"façade, {len(ev.off_circulation)} hors circulation, {len(ev.rooms_short)} courte(s), "
            f"{len(ev.fragmented)} fragmentée(s)",
            f"- caractère forcé : {ev.share_met:.0%} des exigences satisfaites par le parti seul, "
            f"{ev.exceptions} exception(s) locale(s) ; score {ev.forcedness:.2f}",
            "",
            "Fiche du parti :",
            "",
            card_md(card),
        ]
    reasons = Counter(d.reason.split(":")[0].split("(")[0].strip() for d in dropped)
    lines += ["## Gènes écartés", ""]
    lines += [f"- {n} x {r}" for r, n in reasons.most_common(12)]
    lines.append("")
    return "\n".join(lines)


def parti(
    program: Annotated[Path, typer.Option("--program", exists=True, dir_okay=False)],
    site: Annotated[Path, typer.Option("--site", exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", help="Dossier de sortie.")],
    floors: Annotated[str, typer.Option("--floors", help="Niveaux, ex. 3-5.")] = "3-5",
    count: Annotated[int, typer.Option("--count", min=1, help="Nombre de partis.")] = 40,
    from_forms: Annotated[
        Path | None,
        typer.Option("--from-forms", exists=True, file_okay=False, help="Sorties de `ale form`."),
    ] = None,
) -> None:
    """Generate partis (massing + core + circulation + entrance) and rank them jointly."""
    from ale.cli.commands.program import _issue_line
    from ale.program import read_program, read_site

    fl = parse_floors(floors)
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
    matches: list[FormMatch] = []
    seeds: tuple[Parti, ...] = ()
    if from_forms is not None:
        from dataclasses import replace

        forms = {
            p.stem: load_yaml(SiteSpec, p.read_text(encoding="utf-8"))
            for p in sorted(from_forms.glob("form_*.yaml"))
        }
        matches = match_forms(forms, prog, spec, fl)
        seeds = tuple(
            replace(mt.parti, floors=n) for mt in matches for n in range(fl[0], fl[1] + 1)
        )
    entries, dropped = run_partis(prog, spec, floors=fl, count=count, seeds=seeds)
    out.mkdir(parents=True, exist_ok=True)
    for i, e in enumerate(entries, start=1):
        stem = f"parti_{i:02d}"
        (out / f"{stem}.svg").write_text(parti_svg(spec, e), encoding="utf-8", newline="\n")
        d = out / stem
        d.mkdir(exist_ok=True)
        (d / "site.yaml").write_text(
            dump_yaml(typical_floor_site(spec, e.massing)), encoding="utf-8", newline="\n"
        )
        card = build_card(e.massing, e.evaluation, spec.north_angle_deg)
        typer.echo(
            f"{stem} : {e.parti.typology}, {e.parti.floors} niveaux, manques durs "
            f"{e.evaluation.hard_misses}, forçage {e.evaluation.forcedness:.2f}, "
            f"fiches signalées {len(card.flagged)}{' [non dominé]' if e.non_dominated else ''}"
        )
    (out / "partis.md").write_text(
        partis_md(entries, dropped, spec.north_angle_deg, matches), encoding="utf-8", newline="\n"
    )
    typer.echo(f"classement : {out / 'partis.md'}")
    _ = (FLAG_FR, ShPolygon)
    raise typer.Exit(EXIT_OK)
