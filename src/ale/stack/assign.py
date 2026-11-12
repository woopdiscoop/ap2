"""Stacking: which group of rooms on which floor (Ticket M.1, RD section 4).

A *unit* is one room instance. Units are grouped (default: the letters before the digits of the
room id); wet rooms are left out (they form the wet stack, :mod:`ale.stack.skeleton`). The
objective is a tuple ``(hard_count, hard_m2, soft)`` minimised lexicographically; the method is a
deterministic greedy placement followed by best-improvement local search (moves: a group to
another floor, two groups swapped, one unit moved, two units swapped), restarted from each
"everything on one floor" start and from a few seeded perturbations.
"""

from __future__ import annotations

import random
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from itertools import combinations, product
from typing import NamedTuple

from ale.contracts.models import RoomSpec
from ale.stack.rules import WET_TYPES, StackRules

__all__ = [
    "HARD_OVER",
    "Problem",
    "Score",
    "Stacking",
    "Unit",
    "brute_force",
    "build_problem",
    "default_group",
    "derive_groups",
    "evaluate",
    "solve",
]

HARD_OVER = 1.10
"""A floor over 110 % of its capacity is a hard miss (U-15 sketch tolerance)."""
W_SPLIT = 250.0
W_CONTIGUITY = 2000.0
W_TOGETHER = 300.0
W_IMBALANCE = 400.0
TIGHT_SHARE = 0.93
TIGHT_FACTOR = 10.0
"""With the type term (Ticket M.3), load above ``TIGHT_SHARE`` of a floor's capacity costs
``TIGHT_FACTOR x type_weight`` per m²: the exact-plan engine fails near full capacity."""
_MAX_ITER = 10_000
_SWAP_LIMIT = 60
_SMALL = 12
_KICKS_SMALL = 150
_KICKS_LARGE = 4
_EPS = 1e-9


class Score(NamedTuple):
    """Lexicographic objective, all minimised."""

    hard_count: int
    hard_m2: float
    soft: float


@dataclass(frozen=True)
class Unit:
    """One room instance to stack."""

    iid: str
    spec_id: str
    group: str
    area_m2: float
    pin: int | None = None
    type: str = ""


@dataclass(frozen=True)
class Problem:
    """A stacking problem; ``units`` are sorted by ``(group, iid)``."""

    units: tuple[Unit, ...]
    groups: tuple[str, ...]
    capacity: tuple[float, ...]
    together: tuple[tuple[str, str], ...] = ()
    keep_whole: bool = False
    group_pins: dict[str, int] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    type_weight: float = 0.0
    """Weight of the unmatched-type term (0 = ignore room types, the M.1 objective)."""

    @property
    def n_floors(self) -> int:
        return len(self.capacity)

    def members(self, group: str) -> tuple[int, ...]:
        return tuple(i for i, u in enumerate(self.units) if u.group == group)

    def fixed_level(self, i: int) -> int | None:
        u = self.units[i]
        if u.pin is not None:
            return u.pin
        return self.group_pins.get(u.group)


@dataclass(frozen=True)
class Stacking:
    """The result: ``assign[i]`` is the level of ``problem.units[i]``."""

    problem: Problem
    assign: tuple[int, ...]
    score: Score

    def level_of(self, iid: str) -> int:
        return self.assign[next(i for i, u in enumerate(self.problem.units) if u.iid == iid)]

    def loads(self) -> tuple[float, ...]:
        out = [0.0] * self.problem.n_floors
        for u, k in zip(self.problem.units, self.assign, strict=True):
            out[k] += u.area_m2
        return tuple(out)

    def matrix(self) -> dict[tuple[int, str], float]:
        """``(level, group) -> m²``."""
        m: dict[tuple[int, str], float] = {}
        for u, k in zip(self.problem.units, self.assign, strict=True):
            m[(k, u.group)] = m.get((k, u.group), 0.0) + u.area_m2
        return m

    def group_floors(self) -> dict[str, tuple[int, ...]]:
        out: dict[str, set[int]] = {g: set() for g in self.problem.groups}
        for u, k in zip(self.problem.units, self.assign, strict=True):
            out[u.group].add(k)
        return {g: tuple(sorted(s)) for g, s in out.items()}

    def split_groups(self) -> tuple[str, ...]:
        return tuple(g for g, f in self.group_floors().items() if len(f) > 1)

    def pins_met(self) -> dict[str, bool]:
        """Group pins (hard): ``group -> every unit on the pinned level``."""
        gf = self.group_floors()
        return {g: gf[g] == (lvl,) for g, lvl in sorted(self.problem.group_pins.items()) if g in gf}

    def together_met(self) -> dict[tuple[str, str], bool]:
        gf = self.group_floors()
        return {(a, b): _gap(gf.get(a, ()), gf.get(b, ())) <= 1 for a, b in self.problem.together}

    def misses(self) -> tuple[str, ...]:
        """French description of every hard miss with its shortfall in m²."""
        out = []
        for k, (load, cap) in enumerate(zip(self.loads(), self.problem.capacity, strict=True)):
            limit = HARD_OVER * max(cap, 0.0)
            if load > limit + 1e-6:
                out.append(
                    f"Niveau {k} : charge {load:.1f} m² pour une capacité de {cap:.1f} m² "
                    f"(limite {limit:.1f} m² à 110 %) : manque {load - limit:.1f} m²."
                )
        return tuple(out)


