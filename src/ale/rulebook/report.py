"""French Markdown report of a rulebook build (Ticket 2.2 RD section 5).

Summary (plans used / skipped with reasons, source mix, parameters), then one table per
statistic with its value, support and source (seed / mined / blended).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ale.contracts.config import AleConfig
from ale.contracts.enums import Fidelity
from ale.contracts.models import Quantiles, Rulebook
from ale.rulebook.blend import Blended
from ale.rulebook.stats import BEARINGS

__all__ = ["ReportInputs", "render_report"]

_SOURCE_FR = {"seed": "graine", "mined": "miné", "blended": "mélangé"}


@dataclass(frozen=True)
class ReportInputs:
    rulebook: Rulebook
    blended: Blended
    config: AleConfig
    min_support: int
    seed_version: str | None
    #: UTC build date (YYYY-MM-DD), the only date of the outputs.
    build_date: str
    #: (plan label, fidelity, weight, north or None), sorted.
    used: Sequence[tuple[str, Fidelity, float, float | None]]
    #: (plan label, reason), sorted.
    skipped: Sequence[tuple[str, str]]


def _n(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x:.6g}"


def _q(q: Quantiles | None) -> str:
    if q is None:
        return "—"
    return f"{_n(q.p10)} / {_n(q.p50)} / {_n(q.p90)}"


def render_report(inp: ReportInputs) -> str:
    """Report text (deterministic for identical inputs)."""
    rb, bl, cfg = inp.rulebook, inp.blended, inp.config
    out: list[str] = [f"# Rapport de construction du rulebook `{rb.version}`", ""]
    out += ["## Résumé", ""]
    out.append(f"- Date de construction (UTC) : {inp.build_date}")
    out.append(
        f"- Nature : **{rb.kind}**"
        + (f" (graine `{inp.seed_version}`)" if inp.seed_version else "")
    )
    out.append(f"- Plans utilisés : {len(inp.used)}")
    out.append(f"- Plans ignorés : {len(inp.skipped)}")
    out.append(
        f"- Paramètres : laplace_alpha = {_n(cfg.rulebook.laplace_alpha)}, "
        f"blend_k = {_n(cfg.rulebook.blend_k)}, min_support = {inp.min_support}, "
        f"shape.aspect_max = {_n(cfg.shape.aspect_max)}"
    )
    out += ["", "### Répartition des sources", "", "| Fidélité | Plans | Poids |", "|---|---|---|"]
    weights = cfg.rulebook.fidelity_weights
    for fid in Fidelity:
        out.append(
            f"| {fid.value} | {rb.source_mix.get(fid, 0)} | {_n(getattr(weights, fid.value))} |"
        )
    out += ["", "### Plans utilisés", ""]
    if inp.used:
        out += ["| Plan | Fidélité | Poids | Nord (°) |", "|---|---|---|---|"]
        out += [
            f"| `{lbl}` | {fid.value} | {_n(w)} | {_n(north)} |" for lbl, fid, w, north in inp.used
        ]
    else:
        out.append("Aucun.")
    out += ["", "### Plans ignorés", ""]
    if inp.skipped:
        out += ["| Plan | Raison |", "|---|---|"]
        out += [f"| `{lbl}` | {reason} |" for lbl, reason in inp.skipped]
    else:
        out.append("Aucun.")

    out += ["", "## Adjacences", "", f"Probabilité par défaut : {_n(rb.adjacency.default_p)}", ""]
    if bl.pairs:
        out += [
            "| Paire | p | n_support | support pondéré | contacts pondérés "
            "| p graine | p miné | source |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in bl.pairs:
            out.append(
                f"| {r.a} / {r.b} | {_n(r.p)} | {r.n_support} | {_n(r.support)} | {_n(r.hits)} "
                f"| {_n(r.p_seed)} | {_n(r.p_mined)} | {_SOURCE_FR[r.source]} |"
            )
    else:
        out.append("Aucune paire.")

    for stat, title in (("aspect", "Élancement (long / court)"), ("area_m2", "Surface (m²)")):
        out += ["", f"## {title}", ""]
        rows = [q for q in bl.quantiles if q.stat == stat]
        if not rows:
            out.append("Aucun type.")
            continue
        out += [
            "| Type | p10 / p50 / p90 | n | miné | graine | source |",
            "|---|---|---|---|---|---|",
        ]
        for qr in rows:
            mark = " (écrêté)" if qr.clipped else ""
            n = qr.mined.n if qr.mined is not None else qr.value.n
            out.append(
                f"| {qr.type} | {_q(qr.value)} | {n} | {_q(qr.mined)}{mark} | {_q(qr.seed)} "
                f"| {_SOURCE_FR[qr.source]} |"
            )

    out += ["", "## Orientation", ""]
    if bl.orientation:
        out += [
            "| Type | N | E | S | W | plans orientés | source |",
            "|---|---|---|---|---|---|---|",
        ]
        for o in bl.orientation:
            vals = " | ".join(_n(o.values[b]) for b in BEARINGS)
            note = f" ({o.note})" if o.note else ""
            out.append(f"| {o.type} | {vals} | {o.n_plans} | {_SOURCE_FR[o.source]}{note} |")
    else:
        out.append("Aucun type.")

    out += ["", "## Profondeur et largeur de façade", ""]
    if bl.facade:
        out += [
            "| Type | profondeur p50 / p90 (m) | largeur p50 / p90 (m) | façade (m/m²) "
            "| n pièces | source |",
            "|---|---|---|---|---|---|",
        ]
        for f in bl.facade:
            if f.insufficient or f.depth is None or f.width is None:
                out.append(f"| {f.type} | échantillon insuffisant | — | — | {f.n} | — |")
                continue
            out.append(
                f"| {f.type} | {_n(f.depth.p50)} / {_n(f.depth.p90)} "
                f"| {_n(f.width.p50)} / {_n(f.width.p90)} | {_n(f.m_per_m2)} "
                f"| {f.n} | {_SOURCE_FR[f.source]} |"
            )
    else:
        out.append("Aucun type.")

    out += ["", "## Décalage du noyau", ""]
    out += ["| dx_norm | dy_norm | plans | miné (dx / dy) | source |", "|---|---|---|---|---|"]
    core = bl.core
    if core is not None:
        m = core.mined
        mined = "—" if m is None else f"{_n(m.dx_norm)} / {_n(m.dy_norm)}"
        out.append(
            f"| {_n(core.value.dx_norm)} | {_n(core.value.dy_norm)} | {core.value.n} | {mined} "
            f"| {_SOURCE_FR[core.source]} |"
        )

    out += ["", "## Notes", ""]
    out += [f"- {n}" for n in bl.notes] if bl.notes else ["Aucune."]
    return "\n".join(out) + "\n"
