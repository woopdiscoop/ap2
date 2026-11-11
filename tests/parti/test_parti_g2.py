"""Ticket G.2 eval P201 to P210: parti generation (synthetic plot and programme only)."""

from __future__ import annotations

import itertools
import math
import time
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import parti_case as case
import pytest
import yaml
from conftest import run_cli
from shapely import Polygon as ShPolygon
from shapely import box

from ale.contracts.models import Program, SiteSpec
from ale.contracts.serialization import dump_yaml, load_yaml
from ale.parti import (
    Dropped,
    Entry,
    Massing,
    Parti,
    build_card,
    card_md,
    enumerate_genes,
    evaluate_massing,
    make_massing,
    match_forms,
    non_dominated,
    rank,
    validate_parti,
)
from ale.parti.card import FLAG_FR
from ale.parti.evaluate import typical_floor_site
from ale.parti.genes import COURT_TYPES, TYPOLOGIES

ZONE = box(3.0, 4.8, 100.0, 77.0)  # plot 100 x 80, setbacks 4.8 S / 3 N / 3 W, party wall E


def _area(poly: ShPolygon) -> float:
    """Shoelace area of the exterior minus the holes (independent of shapely's own area)."""

    def ring(coords: list[tuple[float, float]]) -> float:
        return sum(a[0] * b[1] - b[0] * a[1] for a, b in itertools.pairwise(coords)) / 2

    return abs(ring(list(poly.exterior.coords))) - sum(
        abs(ring(list(r.coords))) for r in poly.interiors
    )


def _massings(entries: list[Entry]) -> list[Massing]:
    return [e.massing for e in entries]


# ------------------------------------------------------------------------------ P201
def test_P201_genes(program: Program, site: SiteSpec) -> None:
    valid, dropped = enumerate_genes(0, (3, 5))
    assert {g.typology for g in valid} == set(TYPOLOGIES)
    assert all(validate_parti(g, (3, 5)) is None for g in valid)
    assert dropped and all(d.reason.strip() for d in dropped)
    assert any("cour" in d.reason for d in dropped)
    assert any("circulation" in d.reason for d in dropped)
    # every typology yields at least one sized massing on a large plot; the others are dropped
    # with a reason
    sized: dict[str, int] = {}
    for g in valid:
        m = make_massing(g, site, program)
        if isinstance(m, Dropped):
            assert m.reason
        else:
            sized[g.typology] = sized.get(g.typology, 0) + 1
    assert set(sized) == set(TYPOLOGIES), sized
    # an invalid parti is refused with its reason
    bad = replace(valid[0], floors=9)
    assert "niveaux" in (validate_parti(bad, (3, 5)) or "")


# ------------------------------------------------------------------------------ P202
def test_P202_massing(run: tuple[list[Entry], list[Dropped]], program: Program) -> None:
    net = sum(r.target_area_m2 * r.quantity for r in program.rooms)
    need = net / (1 - 0.16)
    entries, _ = run
    assert len(entries) == 40
    for m in _massings(entries):
        # inside the buildable zone (setbacks; the party wall on the east is built against)
        for o in m.outlines:
            assert ZONE.buffer(1e-6).covers(o), m.parti.key()
        # floors x area within +-10 % of the need
        total = sum(_area(o) for o in m.outlines)
        assert abs(total / need - 1) <= 0.10 + 1e-9, (m.parti.key(), total, need)
        # terraces recede: upper floor outline within the one below
        for lo, up in zip(m.outlines[:-1], m.outlines[1:], strict=True):
            assert lo.buffer(1e-6).covers(up)
        if m.parti.terrace:
            assert m.outlines[-1].area < m.outlines[-2].area - 1.0
        # courtyard short side >= H / 2
        if m.court is not None:
            h = m.parti.floors * 3.5
            gaps = [
                g for g in (m.court.geoms if m.court.geom_type == "MultiPolygon" else [m.court])
            ]
            for g in gaps:
                x0, y0, x1, y1 = g.bounds
                assert (
                    min(x1 - x0, y1 - y0) + 1e-9 >= h / 2
                    or min(x1 - x0, y1 - y0) >= m.court_short_m - 1e-9
                )
            assert m.court_short_m + 1e-9 >= h / 2, m.parti.key()
    assert any(m.parti.terrace for m in _massings(entries))


