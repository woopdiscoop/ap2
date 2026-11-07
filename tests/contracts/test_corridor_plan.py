"""Tests K01-K07 and S01-S03 (Ticket A.1): CorridorPlan contract amendment."""

from __future__ import annotations

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
    BlockPlan,
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


def piece(a: list[Any], b: list[Any] | None = None) -> PiecePlan:
    return PiecePlan(block_a=BlockPlan(bays=tuple(a)), block_b=BlockPlan(bays=tuple(b or ())))


def plan(*pieces: PiecePlan) -> CorridorPlan:
    return CorridorPlan(pieces=pieces)


def sample_plan() -> CorridorPlan:
    """2 pieces, room bays, finger bays (one stack empty), junction finger in piece 0 block B."""
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
    assert CONTRACTS_VERSION == "1.1.0"


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
    assert changed == []
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
        a0 = restored.pieces[0].block_a.bays
        assert [type(b) for b in a0] == [RoomBay, FingerBay, RoomBay]
        b0 = restored.pieces[0].block_b.bays
        assert isinstance(b0[0], FingerBay)
        assert b0[0].junction is True
        assert b0[0].left == () and b0[0].right == ()
        assert isinstance(restored.pieces[1].block_a.bays[0], FingerBay)
        assert restored.pieces[1].block_a.bays[0].left == ()
    data = json.loads(canonical_json(x))
    assert data["schema_version"] == "ale.corridor_plan/1"
    assert data["pieces"][0]["block_a"]["bays"][0] == {"kind": "room", "room": "R1"}
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
        (lambda: plan(piece([room("R1")]), piece([room("R2")]), piece([room("R3")])), "1 or 2"),
        (lambda: plan(), "1 or 2"),
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
        "three_pieces",
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
    bad["pieces"][0]["block_a"]["bays"][0] = {"kind": "corridor", "room": "R1"}
    with pytest.raises(ValidationError):
        CorridorPlan.model_validate(bad)
    with pytest.raises(ValidationError):
        RoomBay(room=1)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        FingerBay(left=("R1",), junction=1)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        RoomPosition(piece=0.0, block="A", bay=0, stack=None, index=None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- K05


def test_K05_room_ids_locate() -> None:
    x = plan(piece([room("R1"), finger(left=("R2", "R3"), right=("R4",))], [room("R5")]))
    assert x.room_ids() == ("R1", "R2", "R3", "R4", "R5")
    assert x.locate("R3") == RoomPosition(piece=0, block="A", bay=1, stack="left", index=1)
    assert x.locate("R4") == RoomPosition(piece=0, block="A", bay=1, stack="right", index=0)
    assert x.locate("R1") == RoomPosition(piece=0, block="A", bay=0, stack=None, index=None)
    r5 = x.locate("R5")
    assert r5.stack is None and r5.index is None and r5.block == "B" and r5.bay == 0
    with pytest.raises(KeyError):
        x.locate("X")


def test_K05_room_ids_two_pieces() -> None:
    x = sample_plan()
    assert x.room_ids() == ("R1", "R2", "R3", "R4", "R5", "R6#01", "R6#02", "R7", "R8")
    assert x.locate("R6#02") == RoomPosition(piece=0, block="B", bay=1, stack="right", index=1)
    assert x.locate("R7") == RoomPosition(piece=1, block="A", bay=0, stack="right", index=0)


# --------------------------------------------------------------------------- K06


def test_K06_zone_violations() -> None:
    split = plan(piece([room("R1"), room("R2"), room("R3")]))
    assert split.zone_violations({"R1": P, "R2": A, "R3": P}) == (
        "zone PUBLIC split in piece 0 block A",
    )
    mixed = plan(piece([room("R1"), finger(left=("R2",), right=("R3",))]))
    out = mixed.zone_violations({"R1": A, "R2": A, "R3": S})
    assert "finger bay 1 of piece 0 block A mixes zones" in out
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
        "finger bay 1 of piece 0 block B mixes zones",
        "zone ADMINISTRATIVE split in piece 0 block B",
        "zone SERVICES split in piece 1 block A",
    )
    # The junction finger is ignored for contiguity (its rooms do not break a run).
    j = plan(piece([room("R1"), finger(left=("R2",), junction=True), room("R3")]), piece([]))
    assert j.zone_violations({"R1": P, "R2": A, "R3": P}) == ()
    # A finger's stacks are read left then right for contiguity.
    f = plan(piece([room("R1"), finger(left=("R2",), right=("R3",)), room("R4")]))
    assert f.zone_violations({"R1": P, "R2": A, "R3": A, "R4": P}) == (
        "zone PUBLIC split in piece 0 block A",
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
    assert wrong.check_against(ids, j1) == ("junction finger in block A, expected facing block B",)


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
