"""Ticket 2.2 unit tests: edge cases of the statistics, blending, report and workspace run."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
import shapely
from extract_helpers import Invoke
from rulebook_helpers import (
    TODAY,
    config,
    geometry,
    office_meeting,
    plan,
    seed_rulebook,
    sha,
    split,
)

from ale.contracts.enums import Bearing, FileStatus
from ale.contracts.models import Rulebook
from ale.contracts.serialization import canonical_json, dump_yaml, load_yaml
from ale.mining import PlanTopology
from ale.rulebook import SeedError, build_rulebook, load_seed, run_build
from ale.rulebook.blend import sig
from ale.rulebook.build import REASON_BAD_PLAN, REASON_NO_GEOMETRY, _north_of
from ale.rulebook.stats import (
    PlanInput,
    allowed_type,
    core_offset_stats,
    orientation_stats,
    room_aspect,
    room_facades,
    weighted_quantile,
)
from ale.workspace import Workspace


def test_allowed_type() -> None:
    assert allowed_type("office")
    assert allowed_type("stair")  # VERTICAL is allowed in a rulebook
    assert not allowed_type(None)
    assert not allowed_type("unknown")
    assert not allowed_type("circulation")
    assert not allowed_type("outdoor_space")
    assert not allowed_type("no_such_type")


def test_weighted_quantile_edges() -> None:
    with pytest.raises(ValueError, match="positive weight"):
        weighted_quantile([(1.0, 0.0)], 0.5)
    assert weighted_quantile([(5.0, 1.0)], 0.9) == 5.0
    assert weighted_quantile([(1.0, 1.0), (9.0, 0.0), (3.0, 1.0)], 0.5) == pytest.approx(2.0)


def test_room_aspect() -> None:
    assert room_aspect(shapely.box(0, 0, 4, 2)) == pytest.approx(2.0)
    rotated = shapely.Polygon([(0, 0), (3, 3), (2, 4), (-1, 1)])
    assert room_aspect(rotated) == pytest.approx((18**0.5) / (2**0.5))


def test_sig() -> None:
    assert sig(0.1 + 0.2) == 0.3
    assert str(sig(-0.0)) == "0.0"


def test_core_offset_none_and_untyped() -> None:
    t, g = plan(0, [("a", None, (0.0, 0.0, 4.0, 4.0))])
    assert core_offset_stats([PlanInput(t, g, 1.0)]) is None
    t2, g2 = plan(1, [])
    assert core_offset_stats([PlanInput(t2, g2, 1.0)]) is None
    t3, g3 = plan(2, [("a", "sanitary", (0.0, 0.0, 4.0, 4.0))])
    assert core_offset_stats([PlanInput(t3, g3, 0.0)]) is None  # zero weight only
    single = core_offset_stats([PlanInput(t3, g3, 1.0)])
    assert single is not None and (single.dx_norm, single.dy_norm, single.n) == (0.0, 0.0, 1)


def test_room_facades_rotation() -> None:
    rooms = [
        ("s", "office", (0.0, 0.0, 10.0, 4.0)),
        ("n", "meeting_room", (0.0, 4.2, 10.0, 8.2)),
    ]
    g = geometry(0, rooms)
    north_up = room_facades(g, 0.0)
    assert north_up["s"][Bearing.S] == pytest.approx(10.0)
    assert Bearing.N not in north_up["s"]
    assert north_up["s"][Bearing.E] == pytest.approx(4.0)
    # North pointing to drawing -y: the "south" room now faces north.
    flipped = room_facades(g, 180.0)
    assert flipped["s"][Bearing.N] == pytest.approx(10.0)
    # North pointing to drawing +x (90° clockwise): drawing +y is west.
    east = room_facades(g, 90.0)
    assert east["n"][Bearing.W] == pytest.approx(10.0)
    assert room_facades(geometry(1, []), 0.0) == {}


def test_orientation_skips_unshared_types() -> None:
    t, g = plan(0, [("a", "office", (0.0, 0.0, 4.0, 4.0))])
    # all façade weight zero -> no share -> type skipped
    assert orientation_stats([PlanInput(t, g, 0.0, 0.0)]) == {}
    out = orientation_stats([PlanInput(t, g, 1.0, 0.0)])
    # A single room is the whole plan: its share equals the overall share -> neutral.
    assert set(out["office"].values.values()) == {0.0}
    assert out["office"].n_plans == 1


def test_build_skips_and_errors() -> None:
    t0, g0 = office_meeting(0, contact=True)
    t1, _ = office_meeting(1, contact=True)
    res = build_rulebook([t0, t1], [g0], None, config(), min_support=1, today=TODAY)
    assert res.rulebook.n_plans == 1
    assert f"`{sha(1)[:12]} p0 n0` | {REASON_NO_GEOMETRY}" in res.report_md
    with pytest.raises(ValueError, match="duplicate topology"):
        build_rulebook([t0, t0], [g0], None, config(), today=TODAY)


def test_build_empty_and_seed_only() -> None:
    empty = build_rulebook([], [], None, config(), today=TODAY)
    assert empty.rulebook.kind == "mined"
    assert empty.rulebook.types == {}
    assert empty.rulebook.core_offset.n == 0
    assert "Aucune paire." in empty.report_md and "Aucun type." in empty.report_md
    assert "Plans utilisés : 0" in empty.report_md
    seed = seed_rulebook(pairs=[("office", "office", 0.3)], core=(0.1, -0.2))
    only = build_rulebook([], [], seed, config(), today=TODAY)
    assert only.rulebook.kind == "blended"
    assert only.rulebook.types == seed.types
    assert only.rulebook.adjacency == seed.adjacency
    assert only.rulebook.core_offset == seed.core_offset
    assert "graine" in only.report_md


def test_mined_only_type_below_min_support_and_core_blend() -> None:
    rooms = [("a", "office", (0.0, 0.0, 8.0, 10.0)), ("b", "sanitary", (8.0, 0.0, 10.0, 2.0))]
    pairs = [plan(i, rooms) for i in range(3)]
    seed = seed_rulebook(core=(0.0, 0.0))
    res = build_rulebook(*split(pairs), seed, config(blend_k=7.0), min_support=5, today=TODAY)
    assert "sanitary" not in res.rulebook.types
    assert "Type sanitary miné ignoré : 3 pièce(s) < min_support 5." in res.report_md
    # core offset (0.4, -0.4) blended with the seed (0, 0), w = 3 / 10
    core = res.rulebook.core_offset
    assert (core.dx_norm, core.dy_norm, core.n) == (
        pytest.approx(0.12),
        pytest.approx(-0.12),
        3,
    )
    # same-type pairs need >= 2 rooms of the type
    two = [plan(10 + i, [*rooms, ("c", "office", (0, 10, 1, 11))], [("a", "c")]) for i in range(2)]
    rb = build_rulebook(*split(two), None, config(), min_support=1, today=TODAY).rulebook
    assert ("office", "office") in {(e.a, e.b) for e in rb.adjacency.pairs}
    assert rb.adjacency.p("office", "office") == pytest.approx((2 + 0.5) / 3)


def test_contacts_with_untyped_rooms_ignored() -> None:
    t, g = plan(0, [("a", "office", (0, 0, 4, 4)), ("b", None, (4.2, 0, 8, 4))], [("a", "b")])
    rb = build_rulebook([t], [g], None, config(), min_support=1, today=TODAY).rulebook
    assert rb.adjacency.pairs == ()


def test_topology_with_foreign_type_is_ignored() -> None:
    t, g = office_meeting(0, contact=True)
    data = t.model_dump()
    data["rooms"] = [*data["rooms"], ("zz", "not_a_type", 1.0)]
    t2 = PlanTopology.model_validate(data)
    rb = build_rulebook([t2], [g], None, config(), min_support=1, today=TODAY).rulebook
    assert {(e.a, e.b) for e in rb.adjacency.pairs} == {("meeting_room", "office")}


def test_north_of() -> None:
    assert _north_of({}, 0) is None
    assert _north_of({"north_angle_deg": 12}, 0) == 12.0
    assert _north_of({"north_angle_deg": 12, "pages": {"1": {"north_angle_deg": 30.5}}}, 1) == 30.5
    assert _north_of({"north_angle_deg": True}, 0) is None
    assert _north_of({"north_angle_deg": "N"}, 0) is None
    assert _north_of({"north_angle_deg": float("inf")}, 0) is None
    assert _north_of({"pages": []}, 0) is None


def test_load_seed(tmp_path: Path) -> None:
    good = tmp_path / "seed.yaml"
    good.write_text(dump_yaml(seed_rulebook()), encoding="utf-8")
    assert load_seed(good) == seed_rulebook()
    bad = tmp_path / "bad.yaml"
    bad.write_text("kind: seed\n", encoding="utf-8")
    with pytest.raises(SeedError, match="invalid rulebook"):
        load_seed(bad)
    broken = tmp_path / "broken.yaml"
    broken.write_text("a: [\n", encoding="utf-8")
    with pytest.raises(SeedError, match="invalid YAML"):
        load_seed(broken)
    with pytest.raises(SeedError, match="cannot read"):
        load_seed(tmp_path / "missing.yaml")


def _register(ws: Workspace, sha256: str, status: str = "EXTRACTED", excluded: int = 0) -> None:
    from ale.corpus.db import connect, migrate

    with closing(connect(ws.path("corpus.sqlite"))) as conn:
        migrate(conn)
        conn.execute(
            "INSERT INTO files (sha256, size, ext, first_seen, excluded, meta_json) "
            "VALUES (?, 1, 'dxf', 'x', ?, ?)",
            (sha256, excluded, "not json" if excluded == 0 and status == "BAD" else None),
        )
        conn.execute(
            "INSERT INTO units (sha256, page, kind, status, updated_at) "
            "VALUES (?, 0, 'DXF', ?, 'x')",
            (sha256, FileStatus.EXTRACTED.value if status == "BAD" else status),
        )
        conn.commit()


def _write_plan(ws: Workspace, i: int, data: bytes) -> None:
    path = ws.path("extracted", sha(i), "0", "0", "plan.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_run_build_workspace(tmp_workspace: Workspace) -> None:
    # Not-yet-migrated corpus: nothing to read, outputs still written.
    run = run_build(tmp_workspace, today=TODAY)
    assert run.used == 0
    assert all(p.is_file() for p in run.files)
    # Plans: 0 good, 1 bad JSON, 2 excluded file, 3 FAILED unit, 4 no plan folder.
    for i in range(5):
        _write_plan(tmp_workspace, i, canonical_json(office_meeting(i, contact=True)[1]))
    _write_plan(tmp_workspace, 1, b"{}")
    _register(tmp_workspace, sha(0), "BAD")  # meta_json not JSON -> no north
    _register(tmp_workspace, sha(1))
    _register(tmp_workspace, sha(2), excluded=1)
    _register(tmp_workspace, sha(3), "FAILED")
    _register(tmp_workspace, sha(4))
    import shutil

    shutil.rmtree(tmp_workspace.path("extracted", sha(4)))
    run = run_build(tmp_workspace, min_support=1, today=TODAY)
    assert run.used == 1
    assert run.skipped == ((f"{sha(1)[:12]} p0 n0", REASON_BAD_PLAN),)
    rb = load_yaml(Rulebook, run.files[0].read_text(encoding="utf-8"))
    assert rb.n_plans == 1 and rb.kind == "mined"
    with closing(sqlite3.connect(run.files[2])) as conn:
        rows = conn.execute("SELECT room_id, type, facade_n_m FROM rooms ORDER BY 1").fetchall()
    assert rows == [("r1", "office", None), ("r2", "meeting_room", None), ("r3", None, None)]


def test_cli_invalid_seed(tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke) -> None:
    bad = tmp_path / "seed.yaml"
    bad.write_text("x", encoding="utf-8")
    result = invoke(
        ["rulebook", "build", "--workspace", tmp_workspace.root, "--seed-rulebook", bad]
    )
    assert result.exit_code == 2
    assert "seed.yaml" in result.stderr
    ok = invoke(["rulebook", "build", "--workspace", tmp_workspace.root, "--min-support", "2"])
    assert ok.exit_code == 0, ok.output
    assert "rulebook mined" in ok.stdout
