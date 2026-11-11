"""Unit tests of ``ale.form`` and ``ale form`` beyond the G3 evaluation (edge cases)."""

from __future__ import annotations

from pathlib import Path

import case_helpers as case
import pytest
import yaml
from program_helpers import program_to_xlsx
from typer.testing import CliRunner

from ale.cli import app
from ale.cli.commands.form import build_candidates, form_svg, forms_md
from ale.form.grow import CELL_M, grow_form, outside_cells_connected
from ale.form.metrics import compute_metrics, rank_key
from ale.form.outline import outline_from_cells, ring_area, trace_rings

SMALL_ROOMS = [
    {
        "id": "A01",
        "name": "Bureau",
        "type": "office",
        "target_area_m2": 18.0,
        "quantity": 3,
        "macro_zone": "ADMINISTRATIVE",
        "needs_facade": True,
        "adjacent_to": ["A02"],
        "avoid": ["A03"],
    },
    {
        "id": "A02",
        "name": "Salle",
        "type": "meeting_room",
        "target_area_m2": 36.0,
        "macro_zone": "ADMINISTRATIVE",
    },
    {
        "id": "A03",
        "name": "Rangement",
        "type": "storage",
        "target_area_m2": 9.0,
        "macro_zone": "SERVICES",
    },
]


def _plot(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "footprint": {"exterior": [[0, 0], [24, 0], [24, 18], [0, 18]], "holes": []},
        "setbacks": [3.0, 0.0, 3.0, 3.0],
        "party_edges": [1],
        "entrances": [],
        "cores": [],
    }
    return base | over


def test_outline_empty_and_pieces() -> None:
    assert outline_from_cells(set()).polygons == ()
    two = {(0, 0), (1, 0), (0, 1), (1, 1), (5, 5), (6, 5), (5, 6), (6, 6)}
    o = outline_from_cells(two, origin=(10.0, 20.0), cell_m=0.6)
    assert len(o.polygons) == 2
    assert o.vertices_after == 8
    assert o.polygons[0].area() == pytest.approx(4 * 0.36)
    assert o.polygons[0].perimeter() > 0
    assert o.perimeter() == sum(p.perimeter() for p in o.polygons)
    assert ring_area(((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0))) == -1.0


def test_outline_hole_and_corner_touch() -> None:
    ring = {(x, y) for x in range(6) for y in range(6)} - {(x, y) for x in (2, 3) for y in (2, 3)}
    o = outline_from_cells(ring)
    assert len(o.polygons) == 1 and len(o.polygons[0].holes) == 1
    assert o.polygons[0].area() == pytest.approx(32 * CELL_M**2)
    # two cells touching by a corner stay separate rings (no self-touching polygon)
    rings = trace_rings({(0, 0), (1, 1)})
    assert len(rings) == 2


def test_outline_cuts_when_fill_would_enclose_the_outside() -> None:
    """A one-cell channel into a wide pocket: filling would enclose the pocket, so it is cut."""
    mass = {(x, y) for x in range(20) for y in range(12)}
    pocket = {(x, y) for x in range(7, 13) for y in range(3, 7)}
    channel = {(9, y) for y in range(7, 12)}
    o = outline_from_cells(mass - pocket - channel)
    assert o.cells_cut > 0 and o.cells_filled == 0
    for y in range(7, 12):  # the channel is now at least 2 cells wide
        assert not ((8, y) in o.cells and (10, y) in o.cells and (9, y) not in o.cells)
    # with the pocket declared as courtyard (outside by definition) the channel is filled
    o2 = outline_from_cells(mass - pocket - channel, outside_roots=frozenset(pocket))
    assert o2.cells_filled == len(channel) and o2.cells_cut == 0
    assert len(o2.polygons[0].holes) == 1
    # a protected cell is never cut
    o3 = outline_from_cells(
        mass - pocket - channel, protected=frozenset({(8, y) for y in range(7, 12)} | {(10, 8)})
    )
    assert o3.cells_cut == 0 and o3.cells_filled == 0  # neither move is allowed