# --------------------------------------------------------------------------- groups
def default_group(spec_id: str) -> str:
    """The letters before the digits of a room id (the Annexe import's entity code)."""
    m = re.match(r"[A-Za-z]+", spec_id)
    return m.group(0) if m else spec_id


def _explicit_group(iid: str, spec_id: str, rules: StackRules) -> str | None:
    best: tuple[int, str] | None = None
    for name in sorted(rules.groups):
        for entry in rules.groups[name]:
            if entry in (iid, spec_id):
                score = 10_000 + len(entry)
            elif spec_id.startswith(entry):
                score = len(entry)
            else:
                continue
            if best is None or score > best[0]:
                best = (score, name)
    return None if best is None else best[1]


def derive_groups(
    instances: Sequence[tuple[str, RoomSpec]], rules: StackRules
) -> dict[str, tuple[str, ...]]:
    """``group -> instance ids`` (wet rooms excluded). Explicit ``groups`` (an entry matches an
    instance id, a spec id or a spec-id prefix; the longest entry wins) override the default
    per-prefix groups. Every non-wet instance lands in exactly one group."""
    out: dict[str, list[str]] = {}
    for iid, spec in instances:
        if spec.type in WET_TYPES:
            continue
        name = _explicit_group(iid, spec.id, rules) or default_group(spec.id)
        out.setdefault(name, []).append(iid)
    return {g: tuple(sorted(v)) for g, v in sorted(out.items())}


def build_problem(
    instances: Sequence[tuple[str, RoomSpec]],
    rules: StackRules,
    capacity: Sequence[float],
) -> Problem:
    """Units, resolved pins and capacities (``capacity[k]`` in m² for level ``k``)."""
    n = len(capacity)
    groups = derive_groups(instances, rules)
    gname = {iid: g for g, ids in groups.items() for iid in ids}
    notes: list[str] = []
    units = []
    for iid, spec in sorted(instances, key=lambda t: (gname.get(t[0], ""), t[0])):
        if iid not in gname:
            continue
        pin: int | None = None
        if spec.anchor == "entrance":
            pin = 0
        elif spec.floor > 0:
            pin = min(spec.floor, n - 1)
            if spec.floor > n - 1:
                notes.append(f"Pièce {iid} : niveau {spec.floor} inexistant, ramené à {n - 1}.")
        units.append(Unit(iid, spec.id, gname[iid], spec.target_area_m2, pin, str(spec.type)))
    group_pins: dict[str, int] = {}
    for g, where in sorted(rules.pins.items()):
        if g not in groups:
            notes.append(f"Épingle « {g} » : groupe absent du programme (ignorée).")
            continue
        lvl = n - 1 if where == "top" else 0 if where == "ground" else int(where)
        if lvl > n - 1:
            notes.append(f"Épingle « {g} » : niveau {where} inexistant, ramené à {n - 1}.")
            lvl = n - 1
        group_pins[g] = lvl
    together = []
    for a, b in rules.together:
        if a in groups and b in groups:
            together.append((a, b))
        else:
            notes.append(f"Paire « ensemble » ({a}, {b}) : groupe absent du programme (ignorée).")
    prob = Problem(
        units=tuple(units),
        groups=tuple(groups),
        capacity=tuple(capacity),
        together=tuple(together),
        keep_whole=rules.keep_whole,
        group_pins=group_pins,
        notes=tuple(notes),
        type_weight=rules.type_weight,
    )
    clashes = [
        f"Pièce {u.iid} : épingle de la pièce (niveau {u.pin}) prioritaire sur celle du groupe "
        f"« {u.group} » (niveau {prob.group_pins[u.group]})."
        for u in prob.units
        if u.pin is not None and u.group in prob.group_pins and u.pin != prob.group_pins[u.group]
    ]
    return replace(prob, notes=prob.notes + tuple(clashes))


