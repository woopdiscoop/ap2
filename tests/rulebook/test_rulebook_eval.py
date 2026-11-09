"""Ticket 2.2 eval (K1-K10): ``build_rulebook`` on synthetic inputs and ``ale rulebook build``."""

from __future__ import annotations

import random
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from extract_helpers import Invoke, execute, plan_doc, save_doc, unit_of
from rulebook_helpers import (
    TODAY,
    RoomDef,
    config,
    geometry,
    office_meeting,
    plan,
    seed_rulebook,
    split,
    uniform_stats,
)

from ale.contracts.enums import Bearing, Fidelity, SourceKind
from ale.contracts.models import Quantiles, Rulebook
from ale.contracts.serialization import dump_yaml, load_yaml
from ale.corpus.ingest import ingest
from ale.mining import extract_topology
from ale.rulebook import build_rulebook
from ale.rulebook.blend import blend_quantiles, blend_value
from ale.rulebook.stats import adjacency_stats, weighted_quantile
from ale.workspace import Workspace

TESTS = Path(__file__).resolve().parents[1]


def _build(pairs, seed=None, cfg=None, **kw):  # type: ignore[no-untyped-def]
    topos, geoms = split(pairs)
    return build_rulebook(topos, geoms, seed, cfg or config(), today=TODAY, **kw)


# ---------------------------------------------------------------------- K1


def test_K1_adjacency_p() -> None:
    pairs = [office_meeting(i, contact=i < 3) for i in range(4)]
    rb = _build(pairs, min_support=1).rulebook
    entry = next(e for e in rb.adjacency.pairs if (e.a, e.b) == ("meeting_room", "office"))
    assert entry.p == pytest.approx(0.7)
    assert entry.p == 0.7  # (3 + 0.5) / (4 + 1), rounded to 9 significant digits
    assert entry.n_support == 4
    # unknown rooms (r3, untyped) never form pairs
    assert {(e.a, e.b) for e in rb.adjacency.pairs} == {("meeting_room", "office")}


# ---------------------------------------------------------------------- K2


def test_K2_fidelity_weights() -> None:
    pairs = [
        office_meeting(0, contact=True),
        office_meeting(1, contact=True),
        office_meeting(2, contact=True, kind=SourceKind.RASTER),
        office_meeting(3, contact=False),
    ]
    topos, geoms = split(pairs)
    from ale.rulebook.stats import PlanInput

    inputs = [
        PlanInput(t, g, 0.5 if t.fidelity is Fidelity.RASTER else 1.0)
        for t, g in zip(topos, geoms, strict=True)
    ]
    st = adjacency_stats(inputs)[("meeting_room", "office")]
    assert st.support == pytest.approx(3.5)
    assert st.hits == pytest.approx(2.5)
    rb = _build(pairs, min_support=1).rulebook
    entry = rb.adjacency.pairs[0]
    assert entry.p == pytest.approx((2.5 + 0.5) / (3.5 + 1.0))
    assert entry.n_support == 4  # round(3.5)
    assert rb.source_mix == {Fidelity.CAD: 3, Fidelity.RASTER: 1}


# ---------------------------------------------------------------------- K3


def test_K3_min_support() -> None:
    pairs = [office_meeting(i, contact=True) for i in range(2)]
    seed = seed_rulebook(pairs=[("office", "meeting_room", 0.9)])
    with_seed = _build(pairs, seed=seed, min_support=5)
    assert [(e.a, e.b, e.p, e.n_support) for e in with_seed.rulebook.adjacency.pairs] == [
        ("meeting_room", "office", 0.9, 0)
    ]
    no_seed = _build(pairs, min_support=5)
    assert no_seed.rulebook.adjacency.pairs == ()
    assert "Paire meeting_room / office omise : support 2 < min_support 5." in no_seed.report_md
    # at the threshold the pair is mined
    assert len(_build(pairs, min_support=2).rulebook.adjacency.pairs) == 1


# ---------------------------------------------------------------------- K4


