"""Corridor plan: the corridor-grammar layout model shared by Tickets 3.2, 3.3 and 3.4.

Vocabulary
----------
Piece = axis-aligned rectangle of the module footprint. Spine = corridor strip along the
piece's spine axis, full length, width ``s = ceil(circulation.min_width_m / module)``.
Blocks A and B on each side (possibly empty). Bays ordered along the spine. Room bay = one
room touching the spine along its full width and spanning the block depth. Finger bay =
``[left stack | finger | right stack]``; finger = corridor strip of width ``s``
perpendicular to the spine, spanning the block depth; stack rooms ordered from the spine
outward, each spanning the stack width and touching the finger along its full extent.
Leftover length at a block's far end = circulation end strip.

Guarantees
----------
Every room touches spine or finger with contact ≥ ``ceil(min_door_edge_m / module)``;
circulation connected; exact tiling. Macro-zones contiguous per block; one zone per finger
bay.

L-shaped footprints
-------------------
L shapes: see ``footprint.decompose_footprint``; J1 = corridor turns the corner through a
junction finger in the primary's facing block; J2 = collinear spines.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

from ale.contracts.enums import MacroZone

if TYPE_CHECKING:
    from ale.contracts.footprint import FootprintPieces

__all__ = [
    "Bay",
    "BlockPlan",
    "CorridorPlan",
    "FingerBay",
    "InstanceId",
    "PiecePlan",
    "RoomBay",
    "RoomPosition",
]

_CONFIG = ConfigDict(extra="forbid", frozen=True)

InstanceId = StrictStr
"""An id from ``Program.instances()`` (``"R1"``, ``"R1#03"``, …)."""

BlockName = Literal["A", "B"]


class RoomBay(BaseModel):
    """A bay holding one room that touches the spine."""

    model_config = _CONFIG

    kind: Literal["room"] = "room"
    room: InstanceId


class FingerBay(BaseModel):
    """A bay holding a corridor finger with a stack of rooms on each side.

    ``left`` is the stack before the finger along the spine, ``right`` the stack after it;
    both ordered from the spine outward. ``junction`` is ``True`` only for the L-shape J1
    junction finger. A non-junction finger has at least one room.
    """

    model_config = _CONFIG

    kind: Literal["finger"] = "finger"
    left: tuple[InstanceId, ...] = ()
    right: tuple[InstanceId, ...] = ()
    junction: StrictBool = False

    @model_validator(mode="after")
    def _non_empty(self) -> FingerBay:
        if not self.junction and not self.left and not self.right:
            raise ValueError("a non-junction finger bay needs at least one room")
        return self


Bay = Annotated[RoomBay | FingerBay, Field(discriminator="kind")]
"""A room bay or a finger bay (discriminated by ``kind``)."""


class BlockPlan(BaseModel):
    """One side of a spine: bays ordered along the spine from the piece's min coordinate."""

    model_config = _CONFIG

    bays: tuple[Bay, ...] = ()


class PiecePlan(BaseModel):
    """The two blocks of a piece: A lower (spine axis X) / left (axis Y), B upper / right."""

    model_config = _CONFIG

    block_a: BlockPlan
    block_b: BlockPlan


def _blocks(piece: PiecePlan) -> tuple[tuple[BlockName, BlockPlan], ...]:
    """``(("A", block_a), ("B", block_b))``."""
    return (("A", piece.block_a), ("B", piece.block_b))


def _bay_rooms(bay: RoomBay | FingerBay) -> tuple[str, ...]:
    """Rooms of a bay: the room of a room bay; left then right stack of a finger bay."""
    if isinstance(bay, RoomBay):
        return (bay.room,)
    return (*bay.left, *bay.right)


class RoomPosition(BaseModel):
    """Where a room sits in a plan; ``stack`` and ``index`` are ``None`` for a room bay."""

    model_config = _CONFIG

    piece: StrictInt
    block: BlockName
    bay: StrictInt
    stack: Literal["left", "right"] | None
    index: StrictInt | None