# ------------------------------------------------------------------------ objective
def _gap(a: Sequence[int], b: Sequence[int]) -> int:
    if not a or not b:
        return 0
    return max(0, max(min(a), min(b)) - min(max(a), max(b)))


def evaluate(p: Problem, assign: Sequence[int]) -> Score:
    """Objective of ``assign``; entries ``-1`` (not placed yet) are ignored."""
    n = p.n_floors
    loads = [0.0] * n
    floors: dict[str, set[int]] = {}
    by_type: dict[str, list[float]] = {}
    for u, k in zip(p.units, assign, strict=True):
        if k < 0:
            continue
        loads[k] += u.area_m2
        floors.setdefault(u.group, set()).add(k)
        if p.type_weight:
            by_type.setdefault(u.type, [0.0] * n)[k] += u.area_m2
    hard_n = 0
    hard_m2 = 0.0
    over = 0.0
    shares = []
    for load, cap in zip(loads, p.capacity, strict=True):
        cap = max(cap, 0.0)
        limit = HARD_OVER * cap
        if load > limit + 1e-6:
            hard_n += 1
            hard_m2 += load - limit
        over += max(0.0, load - cap)
        shares.append(load / max(cap, 1.0))
    soft = over
    if p.type_weight:  # M.3: do not pile same-type rooms onto a floor already near capacity
        for load, cap in zip(loads, p.capacity, strict=True):
            soft += TIGHT_FACTOR * p.type_weight * max(0.0, load - TIGHT_SHARE * max(cap, 0.0))
    for fl in floors.values():
        if len(fl) > 1:
            soft += W_SPLIT
            soft += W_CONTIGUITY * ((max(fl) - min(fl) + 1) - len(fl))
    for a, b in p.together:
        soft += W_TOGETHER * max(0, _gap(sorted(floors.get(a, ())), sorted(floors.get(b, ()))) - 1)
    soft += W_IMBALANCE * (max(shares) - min(shares))
    if p.type_weight:
        for per_floor in by_type.values():
            for k in range(n):
                near = (per_floor[k - 1] if k else 0.0) + (per_floor[k + 1] if k + 1 < n else 0.0)
                soft += p.type_weight * max(0.0, per_floor[k] - near)
    return Score(hard_n, round(hard_m2, 6), round(soft, 6))


# ---------------------------------------------------------------------------- search
def _free(p: Problem) -> list[int]:
    return [i for i in range(len(p.units)) if p.fixed_level(i) is None]


def _greedy(p: Problem) -> list[int]:
    n = p.n_floors
    assign = [-1] * len(p.units)
    for i in range(len(p.units)):
        lvl = p.fixed_level(i)
        if lvl is not None:
            assign[i] = lvl
    size = {g: sum(p.units[i].area_m2 for i in p.members(g)) for g in p.groups}
    for g in sorted(p.groups, key=lambda g: (-size[g], g)):
        free = [i for i in p.members(g) if assign[i] < 0]
        if not free:
            continue
        loads = [0.0] * n
        for u, k in zip(p.units, assign, strict=True):
            if k >= 0:
                loads[k] += u.area_m2
        cands: list[list[int]] = []
        for f in range(n):
            cand = list(assign)
            for i in free:
                cand[i] = f
            cands.append(cand)
        total = sum(p.units[i].area_m2 for i in free)
        whole_fits = any(loads[f] + total <= p.capacity[f] + _EPS for f in range(n))
        if not whole_fits and not p.keep_whole:
            for s in range(n):
                cand = list(assign)
                room = list(loads)
                f = s
                for i in free:
                    while f < n - 1 and room[f] + p.units[i].area_m2 > p.capacity[f] + _EPS:
                        f += 1
                    cand[i] = f
                    room[f] += p.units[i].area_m2
                cands.append(cand)
        assign = min(cands, key=lambda c: (evaluate(p, c), c))
    return assign