def test_K4_quantiles() -> None:
    # Hand computation: plotting positions (S_i - w_i/2) / S, linear interpolation.
    assert weighted_quantile([(1, 1), (2, 1), (3, 1), (4, 1)], 0.5) == pytest.approx(2.5)
    assert weighted_quantile([(1, 1), (2, 1), (3, 1), (4, 1)], 0.1) == 1.0
    assert weighted_quantile([(1, 1), (2, 1), (3, 1), (4, 1)], 0.9) == 4.0
    # positions 0.125 and 0.625 -> q=0.5 lies 3/4 of the way from 1 to 3
    assert weighted_quantile([(3.0, 3.0), (1.0, 1.0)], 0.5) == pytest.approx(2.5)
    assert weighted_quantile([(1.0, 0.8), (2.0, 1.0)], 0.5) == pytest.approx(
        1.0 + (0.5 - 0.4 / 1.8) / ((0.8 + 0.5) / 1.8 - 0.4 / 1.8)
    )

    # Offices 4 m deep, widths 4..12 m: aspect 1, 1.5, 2, 2.5, 3; area 16..48 m².
    pairs = [plan(i, [("o", "office", (0.0, 0.0, 4.0 + 2.0 * i, 4.0))]) for i in range(5)]
    # A RASTER office (aspect 1.2, area 19.2) is ignored for aspect / area.
    pairs.append(plan(9, [("o", "office", (0.0, 0.0, 4.8, 4.0))], kind=SourceKind.RASTER))
    res = _build(pairs, min_support=1)
    office = res.rulebook.types["office"]
    # Hazen positions .1 .3 .5 .7 .9 -> p10 = 1, p50 = 2, p90 = 3 clipped to 2.0
    assert office.aspect == Quantiles(p10=1.0, p50=2.0, p90=2.0, n=5)
    assert office.area_m2 == Quantiles(p10=16.0, p50=32.0, p90=48.0, n=5)
    assert "aspect p90 miné écrêté à shape.aspect_max = 2" in res.report_md
    assert "(écrêté)" in res.report_md


# ---------------------------------------------------------------------- K5


def test_K5_core_offset() -> None:
    # Footprint bbox (0,0)-(10,10): centre (5,5), W = H = 10.
    # Plan 0: core rooms (8,0)-(10,2) and (8,2)-(10,6)
    # -> area-weighted centroid (9, (4*1 + 8*4)/12 = 3).
    p0 = plan(
        0,
        [
            ("a", "office", (0.0, 0.0, 8.0, 10.0)),
            ("b", "sanitary", (8.0, 0.0, 10.0, 2.0)),
            ("c", "technical_room", (8.0, 2.0, 10.0, 6.0)),
            ("d", "storage", (8.0, 6.0, 10.0, 10.0)),
        ],
    )
    # Plan 1: core room centred (1, 9) -> (-0.4, 0.4); PDF_VECTOR weight 0.8.
    p1 = plan(
        1,
        [
            ("a", "office", (2.0, 0.0, 10.0, 10.0)),
            ("b", "stair", (0.0, 8.0, 2.0, 10.0)),
            ("c", "storage", (0.0, 0.0, 2.0, 8.0)),
        ],
        kind=SourceKind.PDF_VECTOR,
    )
    # Plan 2: no service core -> not used.
    p2 = plan(2, [("a", "office", (0.0, 0.0, 5.0, 5.0))])
    core = _build([p0, p1, p2]).rulebook.core_offset
    dx0, dy0 = (9.0 - 5.0) / 10.0, (3.0 - 5.0) / 10.0
    assert core.dx_norm == pytest.approx((dx0 * 1.0 + (-0.4) * 0.8) / 1.8)
    assert core.dy_norm == pytest.approx((dy0 * 1.0 + 0.4 * 0.8) / 1.8)
    assert core.n == 2
    single = _build([p0]).rulebook.core_offset
    assert (single.dx_norm, single.dy_norm) == (pytest.approx(0.4), pytest.approx(-0.2))


# ---------------------------------------------------------------------- K6


def _south_office_plan(i: int) -> list[RoomDef]:
    """3 x 2 grid (4 m cells, 0.2 m gaps): the office (bottom middle) faces south only."""
    xs = [(0.0, 4.0), (4.2, 8.2), (8.4, 12.4)]
    bottom = ["storage", "office", "storage"]
    rooms: list[RoomDef] = []
    for k, (x0, x1) in enumerate(xs):
        rooms.append((f"b{k}", bottom[k], (x0, 0.0, x1, 4.0)))
        rooms.append((f"t{k}", "meeting_room", (x0, 4.2, x1, 8.2)))
    return rooms


