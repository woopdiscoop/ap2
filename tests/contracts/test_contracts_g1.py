"""Tests N01, N02, N07 and the contract parts of N05 (Ticket G.1): contracts 1.6.0.

N01 compares rectangle / L decompositions and the P8 / P25 / P60 layouts (seed-3 start,
annealing seed 6, Q.3 budgets) with SHA-256 digests computed with the code at the base commit
of G.1 (``bf798b6``), before any change.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

_TESTS = Path(__file__).resolve().parent.parent
for _sub in ("optimize", "program", "contracts", "."):
    if str(_TESTS / _sub) not in sys.path:
        sys.path.insert(0, str(_TESTS / _sub))

import g1_compat  # noqa: E402
from fixtures import FIXTURE_PAIRS, load_program, load_site  # noqa: E402
from optimize_helpers import (  # noqa: E402
    ANNEAL_ITER,
    ANNEAL_SEED,
    SEED_ATTEMPTS,
    load_test_rulebook,
    prepare,
)

from ale.config import AleConfig  # noqa: E402
from ale.contracts import export_schemas, lock  # noqa: E402
from ale.contracts.corridor_plan import (  # noqa: E402
    MAX_PIECES as PLAN_MAX_PIECES,
)
from ale.contracts.corridor_plan import (  # noqa: E402
    BandPlan,
    BlockPlan,
    CorridorPlan,
    FingerBay,
    PiecePlan,
    RoomBay,
)
from ale.contracts.footprint import (  # noqa: E402
    MAX_PIECES,
    FootprintPieces,
    Junction,
    Piece,
    decompose_footprint,
)
from ale.contracts.geometry import ModulePolygon, ModuleRect, to_shapely  # noqa: E402
from ale.contracts.serialization import canonical_json  # noqa: E402
from ale.contracts.version import CONTRACTS_VERSION  # noqa: E402
from ale.optimize import anneal  # noqa: E402
from ale.topology import seed_plan  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

#: SHA-256 of the seed-3 start and the annealed layout, computed at bf798b6 (equal to the
#: be5d115 digests of A.4: no later ticket changed these layouts).
BASE_LAYOUTS = {
    "P8": (
        "78f40d05384edec3886a7bf7972dabe81e25ca17d85fbfecdf89e09d25b07641",
        "0bf4b64382f2209566f2a0ebe2025ec3cdd7e5e5618deb2bf8c81a6431ebc787",
    ),
    "P25": (
        "c5e26ca4d9b7f3f40ad2b4927e17ded2e4caa99bacc6b6d2f9cb09274875df4f",
        "a71ed5b1c114125da5e75d235781e98c6a5a3ec698eaed09766fe3ec77d24886",
    ),
    "P60": (
        "51b34cc2586f05ae6176f03bf794ba9f3b1216a133fba143dd91d5fe763f4c60",
        "e397b4469752f3a3ede3d1b59e6f07543d06078cf93e2302390723bbf969d0e9",
    ),
}
NAMES = {"program_08": "P8", "program_25": "P25", "program_60": "P60"}
#: Digest of ``g1_compat.decomposition_digest()`` at bf798b6 (3 rectangles, 32 L shapes).
BASE_DECOMPOSITIONS = "284507e634fd6e72dd129c95543bb1029636c09b9c155fc618c2a19ff463b3e6"


def _digest(model: object) -> str:
    return hashlib.sha256(canonical_json(model)).hexdigest()  # type: ignore[arg-type]


def poly(*pts: tuple[int, int], holes: tuple[tuple[tuple[int, int], ...], ...] = ()) -> Any:
    return ModulePolygon(exterior=pts, holes=holes)


# ------------------------------------------------------------------------------ N01
def test_N01_version_and_locks() -> None:
    assert CONTRACTS_VERSION == "1.8.0"  # superseded by M.2, then R.8
    assert lock.main(["--check"]) == 0
    assert export_schemas.main(["--check"]) == 0
    assert PLAN_MAX_PIECES == MAX_PIECES == 12


def test_N01_decompositions_identical() -> None:
    assert len(g1_compat.shapes()) == 35
    assert g1_compat.decomposition_digest() == BASE_DECOMPOSITIONS
    # one- and two-piece footprints list at most one junction, equal to the legacy fields
    for pts in g1_compat.shapes():
        d = decompose_footprint(ModulePolygon(exterior=pts))
        if len(d.pieces) == 1:
            assert d.junctions == () and d.open_contacts == ()
        else:
            (j,) = d.junctions
            assert (j.parent, j.child, j.kind, j.cut, j.facing_block) == (
                0,
                1,
                d.junction,
                d.cut,
                d.facing_block,
            )


def test_N01_old_plans_and_polygons_load_and_serialise_unchanged() -> None:
    old = {
        "schema_version": "ale.corridor_plan/2",
        "pieces": [
            {
                "bands": [
                    {
                        "block_a": {"bays": [{"kind": "room", "room": "R1"}]},
                        "block_b": {
                            "bays": [{"kind": "finger", "left": [], "right": [], "junction": True}]
                        },
                    }
                ],
                "connector": "none",
            },
            {
                "bands": [
                    {
                        "block_a": {"bays": [{"kind": "room", "room": "R2"}]},
                        "block_b": {"bays": []},
                    }
                ],
                "connector": "none",
            },
        ],
    }
    plan = CorridorPlan.model_validate(old)
    assert plan.model_dump(mode="json") == old  # no junction_to key appears
    assert "junction_to" not in plan.model_dump_json()
    flat = poly((0, 0), (4, 0), (4, 3), (0, 3))
    assert flat.holes == () and "holes" not in flat.model_dump(mode="json")
    assert ModulePolygon.model_validate(flat.model_dump(mode="json")) == flat
    assert flat.area_cells() == 12


@pytest.mark.slow
@pytest.mark.timeout(900)
def test_N01_layouts_byte_identical() -> None:
    rulebook = load_test_rulebook()
    cfg = AleConfig()
    for prog, site in FIXTURE_PAIRS:
        name = NAMES[prog]
        prep = prepare(Path(tempfile.mkdtemp()), load_program(prog), load_site(site))
        start = seed_plan(prep, rulebook, cfg, seed=3, max_attempts=SEED_ATTEMPTS)
        layout0 = start.realization.layout
        assert layout0 is not None
        res = anneal(prep, rulebook, cfg, start.plan, seed=ANNEAL_SEED, max_iter=ANNEAL_ITER[name])
        assert (_digest(layout0), _digest(res.layout)) == BASE_LAYOUTS[name], name


# ------------------------------------------------------------------------------ N02
def _summary(fp: FootprintPieces) -> tuple[Any, Any, Any]:
    return (
        [(p.rect.x, p.rect.y, p.rect.w, p.rect.h, p.spine_axis) for p in fp.pieces],
        [(j.parent, j.child, j.kind, j.facing_block, j.cut) for j in fp.junctions],
        list(fp.open_contacts),
    )


def _check_tiling(polygon: Any, fp: FootprintPieces) -> None:
    import shapely

    union = shapely.union_all([to_shapely(p.rect) for p in fp.pieces])
    assert sum(p.rect.area_cells() for p in fp.pieces) == polygon.area_cells()
    assert union.symmetric_difference(to_shapely(polygon)).area == 0
    for i, a in enumerate(fp.pieces):
        for b in fp.pieces[i + 1 :]:
            assert a.rect.intersection_cells(b.rect) == 0
    # parents precede children, every non-root piece has exactly one parent
    assert sorted(j.child for j in fp.junctions) == list(range(1, len(fp.pieces)))
    assert all(j.parent < j.child for j in fp.junctions)


U = poly((0, 0), (30, 0), (30, 24), (20, 24), (20, 10), (10, 10), (10, 24), (0, 24))
T = poly((10, 0), (20, 0), (20, 20), (30, 20), (30, 30), (0, 30), (0, 20), (10, 20))
H = poly(
    (0, 0), (10, 0), (10, 12), (20, 12), (20, 0), (30, 0),
    (30, 30), (20, 30), (20, 18), (10, 18), (10, 30), (0, 30),
)  # fmt: skip
COMB = poly(
    (0, 0), (36, 0), (36, 24), (28, 24), (28, 10), (20, 10),
    (20, 24), (16, 24), (16, 10), (8, 10), (8, 24), (0, 24),
)  # fmt: skip
Z = poly((0, 0), (20, 0), (20, 10), (30, 10), (30, 20), (10, 20), (10, 10), (0, 10))
RING = poly((0, 0), (30, 0), (30, 30), (0, 30), holes=(((10, 10), (10, 20), (20, 20), (20, 10)),))

EXPECTED: dict[str, tuple[Any, tuple[Any, Any, Any]]] = {
    # left arm 10x24 (largest) | base 20x10 | right arm 10x14: both cuts parallel to the
    # parent's spine (J1), facing the right (B).
    "U": (
        U,
        (
            [(0, 0, 10, 24, "Y"), (10, 0, 20, 10, "X"), (20, 10, 10, 14, "Y")],
            [(0, 1, "J1", "B", ((10, 0), (10, 10))), (1, 2, "J1", "B", ((20, 10), (30, 10)))],
            [],
        ),
    ),
    # bar 30x10 on top (largest), stem 10x20 below it (two pieces: the L code path).
    "T": (
        T,
        (
            [(0, 20, 30, 10, "X"), (10, 0, 10, 20, "Y")],
            [(0, 1, "J1", "A", ((10, 20), (20, 20)))],
            [],
        ),
    ),
    # columns 10x30 and a 10x6 crossbar: J1 into the crossbar, then J2 (collinear) to the
    # right column.
    "H": (
        H,
        (
            [(0, 0, 10, 30, "Y"), (10, 12, 10, 6, "X"), (20, 0, 10, 30, "X")],
            [(0, 1, "J1", "B", ((10, 12), (10, 18))), (1, 2, "J2", None, ((20, 12), (20, 18)))],
            [],
        ),
    ),
    # base 36x10 with three fingers: three J1 children of the root, facing B.
    "comb": (
        COMB,
        (
            [(0, 0, 36, 10, "X"), (0, 10, 8, 14, "Y"), (16, 10, 4, 14, "Y"), (28, 10, 8, 14, "Y")],
            [
                (0, 1, "J1", "B", ((0, 10), (8, 10))),
                (0, 2, "J1", "B", ((16, 10), (20, 10))),
                (0, 3, "J1", "B", ((28, 10), (36, 10))),
            ],
            [],
        ),
    ),
    "Z": (
        Z,
        (
            [(0, 0, 20, 10, "X"), (10, 10, 20, 10, "Y")],
            [(0, 1, "J1", "B", ((10, 10), (20, 10)))],
            [],
        ),
    ),
    # top bar 30x10 (root), left and right columns 10x20 hanging from it (J1, facing A), the
    # bottom piece 10x10 hanging from the left column; it also touches the right column: that
    # contact (2, 3) is open.
    "ring": (
        RING,
        (
            [(0, 20, 30, 10, "X"), (0, 0, 10, 20, "Y"), (10, 0, 10, 10, "X"), (20, 0, 10, 20, "Y")],
            [
                (0, 1, "J1", "A", ((0, 20), (10, 20))),
                (0, 3, "J1", "A", ((20, 20), (30, 20))),
                (1, 2, "J1", "B", ((10, 0), (10, 10))),
            ],
            [(2, 3)],
        ),
    ),
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_N02_decompose(name: str) -> None:
    polygon, expected = EXPECTED[name]
    got = decompose_footprint(polygon)
    assert _summary(got) == expected
    _check_tiling(polygon, got)
    assert decompose_footprint(polygon) == got  # deterministic
    # independent of the vertex the ring starts at
    pts = polygon.exterior
    rot = ModulePolygon(exterior=pts[3:] + pts[:3], holes=polygon.holes)
    assert decompose_footprint(rot) == got
    # the legacy fields are the single junction for two pieces, empty for more
    if len(got.pieces) > 2:
        assert (got.junction, got.cut, got.facing_block) == ("NONE", None, None)
    assert got.children(0)[0].parent == 0
    assert got.parent_junction(0) is None
    assert got.parent_junction(1) == got.junctions[0] or len(got.pieces) < 2


def test_N02_more_than_12_pieces() -> None:
    for n in (13, 14):  # 12 reflex vertices need 13 pieces; 13 are refused up front
        stair: list[tuple[int, int]] = [(0, 0), (n, 0)]
        for k in range(n):
            stair += [(n - k, k + 1), (n - k - 1, k + 1)]
        with pytest.raises(ValueError, match="at most 12 rectangles"):
            decompose_footprint(ModulePolygon(exterior=tuple(stair)))
    # 12 pieces are accepted
    n = 12
    stair = [(0, 0), (n, 0)]
    for k in range(n):
        stair += [(n - k, k + 1), (n - k - 1, k + 1)]
    got = decompose_footprint(ModulePolygon(exterior=tuple(stair)))
    assert len(got.pieces) == 12 == len(got.junctions) + 1


def test_N02_holes_validation() -> None:
    good = ((10, 10), (10, 20), (20, 20), (20, 10))
    assert poly((0, 0), (30, 0), (30, 30), (0, 30), holes=(good,)).area_cells() == 800
    ext = ((0, 0), (30, 0), (30, 30), (0, 30))
    bad: dict[str, tuple[tuple[int, int], ...]] = {
        "clockwise": ((10, 10), (20, 10), (20, 20), (10, 20)),
        "vertices": ((10, 10), (10, 20), (20, 10)),
        "axis": ((10, 10), (10, 20), (20, 25), (20, 10)),
        "collinear": ((10, 10), (10, 15), (10, 20), (20, 20), (20, 10)),
        "outside": ((10, 10), (10, 40), (20, 40), (20, 10)),
    }
    for name, ring in bad.items():
        with pytest.raises(ValidationError):
            ModulePolygon(exterior=ext, holes=(ring,))
        del name
    round_trip = poly(*ext, holes=(good,))
    assert ModulePolygon.model_validate(round_trip.model_dump(mode="json")) == round_trip
    assert round_trip.model_dump(mode="json")["holes"]


# ------------------------------------------------------------------------------ N05 (contract)
def _plan(*pieces: PiecePlan) -> CorridorPlan:
    return CorridorPlan(pieces=pieces)


def _piece(a: list[Any], b: list[Any]) -> PiecePlan:
    return PiecePlan(
        bands=(BandPlan(block_a=BlockPlan(bays=tuple(a)), block_b=BlockPlan(bays=tuple(b))),)
    )


def _room(rid: str) -> RoomBay:
    return RoomBay(room=rid)


def _jf(to: int | None) -> FingerBay:
    return FingerBay(junction=True, junction_to=to)


def test_N05_junction_to_validation() -> None:
    with pytest.raises(ValidationError, match="only allowed on a junction finger"):
        FingerBay(left=("R1",), junction_to=1)
    with pytest.raises(ValidationError, match="child piece index"):
        FingerBay(junction=True, junction_to=0)
    f = FingerBay(left=("R1",), right=("R2",), junction=True, junction_to=2)
    assert f.with_rooms(("R3",), ()) == FingerBay(left=("R3",), junction=True, junction_to=2)
    assert FingerBay(junction=True, junction_to=2).model_dump(mode="json")["junction_to"] == 2
    # two pieces: junction_to is None or 1
    _plan(_piece([_jf(1)], []), _piece([_room("R1")], []))
    _plan(_piece([_jf(None)], []), _piece([_room("R1")], []))
    with pytest.raises(ValidationError, match="must be 1"):
        _plan(_piece([_jf(2)], []), _piece([_room("R1")], []))
    # more than two pieces: every junction finger names a later piece, each child once
    three = [_piece([_room("R1")], []), _piece([_room("R2")], []), _piece([_room("R3")], [])]
    with pytest.raises(ValidationError, match="needs junction_to"):
        _plan(_piece([_jf(None)], []), *three[1:])
    with pytest.raises(ValidationError, match="later piece"):
        _plan(_piece([_jf(3)], []), *three[1:])
    with pytest.raises(ValidationError, match="more than one junction finger leads to piece 1"):
        _plan(_piece([_jf(1), _jf(1)], []), *three[1:])
    ok = _plan(_piece([_jf(1), _jf(2)], []), *three[1:])
    assert ok.room_ids() == ("R2", "R3")
    # plans of up to 12 pieces
    assert len(_plan(*(_piece([_room(f"R{k}")], []) for k in range(12))).pieces) == 12


def test_N05_check_against_tree() -> None:
    fp = decompose_footprint(COMB)
    ids = ["R1", "R2", "R3", "R4"]

    def comb_plan(a: list[Any], b: list[Any], kids: tuple[PiecePlan, ...] | None = None) -> Any:
        kids = kids or (
            _piece([_room("R2")], []),
            _piece([_room("R3")], []),
            _piece([_room("R4")], []),
        )
        return _plan(_piece(a, b), *kids)

    good = comb_plan([_room("R1")], [_jf(1), _jf(2), _jf(3)])
    assert good.check_against(ids, fp) == ()
    # fingers in the wrong block / missing / to a non-child
    assert any(
        "block B" in m
        for m in comb_plan([_jf(1), _jf(2), _jf(3), _room("R1")], []).check_against(ids, fp)
    )
    assert any(
        "J1 child 3 needs a junction finger" in m
        for m in comb_plan([_room("R1")], [_jf(1), _jf(2)]).check_against(ids, fp)
    )
    two_bands = PiecePlan(
        bands=(
            BandPlan(block_a=BlockPlan(), block_b=BlockPlan()),
            BandPlan(block_a=BlockPlan(bays=(_room("R2"),)), block_b=BlockPlan()),
        ),
        connector="none",
    )
    msgs = comb_plan(
        [_room("R1")],
        [_jf(1), _jf(2), _jf(3)],
        (two_bands, _piece([_room("R3")], []), _piece([_room("R4")], [])),
    ).check_against(ids, fp)
    assert any("2+ bands but no connector" in m for m in msgs)
    assert any("piece 1 must have exactly one band" in m for m in msgs)
    # a finger in a child piece / a finger to a J2 child
    h = decompose_footprint(H)
    h_plan = _plan(
        _piece([_room("R1")], [_jf(1)]),
        _piece([_room("R2")], [_jf(2)]),
        _piece([_room("R3")], []),
    )
    msgs = h_plan.check_against(["R1", "R2", "R3"], h)
    assert any("not a J1 child" in m for m in msgs)
    wrong_host = comb_plan(
        [_room("R1")],
        [_jf(1), _jf(2)],
        (_piece([_room("R2")], [_jf(3)]), _piece([_room("R3")], []), _piece([_room("R4")], [])),
    )
    assert any(
        "junction finger to piece 3 must be in piece 0" in m
        for m in wrong_host.check_against(ids, fp)
    )
    # piece count mismatch
    assert any(
        "footprint has 4" in m for m in _plan(_piece([_room("R1")], [])).check_against(["R1"], fp)
    )


def test_N05_models_strict() -> None:
    with pytest.raises(ValidationError):
        Junction(parent=0, child=1, kind="J3", cut=((0, 0), (0, 1)), facing_block=None)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Junction(parent=0, child=1.5, kind="J1", cut=((0, 0), (0, 1)), facing_block="A")  # type: ignore[arg-type]
    fp = FootprintPieces(
        pieces=(Piece(rect=ModuleRect(0, 0, 4, 4), spine_axis="X"),),
        junction="NONE",
        cut=None,
        facing_block=None,
    )
    assert fp.junctions == () and fp.open_contacts == ()


# ------------------------------------------------------------------------------ N07
def _tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=250,
    )


TOUCHED = [
    "src/ale/contracts",
    "src/ale/geometry/blocks.py",
    "src/ale/geometry/checks.py",
    "src/ale/geometry/greedy.py",
    "src/ale/geometry/realize.py",
    "src/ale/topology/repair.py",
    "src/ale/topology/seed.py",
    "src/ale/optimize/moves.py",
    "src/ale/optimize/polish.py",
    "tests/contracts/test_contracts_g1.py",
    "tests/contracts/g1_compat.py",
    "tests/geometry/test_geometry_g1.py",
    "tests/geometry/g1_shapes.py",
    "tests/optimize/test_optimize_moves_g1.py",
]


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_N07_gates() -> None:
    """ruff / format / mypy strict on the touched files (the full-suite and coverage gates
    run outside), and the contract lock."""
    if _tool("ruff", "--version").returncode != 0:
        pytest.skip("ruff not installed")  # pragma: no cover
    assert lock.main(["--check"]) == 0
    proc = _tool("ruff", "check", *TOUCHED)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = _tool("ruff", "format", "--check", *TOUCHED)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = _tool("mypy", *[t for t in TOUCHED if t.startswith("src/")])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads('"ok"') == "ok"