def _moves(p: Problem, assign: list[int]) -> list[list[int]]:
    n = p.n_floors
    free = _free(p)
    out: list[list[int]] = []
    free_groups = [g for g in p.groups if any(i in free for i in p.members(g))]
    for g in free_groups:
        mem = [i for i in p.members(g) if i in free]
        for f in range(n):
            if any(assign[i] != f for i in mem):
                cand = list(assign)
                for i in mem:
                    cand[i] = f
                out.append(cand)
    for ga, gb in ((a, b) for a in free_groups for b in free_groups if a < b):
        ma = [i for i in p.members(ga) if i in free]
        mb = [i for i in p.members(gb) if i in free]
        fa = {assign[i] for i in ma}
        fb = {assign[i] for i in mb}
        if len(fa) == 1 and len(fb) == 1 and fa != fb:
            cand = list(assign)
            (xa,), (xb,) = tuple(fa), tuple(fb)
            for i in ma:
                cand[i] = xb
            for i in mb:
                cand[i] = xa
            out.append(cand)
    if not p.keep_whole:
        for i in free:
            for f in range(n):
                if f != assign[i]:
                    cand = list(assign)
                    cand[i] = f
                    out.append(cand)
        if len(free) <= _SWAP_LIMIT:
            for a, b in combinations(free, 2):
                if assign[a] != assign[b]:
                    cand = list(assign)
                    cand[a], cand[b] = cand[b], cand[a]
                    out.append(cand)
    return out


def _search(p: Problem, start: list[int]) -> list[int]:
    cur = start
    best = evaluate(p, cur)
    for _ in range(_MAX_ITER):
        pick: tuple[Score, list[int]] | None = None
        for cand in _moves(p, cur):
            sc = evaluate(p, cand)
            if sc < best and (pick is None or (sc, cand) < pick):
                pick = (sc, cand)
        if pick is None:
            break
        best, cur = pick
    return cur


def solve(p: Problem) -> Stacking:
    """Greedy placement then local search until no move improves (deterministic)."""
    if not p.units:
        return Stacking(p, (), Score(0, 0.0, 0.0))
    starts = [_greedy(p)]
    for f in range(p.n_floors):  # deterministic restarts: every free unit on one floor
        starts.append(
            [f if p.fixed_level(i) is None else p.fixed_level(i) or 0 for i in range(len(p.units))]
        )
    best = min((evaluate(p, a), a) for a in (_search(p, s) for s in starts))
    free = _free(p)
    if free and not p.keep_whole:
        rng = random.Random(0)  # fixed seed: deterministic perturbations
        for _ in range(_KICKS_SMALL if len(free) <= _SMALL else _KICKS_LARGE):
            cand = list(best[1])
            for i in rng.sample(free, min(len(free), rng.randint(2, 3))):
                cand[i] = rng.randrange(p.n_floors)
            sol = _search(p, cand)
            best = min(best, (evaluate(p, sol), sol))
    return Stacking(p, tuple(best[1]), best[0])


def brute_force(p: Problem) -> Score:
    """Optimum by exhaustive enumeration (tests; small problems only)."""
    free = _free(p)
    base = [-1 if (lv := p.fixed_level(i)) is None else lv for i in range(len(p.units))]
    best: Score | None = None
    for combo in product(range(p.n_floors), repeat=len(free)):
        if p.keep_whole:
            by_group: dict[str, set[int]] = {}
            for i, k in zip(free, combo, strict=True):
                by_group.setdefault(p.units[i].group, set()).add(k)
            if any(len(s) > 1 for s in by_group.values()):
                continue
        cand = list(base)
        for i, k in zip(free, combo, strict=True):
            cand[i] = k
        sc = evaluate(p, cand)
        if best is None or sc < best:
            best = sc
    return best if best is not None else evaluate(p, base)
