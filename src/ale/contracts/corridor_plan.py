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

Tree of pieces (contracts 1.6.0)
--------------------------------
Footprints with more than two pieces (T, U, H, comb, Z, courtyard rings) form a tree of pieces
(``FootprintPieces.junctions``). Every J1 child is reached through one junction finger
(``FingerBay(junction=True, junction_to=<child>)``) in its parent's band adjacent to the cut,
in the parent's facing block; a parent may host several. In a plan of more than two pieces a
J1 child has exactly one band and so has every piece incident to a J2 junction.

Bands
-----
Bands: a piece is divided across its spine axis into bands stacked from min v upward; each band is
``block A | spine | block B``; band depths sum to the piece depth. With ≥ 2 bands the piece has a
connector: a corridor of width s spanning the full piece depth at its start (u ∈ [0, s)) or end
(u ∈ [L - s, L)); band spines run from the connector to the far end. 1-band pieces have no
connector. J2: if both pieces have one band, spines are collinear; otherwise the primary's
connector lies on the cut side and the secondary needs none. J1: the secondary has exactly one
band; the junction finger is in the primary's band adjacent to the cut (band 0 if facing_block is
A, else the last band), in that band's facing block.

Inner connector (contracts 1.3.0)
---------------------------------
With ``connector == "inner"`` (≥ 2 bands), the connector is a corridor strip of width ``s``
spanning the full piece depth at a position ``u_c`` chosen by realisation, somewhere inside the
piece's length. Every block of every band of such a piece holds exactly one
:class:`ConnectorBay` marker (an otherwise empty block holds just the marker): in each block,
bays listed before the marker lie at ``u < u_c``, those after at ``u ≥ u_c + s``. Band spines
cross the connector and run the full piece length. Markers hold no room: ``room_ids`` and
``locate`` skip them (bay indices count markers, so ``locate(...).bay`` still indexes
``bays``), and for macro-zone contiguity a marker splits its block into two runs (a zone may
appear once on each side). On a J2 footprint, a rule requiring a connector on the cut side is
satisfied only by ``"start"``/``"end"``; ``"inner"`` is allowed for pieces where no cut-side
connector is required.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_serializer,
    model_validator,
)

from ale.contracts.enums import MacroZone

if TYPE_CHECKING:
    from ale.contracts.footprint import FootprintPieces

__all__ = [
    "BandPlan",
    "Bay",
    "BlockPlan",
    "ConnectorBay",
    "CorridorPlan",
    "FingerBay",
    "InstanceId",
    "PiecePlan",
    "RoomBay",
    "RoomPosition",
]

MAX_PIECES = 12
"""Maximum number of pieces in a plan (equals ``footprint.MAX_PIECES``)."""

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
    both ordered from the spine outward. ``junction`` is ``True`` only for a J1 junction
    finger (the corridor link to a child piece). ``junction_to`` (Ticket G.1, contracts 1.6.0):
    the index of the child piece the junction finger leads to; ``None`` keeps the L-shape
    meaning (the only child) and is the only accepted value in a plan of at most two pieces
    unless it is 1. A non-junction finger has at least one room and no ``junction_to``.
    """

    model_config = _CONFIG

    kind: Literal["finger"] = "finger"
    left: tuple[InstanceId, ...] = ()
    right: tuple[InstanceId, ...] = ()
    junction: StrictBool = False
    junction_to: StrictInt | None = None

    @model_validator(mode="after")
    def _non_empty(self) -> FingerBay:
        if not self.junction and not self.left and not self.right:
            raise ValueError("a non-junction finger bay needs at least one room")
        if self.junction_to is not None and not self.junction:
            raise ValueError("junction_to is only allowed on a junction finger")
        if self.junction_to is not None and self.junction_to < 1:
            raise ValueError("junction_to is a child piece index (>= 1)")
        return self

    @model_serializer(mode="wrap")
    def _drop_unset_target(self, handler: Any) -> Any:
        out = handler(self)
        if isinstance(out, dict) and out.get("junction_to") is None:
            out.pop("junction_to", None)
        return out


class ConnectorBay(BaseModel):
    """Marker for the crossing of an ``"inner"`` connector in a block (holds no room).

    Bays before the marker lie before the connector along the spine, bays after it beyond.
    """

    model_config = _CONFIG

    kind: Literal["connector"] = "connector"


Bay = Annotated[RoomBay | FingerBay | ConnectorBay, Field(discriminator="kind")]
"""A room bay, a finger bay or a connector marker (discriminated by ``kind``)."""


class BlockPlan(BaseModel):
    """One side of a spine: bays ordered along the spine from the piece's min coordinate."""

    model_config = _CONFIG

    bays: tuple[Bay, ...] = ()


