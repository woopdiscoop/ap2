"""Layout evaluation: cost terms and violations (RD 3.3 section 6).

``cost_breakdown`` keys are the ``[optimizer.weights]`` names; ``total_cost`` is the sum of
weight x term. Areas are computed exactly (``Fraction``) and rounded once to ``float``.
"""

from __future__ import annotations

import math
from fractions import Fraction

from ale.contracts.config import AleConfig
from ale.contracts.corridor_plan import CorridorPlan
from ale.contracts.models import Layout, LayoutMetrics, PlacedRoom, RoomSpec, Rulebook, Violation
from ale.contracts.orientation import bearing_bin, compass_bearing_deg
from ale.contracts.taxonomy import load_taxonomy
from ale.contracts.units import to_decimal
from ale.geometry.blocks import Consts, aspect_ok
from ale.geometry.checks import exterior_contacts, share_length
from ale.program.models import PreparedInput

__all__ = ["WEIGHT_NAMES", "core_target", "evaluate"]

WEIGHT_NAMES: tuple[str, ...] = (
    "required_adjacency",
    "rulebook_adjacency",
    "aspect",
    "area_overshoot",
    "facade_orientation",
    "core_distance",
    "circulation_length",
)
_MM2_PER_M2 = 1_000_000


def _m2(cells: int, module_mm: int) -> Fraction:
    return Fraction(cells * module_mm * module_mm, _MM2_PER_M2)


def _exact(x: float) -> Fraction:
    return Fraction(to_decimal(x))


def core_target(layout: Layout, prepared: PreparedInput, rulebook: Rulebook) -> tuple[float, float]:
    """Core target in modules: ``site.core_hint`` if set, else bbox centre + rulebook offset."""
    xs = [p[0] for p in layout.footprint.exterior]
    ys = [p[1] for p in layout.footprint.exterior]
    hint = prepared.site.core_hint
    if hint is not None:
        m = layout.grid.module_mm
        ox, oy = prepared.footprint.origin_m
        return (
            float((_exact(hint[0]) - _exact(ox)) * 1000 / m),
            float((_exact(hint[1]) - _exact(oy)) * 1000 / m),
        )
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    off = rulebook.core_offset
    return (
        min(xs) + width / 2 + off.dx_norm * width,
        min(ys) + height / 2 + off.dy_norm * height,
    )


def _orientation_weight(
    spec: RoomSpec, rulebook: Rulebook, normal: tuple[int, int], north: float
) -> float:
    b = bearing_bin(compass_bearing_deg(normal[0], normal[1], north))
    if spec.orientation_override is not None:
        return spec.orientation_override.get(b, 0.0)
    stats = rulebook.types.get(spec.type)
    return 0.0 if stats is None else stats.orientation[b]