# ------------------------------------------------------------------------------ P203
def test_P203_one_core(run: tuple[list[Entry], list[Dropped]], site: SiteSpec) -> None:
    for e in run[0]:
        m = e.massing
        fsite = typical_floor_site(site, m)
        assert len(fsite.cores) == 1 and fsite.cores[0].kind == "core"
        core = box(*m.core)
        assert m.outlines[-1].buffer(1e-6).covers(core)  # continuous through every floor
        kept = [p for p in m.pieces if not p.dropped_on_top]
        pos = m.parti.core_position
        if pos == "junction":
            touched = [p for p in kept if box(*p.rect).intersection(core).area > 1e-6]
            assert len(touched) >= 2, m.parti.key()
        else:
            main = max(
                kept,
                key=lambda p: (max(p.rect[2] - p.rect[0], p.rect[3] - p.rect[1]), -len(p.name)),
            )
            x0, y0, x1, y1 = main.rect
            cx, cy = (m.core[0] + m.core[2]) / 2, (m.core[1] + m.core[3]) / 2
            if pos == "centre":
                assert abs(cx - (x0 + x1) / 2) <= 1.2 and abs(cy - (y0 + y1) / 2) <= 1.2
            else:
                far = (x1 - cx) if main.long_axis == "x" else (y1 - cy)
                assert far <= 3.6 / 2 + 0.6 + 1.2, m.parti.key()


# ------------------------------------------------------------------------------ P204
def test_P204_evaluate(run: tuple[list[Entry], list[Dropped]], program: Program) -> None:
    net = sum(r.target_area_m2 * r.quantity for r in program.rooms)
    for e in run[0][:12]:
        ev, m = e.evaluation, e.massing
        gross = sum(_area(o) for o in m.outlines)
        assert ev.gross_m2 == pytest.approx(gross, abs=1e-2)
        assert ev.capacity_ratio == pytest.approx(gross * 0.84 / net, abs=1e-5)
        typ = m.outlines[0]
        total = good = 0.0
        for ring in (typ.exterior, *typ.interiors):
            pts = list(ring.coords)
            for a, b in itertools.pairwise(pts):
                if a[0] == b[0] == 100.0:  # party wall
                    continue
                ln = math.hypot(b[0] - a[0], b[1] - a[1])
                total += ln
                if a[1] == b[1]:  # faces N or S: good for this setting; E / W are exposed
                    good += ln
        assert ev.facade_m == pytest.approx(total, abs=1e-2)
        assert ev.good_share == pytest.approx(good / total, abs=1e-5)
        assert ev.compactness == pytest.approx(
            typ.exterior.length / (4 * math.sqrt(typ.area)), abs=1e-5
        )
        # the typical-floor cell diagram has no fragmented room
        assert ev.cells_done and ev.fragmented == ()
        d = ev.diagram
        assert d is not None
        for room in d.rooms:
            cs = set(d.cells[room])
            if not cs:
                continue
            seen = {min(cs)}
            stack = list(seen)
            while stack:
                x, y = stack.pop()
                for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if q in cs and q not in seen:
                        seen.add(q)
                        stack.append(q)
            assert seen == cs, (m.parti.key(), room)
        assert ev.exceptions == (
            len(ev.rooms_short) + len(ev.facade_missing) + len(ev.off_circulation) + len(ev.strays)
        )


