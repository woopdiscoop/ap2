"""Seed / mined blending (Ticket 2.2 RD sections 3-4): ``final = seed + w (mined - seed)``.

``w = n / (n + blend_k)`` where ``n`` is the weighted support (adjacency), the room count
(aspect, area) or the plan count (orientation, core offset). Every value of the result is
recorded with its provenance (``seed`` / ``mined`` / ``blended``) for the report.

Literal readings (see ``eval_report.md``): an adjacency pair counts as "present in the seed"
only when the seed lists it explicitly (unlisted pairs fall back to ``default_p``); the
Laplace prior is always the neutral 0.5 (the seed acts only through the blend); blended
quantiles carry the mined ``n``; a mined
aspect is clipped to ``shape.aspect_max`` before blending (all three quantiles, so that the
order is kept); a mined-only type with fewer than 3 north-known plans gets a neutral
orientation (0.0 everywhere).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ale.contracts.config import AleConfig
from ale.contracts.enums import Bearing
from ale.contracts.models import Adjacency, AdjEntry, CoreOffset, Quantiles, Rulebook, TypeStats
from ale.rulebook.stats import (
    BEARINGS,
    CoreStat,
    OrientationStat,
    PairStat,
    ShapeStat,
    weighted_quantile,
)

__all__ = [
    "MIN_ORIENTATION_PLANS",
    "NEUTRAL_P",
    "Blended",
    "CoreRow",
    "PairRow",
    "QuantRow",
    "Source",
    "blend_quantiles",
    "blend_rulebook",
    "blend_value",
    "laplace_p",
    "sig",
]

#: Types seen in fewer north-known plans keep the seed orientation.
MIN_ORIENTATION_PLANS = 3
#: Neutral Laplace prior of an adjacency probability (amended RD 3: never the seed).
NEUTRAL_P = 0.5
_SIG = 9

Source = Literal["seed", "mined", "blended"]


def sig(x: float) -> float:
    """``x`` rounded to 9 significant digits (stable YAML; ``-0.0`` normalised)."""
    return float(f"{x:.{_SIG}g}") + 0.0


def blend_value(seed: float, mined: float, n: float, k: float) -> float:
    """``seed + w (mined - seed)`` with ``w = n / (n + k)``."""
    w = n / (n + k)
    return seed + w * (mined - seed)


def blend_quantiles(seed: Quantiles, mined: Quantiles, n: float, k: float) -> Quantiles:
    """Per-quantile blend (a convex combination of two ordered triples stays ordered)."""
    p10 = sig(blend_value(seed.p10, mined.p10, n, k))
    p50 = sig(blend_value(seed.p50, mined.p50, n, k))
    p90 = sig(blend_value(seed.p90, mined.p90, n, k))
    p50 = min(max(p50, p10), p90)  # guard against rounding at the 9th digit
    return Quantiles(p10=p10, p50=p50, p90=p90, n=mined.n)


def laplace_p(stat: PairStat, alpha: float, p0: float = NEUTRAL_P) -> float:
    """``(hits + alpha p0) / (support + alpha)``."""
    return (stat.hits + alpha * p0) / (stat.support + alpha)


@dataclass(frozen=True)
class PairRow:
    a: str
    b: str
    p: float
    n_support: int
    source: Source
    support: float | None = None
    hits: float | None = None
    p_seed: float | None = None
    p_mined: float | None = None


@dataclass(frozen=True)
class QuantRow:
    type: str
    stat: Literal["aspect", "area_m2"]
    value: Quantiles
    source: Source
    mined: Quantiles | None = None
    seed: Quantiles | None = None
    clipped: bool = False


@dataclass(frozen=True)
class OrientRow:
    type: str
    values: dict[Bearing, float]
    source: Source
    n_plans: int
    note: str = ""


@dataclass(frozen=True)
class CoreRow:
    value: CoreOffset
    source: Source
    mined: CoreStat | None = None


@dataclass
class Blended:
    """Blended statistics and their provenance."""

    types: dict[str, TypeStats]
    adjacency: Adjacency
    core_offset: CoreOffset
    pairs: list[PairRow] = field(default_factory=list)
    quantiles: list[QuantRow] = field(default_factory=list)
    orientation: list[OrientRow] = field(default_factory=list)
    core: CoreRow | None = None
    notes: list[str] = field(default_factory=list)


def _mined_quantiles(samples: list[tuple[float, float]], n: int) -> Quantiles:
    q = [sig(weighted_quantile(samples, p)) for p in (0.10, 0.50, 0.90)]
    return Quantiles(p10=q[0], p50=q[1], p90=q[2], n=n)


def _adjacency(
    mined: dict[tuple[str, str], PairStat],
    seed: Rulebook | None,
    config: AleConfig,
    min_support: int,
    out: Blended,
) -> Adjacency:
    rb = config.rulebook
    seed_pairs = {(e.a, e.b): e for e in seed.adjacency.pairs} if seed is not None else {}
    entries: dict[tuple[str, str], AdjEntry] = {}
    for (a, b), st in sorted(mined.items()):
        n_support = round(st.support)
        if n_support < min_support:
            if (a, b) not in seed_pairs:
                out.notes.append(
                    f"Paire {a} / {b} omise : support {n_support} < min_support {min_support}."
                )
            continue
        p_mined = laplace_p(st, rb.laplace_alpha)
        prior = seed_pairs.get((a, b))
        if prior is not None:
            p = sig(blend_value(prior.p, p_mined, st.support, rb.blend_k))
            source: Source = "blended"
        else:
            p = sig(p_mined)
            source = "mined"
        p = min(max(p, 0.0), 1.0)
        entries[(a, b)] = AdjEntry(a=a, b=b, p=p, n_support=n_support)
        out.pairs.append(
            PairRow(
                a=a,
                b=b,
                p=p,
                n_support=n_support,
                source=source,
                support=st.support,
                hits=st.hits,
                p_seed=None if prior is None else prior.p,
                p_mined=sig(p_mined),
            )
        )
    for key, e in sorted(seed_pairs.items()):
        if key in entries:
            continue
        entries[key] = e
        mst = mined.get(key)
        out.pairs.append(
            PairRow(
                a=e.a,
                b=e.b,
                p=e.p,
                n_support=e.n_support,
                source="seed",
                support=None if mst is None else mst.support,
                hits=None if mst is None else mst.hits,
                p_seed=e.p,
            )
        )
    out.pairs.sort(key=lambda r: (r.a, r.b))
    default_p = seed.adjacency.default_p if seed is not None else 0.5
    return Adjacency(default_p=default_p, pairs=tuple(entries[k] for k in sorted(entries)))


def _aspect(st: ShapeStat, aspect_max: float) -> tuple[Quantiles, bool]:
    q = _mined_quantiles(st.aspect, st.n)
    if q.p90 <= aspect_max:
        return q, False
    clipped = Quantiles(
        p10=min(q.p10, aspect_max), p50=min(q.p50, aspect_max), p90=aspect_max, n=q.n
    )
    return clipped, True


def _types(
    shapes: dict[str, ShapeStat],
    orient: dict[str, OrientationStat],
    seed: Rulebook | None,
    config: AleConfig,
    min_support: int,
    out: Blended,
) -> dict[str, TypeStats]:
    k = config.rulebook.blend_k
    aspect_max = config.shape.aspect_max
    seed_types = dict(seed.types) if seed is not None else {}
    result: dict[str, TypeStats] = {}
    for t in sorted(set(seed_types) | set(shapes)):
        prior = seed_types.get(t)
        st = shapes.get(t)
        o = orient.get(t)
        o_ok = o is not None and o.n_plans >= MIN_ORIENTATION_PLANS
        if prior is None:
            assert st is not None  # t comes from shapes
            if st.n < min_support:
                out.notes.append(
                    f"Type {t} miné ignoré : {st.n} pièce(s) < min_support {min_support}."
                )
                continue
            aspect, clipped = _aspect(st, aspect_max)
            area = _mined_quantiles(st.area, st.n)
            out.quantiles.append(QuantRow(t, "aspect", aspect, "mined", aspect, None, clipped))
            out.quantiles.append(QuantRow(t, "area_m2", area, "mined", area))
            if o is not None and o_ok:
                values = {b: sig(o.values[b]) for b in BEARINGS}
                out.orientation.append(OrientRow(t, values, "mined", o.n_plans))
            else:
                values = {b: 0.0 for b in BEARINGS}
                n_pl = 0 if o is None else o.n_plans
                out.orientation.append(
                    OrientRow(t, values, "mined", n_pl, "neutre (< 3 plans orientés)")
                )
            result[t] = TypeStats(aspect=aspect, area_m2=area, orientation=values)
            continue
        if st is not None and st.n > 0:
            m_aspect, clipped = _aspect(st, aspect_max)
            m_area = _mined_quantiles(st.area, st.n)
            aspect = blend_quantiles(prior.aspect, m_aspect, st.n, k)
            area = blend_quantiles(prior.area_m2, m_area, st.n, k)
            out.quantiles.append(
                QuantRow(t, "aspect", aspect, "blended", m_aspect, prior.aspect, clipped)
            )
            out.quantiles.append(QuantRow(t, "area_m2", area, "blended", m_area, prior.area_m2))
        else:
            aspect, area = prior.aspect, prior.area_m2
            out.quantiles.append(QuantRow(t, "aspect", aspect, "seed", None, aspect))
            out.quantiles.append(QuantRow(t, "area_m2", area, "seed", None, area))
        if o is not None and o_ok:
            values = {
                b: min(
                    1.0,
                    max(-1.0, sig(blend_value(prior.orientation[b], o.values[b], o.n_plans, k))),
                )
                for b in BEARINGS
            }
            out.orientation.append(OrientRow(t, values, "blended", o.n_plans))
        else:
            values = {b: prior.orientation[b] for b in BEARINGS}
            n_pl = 0 if o is None else o.n_plans
            out.orientation.append(OrientRow(t, values, "seed", n_pl))
        result[t] = TypeStats(aspect=aspect, area_m2=area, orientation=values)
    return result


def _core(core: CoreStat | None, seed: Rulebook | None, config: AleConfig) -> CoreRow:
    k = config.rulebook.blend_k

    def clamp(v: float) -> float:
        return min(0.5, max(-0.5, sig(v)))

    if core is None:
        if seed is not None:
            return CoreRow(seed.core_offset, "seed")
        return CoreRow(CoreOffset(dx_norm=0.0, dy_norm=0.0, n=0), "mined")
    if seed is None:
        value = CoreOffset(dx_norm=clamp(core.dx_norm), dy_norm=clamp(core.dy_norm), n=core.n)
        return CoreRow(value, "mined", core)
    s = seed.core_offset
    value = CoreOffset(
        dx_norm=clamp(blend_value(s.dx_norm, core.dx_norm, core.n, k)),
        dy_norm=clamp(blend_value(s.dy_norm, core.dy_norm, core.n, k)),
        n=core.n,
    )
    return CoreRow(value, "blended", core)


def blend_rulebook(
    *,
    pairs: dict[tuple[str, str], PairStat],
    shapes: dict[str, ShapeStat],
    orientation: dict[str, OrientationStat],
    core: CoreStat | None,
    seed: Rulebook | None,
    config: AleConfig,
    min_support: int,
) -> Blended:
    """Combine the mined statistics with the optional seed."""
    out = Blended(
        types={},
        adjacency=Adjacency(default_p=0.5, pairs=()),
        core_offset=CoreOffset(dx_norm=0.0, dy_norm=0.0),
    )
    out.adjacency = _adjacency(pairs, seed, config, min_support, out)
    out.types = _types(shapes, orientation, seed, config, min_support, out)
    out.core = _core(core, seed, config)
    out.core_offset = out.core.value
    for row in out.quantiles:
        if row.clipped:
            out.notes.append(
                f"Type {row.type} : aspect p90 miné écrêté à shape.aspect_max = "
                f"{config.shape.aspect_max:g} (règle impérative)."
            )
    return out
