"""``report.md`` (French) and the helpers shared by the export writers.

Shared helpers: French number formatting (``,`` decimal separator, 2 decimals), the
module → metre coordinate frame (exact via ``Decimal``, ≤ 4 decimals) and per-room
descriptions (label name, type, zone, areas, facade contact).

Ticket Q.4: with ``facade.max_depth_m`` set, the summary states the depth limit, and the rooms
whose aspect above ``shape.aspect_max`` is imposed by that limit (``ASPECT_DEPTH``, soft) are
listed in a section "Proportion > amax imposée par la règle de profondeur" (only when there is
one).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction

from ale.contracts.config import AleConfig
from ale.contracts.enums import MacroZone
from ale.contracts.geometry import ModulePolygon, ModuleRect, Point2
from ale.contracts.models import Layout, PlacedRoom, RoomSpec, Violation
from ale.contracts.taxonomy import load_taxonomy
from ale.contracts.units import cells_to_m2, to_decimal
from ale.contracts.version import CONTRACTS_VERSION
from ale.program.models import PreparedInput

__all__ = [
    "DXF_NAME",
    "JSON_NAME",
    "REPORT_NAME",
    "SVG_NAME",
    "ZONE_FR",
    "MetricFrame",
    "RoomInfo",
    "area_label",
    "fr_num",
    "fr_pct1",
    "fr_signed",
    "render_report",
    "room_infos",
    "touches_facade",
]

JSON_NAME = "layout.json"
DXF_NAME = "layout.dxf"
SVG_NAME = "preview.svg"
REPORT_NAME = "report.md"

ZONE_FR: dict[MacroZone, str] = {
    MacroZone.PUBLIC: "Public",
    MacroZone.ADMINISTRATIVE: "Administratif",
    MacroZone.SERVICES: "Services",
}

_TIMES = "\u00d7"  # multiplication sign of "L x l"
_CENT = Decimal("0.01")
_TENTH = Decimal("0.1")
_TEN_THOUSANDTH = Decimal("0.0001")
_DEPTH_ASPECT_CODE = "ASPECT_DEPTH"
"""Q.4: soft aspect violation imposed by the depth rule (``ale.geometry.evaluate``)."""


# --------------------------------------------------------------------------- numbers


def _quantize(x: float | int | Decimal, q: Decimal) -> Decimal:
    d = to_decimal(x).quantize(q, rounding=ROUND_HALF_EVEN)
    return d if d != 0 else abs(d)  # no "-0,00"


def fr_num(x: float | int | Decimal) -> str:
    """``x`` with 2 decimals and ``,`` as decimal separator (half-even rounding)."""
    return f"{_quantize(x, _CENT):f}".replace(".", ",")


def fr_pct1(x: float | int | Decimal) -> str:
    """``x`` with 1 decimal and ``,`` as decimal separator (percentages)."""
    return f"{_quantize(x, _TENTH):f}".replace(".", ",")


def fr_signed(x: float | int | Decimal) -> str:
    """Like :func:`fr_num` with an explicit sign (``+0,00``, ``-1,25``)."""
    d = _quantize(x, _CENT)
    sign = "-" if d < 0 else "+"
    return sign + f"{abs(d):f}".replace(".", ",")


# --------------------------------------------------------------------------- coordinates


class MetricFrame:
    """Modules → metres in the site drawing axes: ``n * module_mm / 1000 + origin``.

    Computed exactly with ``Decimal`` and rounded once (half-even) to 4 decimals.
    """

    def __init__(self, module_mm: int, origin_m: Point2) -> None:
        self._module = module_mm
        self._ox = to_decimal(origin_m[0])
        self._oy = to_decimal(origin_m[1])

    def _conv(self, n: int, origin: Decimal) -> float:
        value = Decimal(n * self._module) / 1000 + origin
        return float(_quantize(value, _TEN_THOUSANDTH)) + 0.0

    def x(self, n: int) -> float:
        """x coordinate (metres) of module abscissa ``n``."""
        return self._conv(n, self._ox)

    def y(self, n: int) -> float:
        """y coordinate (metres) of module ordinate ``n``."""
        return self._conv(n, self._oy)

    def point(self, p: tuple[int, int]) -> tuple[float, float]:
        """A module point in metres."""
        return (self.x(p[0]), self.y(p[1]))

    def rect_ccw(self, r: ModuleRect) -> list[tuple[float, float]]:
        """The 4 corners of a module rectangle in metres, counter-clockwise from lower-left."""
        x0, x1, y0, y1 = self.x(r.x), self.x(r.x2()), self.y(r.y), self.y(r.y2())
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    def rect_centre(self, r: ModuleRect) -> tuple[float, float]:
        """Centre of a module rectangle in metres (exact, ≤ 4 decimals)."""
        cx = Decimal(2 * r.x + r.w) * self._module / 2000 + self._ox
        cy = Decimal(2 * r.y + r.h) * self._module / 2000 + self._oy
        return (
            float(_quantize(cx, _TEN_THOUSANDTH)) + 0.0,
            float(_quantize(cy, _TEN_THOUSANDTH)) + 0.0,
        )

    def bbox(self, poly: ModulePolygon) -> tuple[float, float, float, float]:
        """Bounding box ``(x0, y0, x1, y1)`` of a module polygon, in metres."""
        xs = [p[0] for p in poly.exterior]
        ys = [p[1] for p in poly.exterior]
        return (self.x(min(xs)), self.y(min(ys)), self.x(max(xs)), self.y(max(ys)))


# --------------------------------------------------------------------------- rooms


def touches_facade(rect: ModuleRect, poly: ModulePolygon) -> bool:
    """``True`` when a side of ``rect`` lies on a footprint edge over a positive length."""
    for (ax, ay), (bx, by) in poly.edges():
        if ay == by:  # horizontal edge
            lo, hi = min(ax, bx), max(ax, bx)
            if ay in (rect.y, rect.y2()) and min(hi, rect.x2()) - max(lo, rect.x) > 0:
                return True
        else:
            lo, hi = min(ay, by), max(ay, by)
            if ax in (rect.x, rect.x2()) and min(hi, rect.y2()) - max(lo, rect.y) > 0:
                return True
    return False


@dataclass(frozen=True)
class RoomInfo:
    """Description of one placed room (areas in m², dimensions in metres)."""

    instance_id: str
    name: str
    type_label: str
    zone: MacroZone | None
    target_m2: float | None
    placed_m2: float
    delta_m2: float | None
    long_m: float
    short_m: float
    facade: bool
    rect: ModuleRect


def _label_name(placed: PlacedRoom, spec: RoomSpec | None) -> str:
    if spec is None:
        return placed.instance_id
    if spec.quantity > 1 and "#" in placed.instance_id:
        return f"{spec.name} #{placed.instance_id.split('#', 1)[1]}"
    return spec.name


def room_infos(layout: Layout, prepared: PreparedInput) -> tuple[RoomInfo, ...]:
    """One :class:`RoomInfo` per ``layout.rooms`` entry, in instance-id order."""
    specs = {r.id: r for r in prepared.program.rooms}
    tax = load_taxonomy()
    grid = layout.grid
    out: list[RoomInfo] = []
    for p in sorted(layout.rooms, key=lambda r: r.instance_id):
        spec = specs.get(p.spec_id) if p.spec_id is not None else None
        target = p.target_area_m2
        if target is None and spec is not None:
            target = spec.target_area_m2
        placed_cells = p.rect.area_cells() * grid.module_mm**2
        delta = None
        if target is not None:
            delta = float(Fraction(placed_cells, 1_000_000) - Fraction(to_decimal(target)))
        long_mod, short_mod = max(p.rect.w, p.rect.h), min(p.rect.w, p.rect.h)
        out.append(
            RoomInfo(
                instance_id=p.instance_id,
                name=_label_name(p, spec),
                type_label=tax.get(spec.type).label_fr if spec is not None else "—",
                zone=spec.macro_zone if spec is not None else None,
                target_m2=target,
                placed_m2=p.area_m2(grid),
                delta_m2=delta,
                long_m=float(Decimal(long_mod * grid.module_mm) / 1000),
                short_m=float(Decimal(short_mod * grid.module_mm) / 1000),
                facade=touches_facade(p.rect, layout.footprint),
                rect=p.rect,
            )
        )
    return tuple(out)


def area_label(info: RoomInfo) -> str:
    """``12,00 m² (Δ +0,00)`` (the ``Δ`` part only when there is a target)."""
    text = f"{fr_num(info.placed_m2)} m²"
    if info.delta_m2 is not None:
        text += f" (Δ {fr_signed(info.delta_m2)})"
    return text


# --------------------------------------------------------------------------- report


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


def _depth_aspect_section(
    infos: tuple[RoomInfo, ...], violations: tuple[Violation, ...], config: AleConfig
) -> list[str]:
    """Q.4: rooms whose aspect above ``aspect_max`` is imposed by the depth rule."""
    ids = sorted(
        {iid for v in violations if v.code == _DEPTH_ASPECT_CODE for iid in v.instance_ids}
    )
    if not ids:
        return []
    amax = f"{config.shape.aspect_max:g}".replace(".", ",")
    by_id = {i.instance_id: i for i in infos}
    lines = [
        "",
        f"## Proportion > {amax} imposée par la règle de profondeur",
        "",
        f"Ces pièces ne peuvent respecter à la fois la profondeur maximale depuis la façade "
        f"et la proportion ≤ {amax} : la profondeur prime, la proportion est signalée "
        "mais n'est pas comptée comme contrainte dure.",
        "",
    ]
    for iid in ids:
        info = by_id.get(iid)
        if info is None:
            lines.append(f"- `{iid}`")
            continue
        aspect = to_decimal(info.long_m) / to_decimal(info.short_m)
        lines.append(
            f"- `{iid}` {info.name} : {fr_num(info.long_m)} {_TIMES} {fr_num(info.short_m)} m, "
            f"proportion {fr_num(aspect)}"
        )
    return lines


def render_report(
    layout: Layout,
    prepared: PreparedInput,
    *,
    rulebook_version: str,
    run_id: str,
    config: AleConfig,
    dxf_note: str | None,
) -> str:
    """Markdown text of ``report.md`` (``dxf_note`` = reason the DXF was skipped, or None)."""
    grid = layout.grid
    infos = room_infos(layout, prepared)
    footprint_m2 = cells_to_m2(layout.footprint.area_cells(), grid.module_mm)
    net_m2 = sum((to_decimal(spec.target_area_m2) for _, spec in prepared.instances), Decimal(0))
    placed_m2 = sum((to_decimal(i.placed_m2) for i in infos), Decimal(0))
    circ_cells = sum(c.rect.area_cells() for c in layout.circulation)
    circ_m2 = cells_to_m2(circ_cells, grid.module_mm)
    # Engine definition: circulation / sum of net targets (budget = circulation.ratio x net).
    circ_pct = to_decimal(circ_m2) * 100 / net_m2 if net_m2 else Decimal(0)
    budget_pct = to_decimal(config.circulation.ratio) * 100
    module_m = Decimal(grid.module_mm) / 1000
    m = layout.metrics

    lines: list[str] = [f"# Rapport de génération — {run_id}", "", "## Résumé", ""]
    lines += [
        f"- Graine : {layout.seed}",
        f"- Version du rulebook : {rulebook_version}",
        f"- Version des contrats : {CONTRACTS_VERSION}",
        f"- Module : {fr_num(module_m)} m ({grid.module_mm} mm)",
        f"- Surface de l'emprise : {fr_num(footprint_m2)} m²",
        f"- Σ surfaces nettes (programme) : {fr_num(net_m2)} m²",
        f"- Σ surfaces placées : {fr_num(placed_m2)} m²",
        f"- Circulation : {fr_num(circ_m2)} m² ({fr_pct1(circ_pct)} % du net ; "
        f"budget {fr_pct1(budget_pct)} %)",
        f"- Dépassement total : {fr_num(m.total_overshoot_m2)} m²",
        f"- Coût total : {fr_num(m.total_cost)}",
    ]
    if config.facade.max_depth_m is not None:
        lines.append(
            f"- Profondeur max. depuis la façade : {fr_num(config.facade.max_depth_m)} m "
            "(double pour une pièce traversante)"
        )
    lines += [
        "",
        "## Surfaces",
        "",
    ]
    lines.append(
        _row(
            [
                "ID",
                "Nom",
                "Type",
                "Zone",
                "Cible m²",
                "Placée m²",
                "Δ m²",
                "Δ %",
                f"Dimensions L {_TIMES} l m",
                "Façade",
                "Statut",
            ]
        )
    )
    lines.append("|" + "---|" * 11)
    codes_by_id: dict[str, set[str]] = {}
    for v in m.violations:
        for iid in v.instance_ids:
            codes_by_id.setdefault(iid, set()).add(v.code)
    for i in infos:
        pct = "—"
        if i.delta_m2 is not None and i.target_m2:
            pct = fr_signed(to_decimal(i.delta_m2) * 100 / to_decimal(i.target_m2))
        codes = sorted(codes_by_id.get(i.instance_id, ()))
        lines.append(
            _row(
                [
                    i.instance_id,
                    i.name,
                    i.type_label,
                    ZONE_FR[i.zone] if i.zone is not None else "—",
                    fr_num(i.target_m2) if i.target_m2 is not None else "—",
                    fr_num(i.placed_m2),
                    fr_signed(i.delta_m2) if i.delta_m2 is not None else "—",
                    pct,
                    f"{fr_num(i.long_m)} {_TIMES} {fr_num(i.short_m)}",
                    "oui" if i.facade else "non",
                    ", ".join(codes) if codes else "OK",
                ]
            )
        )

    lines += ["", "## Contraintes non respectées", ""]
    if not m.violations:
        lines.append("Aucune.")
    else:
        by_code: dict[str, list[str]] = {}
        for v in m.violations:
            ids = ", ".join(f"`{iid}`" for iid in v.instance_ids) or "(global)"
            by_code.setdefault(v.code, []).append(f"- {ids} : {v.detail}")
        for code in sorted(by_code):
            entries = by_code[code]
            lines += [f"### {code} ({len(entries)})", "", *entries, ""]
        lines.pop()

    lines += _depth_aspect_section(infos, m.violations, config)

    lines += ["", "## Coût", ""]
    lines.append(_row(["Terme", "Valeur", "Poids", "Valeur pondérée"]))
    lines.append("|---|---|---|---|")
    weights: Mapping[str, float] = config.optimizer.weights.model_dump()
    for term in sorted(m.cost_breakdown):
        value = m.cost_breakdown[term]
        w = weights.get(term)
        if w is None:
            lines.append(_row([term, fr_num(value), "—", "—"]))
        else:
            weighted = to_decimal(w) * to_decimal(value)
            lines.append(_row([term, fr_num(value), fr_num(w), fr_num(weighted)]))
    lines.append(_row(["**Total**", "", "", fr_num(m.total_cost)]))

    lines += ["", "## Fichiers", ""]
    lines.append(f"- `{JSON_NAME}` : plan généré (sérialisation canonique du contrat)")
    if dxf_note is None:
        lines.append(f"- `{DXF_NAME}` : plan DAO en calques (DXF R2018, mètres)")
    else:
        lines.append(f"- `{DXF_NAME}` : DXF non généré ({dxf_note})")
    lines.append(f"- `{SVG_NAME}` : aperçu (SVG)")
    lines.append(f"- `{REPORT_NAME}` : ce rapport")
    return "\n".join(lines) + "\n"
