"""Parti card (Ticket G.2, RD section 6): each major element and the problems it solves.

The rule table :data:`RULES` is the documentation: one row per (element kind, problem), with
the condition under which the element solves that problem. An element that solves only one
problem is flagged « élément à fonction unique (rustine possible) ».
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from ale.parti.evaluate import Evaluation, SiteSetting, _is_good
from ale.parti.genes import DEPTH_SINGLE_M, FORECOURT_M, Parti
from ale.parti.massing import Massing, Piece

__all__ = ["FLAG_FR", "RULES", "Card", "Element", "Rule", "build_card", "card_md"]

FLAG_FR = "élément à fonction unique (rustine possible)"
CORE_REACH_M = 40.0


@dataclass(frozen=True)
class Ctx:
    parti: Parti
    massing: Massing
    evaluation: Evaluation
    setting: SiteSetting
    north_angle_deg: float
    piece: Piece | None = None


@dataclass(frozen=True)
class Rule:
    kind: str  # wing | courtyard | core | forecourt | terrace
    problem: str  # French
    test: Callable[[Ctx], bool]


@dataclass(frozen=True)
class Element:
    name: str
    kind: str
    problems: tuple[str, ...]

    @property
    def single(self) -> bool:
        return len(self.problems) == 1


@dataclass(frozen=True)
class Card:
    parti: Parti
    elements: tuple[Element, ...]

    @property
    def flagged(self) -> tuple[Element, ...]:
        return tuple(e for e in self.elements if e.single)


def _wing_faces_good(c: Ctx) -> bool:
    pc = c.piece
    if pc is None:
        return False
    # the long façades of a wing face the normals across its long axis
    across = (0.0, 1.0) if pc.long_axis == "x" else (1.0, 0.0)
    ang = math.degrees(math.atan2(across[0], across[1]))
    return _is_good((ang - c.north_angle_deg) % 360.0, c.setting)


def _wing_deep(c: Ctx) -> bool:
    pc = c.piece
    if pc is None:
        return False
    w, h = pc.rect[2] - pc.rect[0], pc.rect[3] - pc.rect[1]
    return min(w, h) > DEPTH_SINGLE_M + 1e-9


def _core_reach(c: Ctx) -> bool:
    return c.evaluation.core_distance_m <= CORE_REACH_M


def _near_court(c: Ctx) -> bool:
    pc = c.piece
    return (
        c.massing.court is not None
        and pc is not None
        and (c.massing.court.buffer(0.01).intersects(_box(pc)))
    )


def _box(pc: Piece):  # type: ignore[no-untyped-def]
    from shapely import box

    return box(*pc.rect)


def _fc_entrance(c: Ctx) -> bool:
    return c.parti.forecourt_edge == c.parti.entrance_side


#: The documented rule table (problem each kind of element solves, and when).
RULES: tuple[Rule, ...] = (
    Rule("wing", "porte une part de la surface du programme", lambda c: True),
    Rule("wing", "bureaux sur les orientations favorables (NNO / SSE)", _wing_faces_good),
    Rule(
        "wing",
        "aile profonde éclairée par la cour (2 x 7,2 m et plus)",
        lambda c: _wing_deep(c) and _near_court(c),
    ),
    Rule("wing", "ferme et protège la cour (côté calme)", _near_court),
    Rule("wing", "toutes les pièces à moins de 40 m du noyau unique", _core_reach),
    Rule(
        "courtyard",
        "éclairage naturel d'une aile plus profonde que 2 x 7,2 m",
        lambda c: any(
            min(p.rect[2] - p.rect[0], p.rect[3] - p.rect[1]) > DEPTH_SINGLE_M + 1e-9
            for p in c.massing.pieces
        ),
    ),
    Rule("courtyard", "côté calme, à l'écart de la rue", lambda c: True),
    Rule(
        "courtyard",
        "façade intérieure conforme à la règle de prospect (petit côté ≥ H/2)",
        lambda c: c.evaluation.court_ok,
    ),
    Rule(
        "courtyard",
        "façades supplémentaires pour les pièces à façade",
        lambda c: c.evaluation.frontage_capacity_m >= c.evaluation.frontage_demand_m,
    ),
    Rule("core", "un seul noyau, un seul escalier (U-14)", lambda c: True),
    Rule("core", "dessert toutes les ailes à moins de 40 m", _core_reach),
    Rule(
        "core",
        "à la jonction des ailes : distances de circulation minimales",
        lambda c: c.parti.core_position == "junction",
    ),
    Rule(
        "core",
        "au centre de l'aile la plus longue : accès équilibré",
        lambda c: c.parti.core_position == "centre",
    ),
    Rule("forecourt", "dégage un recul libre devant le bâtiment", lambda c: True),
    Rule("forecourt", "arrivée : parvis devant l'entrée principale", _fc_entrance),
    Rule(
        "forecourt",
        "aucune voiture sur le parvis (séparé de la voie)",
        lambda c: _fc_entrance(c) and c.parti.forecourt_m >= FORECOURT_M - 1e-9,
    ),
    Rule("terrace", "terrasse accessible sur l'aile en retrait", lambda c: True),
    Rule(
        "terrace",
        "allège la hauteur du côté de la cour (prospect)",
        lambda c: c.massing.court is not None,
    ),
    Rule(
        "terrace",
        "lumière naturelle sur la toiture-terrasse orientée favorablement",
        _wing_faces_good,
    ),
)


def _solved(kind: str, c: Ctx) -> tuple[str, ...]:
    return tuple(r.problem for r in RULES if r.kind == kind and r.test(c))


def build_card(
    m: Massing,
    ev: Evaluation,
    north_angle_deg: float = 0.0,
    setting: SiteSetting | None = None,
) -> Card:
    """The card of a sized parti: wings, courtyard, core, forecourt, terraces (if any)."""
    setting = setting or SiteSetting()
    base = Ctx(m.parti, m, ev, setting, north_angle_deg)
    els: list[Element] = []
    for pc in m.pieces:
        c = Ctx(m.parti, m, ev, setting, north_angle_deg, pc)
        els.append(Element(f"aile « {pc.name} »", "wing", _solved("wing", c)))
    if m.court is not None:
        els.append(Element("cour", "courtyard", _solved("courtyard", base)))
    els.append(Element("noyau", "core", _solved("core", base)))
    if m.parti.forecourt_m > 0:
        els.append(Element("parvis", "forecourt", _solved("forecourt", base)))
    for pc in m.pieces:
        if pc.dropped_on_top:
            c = Ctx(m.parti, m, ev, setting, north_angle_deg, pc)
            els.append(Element(f"terrasse sur « {pc.name} »", "terrace", _solved("terrace", c)))
    return Card(m.parti, tuple(els))


def card_md(card: Card) -> str:
    """Card as French Markdown lines."""
    lines = []
    for e in card.elements:
        flag = f" **Attention : {FLAG_FR}**" if e.single else ""
        lines.append(f"- {e.name} ({len(e.problems)} problème(s) résolu(s)){flag}")
        lines += [f"  - {p}" for p in e.problems]
    return "\n".join(lines) + "\n"
