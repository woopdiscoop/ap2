"""Genes of a parti (Ticket G.2, RD section 3): a few strong decisions taken together."""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import product

__all__ = [
    "CIRCULATIONS",
    "CORE_POSITIONS",
    "CORRIDOR_M",
    "COURT_TYPES",
    "DEPTH_DOUBLE_M",
    "DEPTH_SINGLE_M",
    "FORECOURT_M",
    "GRID_M",
    "ROOM_DEPTH_M",
    "TYPOLOGIES",
    "Dropped",
    "Parti",
    "enumerate_genes",
    "validate_parti",
]

GRID_M = 0.6
ROOM_DEPTH_M = 7.2
CORRIDOR_M = 1.8
DEPTH_SINGLE_M = ROOM_DEPTH_M + CORRIDOR_M  # 9.0
DEPTH_DOUBLE_M = 2 * ROOM_DEPTH_M + CORRIDOR_M  # 16.2
FORECOURT_M = 7.2

TYPOLOGIES = ("bar", "L", "U", "T", "comb", "courtyard", "H")
COURT_TYPES = frozenset({"U", "comb", "courtyard", "H"})
CIRCULATIONS = ("spine", "loop", "comb")
CORE_POSITIONS = ("junction", "end", "centre")
_CIRC_OF = {
    "bar": "spine",
    "L": "spine",
    "T": "spine",
    "U": "spine",
    "H": "spine",
    "comb": "comb",
    "courtyard": "loop",
}


@dataclass(frozen=True)
class Parti:
    """One parti. ``orientation_deg`` is the direction of the long façades in the site frame
    (0 = along x, 90 = along y); ``wing_depth_m`` is 9.0 (single-loaded) or 16.2
    (double-loaded); ``entrance_side`` is the plot edge of the main entrance;
    ``forecourt_m`` the depth of the forecourt (0 = none) on ``forecourt_side`` (default: the
    entrance side); ``fingers`` is the number of comb fingers (0 for other typologies);
    ``terrace`` makes the top floor recede by one whole wing."""

    typology: str
    orientation_deg: int
    wing_depth_m: float
    floors: int
    core_position: str
    circulation: str
    entrance_side: int
    courtyard: bool
    forecourt_m: float = 0.0
    forecourt_side: int | None = None
    fingers: int = 0
    terrace: bool = False

    @property
    def loading(self) -> str:
        return "double" if self.wing_depth_m > DEPTH_SINGLE_M + 1e-9 else "single"

    @property
    def forecourt_edge(self) -> int | None:
        if self.forecourt_m <= 0:
            return None
        return self.entrance_side if self.forecourt_side is None else self.forecourt_side

    def key(self) -> str:
        return (
            f"{self.typology}-{self.orientation_deg}-{self.loading[0]}-f{self.floors}-"
            f"{self.core_position[0]}-e{self.entrance_side}-c{int(self.forecourt_m > 0)}"
            f"{'-t' if self.terrace else ''}{'-n' + str(self.fingers) if self.fingers else ''}"
        )


@dataclass(frozen=True)
class Dropped:
    """A gene set that is not valid (or does not fit), with the reason (French)."""

    parti: Parti
    reason: str


def validate_parti(p: Parti, floors: tuple[int, int] = (1, 99)) -> str | None:
    """Reason why ``p`` is not a valid gene set, or ``None``."""
    if p.typology not in TYPOLOGIES:
        return f"typologie inconnue « {p.typology} »"
    if p.orientation_deg not in (0, 90):
        return f"orientation {p.orientation_deg}° non prise en charge (0 ou 90)"
    if not floors[0] <= p.floors <= floors[1]:
        return f"{p.floors} niveaux hors de la plage {floors[0]}-{floors[1]}"
    if p.circulation not in CIRCULATIONS:
        return f"circulation inconnue « {p.circulation} »"
    if p.core_position not in CORE_POSITIONS:
        return f"position de noyau inconnue « {p.core_position} »"
    if p.courtyard != (p.typology in COURT_TYPES):
        return (
            f"la typologie « {p.typology} » "
            f"{'ne comporte pas' if p.courtyard else 'comporte'} de cour"
        )
    if p.circulation != _CIRC_OF[p.typology]:
        return f"circulation « {p.circulation} » incompatible avec la typologie « {p.typology} »"
    if p.typology == "comb":
        if not 2 <= p.fingers <= 4:
            return f"peigne à {p.fingers} dents (2 à 4 attendues)"
    elif p.fingers:
        return "des dents ne sont possibles que pour un peigne"
    if p.core_position == "junction" and p.typology == "bar":
        return "une barre n'a pas de jonction d'ailes pour le noyau"
    if p.terrace and (p.typology == "bar" or p.floors < 2):
        return "un retrait par aile entière demande au moins deux ailes et deux niveaux"
    if abs(p.wing_depth_m - DEPTH_SINGLE_M) > 1e-9 and abs(p.wing_depth_m - DEPTH_DOUBLE_M) > 1e-9:
        return f"profondeur d'aile {p.wing_depth_m} m hors {{9,0 ; 16,2}}"
    return None


def enumerate_genes(
    entrance_side: int,
    floors: tuple[int, int],
    *,
    orientations: tuple[int, ...] = (0, 90),
    forecourts: tuple[float, ...] = (0.0, FORECOURT_M),
    include_inconsistent: bool = True,
) -> tuple[list[Parti], list[Dropped]]:
    """All gene sets of the family, split into valid ones and dropped ones with their reason.
    ``include_inconsistent`` also tries court/circulation mismatches, which are then dropped."""
    valid: list[Parti] = []
    dropped: list[Dropped] = []
    court_flags = (False, True) if include_inconsistent else (None,)
    for typ, ori, depth, nfl, core, terr, fc, cflag in product(
        TYPOLOGIES,
        orientations,
        (DEPTH_SINGLE_M, DEPTH_DOUBLE_M),
        range(floors[0], floors[1] + 1),
        CORE_POSITIONS,
        (False, True),
        forecourts,
        court_flags,
    ):
        circ = _CIRC_OF[typ]
        fingers_set = (2, 3, 4) if typ == "comb" else (0,)
        for fingers in fingers_set:
            base = Parti(
                typ,
                ori,
                depth,
                nfl,
                core,
                circ,
                entrance_side,
                (typ in COURT_TYPES) if cflag is None else cflag,
                fc,
                None,
                fingers,
                terr,
            )
            reason = validate_parti(base, floors)
            if reason is None:
                valid.append(base)
            else:
                dropped.append(Dropped(base, reason))
        if typ == "bar":
            # loop on a bar: a deliberately impossible combination, reported once per shape
            bad = replace(
                Parti(typ, ori, depth, nfl, core, "loop", entrance_side, False, fc, None, 0, terr)
            )
            reason = validate_parti(bad, floors)
            if reason is not None:
                dropped.append(Dropped(bad, reason))
    return valid, dropped
