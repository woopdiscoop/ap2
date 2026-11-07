"""Feasibility pre-check: does the program fit the module footprint? (RD 3.1 section 6).

All arithmetic is exact (``Fraction`` over mm² / mm); results are rounded once to float
(m², metres) in the report.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from fractions import Fraction

from ale.contracts.area_rule import AreaTolerance, best_buildable_rect
from ale.contracts.config import AleConfig
from ale.contracts.models import GridSpec, Program, RoomSpec, Rulebook
from ale.contracts.units import Rounding, m_to_modules, to_decimal
from ale.program.excel import COL_AREA
from ale.program.models import FeasibilityReport, Issue, ModuleFootprint, RoomFit, make_issue
from ale.program.site import module_perimeter_mm

__all__ = ["check_feasibility", "room_fit", "rulebook_coverage"]

_MM2_PER_M2 = 1_000_000
_MM_PER_M = 1000


def _exact(x: float) -> Fraction:
    return Fraction(to_decimal(x))


def _fmt2(x: Fraction) -> str:
    """Format a non-negative m² value with 2 decimals (half-even rounding)."""
    cents = round(x * 100)
    return f"{cents // 100}.{cents % 100:02d}"


def rulebook_coverage(types: Iterable[str], rulebook: Rulebook) -> list[Issue]:
    """One ``E_TYPE_NOT_IN_RULEBOOK`` per program type absent from ``rulebook.types``."""
    return [
        make_issue(
            "E_TYPE_NOT_IN_RULEBOOK",
            f"Le type « {key} » du programme est absent du rulebook.",
            value=key,
        )
        for key in rulebook.missing_types(types)
    ]


def room_fit(
    spec: RoomSpec, grid: GridSpec, rulebook: Rulebook, config: AleConfig
) -> tuple[int, int] | None:
    """Best buildable ``(short, long)`` rectangle (modules) for a program row, or ``None``.

    Band = rulebook aspect [p10, p90] ∩ [1.0, ``shape.aspect_max``]; if no rectangle fits,
    retry with [1.0, ``shape.aspect_max``]. ``min_width_m`` gives the minimum short side.
    """
    area = config.area
    tol = AreaTolerance(
        down_pct=area.tol_down_pct, up_pct=area.tol_up_pct, up_abs_m2=area.tol_up_abs_m2
    )
    aspect_max = config.shape.aspect_max
    min_short = 1
    if spec.min_width_m is not None:
        min_short = max(1, m_to_modules(spec.min_width_m, grid.module_mm, Rounding.CEIL))
    stats = rulebook.types.get(spec.type)
    if stats is not None:
        lo = max(stats.aspect.p10, 1.0)
        hi = min(stats.aspect.p90, aspect_max)
        if lo <= hi:
            rect = best_buildable_rect(
                spec.target_area_m2, grid, lo, hi, tol, min_short_side_modules=min_short
            )
            if rect is not None:
                return rect
    return best_buildable_rect(
        spec.target_area_m2, grid, 1.0, aspect_max, tol, min_short_side_modules=min_short
    )


def check_feasibility(
    program: Program,
    footprint: ModuleFootprint,
    rulebook: Rulebook,
    config: AleConfig,
    rows: Mapping[str, int] | None = None,
) -> FeasibilityReport:
    """Run the feasibility pre-check; ``rows`` maps room ids to Excel rows (for issues)."""
    rows = rows or {}
    grid = GridSpec(module_mm=config.grid.module_mm)
    module = grid.module_mm
    cell_mm2 = module * module
    issues = rulebook_coverage({r.type for r in program.rooms}, rulebook)

    per_room: dict[str, RoomFit] = {}
    net = Fraction(0)  # m²
    overshoot = Fraction(0)  # m²
    facade_count = 0
    for spec in program.rooms:
        target = _exact(spec.target_area_m2)
        net += target * spec.quantity
        if spec.needs_facade:
            facade_count += spec.quantity
        rect = room_fit(spec, grid, rulebook, config)
        if rect is None:
            issues.append(
                make_issue(
                    "E_ROOM_INFEASIBLE",
                    f"Aucun rectangle constructible pour « {spec.id} » ({spec.target_area_m2} m²"
                    + (
                        f", largeur min {spec.min_width_m} m"
                        if spec.min_width_m is not None
                        else ""
                    )
                    + ") dans les tolérances de surface et d'élancement.",
                    row=rows.get(spec.id),
                    column=COL_AREA,
                    value=spec.target_area_m2,
                )
            )
            continue
        short, long_ = rect
        over = max(Fraction(0), Fraction(short * long_ * cell_mm2, _MM2_PER_M2) - target)
        overshoot += over * spec.quantity
        per_room[spec.id] = RoomFit(short=short, long=long_, overshoot_m2=float(over))

    ratio = _exact(config.circulation.ratio)
    circulation = net * ratio
    required = net + circulation + overshoot
    footprint_m2 = Fraction(footprint.polygon.area_cells() * cell_mm2, _MM2_PER_M2)
    available = footprint_m2 * _exact(config.site.max_fill)
    if required > available:
        missing = Fraction(math.ceil((required - available) * 100), 100)
        issues.append(
            make_issue(
                "E_NOT_FEASIBLE",
                f"Programme trop grand : il manque {_fmt2(missing)} m² "
                f"(requis {_fmt2(required)} m², disponible {_fmt2(available)} m²).",
            )
        )
    facade_required = _exact(config.facade.min_facade_len_m) * facade_count
    perimeter = Fraction(module_perimeter_mm(footprint.polygon, grid), _MM_PER_M)
    if facade_required > perimeter:
        issues.append(
            make_issue(
                "E_FACADE_INSUFFICIENT",
                f"Façade insuffisante : {float(facade_required)} m requis pour "
                f"{facade_count} pièces en façade, périmètre de l'emprise {float(perimeter)} m.",
            )
        )
    return FeasibilityReport(
        net_m2=float(net),
        circulation_m2=float(circulation),
        overshoot_m2=float(overshoot),
        required_m2=float(required),
        available_m2=float(available),
        footprint_m2=float(footprint_m2),
        fill_ratio=float(required / footprint_m2),
        facade_required_m=float(facade_required),
        perimeter_m=float(perimeter),
        per_room=per_room,
        issues=tuple(issues),
    )
