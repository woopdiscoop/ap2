"""Ticket 3.1 section 2: ``site.yaml`` (inline / DXF) and the module footprint (Y01-Y08)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
from fixtures import load_site
from program_helpers import site_to_yaml, write_dxf, write_site_yaml

from ale.contracts.geometry import Polygon
from ale.contracts.models import GridSpec, SiteSpec
from ale.program.models import InputError
from ale.program.site import (
    module_perimeter_mm,
    normalise_footprint,
    read_site,
    site_from_mapping,
    to_module_footprint,
)

GRID = GridSpec()

SITE_RECT_MM = [(0, 0), (24000, 0), (24000, 18000), (0, 18000)]


def site_of(points: list[tuple[float, float]], access_edge: int = 0) -> SiteSpec:
    spec, issues = site_from_mapping(
        {"footprint": [list(p) for p in points], "access_edge": access_edge}, Path()
    )
    assert spec is not None, issues
    return spec


def site_codes(data: Any, base: Path = Path()) -> list[str]:
    spec, issues = site_from_mapping(data, base)
    assert spec is None
    return [i.code for i in issues]


def footprint_error(site: SiteSpec) -> list[str]:
    with pytest.raises(InputError) as info:
        to_module_footprint(site, GRID)
    return [i.code for i in info.value.issues]


# --------------------------------------------------------------------------- Y01


@pytest.mark.parametrize("name", ["site_rect_small", "site_rect", "site_L"])
def test_Y01_yaml_fixtures(tmp_path: Path, name: str) -> None:
    fixture = load_site(name)  # type: ignore[arg-type]
    spec, issues = read_site(site_to_yaml(fixture, tmp_path / "site.yaml"))
    assert issues == ()
    assert spec == fixture


# --------------------------------------------------------------------------- Y02


def test_Y02_module_exact() -> None:
    rect = to_module_footprint(load_site("site_rect"), GRID)
    assert rect.polygon.exterior == ((0, 0), (240, 0), (240, 180), (0, 180))
    assert rect.sliver_loss_m2 == 0.0
    assert rect.origin_m == (0.0, 0.0)
    assert rect.access_edge == 0
    ell = to_module_footprint(load_site("site_L"), GRID)
    assert ell.polygon.exterior == (
        (0, 0),
        (480, 0),
        (480, 180),
        (300, 180),
        (300, 300),
        (0, 300),
    )
    assert ell.polygon.area_cells() == 122_400
    assert ell.sliver_loss_m2 == 0.0


# --------------------------------------------------------------------------- Y03 / Y04


def test_Y03_inward_snap_rect() -> None:
    fp = to_module_footprint(site_of([(0.05, 0), (10.03, 0), (10.03, 5.07), (0.05, 5.07)]), GRID)
    assert fp.origin_m == (0.05, 0.0)
    assert fp.polygon.exterior == ((0, 0), (99, 0), (99, 50), (0, 50))
    assert fp.sliver_loss_m2 == 1.0986


def test_Y04_inward_snap_L() -> None:
    pts = [(0, 0), (10.05, 0), (10.05, 4.02), (6.03, 4.02), (6.03, 8.07), (0, 8.07)]
    fp = to_module_footprint(site_of(pts), GRID)
    assert fp.polygon.exterior == ((0, 0), (100, 0), (100, 40), (60, 40), (60, 80), (0, 80))
    assert fp.polygon.area_cells() == 6400
    assert fp.sliver_loss_m2 == 0.8225


# --------------------------------------------------------------------------- Y05


def test_Y05_normalise_and_access() -> None:
    cw = site_of([(0, 0), (0, 18), (24, 18), (24, 0)], access_edge=0)
    assert cw.footprint.exterior == ((0.0, 0.0), (24.0, 0.0), (24.0, 18.0), (0.0, 18.0))
    assert cw.access_edge == 3
    merged = site_of([(0, 0), (5, 0), (10, 0), (10, 5), (0, 5)], access_edge=1)
    assert len(merged.footprint.exterior) == 4
    assert merged.access_edge == 0


def test_normalise_rotation_and_duplicates() -> None:
    # Starts elsewhere, has a duplicate vertex and a collinear vertex on the closing edge.
    ring, access = normalise_footprint(
        [(10, 10), (0, 10), (0, 0), (0, 0), (5, 0), (10, 0), (10, 5)], access_edge=6
    )
    assert ring == ((0, 0), (10, 0), (10, 10), (0, 10))
    assert access == 1
    with pytest.raises(InputError) as info:
        normalise_footprint([(0, 0), (0, 0), (10, 0), (10, 10), (0, 10)], access_edge=0)
    assert [i.code for i in info.value.issues] == ["E_SITE_ACCESS_EDGE"]


# --------------------------------------------------------------------------- Y06


def test_Y06_site_errors() -> None:
    square = [[0, 0], [10, 0], [10, 10], [0, 10]]
    both = {"footprint": square, "footprint_dxf": {"path": "a.dxf", "layer": "EMPRISE"}}
    assert site_codes(both) == ["E_SITE_SCHEMA"]
    assert site_codes({"north_angle_deg": 0}) == ["E_SITE_SCHEMA"]

    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    rotated = [[x * c - y * s, x * s + y * c] for x, y in square]
    assert site_codes({"footprint": rotated}) == ["E_SITE_NOT_ORTHOGONAL"]

    bow_tie = [[0, 0], [10, 10], [10, 0], [0, 10]]
    assert site_codes({"footprint": bow_tie}) == ["E_SITE_INVALID"]
    bow_tie_rect = [[0, 0], [10, 0], [10, 10], [5, 10], [5, -5], [0, -5]]
    assert site_codes({"footprint": bow_tie_rect}) == ["E_SITE_INVALID"]

    tiny = site_of([(0, 0), (0.05, 0), (0.05, 0.05), (0, 0.05)])
    assert footprint_error(tiny) == ["E_SITE_TOO_SMALL"]

    assert site_codes({"footprint": square, "nord": 20}) == ["E_SITE_SCHEMA"]


def test_site_schema_details(tmp_path: Path) -> None:
    square = [[0, 0], [10, 0], [10, 10], [0, 10]]
    assert site_codes([1, 2]) == ["E_SITE_SCHEMA"]
    assert site_codes({"footprint": square, "north_angle_deg": 360}) == ["E_SITE_SCHEMA"]
    assert site_codes({"footprint": square, "access_edge": "0"}) == ["E_SITE_SCHEMA"]
    assert site_codes({"footprint": square, "access_edge": 4}) == ["E_SITE_ACCESS_EDGE"]
    assert site_codes({"footprint": square, "core_hint": [1]}) == ["E_SITE_SCHEMA"]
    assert site_codes({"footprint": [[0, 0], [1, 1]]}) == ["E_SITE_SCHEMA"]
    assert site_codes({"footprint": [[0, 0], [1, 0], ["a", 1]]}) == ["E_SITE_SCHEMA"]
    assert site_codes({"footprint": [[0, 0], [1, 0], [2, 0]]}) == ["E_SITE_INVALID"]
    assert site_codes({"footprint_dxf": "emprise.dxf"}) == ["E_SITE_SCHEMA"]
    dxf_bad = {"footprint_dxf": {"path": "", "layer": "L", "units": "ft", "x": 1}}
    assert site_codes(dxf_bad) == ["E_SITE_SCHEMA"] * 3

    spec, issues = read_site(tmp_path / "absent.yaml")
    assert spec is None
    assert [i.code for i in issues] == ["E_FILE_UNREADABLE"]
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("footprint: [[0, 0]\n", encoding="utf-8")
    assert [i.code for i in read_site(bad_yaml)[1]] == ["E_SITE_SCHEMA"]

    full = write_site_yaml(
        tmp_path / "full.yaml",
        {"footprint": square, "north_angle_deg": 12.5, "access_edge": 2, "core_hint": [3, 4]},
    )
    spec, issues = read_site(full)
    assert spec is not None
    assert (spec.north_angle_deg, spec.access_edge, spec.core_hint) == (12.5, 2, (3.0, 4.0))


def test_module_footprint_edge_cases() -> None:
    with_hole = SiteSpec(
        footprint=Polygon(
            exterior=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
            holes=(((2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)),),
        ),
        north_angle_deg=0.0,
        access_edge=0,
    )
    assert footprint_error(with_hole) == ["E_SITE_INVALID"]
    clockwise = SiteSpec(
        footprint=Polygon(exterior=((0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0))),
        north_angle_deg=0.0,
        access_edge=0,
    )
    assert footprint_error(clockwise) == ["E_SITE_INVALID"]
    collinear = SiteSpec(
        footprint=Polygon(
            exterior=((0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        ),
        north_angle_deg=0.0,
        access_edge=0,
    )
    assert footprint_error(collinear) == ["E_SITE_INVALID"]
    # A 0.05 m wide step vanishes on the 0.10 m grid, taking the access edge with it.
    step = site_of([(0, 0), (10, 0), (10, 5), (5, 5), (5, 5.05), (0, 5.05)], access_edge=3)
    assert footprint_error(step) == ["E_SITE_ACCESS_EDGE"]
    # ... while another access edge survives (merged with its collinear neighbour).
    fp = to_module_footprint(site_of(list(step.footprint.exterior), access_edge=4), GRID)
    assert fp.polygon.exterior == ((0, 0), (100, 0), (100, 50), (0, 50))
    assert fp.access_edge == 2
    assert fp.sliver_loss_m2 == 0.25
    assert module_perimeter_mm(fp.polygon, GRID) == 30_000
    # A sliver thinner than one module collapses.
    thin = site_of([(0, 0), (10, 0), (10, 0.05), (0, 0.05)])
    assert footprint_error(thin) == ["E_SITE_TOO_SMALL"]


# --------------------------------------------------------------------------- Y07 / Y08


def _dxf_site(tmp_path: Path, dxf_name: str = "emprise.dxf", **dxf: Any) -> Path:
    spec = {"path": dxf_name, "layer": "EMPRISE", "units": None, **dxf}
    return write_site_yaml(tmp_path / "site.yaml", {"footprint_dxf": spec, "access_edge": 0})


def test_Y07_dxf_mm(tmp_path: Path) -> None:
    pytest.importorskip("ezdxf")  # the 'cad' extra
    write_dxf(tmp_path / "emprise.dxf", [SITE_RECT_MM], insunits=4)
    spec, issues = read_site(_dxf_site(tmp_path))
    assert issues == ()
    assert spec == load_site("site_rect")


def test_Y08_dxf_errors(tmp_path: Path) -> None:
    pytest.importorskip("ezdxf")  # the 'cad' extra

    def codes_for() -> list[str]:
        spec, issues = read_site(_dxf_site(tmp_path))
        assert spec is None
        return [i.code for i in issues]

    write_dxf(tmp_path / "emprise.dxf", [SITE_RECT_MM, SITE_RECT_MM], insunits=4)
    assert codes_for() == ["E_SITE_DXF"]
    write_dxf(tmp_path / "emprise.dxf", [SITE_RECT_MM], insunits=4, layer="AUTRE")
    assert codes_for() == ["E_SITE_DXF"]

    write_dxf(tmp_path / "emprise.dxf", [SITE_RECT_MM], insunits=0)
    assert codes_for() == ["E_SITE_UNITS"]
    spec, issues = read_site(_dxf_site(tmp_path, units="mm"))
    assert issues == ()
    assert spec == load_site("site_rect")

    spec, issues = read_site(_dxf_site(tmp_path, dxf_name="emprise.dwg"))
    assert [i.code for i in issues] == ["E_SITE_DWG"]


def test_dxf_variants(tmp_path: Path) -> None:
    ezdxf = pytest.importorskip("ezdxf")  # the 'cad' extra

    # cm units from the YAML, an open polyline whose last point repeats the first, layer case.
    cm = [(0, 0), (2400, 0), (2400, 1800), (0, 1800), (0, 0)]
    write_dxf(tmp_path / "cm.dxf", [cm], insunits=None, layer="emprise", closed=False)
    spec, issues = read_site(_dxf_site(tmp_path, dxf_name="cm.dxf", units="cm"))
    assert issues == ()
    assert spec == load_site("site_rect")

    # Old-style POLYLINE in metres ($INSUNITS = 6) plus an ignored open polyline.
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    poly = msp.add_polyline2d([(0, 0), (24, 0), (24, 18), (0, 18)], dxfattribs={"layer": "EMPRISE"})
    poly.close(True)
    msp.add_lwpolyline([(0, 0), (1, 1)], dxfattribs={"layer": "EMPRISE"})
    msp.add_polyface().append_face([(0, 0, 0), (1, 0, 0), (1, 1, 0)])
    doc.saveas(tmp_path / "m.dxf")
    spec, issues = read_site(_dxf_site(tmp_path, dxf_name="m.dxf"))
    assert issues == ()
    assert spec == load_site("site_rect")

    # Arc segment (bulge) → not orthogonal.
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6
    doc.modelspace().add_lwpolyline(
        [(0, 0, 0.5), (10, 0, 0), (10, 10, 0), (0, 10, 0)],
        format="xyb",
        close=True,
        dxfattribs={"layer": "EMPRISE"},
    )
    doc.saveas(tmp_path / "arc.dxf")
    spec, issues = read_site(_dxf_site(tmp_path, dxf_name="arc.dxf"))
    assert [i.code for i in issues] == ["E_SITE_NOT_ORTHOGONAL"]

    # Missing and corrupt DXF files.
    spec, issues = read_site(_dxf_site(tmp_path, dxf_name="absent.dxf"))
    assert [i.code for i in issues] == ["E_SITE_DXF"]
    (tmp_path / "corrupt.dxf").write_text("pas un dxf", encoding="utf-8")
    spec, issues = read_site(_dxf_site(tmp_path, dxf_name="corrupt.dxf"))
    assert [i.code for i in issues] == ["E_SITE_DXF"]

    # Degenerate closed polyline (2 vertices).
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6
    doc.modelspace().add_lwpolyline([(0, 0), (10, 0)], close=True, dxfattribs={"layer": "EMPRISE"})
    doc.saveas(tmp_path / "two.dxf")
    spec, issues = read_site(_dxf_site(tmp_path, dxf_name="two.dxf"))
    assert [i.code for i in issues] == ["E_SITE_INVALID"]
