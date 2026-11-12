"""Orchestration and outputs of the stacking phase (Ticket M.1, RD section 7)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from ale.contracts.models import Program
from ale.contracts.serialization import dump_yaml
from ale.export.diagram import PALETTE, write_diagram_svg
from ale.stack.assign import HARD_OVER, Stacking, build_problem, solve
from ale.stack.building import Building
from ale.stack.floors import (
    FloorResult,
    build_floors,
    skeleton_identical,
    stackability,
    write_programme_xlsx,
)
from ale.stack.rules import WET_TYPES, StackRules
from ale.stack.skeleton import AREA_CELL_M2, Skeleton, build_skeleton, core_cell_rect

__all__ = ["StackResult", "render_markdown", "render_svg", "run_stack", "write_outputs"]

_MAX_ROUNDS = 5


@dataclass(frozen=True)
class StackResult:
    """Everything the stacking phase produced."""

    building: Building
    program: Program
    rules: StackRules
    stacking: Stacking
    skeleton: Skeleton
    floors: tuple[FloorResult, ...]
    level_of: Mapping[str, int]
    stackability: float
    skeleton_ok: bool
    misses: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """No hard miss."""
        return not self.misses


def run_stack(
    program: Program,
    building: Building,
    rules: StackRules,
    *,
    seed: int = 0,
    strict_solids: bool = False,
) -> StackResult:
    """Stack the programme, size the skeleton and lay out every floor (deterministic).

    ``strict_solids`` (Ticket M.2): keep the wet stack one cell away from the top outline so
    that core + stack are a valid solid of the exact-plan engine (needed by ``--plans``)."""
    if strict_solids:
        from ale.stack.plans import build_skeleton_strict as make_skeleton
    else:
        make_skeleton = build_skeleton
    instances = program.instances()
    wet = [(i, s) for i, s in instances if s.type in WET_TYPES]
    others = [(i, s) for i, s in instances if s.type not in WET_TYPES]
    outlines = [building.outline(k).area for k in range(building.n_floors)]
    from ale.stack.skeleton import Grid

    ground = building.outline(0).bounds
    core_area = core_cell_rect(building, Grid(ground[0], ground[1]))
    core_m2 = (core_area[2] - core_area[0]) * (core_area[3] - core_area[1]) * AREA_CELL_M2
    wet_m2 = 1.5 * sum(s.target_area_m2 for _, s in wet) / building.n_floors
    stacking = skeleton = None
    for _ in range(_MAX_ROUNDS):
        capacity = [
            max(0.0, (a - core_m2 - wet_m2) * (1.0 - rules.circulation_share)) for a in outlines
        ]
        stacking = solve(build_problem(others, rules, capacity))
        skeleton = make_skeleton(building, wet, stacking.loads())
        if abs(skeleton.wet_area_m2 - wet_m2) < 1e-6:
            break
        wet_m2 = skeleton.wet_area_m2
    assert stacking is not None and skeleton is not None
    level_of: dict[str, int] = {
        u.iid: k for u, k in zip(stacking.problem.units, stacking.assign, strict=True)
    }
    level_of.update(skeleton.level_of)
    floors = build_floors(building, skeleton, program, level_of, seed=seed)
    ok = skeleton_identical(floors, skeleton)
    misses = [*stacking.misses(), *skeleton.misses]
    if not ok:
        misses.append("Squelette : noyau ou colonne humide différents selon les niveaux.")
    misses += [f.error for f in floors if f.error]
    misses += [
        f"Niveau {f.level} : pièce(s) fragmentée(s) après réparation : {', '.join(f.fragmented)}."
        for f in floors
        if f.fragmented
    ]
    return StackResult(
        building=building,
        program=program,
        rules=rules,
        stacking=stacking,
        skeleton=skeleton,
        floors=floors,
        level_of=level_of,
        stackability=stackability([f.layer() for f in floors]),
        skeleton_ok=ok,
        misses=tuple(misses),
    )


# ------------------------------------------------------------------------- markdown
def _yn(v: bool) -> str:
    return "oui" if v else "non"


def _pin_text(where: str | int) -> str:
    return {"top": "dernier niveau", "ground": "rez-de-chaussée"}.get(str(where), f"niveau {where}")


def render_markdown(r: StackResult) -> str:
    """``stacking.md`` (French)."""
    st, sk, b = r.stacking, r.skeleton, r.building
    p = st.problem
    n = b.n_floors
    loads = st.loads()
    mat = st.matrix()
    lines = [
        "# Empilement et squelette vertical",
        "",
        f"{n} niveaux (hauteur d'étage {b.floor_height_m:.2f} m), un noyau « {b.core.id} » de "
        f"{sk.core_area_m2:.1f} m², colonne humide de {sk.wet_area_m2:.1f} m² ; "
        f"part de circulation {r.rules.circulation_share:.0%}.",
        "",
        "## Répartition par niveau (m², charge en % de la capacité)",
        "",
        "| Niveau | " + " | ".join(p.groups) + " | Total | Capacité | Charge |",
        "|---|" + "---|" * (len(p.groups) + 3),
    ]
    for k in range(n - 1, -1, -1):
        cap = p.capacity[k]
        cells = [f"{mat.get((k, g), 0.0):.1f}" if (k, g) in mat else "" for g in p.groups]
        share = f"{loads[k] / cap:.0%}" if cap > 0 else "n/a"
        lines.append(f"| {k} | " + " | ".join(cells) + f" | {loads[k]:.1f} | {cap:.1f} | {share} |")
    over = [
        k for k in range(n) if p.capacity[k] > 0 and loads[k] > HARD_OVER * p.capacity[k] + 1e-6
    ]
    lines += ["", f"Niveaux au-delà de 110 % de la capacité : {over or 'aucun'}.", ""]

    lines += ["## Épingles et regroupements", ""]
    met = st.pins_met()
    if met:
        lines += ["| Groupe | Épingle | Respectée |", "|---|---|---|"]
        lines += [f"| {g} | {_pin_text(p.group_pins[g])} | {_yn(ok)} |" for g, ok in met.items()]
    else:
        lines.append("Aucune épingle de groupe.")
    anchored = [u.iid for u in p.units if u.pin is not None]
    if anchored:
        lines += [
            "",
            "Pièces épinglées à leur niveau (ancrage entrée ou niveau du programme) : "
            + ", ".join(f"{i} (niveau {st.level_of(i)})" for i in anchored)
            + ".",
        ]
    split = st.split_groups()
    gf = st.group_floors()
    lines += [
        "",
        "Groupes scindés : "
        + (
            ", ".join(f"{g} (niveaux {', '.join(map(str, gf[g]))})" for g in split)
            if split
            else "aucun"
        )
        + ".",
    ]
    tg = st.together_met()
    if tg:
        lines += ["", "| Paire « ensemble » | Même niveau ou niveaux voisins |", "|---|---|"]
        lines += [f"| {a} / {c} | {_yn(ok)} |" for (a, c), ok in tg.items()]
    for note in p.notes:
        lines.append(f"- Remarque : {note}")

    lines += ["", "## Colonne humide par niveau", ""]
    if sk.wet is None:
        lines.append("Pas de colonne humide.")
    else:
        x, y, w, h = sk.grid.metres(sk.wet)
        lines += [
            f"Rectangle ({x:.2f} ; {y:.2f}), {w:.2f} x {h:.2f} m, collé au noyau, un bandeau de "
            "gaine de 0,60 m.",
            "",
            "| Niveau | Local | Type | Cible (m²) | Placé (m²) |",
            "|---|---|---|---|---|",
        ]
        for f in sk.floors:
            for wr in f.rooms:
                lines.append(
                    f"| {f.level} | {wr.iid} | {wr.type} | {wr.target_m2:.1f} | {wr.area_m2:.1f} |"
                )
            if f.reserve:
                lines.append(
                    f"| {f.level} | reserve_technique | reserve_technique | | "
                    f"{len(f.reserve) * AREA_CELL_M2:.1f} |"
                )
    lines += [
        "",
        "## Contrôle du squelette (dur)",
        "",
        f"- Noyau et colonne humide sur les mêmes cellules à tous les niveaux : "
        f"{_yn(r.skeleton_ok)}.",
        "- Colonne humide adjacente au noyau et dans le contour du dernier niveau : "
        + ("sans objet (pas de pièce humide)" if not sk.level_of else _yn(sk.wet_adjacent()))
        + ".",
        "",
        "## Diagrammes par niveau",
        "",
        "| Niveau | Pièces | Façade manquante | Hors circulation | Courtes | Réparées | "
        "Fragmentées |",
        "|---|---|---|---|---|---|---|",
    ]
    for fl in r.floors:
        if fl.diagram is None:
            lines.append(f"| {fl.level} | 0 | | | | | |")
            continue
        lines.append(
            f"| {fl.level} | {len(fl.diagram.rooms)} | {len(fl.facade_missing)} | "
            f"{len(fl.off_circulation)} | {len(fl.short)} | {len(fl.repaired)} | "
            f"{len(fl.fragmented)} |"
        )
    lines += [
        "",
        f"## Empilabilité : {r.stackability:.1%}",
        "",
        "Part des cellules de pièces dont la cellule juste au-dessus ou au-dessous est occupée "
        "par une pièce du même type.",
        "",
        "## Manques durs",
        "",
    ]
    lines += [f"- {m}" for m in r.misses] or ["Aucun."]
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------- svg
_PX_M = 8.0
_BAND = 44.0
_GAP = 6.0


def render_svg(r: StackResult) -> str:
    """``stack.svg``: schematic section, one band per floor, core and wet stack through all."""
    b, st, sk = r.building, r.stacking, r.skeleton
    p = st.problem
    gb = b.outline(0).bounds
    width = (gb[2] - gb[0]) * _PX_M
    n = b.n_floors
    legend_h = 18.0 * (1 + len(p.groups) // 4)
    height = n * (_BAND + _GAP) + legend_h + 10
    colours = {g: PALETTE[i % len(PALETTE)] for i, g in enumerate(p.groups)}
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width + 20:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width + 20:.0f} {height:.0f}">',
        f'<rect x="0" y="0" width="{width + 20:.0f}" height="{height:.0f}" fill="#ffffff"/>',
    ]
    mat = st.matrix()
    for k in range(n):
        y = (n - 1 - k) * (_BAND + _GAP) + 4
        ob = b.outline(k).bounds
        x0 = 10 + (ob[0] - gb[0]) * _PX_M
        w = (ob[2] - ob[0]) * _PX_M
        total = sum(mat.get((k, g), 0.0) for g in p.groups)
        cx = x0
        for g in p.groups:
            a = mat.get((k, g), 0.0)
            if a <= 0 or total <= 0:
                continue
            sw = w * a / total
            out.append(
                f'<rect class="group" data-floor="{k}" data-group="{escape(g)}" x="{cx:.1f}" '
                f'y="{y:.1f}" width="{sw:.1f}" height="{_BAND:.0f}" fill="{colours[g]}" '
                'stroke="#ffffff" stroke-width="1"/>'
            )
            cx += sw
        if total <= 0:
            out.append(
                f'<rect x="{x0:.1f}" y="{y:.1f}" width="{w:.1f}" height="{_BAND:.0f}" '
                'fill="#eeeeee"/>'
            )
        out.append(
            f'<text x="{x0 + 4:.1f}" y="{y + 14:.1f}" font-size="11" font-family="sans-serif">'
            f"N{k} · {sum(mat.get((k, g), 0.0) for g in p.groups):.0f} m²</text>"
        )
    cx0 = gb[0]
    for name, rect in (("core", sk.core), ("wet", sk.wet)):
        if rect is None:
            continue
        x, _, w, _ = sk.grid.metres(rect)
        fill = "#444444" if name == "core" else "#2b6cb0"
        out.append(
            f'<rect class="{name}" x="{10 + (x - cx0) * _PX_M:.1f}" y="4" width="{w * _PX_M:.1f}" '
            f'height="{n * (_BAND + _GAP) - _GAP:.1f}" fill="{fill}" '
            'fill-opacity="0.75"/>'
        )
    ly = n * (_BAND + _GAP) + 14
    for i, g in enumerate(p.groups):
        lx = 10 + (i % 4) * (width / 4)
        yy = ly + (i // 4) * 18
        out.append(
            f'<rect x="{lx:.1f}" y="{yy - 10:.1f}" width="10" height="10" fill="{colours[g]}"/>'
        )
        out.append(
            f'<text x="{lx + 14:.1f}" y="{yy:.1f}" font-size="11" font-family="sans-serif">'
            f"{escape(g)}</text>"
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- outputs
def write_outputs(r: StackResult, out: Path) -> list[Path]:
    """Write ``stacking.md``, ``stack.svg`` and ``floor_NN/{site.yaml,programme.xlsx,
    diagram.svg}`` under ``out``; returns the files written."""
    out.mkdir(parents=True, exist_ok=True)
    files = []
    md = out / "stacking.md"
    md.write_text(render_markdown(r), encoding="utf-8", newline="\n")
    files.append(md)
    svg = out / "stack.svg"
    svg.write_text(render_svg(r), encoding="utf-8", newline="\n")
    files.append(svg)
    for f in r.floors:
        d = out / f"floor_{f.level:02d}"
        d.mkdir(exist_ok=True)
        site = d / "site.yaml"
        site.write_text(dump_yaml(f.site), encoding="utf-8", newline="\n")
        files.append(site)
        if f.program_all is not None:
            files.append(write_programme_xlsx(f.program_all, d / "programme.xlsx"))
        if f.diagram is not None:
            files.append(write_diagram_svg(f.diagram, d / "diagram.svg"))
    return files
