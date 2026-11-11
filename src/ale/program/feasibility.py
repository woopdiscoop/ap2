"""Feasibility pre-check: does the program fit the module footprint? (RD 3.1 section 6).

All arithmetic is exact (``Fraction`` over mm² / mm); results are rounded once to float
(m², metres) in the report.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from fractions import Fraction

from ale.contracts.area_rule import AreaTolerance, area_bounds_mm2, best_buildable_rect
from ale.contracts.config import AleConfig
from ale.contracts.corridor_plan import MAX_BANDS
from ale.contracts.footprint import Piece, decompose_footprint
from ale.contracts.geometry import ModulePoint, ModulePolygon
from ale.contracts.models import GridSpec, Program, RoomSpec, Rulebook
from ale.contracts.units import Rounding, m_to_modules, to_decimal
from ale.program.excel import COL_AREA
from ale.program.models import FeasibilityReport, Issue, ModuleFootprint, RoomFit, make_issue
from ale.program.site import module_perimeter_mm

__all__ = [
    "band_estimate",
    "check_feasibility",
    "facade_usable_mm",
    "narrowest_width",
    "room_fit",
    "rulebook_coverage",
]

_MM2_PER_M2 = 1_000_000
_MM_PER_M = 1000
_D_T_FACTOR = Fraction(7, 5)


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
    tol = _tolerance(config)
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


def _tolerance(config: AleConfig) -> AreaTolerance:
    area = config.area
    return AreaTolerance(
        down_pct=area.tol_down_pct, up_pct=area.tol_up_pct, up_abs_m2=area.tol_up_abs_m2
    )


def _modules_ceil(length_m: float, module_mm: int) -> int:
    return math.ceil(_exact(length_m) * _MM_PER_M / module_mm)


def narrowest_width(spec: RoomSpec, grid: GridSpec, config: AleConfig) -> int | None:
    """Narrowest compliant short side (modules) of a room, or ``None`` if none exists.

    Smallest ``w ≥ ceil(min_width_m / module)`` (1 if absent) such that some ``l`` with
    ``w ≤ l ≤ shape.aspect_max · w`` gives an area ``w·l`` within the area tolerance.
    """
    module = grid.module_mm
    cell = module * module
    lo_mm2, hi_mm2 = area_bounds_mm2(spec.target_area_m2, _tolerance(config))
    lo = -(-lo_mm2 // cell)
    hi = hi_mm2 // cell
    a_max = Fraction(str(config.shape.aspect_max))
    w = 1 if spec.min_width_m is None else max(1, _modules_ceil(spec.min_width_m, module))
    while w * w <= hi:
        l_min = max(w, -(-lo // w))
        l_max = min(math.floor(a_max * w), hi // w)
        if l_min <= l_max:
            return w
        w += 1
    return None


def _ceil_sqrt(x: Fraction) -> int:
    d = math.isqrt(math.floor(x))
    while d * d < x:
        d += 1
    return d


def band_estimate(depth: int, targets: list[Fraction], s: int) -> int:
    """Band count estimate ``n0`` of RD 3.2: ``max(1, round((P - s) / (2·D_t + s)))``.

    ``P`` = piece depth across the spine and ``s`` = spine width (modules); ``D_t =
    ceil(sqrt(1.4 x median target))`` with targets in cells (one per instance); ``round``
    is half-to-even; capped at ``MAX_BANDS`` as in 3.2.
    """
    if not targets:
        return 1
    ordered = sorted(targets)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    d_t = _ceil_sqrt(median * _D_T_FACTOR)
    return max(1, min(MAX_BANDS, round(Fraction(depth - s, 2 * d_t + s))))


Segment = tuple[ModulePoint, ModulePoint]


def _overlap(seg: Segment, cut: Segment | None) -> int:
    """Length (modules) shared by an axis-aligned segment and the cut segment."""
    if cut is None:
        return 0
    (ax, ay), (bx, by) = seg
    (cx0, cy0), (cx1, cy1) = cut
    if ay == by == cy0 == cy1:  # horizontal, same line
        lo, hi = max(min(ax, bx), min(cx0, cx1)), min(max(ax, bx), max(cx0, cx1))
    elif ax == bx == cx0 == cx1:  # vertical, same line
        lo, hi = max(min(ay, by), min(cy0, cy1)), min(max(ay, by), max(cy0, cy1))
    else:
        return 0
    return max(0, hi - lo)


def _piece_edges(piece: Piece) -> tuple[list[Segment], list[Segment]]:
    """``(long, short)``: the piece edges parallel / perpendicular to its spine axis."""
    r = piece.rect
    x0, y0, x1, y1 = r.x, r.y, r.x2(), r.y2()
    horizontal: list[Segment] = [((x0, y0), (x1, y0)), ((x0, y1), (x1, y1))]
    vertical: list[Segment] = [((x0, y0), (x0, y1)), ((x1, y0), (x1, y1))]
    return (horizontal, vertical) if piece.spine_axis == "X" else (vertical, horizontal)


def facade_usable_mm(
    polygon: ModulePolygon, targets: list[Fraction], s: int, module_mm: int
) -> int:
    """Grammar-aware usable façade length (mm) of a module footprint (Q.2a).

    Pieces from :func:`decompose_footprint`. Σ over pieces of the length of the edges
    parallel to the spine axis minus their part on any junction cut (X.3: all the junctions
    of the piece tree; a courtyard face is a façade), minus ``s x n0`` for each
    exterior short edge of the piece (a short edge touching the cut is not exterior);
    ``n0`` = :func:`band_estimate` of the piece. Floored at 0.
    """
    fp = decompose_footprint(polygon)
    cuts: list[Segment] = [j.cut for j in fp.junctions]
    total = 0
    for piece in fp.pieces:
        long_edges, short_edges = _piece_edges(piece)
        for (ax, ay), (bx, by) in long_edges:
            total += (
                abs(bx - ax) + abs(by - ay) - sum(_overlap(((ax, ay), (bx, by)), c) for c in cuts)
            )
        depth = piece.rect.h if piece.spine_axis == "X" else piece.rect.w
        n0 = band_estimate(depth, targets, s)
        ends = sum(1 for seg in short_edges if all(_overlap(seg, c) == 0 for c in cuts))
        total -= s * n0 * ends
    return max(0, total) * module_mm


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
    min_facade = _exact(config.facade.min_facade_len_m)
    facade_demand = Fraction(0)  # m
    targets: list[Fraction] = []  # cells, one per instance
    for spec in program.rooms:
        target = _exact(spec.target_area_m2)
        net += target * spec.quantity
        targets.extend([target * _MM2_PER_M2 / cell_mm2] * spec.quantity)
        if spec.needs_facade:
            facade_count += spec.quantity
            w = narrowest_width(spec, grid, config)
            w_est = Fraction(0) if w is None else Fraction(w * module, _MM_PER_M)
            facade_demand += max(min_facade, w_est) * spec.quantity
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
    s = _modules_ceil(config.circulation.min_width_m, module)
    try:
        usable = Fraction(facade_usable_mm(footprint.polygon, targets, s, module), _MM_PER_M)
    except ValueError:  # footprint outside the v1 grammar (neither rectangle nor L)
        usable = perimeter  # no grammar estimate: fall back to the raw perimeter
    if facade_demand > usable:
        issues.append(
            make_issue(
                "W_FACADE_TIGHT",
                f"Façade tendue : {float(facade_demand)} m de façade demandés pour "
                f"{facade_count} pièces en façade, {float(usable)} m utilisables "
                "le long des épines.",
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
        facade_usable_m=float(usable),
        per_room=per_room,
        issues=tuple(issues),
    )
