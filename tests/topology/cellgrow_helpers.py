"""Helpers of the Ticket R.9 tests: the AREP top-floor programme of Q.4 D05 and an anchor
fixture (written independently of ``ale.topology.cellgrow``)."""

from __future__ import annotations

import sys
from pathlib import Path

_OPTIMIZE_TESTS = Path(__file__).resolve().parent.parent / "optimize"
if str(_OPTIMIZE_TESTS) not in sys.path:
    sys.path.insert(0, str(_OPTIMIZE_TESTS))

from test_optimize_q4 import arep_config, arep_prepared  # noqa: E402
from topology_helpers import prepare  # noqa: E402

from ale.contracts.models import Program, RoomSpec, SiteSpec  # noqa: E402
from ale.program.models import PreparedInput  # noqa: E402

__all__ = ["anchor_prepared", "arep_config", "arep_prepared"]


def anchor_prepared(tmp: Path) -> PreparedInput:
    """A 30 x 18 m building with a core (stair, 3 x 4 m) and a main entrance on the south
    side: a corner office, an entrance hall, REQUIRED pairs and two sanitary rooms."""

    def room(rid: str, rtype: str, area: float, zone: str, **kw: object) -> RoomSpec:
        return RoomSpec.model_validate(
            {
                "id": rid,
                "name": rid,
                "type": rtype,
                "target_area_m2": area,
                "macro_zone": zone,
                **kw,
            }
        )

    rooms = (
        room("E01", "entrance_hall", 30, "PUBLIC", needs_facade=True, anchor="entrance"),
        room("R01", "reception", 30, "PUBLIC", needs_facade=True, adjacent_to=["E01"]),
        room("O01", "office", 40, "ADMINISTRATIVE", needs_facade=True, anchor="corner"),
        room("O02", "office", 25, "ADMINISTRATIVE", needs_facade=True, adjacent_to=["O01"]),
        room("O03", "office", 20, "ADMINISTRATIVE", needs_facade=True),
        room("M01", "meeting_room", 25, "ADMINISTRATIVE", adjacent_to=["O02"]),
        room("W01", "open_office", 80, "ADMINISTRATIVE", needs_facade=True),
        room("S01", "sanitary", 12, "SERVICES"),
        room("S02", "sanitary", 12, "SERVICES"),
        room("T01", "storage", 15, "SERVICES"),
    )
    site = SiteSpec.model_validate(
        {
            "footprint": {"exterior": [[0, 0], [30, 0], [30, 18], [0, 18]], "holes": []},
            "north_angle_deg": 0.0,
            "access_edge": 0,
            "entrances": [{"point": [15, 0], "label": "main", "main": True}],
            "cores": [{"id": "C1", "rect": [12, 7, 3, 4], "kind": "stair"}],
        }
    )
    return prepare(tmp, Program(rooms=rooms), site)