class CorridorPlan(BaseModel):
    """Corridor-grammar plan: one :class:`PiecePlan` per footprint piece (1 or 2).

    ``pieces`` are in the same order as ``FootprintPieces.pieces``. Every instance id appears
    exactly once; at most one junction finger, only in ``pieces[0]`` of a 2-piece plan.
    """

    model_config = _CONFIG

    schema_version: Literal["ale.corridor_plan/1"] = "ale.corridor_plan/1"
    pieces: tuple[PiecePlan, ...]

    @model_validator(mode="after")
    def _valid(self) -> CorridorPlan:
        n = len(self.pieces)
        if n not in (1, 2):
            raise ValueError(f"a corridor plan has 1 or 2 pieces, got {n}")
        dup = sorted(k for k, c in Counter(self.room_ids()).items() if c > 1)
        if dup:
            raise ValueError(f"instance ids appear more than once: {', '.join(dup)}")
        junctions = [
            pos for pos, bay in self._bays() if isinstance(bay, FingerBay) and bay.junction
        ]
        if len(junctions) > 1:
            raise ValueError(f"at most one junction finger allowed, got {len(junctions)}")
        if junctions:
            if n != 2:
                raise ValueError("a junction finger is only allowed in a 2-piece plan")
            if junctions[0][0] != 0:
                raise ValueError("a junction finger is only allowed in pieces[0]")
        return self

    def _bays(self) -> Iterator[tuple[tuple[int, BlockName, int], RoomBay | FingerBay]]:
        """Every bay with its ``(piece, block, bay)`` position, in plan order."""
        for p, piece in enumerate(self.pieces):
            for name, block in _blocks(piece):
                for b, bay in enumerate(block.bays):
                    yield (p, name, b), bay

    def room_ids(self) -> tuple[str, ...]:
        """Every room in plan order (piece, block A then B, bay, left stack, right stack)."""
        return tuple(r for _, bay in self._bays() for r in _bay_rooms(bay))

    def locate(self, instance_id: str) -> RoomPosition:
        """Position of ``instance_id``; ``KeyError`` if it is not in the plan."""
        for (p, block, b), bay in self._bays():
            if isinstance(bay, RoomBay):
                if bay.room == instance_id:
                    return RoomPosition(piece=p, block=block, bay=b, stack=None, index=None)
                continue
            stacks: tuple[tuple[Literal["left", "right"], tuple[str, ...]], ...] = (
                ("left", bay.left),
                ("right", bay.right),
            )
            for stack, rooms in stacks:
                if instance_id in rooms:
                    return RoomPosition(
                        piece=p, block=block, bay=b, stack=stack, index=rooms.index(instance_id)
                    )
        raise KeyError(instance_id)

    def zone_violations(self, zone_of: Mapping[str, MacroZone]) -> tuple[str, ...]:
        """Macro-zone grammar violations, sorted.

        A zone in more than one contiguous run of rooms within a block (rooms in plan order,
        junction finger ignored) → ``"zone <Z> split in piece <p> block <B>"``; a finger bay
        whose stacks hold more than one zone → ``"finger bay <i> of piece <p> block <B>
        mixes zones"``. ``KeyError`` for an id missing from ``zone_of``.
        """
        out: list[str] = []
        for p, piece in enumerate(self.pieces):
            for name, block in _blocks(piece):
                runs: list[str] = []
                for b, bay in enumerate(block.bays):
                    rooms = _bay_rooms(bay)
                    if isinstance(bay, FingerBay):
                        if len({str(zone_of[r]) for r in rooms}) > 1:
                            out.append(f"finger bay {b} of piece {p} block {name} mixes zones")
                        if bay.junction:
                            continue
                    for r in rooms:
                        zone = str(zone_of[r])
                        if not runs or runs[-1] != zone:
                            runs.append(zone)
                for zone, count in Counter(runs).items():
                    if count > 1:
                        out.append(f"zone {zone} split in piece {p} block {name}")
        return tuple(sorted(out))

    def check_against(
        self, instance_ids: Iterable[str], footprint: FootprintPieces
    ) -> tuple[str, ...]:
        """Consistency with the program instances and the footprint decomposition, sorted.

        Reports ``"missing room <id>"`` / ``"unknown room <id>"``, a piece count different
        from the footprint's, and a junction finger that is absent on a J1 footprint, present
        on a non-J1 footprint, or not in the primary's ``facing_block``.
        """
        expected = set(instance_ids)
        planned = set(self.room_ids())
        out = [f"missing room {r}" for r in expected - planned]
        out += [f"unknown room {r}" for r in planned - expected]
        if len(self.pieces) != len(footprint.pieces):
            out.append(
                f"plan has {len(self.pieces)} piece(s), footprint has {len(footprint.pieces)}"
            )
        junction = next(
            (pos for pos, bay in self._bays() if isinstance(bay, FingerBay) and bay.junction),
            None,
        )
        if footprint.junction == "J1":
            if junction is None:
                out.append("J1 footprint needs a junction finger")
            elif junction[1] != footprint.facing_block:
                out.append(
                    f"junction finger in block {junction[1]}, "
                    f"expected facing block {footprint.facing_block}"
                )
        elif junction is not None:
            out.append(f"junction finger on a {footprint.junction} footprint (J1 only)")
        return tuple(sorted(out))
