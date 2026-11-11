"""Footprints and prepared inputs of the Ticket G.1 tests (N-piece footprints)."""

from __future__ import annotations

from fixtures import load_program
from geometry_helpers import load_test_rulebook, prepared_from, site_modules

from ale.config import AleConfig
from ale.contracts.geometry import ModulePolygon
from ale.program.models import PreparedInput

Pts = tuple[tuple[int, int], ...]

# Module = 0.1 m. Areas about 420-510 m2 for the 334 m2 programme P25.
U: Pts = ((0, 0), (240, 0), (240, 200), (150, 200), (150, 100), (90, 100), (90, 200), (0, 200))
T: Pts = ((70, 0), (170, 0), (170, 200), (240, 200), (240, 300), (0, 300), (0, 200), (70, 200))
COMB: Pts = (
    (0, 0),
    (300, 0),
    (300, 200),
    (230, 200),
    (230, 90),
    (185, 90),
    (185, 200),
    (115, 200),
    (115, 90),
    (70, 90),
    (70, 200),
    (0, 200),
)
H: Pts = (
    (0, 0),
    (100, 0),
    (100, 70),
    (200, 70),
    (200, 0),
    (300, 0),
    (300, 200),
    (200, 200),
    (200, 130),
    (100, 130),
    (100, 200),
    (0, 200),
)
Z: Pts = ((0, 0), (200, 0), (200, 100), (300, 100), (300, 200), (100, 200), (100, 100), (0, 100))
RING_OUTER: Pts = ((0, 0), (240, 0), (240, 240), (0, 240))
RING_HOLE: Pts = ((80, 80), (80, 160), (160, 160), (160, 80))  # clockwise
RING = ModulePolygon(exterior=RING_OUTER, holes=(RING_HOLE,))


def p25(points: Pts) -> PreparedInput:
    """Programme P25 on a footprint (exterior ring ``points``)."""
    return prepared_from(
        load_program("program_25"), site_modules(list(points)), load_test_rulebook(), AleConfig()
    )


def p25_ring() -> PreparedInput:
    """Programme P25 on the courtyard ring ``RING`` (the site intake rejects holes, so the
    module footprint is swapped in after preparation)."""
    prep = p25(RING_OUTER)
    return prep.model_copy(
        update={"footprint": prep.footprint.model_copy(update={"polygon": RING})}
    )