class BandPlan(BaseModel):
    """One band of a piece: A lower (spine axis X) / left (axis Y), B upper / right."""

    model_config = _CONFIG

    block_a: BlockPlan
    block_b: BlockPlan


MAX_BANDS = 6
"""Maximum number of bands in a piece."""


class PiecePlan(BaseModel):
    """The bands of a piece, ordered from the piece's min v (across the spine axis) upward.

    ``connector``: where the connector corridor lies along the spine axis (``"start"`` at
    ``u ∈ [0, s)``, ``"end"`` at ``u ∈ [L - s, L)``, ``"inner"`` at ``u ∈ [u_c, u_c + s)``
    with ``u_c`` chosen by realisation); a 1-band piece must have ``"none"``. With
    ``"inner"`` every block of every band holds exactly one :class:`ConnectorBay`; with any
    other value no block holds one.
    """

    model_config = _CONFIG

    bands: tuple[BandPlan, ...] = Field(min_length=1, max_length=MAX_BANDS)
    connector: Literal["none", "start", "end", "inner"] = "none"

    @model_validator(mode="after")
    def _connector(self) -> PiecePlan:
        if len(self.bands) == 1 and self.connector != "none":
            raise ValueError(f"a 1-band piece has no connector, got {self.connector!r}")
        for k, band in enumerate(self.bands):
            for name, block in _blocks(band):
                markers = sum(isinstance(bay, ConnectorBay) for bay in block.bays)
                where = f"band {k} block {name}"
                if self.connector == "inner" and markers != 1:
                    raise ValueError(
                        f"an inner-connector piece needs exactly one connector bay per block,"
                        f" got {markers} in {where}"
                    )
                if self.connector != "inner" and markers:
                    raise ValueError(
                        f"a connector bay is only allowed in an inner-connector piece"
                        f" (connector {self.connector!r}, {where})"
                    )
        return self


def _blocks(band: BandPlan) -> tuple[tuple[BlockName, BlockPlan], ...]:
    """``(("A", block_a), ("B", block_b))``."""
    return (("A", band.block_a), ("B", band.block_b))


AnyBay = RoomBay | FingerBay | ConnectorBay
"""The bay classes (the plain union behind :data:`Bay`)."""


def _bay_rooms(bay: AnyBay) -> tuple[str, ...]:
    """Rooms of a bay: the room of a room bay; left then right stack of a finger bay; none for
    a connector marker."""
    if isinstance(bay, RoomBay):
        return (bay.room,)
    if isinstance(bay, ConnectorBay):
        return ()
    return (*bay.left, *bay.right)


class RoomPosition(BaseModel):
    """Where a room sits in a plan; ``stack`` and ``index`` are ``None`` for a room bay."""

    model_config = _CONFIG

    piece: StrictInt
    band: StrictInt
    block: BlockName
    bay: StrictInt
    stack: Literal["left", "right"] | None
    index: StrictInt | None


BayPosition = tuple[int, int, BlockName, int]
"""``(piece, band, block, bay)``."""