# ------------------------------------------------------------------------------ P205
def _office_case() -> tuple[Program, SiteSpec]:
    rooms = [
        dict(
            id="B01",
            name="Bureau",
            type="office",
            target_area_m2=18.0,
            quantity=70,
            macro_zone="ADMINISTRATIVE",
            needs_facade=True,
        ),
        dict(
            id="M01",
            name="Reunion",
            type="meeting_room",
            target_area_m2=36.0,
            quantity=4,
            macro_zone="ADMINISTRATIVE",
            needs_facade=True,
        ),
        dict(
            id="S01",
            name="Sanitaires",
            type="sanitary",
            target_area_m2=12.0,
            quantity=4,
            macro_zone="SERVICES",
        ),
    ]
    return load_yaml(Program, yaml.safe_dump({"rooms": rooms})), case.site()


def test_P205_forcedness() -> None:
    prog, site = _office_case()
    thin = Parti("bar", 0, 9.0, 4, "centre", "spine", 0, False)
    comb = Parti("comb", 90, 9.0, 4, "junction", "comb", 0, True, 0.0, None, 2)
    ms = [make_massing(g, site, prog) for g in (thin, comb)]
    assert all(isinstance(m, Massing) for m in ms)
    m_thin, m_comb = ms
    assert isinstance(m_thin, Massing) and isinstance(m_comb, Massing)
    ev_thin = evaluate_massing(m_thin, prog, site, cells=False)
    ev_comb = evaluate_massing(m_comb, prog, site, cells=False)
    # the thin bar cannot hold its facade rooms, the comb does
    assert ev_thin.frontage_capacity_m < ev_thin.frontage_demand_m
    assert ev_comb.frontage_capacity_m >= ev_comb.frontage_demand_m
    assert ev_thin.forcedness > ev_comb.forcedness
    assert ev_thin.share_met < ev_comb.share_met
    ranked = rank([Entry(thin, m_thin, ev_thin), Entry(comb, m_comb, ev_comb)])
    assert [e.parti.typology for e in ranked] == ["comb", "bar"]


# ------------------------------------------------------------------------------ P206
def test_P206_card(
    run: tuple[list[Entry], list[Dropped]], program: Program, site: SiteSpec
) -> None:
    for e in run[0]:
        card = build_card(e.massing, e.evaluation, 0.0)
        names = [el.name for el in card.elements]
        for p in e.massing.pieces:
            assert f"aile « {p.name} »" in names
        assert "noyau" in names
        assert ("cour" in names) == (e.massing.court is not None)
        assert ("parvis" in names) == (e.parti.forecourt_m > 0)
        assert sum(n.startswith("terrasse") for n in names) == int(e.parti.terrace)
        assert all(len(el.problems) >= 1 for el in card.elements)
    # a forecourt on the entrance street solves several problems; one on the north street none
    good = Parti("bar", 0, 9.0, 4, "centre", "spine", 0, False, 7.2)
    useless = replace(good, forecourt_side=2)
    for g, expect_flag in ((good, False), (useless, True)):
        m = make_massing(g, site, program)
        assert isinstance(m, Massing), m
        ev = evaluate_massing(m, program, site, cells=False)
        card = build_card(m, ev, 0.0)
        parvis = next(el for el in card.elements if el.name == "parvis")
        assert parvis.single is expect_flag
        assert (FLAG_FR in card_md(card)) or not expect_flag
    assert "fonction unique" in card_md(card)


# ------------------------------------------------------------------------------ P207
def test_P207_ranking(inputs: tuple[Path, Path], tmp_path: Path) -> None:
    # hand-checked: keys are (hard misses, forcedness, 1 - good share, compactness)
    keys = [
        (0.0, 5.0, 0.4, 1.5),  # A  dominated by B
        (0.0, 4.0, 0.4, 1.5),  # B  non dominated
        (1.0, 1.0, 0.1, 1.2),  # C  non dominated (best forcedness / orientation / compactness)
        (0.0, 6.0, 0.3, 1.7),  # D  non dominated (best orientation among hard 0)
        (1.0, 1.0, 0.1, 1.2),  # E  equal to C: neither dominates the other
        (2.0, 9.0, 0.5, 2.0),  # F  dominated by everything
    ]
    assert non_dominated(keys) == [False, True, True, True, True, False]
    out = tmp_path / "p"
    run_cli(inputs, out, "--count", "8")
    md = (out / "partis.md").read_text(encoding="utf-8")
    assert md.startswith("# Génération de partis")
    for word in ("Classement", "Fiche du parti", "Manques durs", "non dominés"):
        assert word in md
    rows = [ln for ln in md.splitlines() if ln.startswith("| ") and "parti_" in ln.split("|")[2]]
    assert len(rows) == 8
    flags = [r.split("|")[3].strip() for r in rows]
    assert flags == sorted(flags, key=lambda f: f != "oui")  # non-dominated first
    assert md.count("Fiche du parti") == 8