def test_grow_without_anchors_and_shortfall() -> None:
    """No entrance, no PUBLIC room, no core: the access edge and the largest room serve; a plot
    too small for the programme reports the shortfall."""
    site = case.site(**_plot())
    prog = case.program(SMALL_ROOMS)
    cands = build_candidates(prog, site, 2)
    for c in cands:
        assert c.result.hall == "A02"  # the largest room when none is PUBLIC
        assert outside_cells_connected(c.result)
        assert c.metrics.short == 0
        assert c.metrics.circulation_share <= 1.0 and c.metrics.facade_share <= 1.0
    tiny = case.site(
        **_plot(
            footprint={"exterior": [[0, 0], [9, 0], [9, 7.2], [0, 7.2]], "holes": []},
            setbacks=[1.2, 0.0, 1.2, 1.2],
        )
    )
    short = build_candidates(prog, tiny, 1)[0]
    assert short.metrics.short > 0
    assert rank_key(short.metrics) > rank_key(cands[0].metrics)


def test_grow_cores_party_and_court_on_small_plot() -> None:
    site = case.site(
        **_plot(
            entrances=[{"point": [12.0, 0.0], "main": True}],
            cores=[{"id": "K", "rect": [10.2, 9.0, 1.8, 1.8], "kind": "shaft"}],
        )
    )
    res = grow_form(case.program(SMALL_ROOMS), site, seed=3, courtyard=True)
    assert res.court_cells and res.notes
    assert outside_cells_connected(res)
    metrics = compute_metrics(
        res,
        outline_from_cells({res.xy(i) for i in res.built_cells()}, res.origin, res.cell_m),
    )
    assert metrics.courtyard in ("open", "enclosed")
    assert res.counts()["A03"] == res.need["A03"]


def test_grow_is_deterministic_and_seeds_differ() -> None:
    site, prog = case.site(**_plot()), case.program(SMALL_ROOMS)
    a = grow_form(prog, site, seed=2)
    b = grow_form(prog, site, seed=2)
    assert a.owner == b.owner
    assert a.owner != grow_form(prog, site, seed=1).owner


def test_cli_options_and_errors(tmp_path: Path) -> None:
    prog = program_to_xlsx(case.program(SMALL_ROOMS), tmp_path / "p.xlsx")
    site = case.write_site_yaml(
        tmp_path / "s.yaml", **_plot(footprint={"exterior": [[0, 0], [24, 0], [24, 18], [0, 18]]})
    )
    runner = CliRunner()
    out = tmp_path / "out"
    ok = runner.invoke(
        app,
        [
            "form",
            "--program",
            str(prog),
            "--site",
            str(site),
            "--out",
            str(out),
            "--candidates",
            "2",
            "--courtyard",
        ],
    )
    assert ok.exit_code == 0, ok.output
    assert sorted(p.name for p in out.iterdir()) == [
        "form_01.svg",
        "form_01.yaml",
        "form_02.svg",
        "form_02.yaml",
        "forms.md",
    ]
    svg = (out / "form_01.svg").read_text(encoding="utf-8")
    assert svg.startswith("<?xml") and 'id="entrance"' in svg and 'class="outline"' in svg
    assert 'class="party"' in svg
    assert "Recherche de forme" in (out / "forms.md").read_text(encoding="utf-8")
    # footprint-mode site: refused
    data = yaml.safe_load(site.read_text(encoding="utf-8"))
    data.pop("setbacks")
    data.pop("party_edges")
    data["mode"] = "footprint"
    foot = tmp_path / "foot.yaml"
    foot.write_text(yaml.safe_dump(data), encoding="utf-8")
    bad = runner.invoke(
        app, ["form", "--program", str(prog), "--site", str(foot), "--out", str(tmp_path / "x")]
    )
    assert bad.exit_code == 1
    # unreadable programme: reported, exit 1
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a workbook")
    bad = runner.invoke(
        app, ["form", "--program", str(broken), "--site", str(site), "--out", str(tmp_path / "y")]
    )
    assert bad.exit_code == 1 and "Erreurs" in bad.output


def test_form_md_and_svg_helpers() -> None:
    site = case.site(**_plot())
    cands = build_candidates(case.program(SMALL_ROOMS), site, 3)
    md = forms_md(cands)
    assert md.count("| form_") == 3
    assert "contour" in md
    svg = form_svg(site, cands[0])
    assert svg.count("<polygon") == len(cands[0].outline.polygons)