def _oriented(n: int) -> tuple[list, list, dict[tuple[str, int], float]]:  # type: ignore[type-arg]
    topos, geoms = [], []
    north: dict[tuple[str, int], float] = {}
    for i in range(n):
        g = geometry(i, _south_office_plan(i))
        t = extract_topology(g, config())
        assert t is not None
        topos.append(t)
        geoms.append(g)
        north[(g.source_sha256, 0)] = 0.0
    return topos, geoms, north


def test_K6_orientation() -> None:
    topos, geoms, north = _oriented(3)
    rb = build_rulebook(topos, geoms, None, config(), north=north, min_support=1, today=TODAY)
    office = rb.rulebook.types["office"].orientation
    assert office[Bearing.S] == 1.0
    assert office[Bearing.N] < 0.0
    assert all(-1.0 <= v <= 1.0 for v in office.values())
    # Without north nothing is mined: neutral orientation for a mined-only type.
    rb2 = build_rulebook(topos, geoms, None, config(), min_support=1, today=TODAY)
    assert set(rb2.rulebook.types["office"].orientation.values()) == {0.0}
    # Fewer than 3 plans with a known north: the seed orientation is kept.
    seed_orient = {"N": 0.3, "E": 0.5, "S": -0.2, "W": -0.5}
    seed = seed_rulebook(types={"office": uniform_stats(seed_orient)})
    t2, g2, n2 = _oriented(2)
    rb3 = build_rulebook(t2, g2, seed, config(), north=n2, min_support=1, today=TODAY)
    assert {k.value: v for k, v in rb3.rulebook.types["office"].orientation.items()} == seed_orient
    # With 3 plans the seed and the mined orientation are blended (w = 3 / 13).
    rb4 = build_rulebook(topos, geoms, seed, config(), north=north, min_support=1, today=TODAY)
    s = rb4.rulebook.types["office"].orientation[Bearing.S]
    assert s == pytest.approx(-0.2 + 3.0 / 13.0 * (1.0 + 0.2))


# ---------------------------------------------------------------------- K7


def test_K7_blend() -> None:
    assert blend_value(0.8, 0.4, 10, 10) == pytest.approx(0.6)
    # Through the build: seed p = 0.8, mined p = 4 / 10 (alpha = 0), support 10, k = 10.
    pairs = [office_meeting(i, contact=i < 4) for i in range(10)]
    seed = seed_rulebook(pairs=[("office", "meeting_room", 0.8)])
    rb = _build(pairs, seed=seed, cfg=config(laplace_alpha=0.0, blend_k=10.0)).rulebook
    entry = rb.adjacency.pairs[0]
    assert entry.p == pytest.approx(0.6)
    assert entry.n_support == 10
    # Quantile order preserved after blending, whatever the inputs.
    rng = random.Random(7)
    for _ in range(200):
        a = sorted(rng.uniform(1.0, 6.0) for _ in range(3))
        b = sorted(rng.uniform(1.0, 6.0) for _ in range(3))
        q = blend_quantiles(
            Quantiles(p10=a[0], p50=a[1], p90=a[2]),
            Quantiles(p10=b[0], p50=b[1], p90=b[2], n=4),
            rng.uniform(0.0, 50.0),
            10.0,
        )
        assert q.p10 <= q.p50 <= q.p90
    # Seed office (aspect 1/1.4/2) blended with mined office aspect (n = 10 rooms).
    office = rb.types["office"]
    mined_aspect = 4.0 / 3.0
    assert office.aspect.p50 == pytest.approx(1.4 + 0.5 * (mined_aspect - 1.4))
    assert office.aspect.p10 <= office.aspect.p50 <= office.aspect.p90


# ---------------------------------------------------------------------- K8


def test_K8_output_valid() -> None:
    pairs = [office_meeting(i, contact=True) for i in range(5)]
    pairs.append(office_meeting(7, contact=True, kind=SourceKind.PDF_VECTOR))
    pairs.append(office_meeting(8, contact=False, kind=SourceKind.RASTER))
    mined = _build(pairs).rulebook
    assert mined.kind == "mined"
    assert re.fullmatch(r"mined-2026-11-08-[0-9a-f]{8}", mined.version)
    assert mined.n_plans == 7
    assert mined.source_mix == {Fidelity.CAD: 5, Fidelity.PDF_VECTOR: 1, Fidelity.RASTER: 1}
    assert load_yaml(Rulebook, dump_yaml(mined)) == mined
    assert set(mined.types) == {"office", "meeting_room"}
    blended = _build(pairs, seed=seed_rulebook()).rulebook
    assert blended.kind == "blended"
    assert load_yaml(Rulebook, dump_yaml(blended)) == blended
    assert blended.version != mined.version  # the seed is an input


