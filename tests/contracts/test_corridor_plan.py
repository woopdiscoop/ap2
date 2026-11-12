"""Tests K01-K07, S01-S03 (A.1), B01-B10 (A.2) and I01-I07 (A.3): CorridorPlan contract."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pydantic import ValidationError

from ale.contracts import export_schemas, lock
from ale.contracts.corridor_plan import (
    BandPlan,
    BlockPlan,
    ConnectorBay,
    CorridorPlan,
    FingerBay,
    PiecePlan,
    RoomBay,
    RoomPosition,
)
from ale.contracts.enums import MacroZone
from ale.contracts.footprint import FootprintPieces, decompose_footprint
from ale.contracts.geometry import ModulePolygon
from ale.contracts.models import Layout, PlanGeometry, Program, RoomSpec, Rulebook, SiteSpec
from ale.contracts.serialization import canonical_json, dump_yaml, load_yaml
from ale.contracts.taxonomy import Taxonomy
from ale.contracts.version import CONTRACTS_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]
NEW_MODULES = ("src/ale/contracts/corridor_plan.py", "src/ale/contracts/footprint.py")

P = MacroZone.PUBLIC
A = MacroZone.ADMINISTRATIVE
S = MacroZone.SERVICES

J1_POLY = ((0, 0), (600, 0), (600, 120), (200, 120), (200, 300), (0, 300))
J2_POLY = ((0, 0), (480, 0), (480, 180), (300, 180), (300, 300), (0, 300))


def room(r: str) -> RoomBay:
    return RoomBay(room=r)


def finger(left: tuple[str, ...] = (), right: tuple[str, ...] = (), **kw: Any) -> FingerBay:
    return FingerBay(left=left, right=right, **kw)


def band(a: list[Any] | None = None, b: list[Any] | None = None) -> BandPlan:
    return BandPlan(block_a=BlockPlan(bays=tuple(a or ())), block_b=BlockPlan(bays=tuple(b or ())))


def piece(a: list[Any], b: list[Any] | None = None) -> PiecePlan:
    """A 1-band piece."""
    return PiecePlan(bands=(band(a, b),))


def bands(*bs: BandPlan, connector: Any = "none") -> PiecePlan:
    """A piece with the given bands (min v first)."""
    return PiecePlan(bands=bs, connector=connector)


def plan(*pieces: PiecePlan) -> CorridorPlan:
    return CorridorPlan(pieces=pieces)


def sample_plan() -> CorridorPlan:
    """2 pieces, room bays, finger bays (one stack empty), junction in piece 0 band 0 block B."""
    return plan(
        piece(
            [room("R1"), finger(left=("R2", "R3")), room("R4")],
            [finger(junction=True), finger(left=("R5",), right=("R6#01", "R6#02"))],
        ),
        piece([finger(right=("R7",))], [room("R8")]),
    )


def fp(pts: tuple[tuple[int, int], ...]) -> FootprintPieces:
    return decompose_footprint(ModulePolygon(exterior=pts))


# --------------------------------------------------------------------------- K01 / K02


def test_K01_version() -> None:
    assert (
        CONTRACTS_VERSION == "1.7.0"
    )  # superseded by A.3 (I01), Q.4 (D01), A.4 (A401), G.1 (N01), then M.2, then M.2


# SHA-256 of the contract files as frozen at 1.0.0 (CONTRACTS.lock before amendment A.1),
# excluding version.py and export_schemas.py which A.1 is allowed to change.
FROZEN_1_0_0 = {
    "__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "area_rule.py": "505b80bbd784a6506f5a0e4fe5fd2391cf528dc7975cc77cf09c916f3f590508",
    "config.py": "5db57f921bc42f21430ce96e5aef0a4d94f837e412c6047f7b29b3345c60b536",
    "config.schema.json": "ce5951a079a932d0f83adc0a19f8c0611b12cfc497d6cff6896358724018920b",
    "enums.py": "5fea5b9660d5b51f6e201569057aa414cae3cbf86afe79436f4298e8fb2c9725",
    "geometry.py": "4070d990f5332b48491a2f131e727e27e2121c391e48182f4c9955454daad640",
    "lock.py": "ccb3ba95c119ab665e790d56d86a72ea8ca9f9f658dc7ff1372c378e01779ec2",
    "models.py": "a8358f9a81debc485842061c5a5c40d6ef4ba7f15fc76e7f1cb0772ef9ccda79",
    "orientation.py": "7d2101b6f1e0b9d45cc8c39dfe0deafd449f71a14fc42a277a5515cec893f646",
    "schemas/Layout.schema.json": (
        "4f779bdc6e75f38af590c00272af0bddc363313f866acd3d479d8bef01d9fd8a"
    ),
    "schemas/PlanGeometry.schema.json": (
        "1dc4d22cd17a8656880b3b0618461ba7b08eca3b1796caf85fbdaaae9cf923e8"
    ),
    "schemas/Program.schema.json": (
        "521eb46a6374e55b50ed1451ce736fdc3215702592999c7d98dffea10a069d58"
    ),
    "schemas/RoomSpec.schema.json": (
        "8d50705b597e46e495c4bf9d3982308af129e5a5f2882185e4a040a98fdef405"
    ),
    "schemas/Rulebook.schema.json": (
        "24551d5fee5c973f467d2285ab815ac09f3a24b7d27ff3c94ed261bcd1ea0121"
    ),
    "schemas/SiteSpec.schema.json": (
        "41eade547fdfb4c3c5887daa0774fe0c850c7b716bc0507cec211eba09216370"
    ),
    "schemas/Taxonomy.schema.json": (
        "06135921f40742fe25f8e572cae23951dcb40638cb35db31acee5db29058475b"
    ),
    "serialization.py": "3fd470528232615549e5efe8633de40801cab99226e8d32d0f631cfe51c82962",
    "taxonomy.py": "688300e552096184bf87fc5536460628e898956c0ba1d4b4fa9d0fb28596c107",
    "taxonomy.yaml": "888399b843277befc1d587755bbcaa2ccc838e4b4e9bdfb5732a18351a1022c5",
    "units.py": "dac72d439101d56721daa1c33f00c22dc7b6e701711c0c6633de9448dacd0e83",
    "validate.py": "584e09a06893408f5196a27a786cec28c736faffa2abdd8a73c7e9d8c500a28b",
}


def test_K02_existing_unchanged() -> None:
    current = lock.compute_lock(lock.PACKAGE_DIR)
    changed = sorted(rel for rel, digest in FROZEN_1_0_0.items() if current.get(rel) != digest)
    # Amendment Q.4 (contracts 1.4.0) adds ``FacadeConfig.max_depth_m`` (config model and its
    # schema); amendment A.4 (contracts 1.5.0) adds the site / room anchors (models.py and the
    # Program, RoomSpec and SiteSpec schemas; checked in tests/contracts/test_contracts_a4);
    # amendment G.1 (contracts 1.6.0) adds ``ModulePolygon.holes`` (geometry.py and the Layout
    # schema that embeds it).
    assert changed == [
        "config.py",
        "config.schema.json",
        "geometry.py",
        "models.py",
        "schemas/Layout.schema.json",
        "schemas/Program.schema.json",
        "schemas/RoomSpec.schema.json",
        "schemas/SiteSpec.schema.json",
    ]
    # export_schemas: list update only (the 1.0.0 models first, in order, then the new ones).
    models = export_schemas.SCHEMA_MODELS
    assert models == (
        RoomSpec,
        Program,
        SiteSpec,
        Layout,
        PlanGeometry,
        Rulebook,
        Taxonomy,
        CorridorPlan,
        FootprintPieces,
    )
    added = sorted(set(current) - set(FROZEN_1_0_0) - {"version.py", "export_schemas.py"})
    assert added == [
        "corridor_plan.py",
        "footprint.py",
        "schemas/CorridorPlan.schema.json",
        "schemas/FootprintPieces.schema.json",
    ]


# --------------------------------------------------------------------------- K03


def test_K03_roundtrip() -> None:
    x = sample_plan()
    back = CorridorPlan.model_validate_json(canonical_json(x))
    assert back == x
    assert canonical_json(back) == canonical_json(x)
    y = load_yaml(CorridorPlan, dump_yaml(x))
    assert y == x
    for restored in (back, y):
        a0 = restored.pieces[0].bands[0].block_a.bays
        assert [type(b) for b in a0] == [RoomBay, FingerBay, RoomBay]
        b0 = restored.pieces[0].bands[0].block_b.bays
        assert isinstance(b0[0], FingerBay)
        assert b0[0].junction is True
        assert b0[0].left == () and b0[0].right == ()
        assert isinstance(restored.pieces[1].bands[0].block_a.bays[0], FingerBay)
        assert restored.pieces[1].bands[0].block_a.bays[0].left == ()
    data = json.loads(canonical_json(x))
    assert data["schema_version"] == "ale.corridor_plan/2"
    assert data["pieces"][0]["bands"][0]["block_a"]["bays"][0] == {"kind": "room", "room": "R1"}
    schema = json.loads(
        (export_schemas.SCHEMA_DIR / "CorridorPlan.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(data)


# --------------------------------------------------------------------------- K04


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (lambda: plan(piece([room("R1"), finger(left=("R1",))])), "more than once: R1"),
        (lambda: plan(*(piece([room(f"R{k}")]) for k in range(13))), "1 to 12"),
        (lambda: plan(), "1 to 12"),
        (lambda: plan(piece([finger()])), "at least one room"),
        (lambda: plan(piece([finger(junction=True)])), "2-piece"),
        (
            lambda: plan(piece([room("R1")]), piece([finger(junction=True)])),
            r"pieces\[0\]",
        ),
        (
            lambda: plan(
                piece([finger(junction=True)], [finger(junction=True)]), piece([room("R1")])
            ),
            "at most one junction",
        ),
    ],
    ids=[
        "duplicate",
        "thirteen_pieces",
        "zero_pieces",
        "empty_finger",
        "junction_1_piece",
        "junction_piece1",
        "two_junctions",
    ],
)
def test_K04_validators(build: Any, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        build()


def test_K04_validators_raw_data() -> None:
    good = sample_plan().model_dump(mode="json")
    assert CorridorPlan.model_validate(good) == sample_plan()
    bad = json.loads(json.dumps(good))
    bad["pieces"][0]["bands"][0]["block_a"]["bays"][0] = {"kind": "corridor", "room": "R1"}
    with pytest.raises(ValidationError):
        CorridorPlan.model_validate(bad)
    with pytest.raises(ValidationError):
        RoomBay(room=1)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        FingerBay(left=("R1",), junction=1)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        RoomPosition(piece=0.0, band=0, block="A", bay=0, stack=None, index=None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- K05


def test_K05_room_ids_locate() -> None:
    x = plan(piece([room("R1"), finger(left=("R2", "R3"), right=("R4",))], [room("R5")]))
    assert x.room_ids() == ("R1", "R2", "R3", "R4", "R5")
    assert x.locate("R3") == RoomPosition(piece=0, band=0, block="A", bay=1, stack="left", index=1)
    assert x.locate("R4") == RoomPosition(piece=0, band=0, block="A", bay=1, stack="right", index=0)
    assert x.locate("R1") == RoomPosition(piece=0, band=0, block="A", bay=0, stack=None, index=None)
    r5 = x.locate("R5")
    assert r5.stack is None and r5.index is None and r5.block == "B" and r5.bay == 0
    with pytest.raises(KeyError):
        x.locate("X")


def test_K05_room_ids_two_pieces() -> None:
    x = sample_plan()
    assert x.room_ids() == ("R1", "R2", "R3", "R4", "R5", "R6#01", "R6#02", "R7", "R8")
    assert x.locate("R6#02") == RoomPosition(
        piece=0, band=0, block="B", bay=1, stack="right", index=1
    )
    assert x.locate("R7") == RoomPosition(piece=1, band=0, block="A", bay=0, stack="right", index=0)


# --------------------------------------------------------------------------- K06


def test_K06_zone_violations() -> None:
    split = plan(piece([room("R1"), room("R2"), room("R3")]))
    assert split.zone_violations({"R1": P, "R2": A, "R3": P}) == (
        "zone PUBLIC split in piece 0 band 0 block A",
    )
    mixed = plan(piece([room("R1"), finger(left=("R2",), right=("R3",))]))
    out = mixed.zone_violations({"R1": A, "R2": A, "R3": S})
    assert "finger bay 1 of piece 0 band 0 block A mixes zones" in out
    assert out == tuple(sorted(out))
    clean = sample_plan()
    zones = {"R1": P, "R2": P, "R3": P, "R4": A, "R5": S, "R6#01": S, "R6#02": S}
    assert clean.zone_violations({**zones, "R7": A, "R8": P}) == ()


def test_K06_zone_violations_details() -> None:
    # Sorted output, several blocks/pieces, block B naming.
    x = plan(
        piece([room("R1")], [room("R2"), finger(left=("R3",), right=("R4",)), room("R5")]),
        piece([room("R6"), room("R7"), room("R8")]),
    )
    zones = {"R1": P, "R2": A, "R3": P, "R4": A, "R5": A, "R6": S, "R7": P, "R8": S}
    assert x.zone_violations(zones) == (
        "finger bay 1 of piece 0 band 0 block B mixes zones",
        "zone ADMINISTRATIVE split in piece 0 band 0 block B",
        "zone SERVICES split in piece 1 band 0 block A",
    )
    # The junction finger is ignored for contiguity (its rooms do not break a run).
    j = plan(piece([room("R1"), finger(left=("R2",), junction=True), room("R3")]), piece([]))
    assert j.zone_violations({"R1": P, "R2": A, "R3": P}) == ()
    # A finger's stacks are read left then right for contiguity.
    f = plan(piece([room("R1"), finger(left=("R2",), right=("R3",)), room("R4")]))
    assert f.zone_violations({"R1": P, "R2": A, "R3": A, "R4": P}) == (
        "zone PUBLIC split in piece 0 band 0 block A",
    )
    with pytest.raises(KeyError):
        f.zone_violations({"R1": P, "R2": A, "R3": A})


# --------------------------------------------------------------------------- K07


def test_K07_check_against() -> None:
    j1 = fp(J1_POLY)
    assert j1.junction == "J1" and j1.facing_block == "B"
    good = plan(piece([room("R1")], [finger(left=("R2",), junction=True)]), piece([room("R3")]))
    ids = ["R1", "R2", "R3"]
    assert good.check_against(ids, j1) == ()
    # Missing / unknown ids.
    assert good.check_against(["R1", "R2", "R7"], j1) == ("missing room R7", "unknown room R3")
    # J1 footprint without junction finger.
    no_junction = plan(piece([room("R1")], [finger(left=("R2",))]), piece([room("R3")]))
    out = no_junction.check_against(ids, j1)
    assert out == ("J1 footprint needs a junction finger",)
    # Junction finger in the wrong block.
    wrong = plan(piece([finger(left=("R2",), junction=True)], [room("R1")]), piece([room("R3")]))
    assert wrong.check_against(ids, j1) == ("junction finger must be in band 0 block B",)


def test_K07_check_against_counts_and_junction_kinds() -> None:
    rect = fp(((0, 0), (240, 0), (240, 180), (0, 180)))
    j2 = fp(J2_POLY)
    one = plan(piece([room("R1")], [room("R2")]))
    assert one.check_against(["R1", "R2"], rect) == ()
    assert one.check_against(["R1", "R2"], j2) == ("plan has 1 piece(s), footprint has 2",)
    two = plan(piece([room("R1")]), piece([room("R2")]))
    assert two.check_against(("R1", "R2"), j2) == ()
    assert two.check_against(("R1", "R2"), rect) == ("plan has 2 piece(s), footprint has 1",)
    with_junction = plan(piece([room("R1"), finger(junction=True)]), piece([room("R2")]))
    assert with_junction.check_against(iter(["R1", "R2"]), j2) == (
        "junction finger on a J2 footprint (J1 only)",
    )


# --------------------------------------------------------------------------- B01-B09 (A.2)


BASE_REV = "3dcd970"  # spec commit of Ticket A.2, before the amendment


def test_B01_version_schema() -> None:
    assert (
        CONTRACTS_VERSION == "1.7.0"
    )  # superseded by A.3 (I01), Q.4 (D01), A.4 (A401), G.1 (N01), then M.2, then M.2
    # ``pieces`` is required, so the default is read from the field (CorridorPlan() is invalid).
    assert CorridorPlan.model_fields["schema_version"].default == "ale.corridor_plan/2"
    assert plan(piece([room("R1")])).schema_version == "ale.corridor_plan/2"
    assert export_schemas.main(["--check"]) == 0
    assert lock.main(["--check"]) == 0


#: Lines of ``models.py`` that amendment A.4 (contracts 1.5.0) replaced; nothing else of the
#: A.2 version may be removed from it (the new models and fields are additions).
A4_REPLACED_LINES = {
    "-    def _floor_zero(cls, v: int) -> int:",
    "-        if v != 0:",
    '-            raise ValueError("floor must be 0 in v1")',
    '-    """Buildable site (metres, y-up)."""',
}


#: Lines of ``footprint.py`` / ``geometry.py`` that amendment G.1 (contracts 1.6.0) replaced
#: (the N-piece decomposition and courtyard holes; the rectangle / L logic is unchanged).
G1_REPLACED_LINES = {
    "-from pydantic import BaseModel, ConfigDict",
    '-__all__ = ["FootprintPieces", "Piece", "decompose_footprint"]',
    '-UNSUPPORTED_MESSAGE = "v1 supports rectangular and L-shaped footprints only"',
    "-    ``pieces``: primary first (one piece for a rectangle, two for an L). ``cut``: endpoints"
    " of",
    "-    the shared cut segment (lower/left endpoint first), ``None`` for a rectangle.",
    '-    ``facing_block``: J1 only, the block of the primary (``"A"`` lower/left, ``"B"``',
    "-    upper/right) that faces the cut.",
    '-        junction="J1" if parallel else "J2",',
    '-    """Decompose a rectangular or L-shaped module footprint into 1 or 2 pieces.',
    "-    secondary spine perpendicular to the cut line. Raises ``ValueError`` for any other vertex"
    " count.",
    "-    if len(pts) == 4:",
    "-    if len(pts) == 6:",
    "-    raise ValueError(UNSUPPORTED_MESSAGE)",
    '-        """Area in module² cells (exact shoelace)."""',
    "-        return _signed_area2(self.exterior) // 2",
    "-        return shapely.Polygon(g.exterior)",
}