class CorridorPlan(BaseModel):
    """Corridor-grammar plan: one :class:`PiecePlan` per footprint piece (1 to 12).

    ``pieces`` are in the same order as ``FootprintPieces.pieces``. Every instance id appears
    exactly once. A 2-piece plan has at most one junction finger, in ``pieces[0]``; a plan of
    more than two pieces has junction fingers that all name their child (``junction_to``),
    each child at most once.
    """

    model_config = _CONFIG

    schema_version: Literal["ale.corridor_plan/2"] = "ale.corridor_plan/2"
    pieces: tuple[PiecePlan, ...]

    @model_validator(mode="after")
    def _valid(self) -> CorridorPlan:
        n = len(self.pieces)
        if not 1 <= n <= MAX_PIECES:
            raise ValueError(f"a corridor plan has 1 to {MAX_PIECES} pieces, got {n}")
        dup = sorted(k for k, c in Counter(self.room_ids()).items() if c > 1)
        if dup:
            raise ValueError(f"instance ids appear more than once: {', '.join(dup)}")
        junctions = self._junctions()
        if n > 2:
            self._check_tree_junctions(junctions)
            return self
        if len(junctions) > 1:
            raise ValueError(f"at most one junction finger allowed, got {len(junctions)}")
        if junctions:
            if n != 2:
                raise ValueError("a junction finger is only allowed in a 2-piece plan")
            if junctions[0][0] != 0:
                raise ValueError("a junction finger is only allowed in pieces[0]")
            if self._junction_targets(junctions) not in ([None], [1]):
                raise ValueError("junction_to of a 2-piece plan must be 1")
        return self

    def _junction_targets(self, positions: list[BayPosition]) -> list[int | None]:
        bays = {pos: bay for pos, bay in self._bays()}
        return [bay.junction_to for pos in positions if isinstance(bay := bays[pos], FingerBay)]

    def _check_tree_junctions(self, positions: list[BayPosition]) -> None:
        n = len(self.pieces)
        targets = self._junction_targets(positions)
        for pos, to in zip(positions, targets, strict=True):
            if to is None:
                raise ValueError(
                    "a junction finger in a plan of more than two pieces needs junction_to"
                )
            if not pos[0] < to < n:
                raise ValueError(f"junction_to {to} must be a later piece than the host {pos[0]}")
        dup = sorted(k for k, c in Counter(targets).items() if k is not None and c > 1)
        if dup:
            raise ValueError(f"more than one junction finger leads to piece {dup[0]}")

    def _bays(self) -> Iterator[tuple[BayPosition, AnyBay]]:
        """Every bay with its ``(piece, band, block, bay)`` position, in plan order."""
        for p, piece in enumerate(self.pieces):
            for k, band in enumerate(piece.bands):
                for name, block in _blocks(band):
                    for b, bay in enumerate(block.bays):
                        yield (p, k, name, b), bay

    def _junctions(self) -> list[BayPosition]:
        """Positions of the junction fingers, in plan order."""
        return [pos for pos, bay in self._bays() if isinstance(bay, FingerBay) and bay.junction]

    def room_ids(self) -> tuple[str, ...]:
        """Every room in plan order (piece, band, block A then B, bay, left stack, right stack)."""
        return tuple(r for _, bay in self._bays() for r in _bay_rooms(bay))

    def locate(self, instance_id: str) -> RoomPosition:
        """Position of ``instance_id``; ``KeyError`` if it is not in the plan."""
        for (p, k, block, b), bay in self._bays():
            if isinstance(bay, RoomBay):
                if bay.room == instance_id:
                    return RoomPosition(piece=p, band=k, block=block, bay=b, stack=None, index=None)
                continue
            if isinstance(bay, ConnectorBay):
                continue
            stacks: tuple[tuple[Literal["left", "right"], tuple[str, ...]], ...] = (
                ("left", bay.left),
                ("right", bay.right),
            )
            for stack, rooms in stacks:
                if instance_id in rooms:
                    return RoomPosition(
                        piece=p,
                        band=k,
                        block=block,
                        bay=b,
                        stack=stack,
                        index=rooms.index(instance_id),
                    )
        raise KeyError(instance_id)

    def zone_violations(self, zone_of: Mapping[str, MacroZone]) -> tuple[str, ...]:
        """Macro-zone grammar violations, sorted.

        A zone in more than one contiguous run of rooms within a band block (rooms in plan
        order, junction finger ignored; a connector marker splits the block into two parts, each
        checked on its own) → ``"zone <Z> split in piece <p> band <k> block <B>"``;
        a finger bay whose stacks hold more than one zone → ``"finger bay <i> of piece <p>
        band <k> block <B> mixes zones"``. ``KeyError`` for an id missing from ``zone_of``.
        """
        out: list[str] = []
        for p, piece in enumerate(self.pieces):
            for k, band in enumerate(piece.bands):
                for name, block in _blocks(band):
                    where = f"piece {p} band {k} block {name}"
                    split: set[str] = set()
                    runs: list[str] = []
                    for b, bay in enumerate(block.bays):
                        if isinstance(bay, ConnectorBay):
                            split |= _repeated(runs)
                            runs = []
                            continue
                        rooms = _bay_rooms(bay)
                        if isinstance(bay, FingerBay):
                            if len({str(zone_of[r]) for r in rooms}) > 1:
                                out.append(f"finger bay {b} of {where} mixes zones")
                            if bay.junction:
                                continue
                        for r in rooms:
                            zone = str(zone_of[r])
                            if not runs or runs[-1] != zone:
                                runs.append(zone)
                    split |= _repeated(runs)
                    out += [f"zone {zone} split in {where}" for zone in split]
        return tuple(sorted(out))

    def check_against(
        self, instance_ids: Iterable[str], footprint: FootprintPieces
    ) -> tuple[str, ...]:
        """Consistency with the program instances and the footprint decomposition, sorted.

        Reports ``"missing room <id>"`` / ``"unknown room <id>"``, a piece count different
        from the footprint's, a junction finger that is absent on a J1 footprint or present on
        a non-J1 footprint, and the band rules: a piece with 2+ bands needs a connector
        (except the secondary of a J2 footprint); on a J2 footprint with any multi-band piece
        the primary's connector must be on its cut side if the primary has 2+ bands, else the
        secondary's connector must be on its cut side; on a J1 footprint the secondary has
        exactly one band and the junction finger lies in the primary's band adjacent to the
        cut (band 0 for ``facing_block`` ``"A"``, the last band for ``"B"``), in its block of
        the same letter.
        """
        expected = set(instance_ids)
        planned = set(self.room_ids())
        out = [f"missing room {r}" for r in expected - planned]
        out += [f"unknown room {r}" for r in planned - expected]
        if len(self.pieces) != len(footprint.pieces):
            out.append(
                f"plan has {len(self.pieces)} piece(s), footprint has {len(footprint.pieces)}"
            )
        if len(footprint.pieces) > 2:
            return tuple(sorted(out + self._check_tree(footprint)))
        for p, piece in enumerate(self.pieces):
            j2_secondary = footprint.junction == "J2" and p == 1
            if len(piece.bands) >= 2 and piece.connector == "none" and not j2_secondary:
                out.append(f"piece {p} has 2+ bands but no connector")
        junctions = self._junctions()
        junction = junctions[0] if junctions else None
        if footprint.junction == "J1":
            out += self._check_j1(junction, footprint)
        elif junction is not None:
            out.append(f"junction finger on a {footprint.junction} footprint (J1 only)")
        if footprint.junction == "J2" and any(len(pc.bands) >= 2 for pc in self.pieces):
            # The primary carries the connector when it can (2+ bands), else the secondary does.
            p = 0 if len(self.pieces[0].bands) >= 2 else 1
            side = _cut_side(footprint, p)
            if self.pieces[p].connector != side:
                role = ("primary", "secondary")[p]
                out.append(f"{role} connector must be on the cut side ({side})")
        return tuple(sorted(out))

    def _check_tree(self, footprint: FootprintPieces) -> list[str]:
        """Tree rules (more than two pieces): connector for 2+ bands; one band for every J1
        child and every piece incident to a J2 junction; one junction finger per J1 child, in
        the parent's band adjacent to the cut and its block facing the cut; no other
        junction fingers."""
        out: list[str] = []
        if len(self.pieces) != len(footprint.pieces):
            return out
        one_band: set[int] = set()
        for j in footprint.junctions:
            if j.kind == "J1":
                one_band.add(j.child)
            else:
                one_band |= {j.parent, j.child}
        for p, piece in enumerate(self.pieces):
            if len(piece.bands) >= 2 and piece.connector == "none":
                out.append(f"piece {p} has 2+ bands but no connector")
            if p in one_band and len(piece.bands) != 1:
                out.append(f"piece {p} must have exactly one band (junction rules)")
        where: dict[int, BayPosition] = {}
        for pos, bay in self._bays():
            if isinstance(bay, FingerBay) and bay.junction and bay.junction_to is not None:
                where[bay.junction_to] = pos
        j1_children = {j.child for j in footprint.junctions if j.kind == "J1"}
        for child in sorted(set(where) - j1_children):
            out.append(f"junction finger to piece {child}, which is not a J1 child")
        for j in footprint.junctions:
            if j.kind != "J1":
                continue
            host = where.get(j.child)
            if host is None:
                out.append(f"J1 child {j.child} needs a junction finger")
                continue
            if host[0] != j.parent:
                out.append(f"junction finger to piece {j.child} must be in piece {j.parent}")
                continue
            band = 0 if j.facing_block == "A" else len(self.pieces[j.parent].bands) - 1
            if (host[1], host[2]) != (band, j.facing_block):
                out.append(
                    f"junction finger to piece {j.child} must be in band {band} block"
                    f" {j.facing_block}"
                )
        return out

    def _check_j1(self, junction: BayPosition | None, footprint: FootprintPieces) -> list[str]:
        """J1 rules: one-band secondary; junction finger in the band/block facing the cut."""
        out: list[str] = []
        if len(self.pieces) >= 2 and len(self.pieces[1].bands) != 1:
            out.append("secondary must have exactly one band in a J1 footprint")
        if junction is None:
            out.append("J1 footprint needs a junction finger")
            return out
        facing = footprint.facing_block
        band = 0 if facing == "A" else len(self.pieces[0].bands) - 1
        if (junction[1], junction[2]) != (band, facing):
            out.append(f"junction finger must be in band {band} block {facing}")
        return out


def _repeated(runs: list[str]) -> set[str]:
    """Zones appearing in more than one run."""
    return {zone for zone, count in Counter(runs).items() if count > 1}


def _cut_side(footprint: FootprintPieces, p: int) -> Literal["start", "end"]:
    """``"end"`` if the cut lies on piece ``p``'s max-u edge, else ``"start"``."""
    if footprint.cut is None:  # pragma: no cover - a 2-piece footprint always has a cut
        raise ValueError("a J2 footprint has a cut")
    piece = footprint.pieces[p]
    (cx, cy), _ = footprint.cut
    if piece.spine_axis == "X":
        return "end" if cx == piece.rect.x2() else "start"
    return "end" if cy == piece.rect.y2() else "start"