# ---------------------------------------------------------------------- K9


def test_K9_deterministic() -> None:
    pairs = [office_meeting(i, contact=i % 3 != 0) for i in range(8)]
    pairs += [plan(20 + i, [("o", "office", (0.0, 0.0, 4.0 + i, 4.0))]) for i in range(4)]
    topos, geoms = split(pairs)
    seed = seed_rulebook(pairs=[("office", "meeting_room", 0.8)])
    ref = build_rulebook(topos, geoms, seed, config(), min_support=2, today=TODAY)
    rng = random.Random(3)
    for _ in range(3):
        t2, g2 = list(topos), list(geoms)
        rng.shuffle(t2)
        rng.shuffle(g2)
        res = build_rulebook(t2, g2, seed, config(), min_support=2, today=TODAY)
        assert dump_yaml(res.rulebook).encode() == dump_yaml(ref.rulebook).encode()
        assert res.report_md.encode() == ref.report_md.encode()


# ---------------------------------------------------------------------- K10


def test_K10_cli(tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke) -> None:
    inp = tmp_path / "input"
    save_doc(plan_doc(labels=True), inp / "a.dxf")
    save_doc(plan_doc(labels=True, extra_layers=("X",)), inp / "b.dxf")
    save_doc(plan_doc(insunits=None, labels=True, extra_layers=("Y",)), inp / "noscale.dxf")
    meta = tmp_path / "plans_meta.csv"
    meta.write_text("filename,north_angle_deg\na.dxf,0\nb.dxf,90\n", encoding="utf-8")
    report = ingest(tmp_workspace, inp, meta=meta)
    # plans_meta.csv has no north column in Ticket 1.1 (it is ignored with a warning), so the
    # north is written to files.meta_json where Ticket 2.2 reads it (see eval_report.md).
    assert any("north_angle_deg" in w for w in report.meta_warnings)
    for rel, north in (("a.dxf", 0), ("b.dxf", 90)):
        sha = unit_of(tmp_workspace, rel)[0]
        execute(
            tmp_workspace,
            "UPDATE files SET meta_json = ? WHERE sha256 = ?",
            (f'{{"north_angle_deg": {north}}}', sha),
        )
    assert invoke(["layers", "--workspace", tmp_workspace.root]).exit_code == 0
    assert invoke(["extract", "--workspace", tmp_workspace.root]).exit_code == 0
    seed_path = tmp_path / "seed.yaml"
    shutil.copyfile(TESTS / "program" / "data" / "rulebook_test.yaml", seed_path)

    result = invoke(
        ["rulebook", "build", "--workspace", tmp_workspace.root, "--seed-rulebook", seed_path]
    )

    assert result.exit_code == 0, result.output
    out = tmp_workspace.path("rulebook")
    rb = load_yaml(Rulebook, (out / "rulebook.yaml").read_text(encoding="utf-8"))
    assert rb.kind == "blended"
    assert rb.n_plans == 2
    assert rb.source_mix == {Fidelity.CAD: 2}
    text = (out / "report.md").read_text(encoding="utf-8")
    noscale = unit_of(tmp_workspace, "noscale.dxf")[0]
    assert f"`{noscale[:12]} p0 n0` | échelle inconnue" in text
    assert "Plans ignorés : 1" in text
    assert "ignoré" in result.stdout
    with closing(sqlite3.connect(out / "rulebook.sqlite")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 2
        norths = conn.execute("SELECT north_angle_deg FROM plans ORDER BY 1").fetchall()
        assert sorted(n for (n,) in norths) == [0.0, 90.0]
    # Re-running gives byte-identical outputs.
    before = {n: (out / n).read_bytes() for n in ("rulebook.yaml", "report.md")}
    again = invoke(
        ["rulebook", "build", "--workspace", tmp_workspace.root, "--seed-rulebook", seed_path]
    )
    assert again.exit_code == 0
    assert {n: (out / n).read_bytes() for n in before} == before