#: Lines of ``footprint.py`` / ``geometry.py`` / ``models.py`` that amendment M.2 (contracts
#: 1.7.0) replaced (solids, ``Layout.fixed``; the hole validation became a shared ring check).
M2_REPLACED_LINES = {
    "-    :data:`MAX_PIECES` pieces are needed.",
    '-        if isinstance(out, dict) and not out.get("holes"):',
    '-            out.pop("holes", None)',
    '-        """Area in module² cells (exact shoelace, holes subtracted)."""',
    "-        holes = sum(_signed_area2(h) for h in self.holes)  # clockwise rings: negative",
    "-def _check_holes(",
    "-    exterior: tuple[ModulePoint, ...], holes: tuple[tuple[ModulePoint, ...], ...]",
    "-) -> None:",
    '-    """Validate courtyard rings: rectilinear, clockwise, no collinear neighbours, inside."""',
    "-    import shapely",
    "-",
    "-    for k, ring in enumerate(holes):",
    '-            raise ValueError(f"hole {k} needs at least 4 vertices")',
    '-                raise ValueError(f"hole {k} ed'
    'ge {i} is not axis-parallel or has zero length")',
    '-            raise ValueError(f"hole {k} has collinear consecutive edges")',
    '-            raise ValueError(f"hole {k} vertices must be clockwise")',
    "-        return shapely.Polygon(g.exterior, g.holes)",
    "-    party wall. None of the A.4 fields is used by the v1 engines.",
    '-    """Output of Phase 3: placed rooms on the module grid (+y up, 1 unit = 1 module)."""',
    "-    model_config = _CONFIG",
    "-        ids = [p.instance_id for p in (*self.rooms, *self.circulation)]",
    '-        for name in ("rooms", "circulation"):',
}


