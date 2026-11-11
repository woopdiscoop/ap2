"""From the cell diagram to a corridor plan (Ticket R.9, RD §4).

The band / block structure (band counts, connectors, depths, capacity estimate and repair)
stays that of the seeder; the diagram replaces only the assignment and the order. A room's
position is the centroid of its cells, in footprint metres: the depth-aware assignment
sends every room to the compatible block nearest to it on the serpentine path (façade
rooms to the exterior blocks on their side) and orders each block by the projection of
that position on the spine, which is "the block whose region contains most of its cells,
ordered by the projection of its centroid" of the RD with the capacity constraints of 3.2.
"""

from __future__ import annotations

from collections.abc import Sequence

from ale.contracts.corridor_plan import CorridorPlan
from ale.topology.cellgrow import CellDiagram
from ale.topology.embed import Positions
from ale.topology.repair import Ctx

__all__ = ["diagram_positions", "plan_from_diagram"]


def diagram_positions(diagram: CellDiagram) -> Positions:
    """Cell centroid of every placed room, footprint metres (rooms without cells: footprint
    centre)."""
    k = diagram.step * diagram.module_m
    centre = (diagram.width * k / 2, diagram.height * k / 2)
    return {
        room: diagram.centroid_m(room) if diagram.cells[room] else centre for room in diagram.rooms
    }


def plan_from_diagram(ctx: Ctx, diagram: CellDiagram, counts: Sequence[int]) -> CorridorPlan:
    """The corridor plan with band counts ``counts`` whose assignment and order follow
    ``diagram``."""
    from ale.topology.seed import assign  # late: seed imports this module

    return assign(ctx, counts, diagram_positions(diagram)).to_plan()