class _Eval:
    def __init__(
        self, layout: Layout, prepared: PreparedInput, rulebook: Rulebook, config: AleConfig
    ) -> None:
        self.layout = layout
        self.prepared = prepared
        self.rulebook = rulebook
        self.config = config
        self.k = Consts.from_config(config)
        self.m = layout.grid.module_mm
        specs = dict(prepared.instances)
        self.rooms: list[tuple[PlacedRoom, RoomSpec]] = [
            (p, specs[p.instance_id]) for p in layout.rooms if p.instance_id in specs
        ]
        self.violations: list[Violation] = []

    def flag(self, code: str, ids: tuple[str, ...], detail: str) -> None:
        self.violations.append(Violation(code=code, instance_ids=ids, detail=detail))

    def per_room(self, total: float) -> float:
        return total / len(self.rooms) if self.rooms else 0.0

    # -------------------------------------------------------------- adjacency terms
    def adjacency(self) -> tuple[float, float]:
        c = self.k.c
        rooms = self.rooms
        by_spec: dict[str, list[PlacedRoom]] = {}
        for p, spec in rooms:
            by_spec.setdefault(spec.id, []).append(p)
        required = 0
        for p, spec in rooms:
            for other in spec.adjacent_to:
                partners = by_spec.get(other, [])
                if not any(share_length(p.rect, q.rect) >= c for q in partners):
                    required += 1
                    self.flag(
                        "REQUIRED_ADJ",
                        (p.instance_id,),
                        f"{p.instance_id} shares < {c} modules with every {other}",
                    )
        prior = 0.0
        for i in range(len(rooms)):
            pa, sa = rooms[i]
            for j in range(i + 1, len(rooms)):
                pb, sb = rooms[j]
                if share_length(pa.rect, pb.rect) < 1:
                    continue
                prior += 0.5 - self.rulebook.adjacency.p(sa.type, sb.type)
                if sb.id in sa.avoid or sa.id in sb.avoid:
                    required += 1
                    ids = tuple(sorted((pa.instance_id, pb.instance_id)))
                    self.flag("AVOID_ADJ", ids, f"{ids[0]} touches {ids[1]}")
        return float(required), self.per_room(prior)

    # -------------------------------------------------------------- shape / area
    def aspect(self) -> float:
        amax = float(self.k.amax)
        total = 0.0
        for p, spec in self.rooms:
            stats = self.rulebook.types.get(spec.type)
            if stats is None:
                continue
            p10 = min(max(stats.aspect.p10, 1.0), amax)
            p90 = min(max(stats.aspect.p90, 1.0), amax)
            a = p.aspect_ratio()
            total += max(0.0, a - p90) + max(0.0, p10 - a)
        return self.per_room(total)

    def area(self) -> tuple[float, Fraction]:
        over = Fraction(0)
        target = Fraction(0)
        for p, spec in self.rooms:
            t = _exact(spec.target_area_m2)
            target += t
            over += max(Fraction(0), _m2(p.rect.area_cells(), self.m) - t)
        return (float(over / target) if target else 0.0), over

    def room_rules(self) -> None:
        k = self.k
        circ = self.layout.circulation
        for p, spec in self.rooms:
            iid = p.instance_id
            r = p.rect
            req = k.req(spec)
            cells = r.area_cells()
            if cells < req.lo:
                self.flag("AREA_UNDER", (iid,), f"{iid}: {cells} cells < {req.lo}")
            elif cells > req.hi:
                self.flag("AREA_OVER", (iid,), f"{iid}: {cells} cells > {req.hi}")
            if not aspect_ok(r.w, r.h, k.amax):
                self.flag("ASPECT", (iid,), f"{iid}: aspect {p.aspect_ratio():.3f} > {k.amax}")
            if min(r.w, r.h) < req.wmin:
                self.flag("MIN_WIDTH", (iid,), f"{iid}: width {min(r.w, r.h)} < {req.wmin}")
            access = max((share_length(r, q.rect) for q in circ), default=0)
            if access < k.c:
                self.flag(
                    "NO_CIRCULATION_ACCESS", (iid,), f"{iid}: circulation contact {access} < {k.c}"
                )
            if spec.needs_facade:
                facade = sum(n for n, _ in exterior_contacts(r, self.layout.footprint))
                if facade < k.f:
                    self.flag("NO_FACADE", (iid,), f"{iid}: facade {facade} < {k.f}")

    # -------------------------------------------------------------- site terms
    def facade_orientation(self) -> float:
        north = self.prepared.site.north_angle_deg
        total = 0.0
        for p, spec in self.rooms:
            best: tuple[int, tuple[int, int]] | None = None
            for length, normal in exterior_contacts(p.rect, self.layout.footprint):
                if best is None or length > best[0]:
                    best = (length, normal)
            if best is not None:
                total += _orientation_weight(spec, self.rulebook, best[1], north)
        return 0.0 - self.per_room(total)

    def core_distance(self) -> float:
        tax = load_taxonomy()
        core = [p for p, spec in self.rooms if tax.get(spec.type).service_core]
        if not core:
            return 0.0
        tx, ty = core_target(self.layout, self.prepared, self.rulebook)
        xs = [q[0] for q in self.layout.footprint.exterior]
        ys = [q[1] for q in self.layout.footprint.exterior]
        diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        dist = sum(
            math.hypot(p.rect.x + p.rect.w / 2 - tx, p.rect.y + p.rect.h / 2 - ty) for p in core
        )
        return dist / len(core) / diag

    def circulation(self) -> tuple[float, Fraction]:
        area = sum((_m2(c.rect.area_cells(), self.m) for c in self.layout.circulation), Fraction(0))
        net = sum((_exact(spec.target_area_m2) for _, spec in self.prepared.instances), Fraction(0))
        budget = net * _exact(self.config.circulation.ratio)
        term = max(Fraction(0), area / budget - 1) if budget else Fraction(0)
        return float(term), area


def evaluate(
    layout: Layout,
    prepared: PreparedInput,
    rulebook: Rulebook,
    config: AleConfig,
    plan: CorridorPlan | None = None,
) -> LayoutMetrics:
    """Cost terms, weighted total and violations of ``layout`` (RD section 6)."""
    ev = _Eval(layout, prepared, rulebook, config)
    required, prior = ev.adjacency()
    area_term, overshoot = ev.area()
    circ_term, circ_area = ev.circulation()
    ev.room_rules()
    terms = {
        "required_adjacency": required,
        "rulebook_adjacency": prior,
        "aspect": ev.aspect(),
        "area_overshoot": area_term,
        "facade_orientation": ev.facade_orientation(),
        "core_distance": ev.core_distance(),
        "circulation_length": circ_term,
    }
    if plan is not None:
        zones = {iid: spec.macro_zone for iid, spec in prepared.instances}
        try:
            for msg in plan.zone_violations(zones):
                ev.flag("ZONE_SPLIT", (), msg)
        except KeyError as exc:
            ev.flag("ZONE_SPLIT", (), f"room {exc.args[0]} is not in the program")
    weights = config.optimizer.weights
    total = sum(getattr(weights, name) * terms[name] for name in WEIGHT_NAMES)
    violations = sorted(ev.violations, key=lambda v: (v.code, v.instance_ids, v.detail))
    return LayoutMetrics(
        total_cost=total,
        cost_breakdown=terms,
        total_overshoot_m2=float(overshoot),
        circulation_area_m2=float(circ_area),
        residue_area_m2=0.0,
        violations=tuple(violations),
    )