def test_B02_footprint_unchanged() -> None:
    files = (
        "src/ale/contracts/footprint.py",
        "src/ale/contracts/geometry.py",
    )
    proc = subprocess.run(
        ["git", "diff", BASE_REV, "--", *files],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if proc.returncode != 0:  # pragma: no cover - not a git checkout / revision unknown
        pytest.skip(f"git diff unavailable: {proc.stderr.strip()}")
    removed_fp = {
        line for line in proc.stdout.splitlines() if line.startswith("-") and line[:3] != "---"
    }
    assert removed_fp <= G1_REPLACED_LINES | M2_REPLACED_LINES
    models = subprocess.run(
        ["git", "diff", BASE_REV, "--", "src/ale/contracts/models.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    removed = {
        line for line in models.stdout.splitlines() if line.startswith("-") and line[:3] != "---"
    }
    assert removed <= A4_REPLACED_LINES | M2_REPLACED_LINES


def b03_plan() -> CorridorPlan:
    return plan(
        bands(
            band([room("R1"), finger(left=("R2",), right=("R3",))], [room("R4")]),
            band([], [finger(left=("R5", "R6"))]),
            band([room("R7")], [finger(junction=True), room("R8")]),
            connector="end",
        ),
        piece([finger(right=("R9",))], [room("R10")]),
    )


def test_B03_roundtrip() -> None:
    x = b03_plan()
    back = CorridorPlan.model_validate_json(canonical_json(x))
    assert back == x
    assert canonical_json(back) == canonical_json(x)
    y = load_yaml(CorridorPlan, dump_yaml(x))
    assert y == x
    assert canonical_json(y) == canonical_json(x)
    data = json.loads(canonical_json(x))
    assert data["pieces"][0]["connector"] == "end"
    assert len(data["pieces"][0]["bands"]) == 3
    assert data["pieces"][1]["connector"] == "none"
    schema = json.loads(
        (export_schemas.SCHEMA_DIR / "CorridorPlan.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(data)
    bad = json.loads(canonical_json(x))
    bad["pieces"][1]["bands"] = []
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(bad)


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (lambda: plan(bands()), "at least 1"),
        (lambda: plan(bands(*[band() for _ in range(7)], connector="start")), "at most 6"),
        (lambda: plan(bands(band([room("R1")]), connector="start")), "1-band piece"),
        (
            lambda: plan(
                bands(band([room("R1")]), band([], [finger(left=("R1",))]), connector="end")
            ),
            "more than once: R1",
        ),
        (
            lambda: plan(piece([room("R1")]), piece([], [finger(junction=True)])),
            r"pieces\[0\]",
        ),
    ],
    ids=["zero_bands", "seven_bands", "one_band_connector", "dup_across_bands", "junction_p1"],
)
def test_B04_validators(build: Any, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        build()


def test_B04_validators_ok() -> None:
    six = bands(*[band() for _ in range(6)], connector="start")
    assert len(six.bands) == 6
    # A junction finger in any band of pieces[0] passes the model validator.
    x = plan(bands(band(), band([finger(junction=True)]), connector="end"), piece([room("R1")]))
    assert x.locate("R1").piece == 1
    with pytest.raises(ValidationError):
        PiecePlan(bands=(band(),), connector="middle")  # type: ignore[arg-type]


def test_B05_order_locate() -> None:
    x = plan(bands(band([room("R1")], [room("R2")]), band([finger(left=("R3", "R4"))], [])))
    assert x.room_ids() == ("R1", "R2", "R3", "R4")
    assert x.locate("R4") == RoomPosition(piece=0, band=1, block="A", bay=0, stack="left", index=1)
    assert x.locate("R2") == RoomPosition(piece=0, band=0, block="B", bay=0, stack=None, index=None)


def test_B06_zones_per_band() -> None:
    x = plan(bands(band([room("R1")]), band([room("R2")])))
    assert x.zone_violations({"R1": P, "R2": P}) == ()
    split = plan(bands(band([room("R0")]), band([room("R1"), room("R2"), room("R3")])))
    assert split.zone_violations({"R0": P, "R1": P, "R2": A, "R3": P}) == (
        "zone PUBLIC split in piece 0 band 1 block A",
    )
    mixed = plan(bands(band([room("R0")]), band([], [room("R1"), finger(("R2",), ("R3",))])))
    assert mixed.zone_violations({"R0": P, "R1": P, "R2": A, "R3": S}) == (
        "finger bay 1 of piece 0 band 1 block B mixes zones",
    )


RECT = ((0, 0), (240, 0), (240, 180), (0, 180))


def test_B07_connector_rules() -> None:
    rect = fp(RECT)
    ids = ["R1", "R2"]
    none = plan(bands(band([room("R1")]), band([room("R2")])))
    assert none.check_against(ids, rect) == ("piece 0 has 2+ bands but no connector",)
    start = plan(bands(band([room("R1")]), band([room("R2")]), connector="start"))
    assert start.check_against(ids, rect) == ()


def test_B08_J2_rules() -> None:
    j2 = fp(J2_POLY)
    assert j2.junction == "J2"
    assert j2.cut is not None and j2.cut[0][0] == j2.pieces[0].rect.x2()
    ids = ["R1", "R2", "R3", "R4"]
    one = plan(piece([room("R1")], [room("R2")]), piece([room("R3")], [room("R4")]))
    assert one.check_against(ids, j2) == ()
    wrong = plan(
        bands(band([room("R1")]), band([room("R2")]), connector="start"),
        piece([room("R3")], [room("R4")]),
    )
    out = wrong.check_against(ids, j2)
    assert len(out) == 1 and "cut side (end)" in out[0]
    assert out == ("primary connector must be on the cut side (end)",)
    good = plan(
        bands(band([room("R1")]), band([room("R2")]), connector="end"),
        bands(band([room("R3")]), band([room("R4")])),
    )
    assert good.check_against(ids, j2) == ()
    # 1-band primary + multi-band secondary: the secondary's connector goes on its cut side
    # (site_L: the cut is the secondary's min-x edge -> "start").
    sec_end = plan(
        piece([room("R1")], [room("R2")]),
        bands(band([room("R3")]), band([room("R4")]), connector="end"),
    )
    out = sec_end.check_against(ids, j2)
    assert len(out) == 1 and "secondary connector must be on the cut side (start)" in out[0]
    sec_start = plan(
        piece([room("R1")], [room("R2")]),
        bands(band([room("R3")]), band([room("R4")]), connector="start"),
    )
    assert sec_start.check_against(ids, j2) == ()
    sec_none = plan(
        piece([room("R1")], [room("R2")]), bands(band([room("R3")]), band([room("R4")]))
    )
    assert sec_none.check_against(ids, j2) == (
        "secondary connector must be on the cut side (start)",
    )


def test_B08_J2_cut_side_variants() -> None:
    # site_L mirrored in x: the cut lies on the primary's min-x edge ("start").
    mirrored = fp(((480, 300), (180, 300), (180, 180), (0, 180), (0, 0), (480, 0)))
    # Vertical variants (primary spine Y): cut on max y / min y.
    tall = fp(((300, 0), (300, 300), (180, 300), (180, 480), (0, 480), (0, 0)))
    tall_low = fp(((0, 480), (0, 0), (180, 0), (180, 180), (300, 180), (300, 480)))
    two = plan(bands(band([room("R1")]), band([room("R2")]), connector="end"), piece([room("R3")]))
    ids = ["R1", "R2", "R3"]
    got = {}
    for name, f in (("mirrored", mirrored), ("tall", tall), ("tall_low", tall_low)):
        assert f.junction == "J2", name
        got[name] = two.check_against(ids, f)
    assert tall.pieces[0].spine_axis == "Y" and tall_low.pieces[0].spine_axis == "Y"
    assert got == {
        "mirrored": ("primary connector must be on the cut side (start)",),
        "tall": (),
        "tall_low": ("primary connector must be on the cut side (start)",),
    }


J1_IDS = ["R1", "R2", "R3", "R4"]


def test_B09_J1_rules() -> None:
    j1 = fp(J1_POLY)
    assert j1.junction == "J1" and j1.facing_block == "B"
    sec2 = plan(
        piece([room("R1")], [finger(left=("R2",), junction=True)]),
        bands(band([room("R3")]), band([room("R4")]), connector="start"),
    )
    out = sec2.check_against(J1_IDS, j1)
    assert any(m.startswith("secondary must have exactly one band") for m in out)
    assert out == ("secondary must have exactly one band in a J1 footprint",)
    in_band0 = plan(
        bands(
            band([room("R1")], [finger(left=("R2",), junction=True)]),
            band([room("R3")]),
            band(),
            connector="start",
        ),
        piece([room("R4")]),
    )
    assert in_band0.check_against(J1_IDS, j1) == ("junction finger must be in band 2 block B",)
    in_band2 = plan(
        bands(
            band([room("R1")]),
            band([room("R3")]),
            band([], [finger(left=("R2",), junction=True)]),
            connector="start",
        ),
        piece([room("R4")]),
    )
    assert in_band2.check_against(J1_IDS, j1) == ()
    wrong_block = plan(
        bands(
            band([room("R1")]),
            band([room("R3")]),
            band([finger(left=("R2",), junction=True)]),
            connector="start",
        ),
        piece([room("R4")]),
    )
    assert wrong_block.check_against(J1_IDS, j1) == ("junction finger must be in band 2 block B",)
    # Missing junction is still reported alongside a multi-band secondary.
    none = plan(piece([room("R1"), room("R2")]), bands(band([room("R3")]), band([room("R4")])))
    assert none.check_against(J1_IDS, j1) == (
        "J1 footprint needs a junction finger",
        "piece 1 has 2+ bands but no connector",
        "secondary must have exactly one band in a J1 footprint",
    )


def test_B09_J1_facing_A() -> None:
    # J1_POLY mirrored in x: the cut lies on the primary's left side -> facing block A.
    j1a = fp(((600, 300), (400, 300), (400, 120), (0, 120), (0, 0), (600, 0)))
    assert j1a.junction == "J1" and j1a.facing_block == "A"
    ok = plan(
        bands(band([finger(left=("R2",), junction=True)]), band([room("R1")]), connector="end"),
        piece([room("R3")]),
    )
    assert ok.check_against(["R1", "R2", "R3"], j1a) == ()
    bad = plan(
        bands(band([room("R1")]), band([finger(left=("R2",), junction=True)]), connector="end"),
        piece([room("R3")]),
    )
    assert bad.check_against(["R1", "R2", "R3"], j1a) == (
        "junction finger must be in band 0 block A",
    )


# --------------------------------------------------------------------------- S01-S03


def test_S01_schemas() -> None:
    assert export_schemas.main(["--check"]) == 0
    names = set(export_schemas.render_schemas())
    assert {"CorridorPlan.schema.json", "FootprintPieces.schema.json"} <= names
    for name in ("CorridorPlan.schema.json", "FootprintPieces.schema.json"):
        assert (export_schemas.SCHEMA_DIR / name).is_file()
    schema = json.loads(
        (export_schemas.SCHEMA_DIR / "FootprintPieces.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(json.loads(canonical_json(fp(J1_POLY))))


def test_S02_lock(capsys: pytest.CaptureFixture[str]) -> None:
    assert lock.main(["--check"]) == 0
    assert "OK" in capsys.readouterr().out


def _tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=50,
    )


@pytest.mark.slow
@pytest.mark.timeout(120)
def test_S03_gates() -> None:
    if shutil.which("ruff") is None and _tool("ruff", "--version").returncode != 0:
        pytest.skip("ruff not installed")  # pragma: no cover
    files = [*NEW_MODULES, "tests/contracts/test_corridor_plan.py"]
    files.append("tests/contracts/test_footprint.py")
    proc = _tool("ruff", "check", *files)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = _tool("ruff", "format", "--check", *files)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = _tool("mypy", *NEW_MODULES)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.slow
@pytest.mark.timeout(120)
def test_B10_gates() -> None:
    """ruff / format / mypy strict on the A.2 files (suite and coverage gates run outside)."""
    if shutil.which("ruff") is None and _tool("ruff", "--version").returncode != 0:
        pytest.skip("ruff not installed")  # pragma: no cover
    files = ["src/ale/contracts/corridor_plan.py", "tests/contracts/test_corridor_plan.py"]
    files.append("tests/contracts/test_models.py")
    proc = _tool("ruff", "check", *files)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = _tool("ruff", "format", "--check", *files)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = _tool("mypy", "src/ale/contracts/corridor_plan.py", "src/ale/contracts/version.py")
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --------------------------------------------------------------------------- I01-I07 (A.3)


def conn() -> ConnectorBay:
    return ConnectorBay()


def inner_plan() -> CorridorPlan:
    """A valid 2-band ``inner`` piece; one block holds just the marker."""
    return plan(
        bands(
            band([room("R1"), conn(), room("R2")], [conn(), finger(left=("R3",))]),
            band([conn()], [room("R4"), conn()]),
            connector="inner",
        )
    )


def inner2(a0: list[Any], a1: list[Any]) -> PiecePlan:
    """A 2-band ``inner`` piece: ``a0`` / ``a1`` = block A of band 0 / 1 (each with its marker),
    blocks B hold just the marker."""
    return bands(band(a0, [conn()]), band(a1, [conn()]), connector="inner")


def test_I01_version_schema() -> None:
    assert (
        CONTRACTS_VERSION == "1.7.0"
    )  # superseded by Q.4 (D01), A.4 (A401), then G.1 (N01), then M.2
    assert export_schemas.main(["--check"]) == 0
    assert lock.main(["--check"]) == 0
    schema = json.loads(
        (export_schemas.SCHEMA_DIR / "CorridorPlan.schema.json").read_text(encoding="utf-8")
    )
    data = json.loads(canonical_json(inner_plan()))
    jsonschema.Draft202012Validator(schema).validate(data)
    assert data["pieces"][0]["connector"] == "inner"
    assert data["pieces"][0]["bands"][0]["block_a"]["bays"][1] == {"kind": "connector"}


# canonical_json SHA-256 of the plans as serialised by the 1.2.0 contract (pre-A.3).
GOLDEN_1_2_0 = {
    "sample_plan": "2295742c8710c3e16870ede1b98f1427c7e6da6990268671bedfc66457bc99e0",
    "b03_plan": "73925cb933e9352159c4fb38613efb2eba3eb23d519fe4140bd54929dcce7a9a",
}

EXISTING_PLANS: dict[str, Any] = {
    "sample_plan": sample_plan,
    "b03_plan": b03_plan,
    "k05": lambda: plan(
        piece([room("R1"), finger(left=("R2", "R3"), right=("R4",))], [room("R5")])
    ),
    "k07_j1": lambda: plan(
        piece([room("R1")], [finger(left=("R2",), junction=True)]), piece([room("R3")])
    ),
    "b04_six": lambda: plan(
        bands(*[band() for _ in range(5)], band([room("R1")]), connector="start")
    ),
    "b08_good": lambda: plan(
        bands(band([room("R1")]), band([room("R2")]), connector="end"),
        bands(band([room("R3")]), band([room("R4")])),
    ),
    "b09_band2": lambda: plan(
        bands(
            band([room("R1")]),
            band([room("R3")]),
            band([], [finger(left=("R2",), junction=True)]),
            connector="start",
        ),
        piece([room("R4")]),
    ),
}


@pytest.mark.parametrize("name", sorted(EXISTING_PLANS))
def test_I02_backward(name: str) -> None:
    x = EXISTING_PLANS[name]()
    raw = canonical_json(x)
    assert b'"connector"}' not in raw  # no marker bays
    back = CorridorPlan.model_validate_json(raw)
    assert back == x
    assert canonical_json(back) == raw
    assert load_yaml(CorridorPlan, dump_yaml(x)) == x
    assert CorridorPlan.model_validate(x.model_dump(mode="json")) == x
    if name in GOLDEN_1_2_0:
        assert hashlib.sha256(raw).hexdigest() == GOLDEN_1_2_0[name]


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (
            lambda: PiecePlan(bands=(band([conn(), room("R1")]),), connector="inner"),
            "1-band piece",
        ),
        (
            lambda: bands(band([room("R1"), conn()], [conn()]), band(), connector="start"),
            "only allowed in an inner-connector piece",
        ),
        (
            lambda: bands(band([room("R1"), conn()]), band(), connector="none"),
            "only allowed in an inner-connector piece",
        ),
        (
            lambda: bands(band([room("R1"), conn()], [conn()]), band([conn()]), connector="inner"),
            "got 0 in band 1 block B",
        ),
        (
            lambda: inner2([conn(), room("R1"), conn()], [conn()]),
            "got 2 in band 0 block A",
        ),
    ],
    ids=["one_band", "marker_in_start", "marker_in_none", "block_lacks_marker", "two_markers"],
)
def test_I03_validators(build: Any, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        build()


def test_I03_validators_ok() -> None:
    x = inner_plan()
    assert x.pieces[0].connector == "inner"
    back = CorridorPlan.model_validate_json(canonical_json(x))
    assert back == x
    assert isinstance(back.pieces[0].bands[1].block_a.bays[0], ConnectorBay)
    assert load_yaml(CorridorPlan, dump_yaml(x)) == x
    with pytest.raises(ValidationError):
        ConnectorBay(kind="room")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ConnectorBay(room="R1")  # type: ignore[call-arg]


def test_I04_locate_and_ids() -> None:
    x = inner_plan()
    assert x.room_ids() == ("R1", "R2", "R3", "R4")
    assert x.locate("R1") == RoomPosition(piece=0, band=0, block="A", bay=0, stack=None, index=None)
    assert x.locate("R2") == RoomPosition(piece=0, band=0, block="A", bay=2, stack=None, index=None)
    assert x.locate("R3") == RoomPosition(piece=0, band=0, block="B", bay=1, stack="left", index=0)
    r2 = x.locate("R2")
    assert x.pieces[0].bands[0].block_a.bays[r2.bay] == room("R2")
    with pytest.raises(KeyError):
        x.locate("connector")


def test_I05_zones() -> None:
    def one_block(bays: list[Any]) -> CorridorPlan:
        return plan(inner2(bays, [conn()]))

    across = one_block([room("R1"), conn(), room("R2")])
    assert across.zone_violations({"R1": P, "R2": P}) == ()
    around = one_block([room("R1"), room("R2"), conn(), room("R3"), finger(left=("R4",))])
    assert around.zone_violations({"R1": P, "R2": A, "R3": A, "R4": P}) == ()
    before = one_block([room("R1"), room("R2"), room("R3"), conn(), room("R4")])
    assert before.zone_violations({"R1": P, "R2": A, "R3": P, "R4": P}) == (
        "zone PUBLIC split in piece 0 band 0 block A",
    )
    after = one_block([room("R0"), conn(), room("R1"), room("R2"), room("R3")])
    assert after.zone_violations({"R0": S, "R1": P, "R2": A, "R3": P}) == (
        "zone PUBLIC split in piece 0 band 0 block A",
    )
    # Reported once even when split on both sides.
    rooms6 = [room(f"R{i}") for i in range(1, 7)]
    both = one_block([*rooms6[:3], conn(), *rooms6[3:]])
    zones = {"R1": P, "R2": A, "R3": P, "R4": P, "R5": A, "R6": P}
    assert both.zone_violations(zones) == ("zone PUBLIC split in piece 0 band 0 block A",)


def test_I06_J2() -> None:
    j2 = fp(J2_POLY)
    ids = ["R1", "R2", "R3", "R4"]
    inner_a = inner2([room("R1"), conn()], [conn(), room("R2")])
    inner_b = inner2([room("R3"), conn()], [conn(), room("R4")])
    inner_primary = plan(inner_a, piece([room("R3")], [room("R4")]))
    assert inner_primary.check_against(ids, j2) == (
        "primary connector must be on the cut side (end)",
    )
    # Secondary rule: "inner" does not satisfy the cut-side requirement either.
    inner_secondary = plan(piece([room("R1")], [room("R2")]), inner_b)
    assert inner_secondary.check_against(ids, j2) == (
        "secondary connector must be on the cut side (start)",
    )
    # Allowed where no cut-side connector is required: a J2 secondary when the primary carries
    # it, and a multi-band piece of a rectangle (it counts as having a connector).
    ok_secondary = plan(bands(band([room("R1")]), band([room("R2")]), connector="end"), inner_b)
    assert ok_secondary.check_against(ids, j2) == ()
    rect = plan(inner2([room("R1"), conn()], [conn(), room("R2")]))
    assert rect.check_against(["R1", "R2"], fp(RECT)) == ()


@pytest.mark.slow
@pytest.mark.timeout(120)
def test_I07_gates() -> None:
    """ruff / format on the A.3 files, mypy strict on the contracts package (suite and coverage
    gates run outside)."""
    if shutil.which("ruff") is None and _tool("ruff", "--version").returncode != 0:
        pytest.skip("ruff not installed")  # pragma: no cover
    files = ["src/ale/contracts/corridor_plan.py", "tests/contracts/test_corridor_plan.py"]
    files.append("src/ale/contracts/version.py")
    proc = _tool("ruff", "check", *files)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = _tool("ruff", "format", "--check", *files)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = _tool("mypy", "src/ale/contracts")
    assert proc.returncode == 0, proc.stdout + proc.stderr