# ------------------------------------------------------------------------------ P208
def test_P208_from_forms(
    inputs: tuple[Path, Path], program: Program, site: SiteSpec, tmp_path: Path
) -> None:
    forms = tmp_path / "forms"
    forms.mkdir()
    wanted = {
        "form_01": Parti("U", 0, 9.0, 3, "centre", "spine", 0, True),
        "form_02": Parti("bar", 90, 16.2, 4, "centre", "spine", 0, False),
        "form_03": Parti("courtyard", 0, 9.0, 3, "centre", "loop", 0, True),
    }
    for name, g in wanted.items():
        m = make_massing(g, site, program)
        assert isinstance(m, Massing), (name, m)
        (forms / f"{name}.yaml").write_text(
            dump_yaml(typical_floor_site(site, m)), encoding="utf-8"
        )
    specs = {
        p.stem: load_yaml(SiteSpec, p.read_text(encoding="utf-8"))
        for p in sorted(forms.glob("*.yaml"))
    }
    matches = match_forms(specs, program, site, (3, 5))
    assert {m.name: m.typology for m in matches} == {k: v.typology for k, v in wanted.items()}
    assert all(m.iou >= 0.95 for m in matches), matches
    out = tmp_path / "out"
    run_cli(inputs, out, "--count", "5", "--from-forms", str(forms))
    md = (out / "partis.md").read_text(encoding="utf-8")
    assert "Formes G.3 rapprochées" in md and "IoU" in md
    for name, g in wanted.items():
        assert f"| {name} | {g.typology} |" in md


# ------------------------------------------------------------------------------ P209
def test_P209_outputs(inputs: tuple[Path, Path], tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    run_cli(inputs, a, "--count", "6")
    run_cli(inputs, b, "--count", "6")
    files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    assert len([f for f in files if f.suffix == ".svg"]) == 6
    assert len([f for f in files if f.name == "site.yaml"]) == 6
    for f in files:
        assert (a / f).read_bytes() == (b / f).read_bytes(), f  # deterministic
    for k in range(1, 7):
        svg = ET.fromstring((a / f"parti_{k:02d}.svg").read_text(encoding="utf-8"))
        assert svg.tag.endswith("svg")
        text = (a / f"parti_{k:02d}.svg").read_text(encoding="utf-8")
        assert 'class="floor"' in text and 'class="core"' in text and 'class="cells"' in text
        spec = load_yaml(SiteSpec, (a / f"parti_{k:02d}" / "site.yaml").read_text(encoding="utf-8"))
        assert spec.mode == "footprint" and len(spec.cores) == 1


# ------------------------------------------------------------------------------ P210
@pytest.mark.timeout(300)
def test_P210_gates_speed(inputs: tuple[Path, Path], tmp_path: Path) -> None:
    """40 partis in <= 60 s through the command (ruff, mypy, coverage and `lock --check` are
    run as gates by the ticket; see eval_report.md)."""
    t0 = time.perf_counter()
    run_cli(inputs, tmp_path / "o", "--count", "40")
    assert time.perf_counter() - t0 <= 60.0
    assert len(list((tmp_path / "o").glob("parti_*.svg"))) == 40
    assert COURT_TYPES  # keep the import honest
