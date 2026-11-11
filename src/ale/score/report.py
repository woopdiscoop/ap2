"""Scores of a matched sheet: ``score.json`` and the French ``score.md`` (R.10, U-14/U-15).

No depth penalty and no "shape change between floors" penalty (U-15). A small gap is
« à ajuster », never a failure. One stairwell is fine (U-14).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ale.score.match import MAX_GAP, Line, Match, Sheet, match_lines

__all__ = [
    "STATUS_LABELS",
    "ScoreResult",
    "build_score",
    "classify",
    "render_markdown",
    "write_outputs",
]

ABOVE_PCT = 10.0  # above this relative excess: « au-dessus de la tolérance »
STATUS_LABELS = {
    "conforme": "conforme",
    "a_ajuster": "à ajuster",
    "sous_programme": "sous le programme",
    "au_dessus": "au-dessus de la tolérance",
}


@dataclass(frozen=True)
class ScoreResult:
    """The machine-readable score and its French rendering."""

    data: dict[str, Any]
    markdown: str


def classify(gap: float, tolerance_pct: float) -> str:
    """Status of a relative gap (fraction): see module docstring and RD §4."""
    tol = tolerance_pct / 100.0
    if abs(gap) < 1e-9:
        return "conforme"
    if abs(gap) <= tol:
        return "a_ajuster"
    if gap < -tol:
        return "sous_programme"
    return "au_dessus" if gap > max(ABOVE_PCT / 100.0, tol) else "a_ajuster"


def _r(x: float) -> float:
    return round(x, 4)


def _totals(target: float, drawn: float, all_drawn: float, matched: int, n: int) -> dict[str, Any]:
    gap = (drawn - target) / target * 100.0 if target else 0.0
    return {
        "rooms_drawn": n,
        "matched": matched,
        "programme_m2": _r(target),
        "matched_drawn_m2": _r(drawn),
        "all_drawn_m2": _r(all_drawn),
        "gap_pct": _r(gap),
    }


def build_score(
    sheet: Sheet,
    lines: Sequence[Line],
    *,
    tolerance_pct: float = 5.0,
    plan_name: str,
    plan_sha256: str,
    page: int,
    programme_name: str,
) -> ScoreResult:
    """Match ``lines`` with the rooms of ``sheet`` and score the result."""
    matches: list[Match] = match_lines(lines, sheet.rooms)
    by_line = {m.line: m for m in matches}
    matched_rooms = {m.room for m in matches}

    rows: list[dict[str, Any]] = []
    for m in sorted(matches, key=lambda x: x.line):
        ln, rm = lines[m.line], sheet.rooms[m.room]
        facade: str | None = None
        if ln.needs_facade:
            facade = "ok" if rm.on_facade else "signale"
        rows.append(
            {
                "line": ln.key,
                "name": ln.name,
                "target_m2": _r(ln.target_m2),
                "plan": rm.plan + 1,
                "room": rm.room_id,
                "area_m2": _r(rm.area_m2),
                "area_source": rm.source,
                "gap_pct": _r(m.gap * 100.0),
                "status": classify(m.gap, tolerance_pct),
                "needs_facade": ln.needs_facade,
                "facade": facade,
            }
        )
    unmatched_lines = [
        {"line": ln.key, "name": ln.name, "target_m2": _r(ln.target_m2)}
        for i, ln in enumerate(lines)
        if i not in by_line
    ]
    unmatched_rooms = [
        {"plan": rm.plan + 1, "room": rm.room_id, "area_m2": _r(rm.area_m2), "label": rm.label}
        for j, rm in enumerate(sheet.rooms)
        if j not in matched_rooms
    ]

    plan_totals: list[dict[str, Any]] = []
    for info in sheet.plans:
        mine = [m for m in matches if sheet.rooms[m.room].plan == info.index]
        plan_totals.append(
            {
                "plan": info.index + 1,
                **_totals(
                    sum(lines[m.line].target_m2 for m in mine),
                    sum(sheet.rooms[m.room].area_m2 for m in mine),
                    sum(r.area_m2 for r in sheet.rooms if r.plan == info.index),
                    len(mine),
                    info.rooms,
                ),
            }
        )
    building = _totals(
        sum(lines[m.line].target_m2 for m in matches),
        sum(sheet.rooms[m.room].area_m2 for m in matches),
        sum(r.area_m2 for r in sheet.rooms),
        len(matches),
        sum(i.rooms for i in sheet.plans),
    )

    stairs = [
        {
            "plan": i.index + 1,
            "cores": i.stair_cores,
            "status": "ok"
            if i.stair_cores == 1
            else ("absente" if i.stair_cores == 0 else "a_verifier"),
        }
        for i in sheet.plans
    ]
    limits = _limits(sheet, matches)
    data: dict[str, Any] = {
        "schema": "ale.score/1",
        "plan": {"file": plan_name, "sha256": plan_sha256, "page": page},
        "programme": {"file": programme_name, "lines": len(lines)},
        "tolerance_pct": tolerance_pct,
        "coverage": {
            "programme_lines": len(lines),
            "matched": len(matches),
            "unmatched_lines": unmatched_lines,
            "unmatched_rooms": unmatched_rooms,
        },
        "matches": rows,
        "totals": {"plans": plan_totals, "building": building},
        "stairs": {"stair_rooms": len(sheet.stairs), "plans": stairs},
        "limits": limits,
    }
    return ScoreResult(data, render_markdown(data))


def _limits(sheet: Sheet, matches: Sequence[Match]) -> list[str]:
    limits = [
        "Les pièces sont appariées au programme par la surface (assignation à coût minimal, "
        f"écart relatif maximal {MAX_GAP * 100:.0f} %) : l'affectation n'est pas vérifiée "
        "par les noms."
    ]
    unnamed = sum(1 for r in sheet.rooms if r.label is None)
    if unnamed:
        limits.append(f"{unnamed} pièce(s) dessinée(s) sans nom lisible : nom non vérifiable.")
    from_text = sum(1 for r in sheet.rooms if r.source == "texte")
    limits.append(
        f"Surfaces : {from_text} lue(s) dans le texte du plan, "
        f"{len(sheet.rooms) - from_text} calculée(s) depuis la géométrie."
    )
    if sheet.skipped:
        limits.append(
            f"{len(sheet.skipped)} pièce(s) sans surface exploitable (échelle inconnue) : "
            + ", ".join(sheet.skipped)
        )
    limits.append(
        "Circulation verticale : cages repérées par les pièces nommées « escalier » ; "
        "la géométrie des volées n'est pas lue."
    )
    limits.append(
        "Façade : une pièce est en façade si elle touche le contour extérieur du plan "
        "(union des pièces) ; les ouvertures ne sont pas vérifiées."
    )
    if not matches:
        limits.append("Aucune pièce n'a pu être appariée.")
    limits.extend(dict.fromkeys(sheet.warnings))
    return limits


def _fmt(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def render_markdown(d: dict[str, Any]) -> str:
    """French ``score.md`` of a score dictionary (deterministic)."""
    cov = d["coverage"]
    out = [
        "# Score du projet existant",
        "",
        f"- Plan : `{d['plan']['file']}` (page {d['plan']['page']})",
        f"- Programme : `{d['programme']['file']}` ({d['programme']['lines']} lignes)",
        f"- Tolérance d'esquisse : {_fmt(d['tolerance_pct'])} %",
        "",
        "## Couverture du programme",
        "",
        f"{cov['matched']} ligne(s) sur {cov['programme_lines']} appariée(s) à une pièce dessinée.",
        "",
    ]
    out.append("### Lignes du programme sans pièce")
    out.append("")
    if cov["unmatched_lines"]:
        out += [
            f"- {x['name']} ({x['line']}) : {_fmt(x['target_m2'])} m²"
            for x in cov["unmatched_lines"]
        ]
    else:
        out.append("Aucune.")
    out += ["", "### Pièces dessinées sans ligne de programme", ""]
    if cov["unmatched_rooms"]:
        out += [
            f"- plan {x['plan']}, {x['room']} : {_fmt(x['area_m2'])} m²"
            + (f" ({x['label']})" if x["label"] else "")
            for x in cov["unmatched_rooms"]
        ]
    else:
        out.append("Aucune.")
    out += ["", "## Surfaces", ""]
    if d["matches"]:
        out += [
            "| Ligne | Programme (m²) | Plan | Pièce | Dessin (m²) | Écart | Statut |",
            "|---|---:|---:|---|---:|---:|---|",
        ]
        for r in d["matches"]:
            out.append(
                f"| {r['name']} ({r['line']}) | {_fmt(r['target_m2'])} | {r['plan']} | {r['room']} "
                f"| {_fmt(r['area_m2'])} | {_fmt(r['gap_pct'])} % "
                f"| « {STATUS_LABELS[r['status']]} » |"
            )
    else:
        out.append("Aucune pièce appariée.")
    out += [
        "",
        "### Totaux",
        "",
        "| Périmètre | Pièces | Appariées | Programme (m²) | Dessin apparié (m²) | Écart |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for t in d["totals"]["plans"]:
        out.append(_total_row(f"Plan {t['plan']}", t))
    out.append(_total_row("Bâtiment", d["totals"]["building"]))
    out += ["", "## Façade", ""]
    facade = [r for r in d["matches"] if r["needs_facade"]]
    if facade:
        for r in facade:
            verdict = "en façade" if r["facade"] == "ok" else "pièce intérieure : façade manquante"
            out.append(f"- {r['name']} ({r['line']}) : {verdict}")
    else:
        out.append("Aucune pièce appariée n'exige de façade.")
    out += ["", "## Circulation verticale", ""]
    out.append(f"Pièces d'escalier repérées : {d['stairs']['stair_rooms']}.")
    out.append("")
    for s in d["stairs"]["plans"]:
        text = {
            "ok": "une cage d'escalier : conforme (une seule cage requise)",
            "absente": "aucune cage d'escalier repérée",
            "a_verifier": "plusieurs cages sur le même plan : à vérifier",
        }[s["status"]]
        out.append(f"- Plan {s['plan']} : {s['cores']} cage(s), {text}")
    out += ["", "## Limites", ""]
    out += [f"- {x}" for x in d["limits"]]
    return "\n".join(out) + "\n"


def _total_row(name: str, t: dict[str, Any]) -> str:
    return (
        f"| {name} | {t['rooms_drawn']} | {t['matched']} | {_fmt(t['programme_m2'])} "
        f"| {_fmt(t['matched_drawn_m2'])} | {_fmt(t['gap_pct'])} % |"
    )


def write_outputs(result: ScoreResult, out_dir: Path) -> list[Path]:
    """Write ``score.md`` and ``score.json`` into ``out_dir`` (created) and nothing else."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md = out / "score.md"
    js = out / "score.json"
    md.write_text(result.markdown, encoding="utf-8", newline="\n")
    js.write_text(
        json.dumps(result.data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return [md, js]
