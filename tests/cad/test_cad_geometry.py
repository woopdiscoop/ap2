"""D03-D10 and D13: walls, rooms, labels, openings, plans, blocks/xrefs, contract."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest
import shapely
from cad_helpers import (
    GT_ROOM_AREAS_MM2,
    GT_WALLS,
    add_block,
    add_plan_pairs,
    add_plan_width,
    assert_walls_match,
    layer_map_for,
    new_doc,
    read,
    save,
    transform_gt,
)

from ale.cad import CadReadResult
from ale.contracts.enums import Frame, LabelSource, OpeningKind, SourceKind
from ale.contracts.models import PlanGeometry
from ale.contracts.serialization import canonical_json


def _area(room_polygon: object) -> float:
    poly = room_polygon  # contract Polygon
    return float(shapely.Polygon(poly.exterior, poly.holes).area)  # type: ignore[attr-defined]


def _pairs(tmp_path: Path, **kw: object) -> CadReadResult:
    doc = new_doc()
    add_plan_pairs(doc.modelspace(), **kw)  # type: ignore[arg-type]
    return read(save(doc, tmp_path / "pairs.dxf"))


def _assert_contract(res: CadReadResult) -> None:
    for plan in res.plans:
        back = PlanGeometry.model_validate_json(canonical_json(plan))
        assert canonical_json(back) == canonical_json(plan)
        assert plan.frame is Frame.Y_UP
        assert plan.source_kind is SourceKind.DXF


def test_D03_walls_pairs(tmp_path: Path) -> None:
    res = _pairs(tmp_path)
    assert len(res.plans) == 1, res.warnings
    assert_walls_match(res.plans[0], GT_WALLS)
    _assert_contract(res)


def test_D04_walls_width_polyline(tmp_path: Path) -> None:
    doc = new_doc()
    add_plan_width(doc.modelspace())
    res = read(save(doc, tmp_path / "width.dxf"))
    assert len(res.plans) == 1, res.warnings
    assert_walls_match(res.plans[0], GT_WALLS)
    areas = sorted(_area(r.polygon) for r in res.plans[0].rooms)
    assert areas == pytest.approx(sorted(GT_ROOM_AREAS_MM2), rel=0.01)
    _assert_contract(res)


def test_D04_width_polyline_variants(tmp_path: Path) -> None:
    """Old-style POLYLINE with a default width and per-vertex equal widths."""
    doc = new_doc()
    msp = doc.modelspace()
    pl = msp.add_polyline2d(
        [(0, 0), (8000, 0), (8000, 5000), (0, 5000)], close=True, dxfattribs={"layer": "MUR"}
    )
    pl.dxf.default_start_width = 200.0
    pl.dxf.default_end_width = 200.0
    msp.add_lwpolyline(
        [(4050, 0, 100, 100), (4050, 5000, 100, 100)], format="xyse", dxfattribs={"layer": "MUR"}
    )
    res = read(save(doc, tmp_path / "poly2d.dxf"))
    assert len(res.plans) == 1, res.warnings
    assert_walls_match(res.plans[0], GT_WALLS)


def test_D05_rooms_polygonize(tmp_path: Path) -> None:
    res = _pairs(tmp_path)
    plan = res.plans[0]
    assert len(plan.rooms) == 2
    areas = sorted(_area(r.polygon) for r in plan.rooms)
    assert areas == pytest.approx(sorted(GT_ROOM_AREAS_MM2), rel=0.01)
    for r in plan.rooms:  # no wall-cavity face: every room is at least 0.5 m wide
        assert shapely.Polygon(r.polygon.exterior).buffer(-250).area > 0
    assert [r.id for r in plan.rooms] == ["r001", "r002"]


def test_D05_rooms_polygonize_single_line_walls(tmp_path: Path) -> None:
    """Walls drawn as single lines (no pairs): thickness None, rooms still found."""
    doc = new_doc()
    msp = doc.modelspace()
    for a, b in [
        ((0, 0), (8000, 0)),
        ((8000, 0), (8000, 5000)),
        ((8000, 5000), (0, 5000)),
        ((0, 5000), (0, 0)),
        ((4000, 0), (4000, 5000)),
    ]:
        msp.add_line(a, b, dxfattribs={"layer": "MUR"})
    res = read(save(doc, tmp_path / "single.dxf"))
    plan = res.plans[0]
    assert all(w.thickness is None for w in plan.walls)
    assert sorted(_area(r.polygon) for r in plan.rooms) == pytest.approx([20e6, 20e6])


def test_D06_rooms_zones(tmp_path: Path) -> None:
    doc = new_doc()
    msp = doc.modelspace()
    add_plan_pairs(msp)
    zone_a = [(100, 100), (4000, 100), (4000, 4900), (100, 4900)]
    zone_b = [(4100, 100), (7900, 100), (7900, 3000), (6000, 3000), (6000, 4900), (4100, 4900)]
    msp.add_lwpolyline(zone_a, close=True, dxfattribs={"layer": "ZONES"})
    msp.add_lwpolyline(zone_b, close=True, dxfattribs={"layer": "ZONES"})
    res = read(save(doc, tmp_path / "zones.dxf"))
    plan = res.plans[0]
    got = sorted(_area(r.polygon) for r in plan.rooms)
    want = sorted(shapely.Polygon(z).area for z in (zone_a, zone_b))
    assert got == want  # exact
    rings = {frozenset(r.polygon.exterior) for r in plan.rooms}
    assert rings == {frozenset((float(x), float(y)) for x, y in z) for z in (zone_a, zone_b)}
    _assert_contract(res)


def test_D06_rooms_zone_hatch_and_zone_label(tmp_path: Path) -> None:
    doc = new_doc()
    msp = doc.modelspace()
    add_plan_pairs(msp)
    hatch = msp.add_hatch(dxfattribs={"layer": "ZONES"})
    hatch.paths.add_polyline_path([(100, 100), (4000, 100), (4000, 4900), (100, 4900)])
    edge = hatch.paths.add_edge_path()
    edge.add_line((1000, 1000), (2000, 1000))
    edge.add_line((2000, 1000), (2000, 2000))
    edge.add_line((2000, 2000), (1000, 2000))
    edge.add_line((1000, 2000), (1000, 1000))
    msp.add_text("ACCUEIL", dxfattribs={"layer": "ZONES", "insert": (500, 4000)})
    res = read(save(doc, tmp_path / "hatch.dxf"))
    plan = res.plans[0]
    assert len(plan.rooms) == 1
    room = plan.rooms[0]
    assert _area(room.polygon) == pytest.approx(3900 * 4800 - 1000 * 1000)
    assert room.type == "reception"
    assert room.label_source is LabelSource.CAD_ZONE


def test_D07_labels(tmp_path: Path) -> None:
    doc = new_doc()
    msp = doc.modelspace()
    add_plan_width(msp, extra_partition=True)
    msp.add_text("BUREAU 12", dxfattribs={"layer": "TEXTE", "insert": (1000, 2500), "height": 200})
    msp.add_text("12,40 m²", dxfattribs={"layer": "SURFACES", "insert": (1000, 2000)})
    msp.add_mtext("S. R\\fArial;ÉUNION", dxfattribs={"layer": "TEXTE", "insert": (5000, 1200)})
    res = read(save(doc, tmp_path / "labels.dxf"))
    plan = res.plans[0]
    assert len(plan.rooms) == 3
    by_type = {r.type: r for r in plan.rooms}
    office, meeting, none = by_type["office"], by_type["meeting_room"], by_type[None]
    assert office.label_source is LabelSource.CAD_TEXT
    assert office.confidence == 1.0
    assert office.raw_label == "BUREAU 12"
    assert office.area_text_m2 == 12.4
    assert meeting.label_source is LabelSource.CAD_TEXT
    assert meeting.raw_label == "S. RÉUNION"
    assert none.label_source is None and none.area_text_m2 is None
    assert {t.text for t in plan.texts} == {"BUREAU 12", "12,40 m²", "S. RÉUNION"}
    assert all(t.source == "CAD" for t in plan.texts)
    bureau = next(t for t in plan.texts if t.text == "BUREAU 12")
    assert bureau.height == 200 and bureau.layer == "TEXTE"
    _assert_contract(res)


def test_D07_labels_prefix_longest_and_area_formats(tmp_path: Path) -> None:
    from ale.cad.rooms import parse_area_text

    assert parse_area_text("S=12.4m2") == 12.4
    assert parse_area_text("12,40 m²") == 12.4
    assert parse_area_text("no area") is None
    doc = new_doc()
    msp = doc.modelspace()
    add_plan_pairs(msp)
    # two texts in the left room: the longest canonical match wins
    msp.add_text("SALLE", dxfattribs={"layer": "TEXTE", "insert": (500, 500)})
    msp.add_text("SALLE DE REUNION", dxfattribs={"layer": "TEXTE", "insert": (500, 1500)})
    msp.add_text("S=12.4m2", dxfattribs={"layer": "TEXTE", "insert": (500, 2500)})
    # right room: prefix match (confidence 0.8)
    msp.add_text("BUREAU DU CHEF", dxfattribs={"layer": "TEXTE", "insert": (5000, 2500)})
    res = read(save(doc, tmp_path / "prefix.dxf"))
    left, right = res.plans[0].rooms
    assert left.type == "meeting_room" and left.confidence == 1.0
    assert left.area_text_m2 == 12.4
    assert right.type == "office" and right.confidence == 0.8


def test_D08_openings(tmp_path: Path) -> None:
    doc = new_doc()
    msp = doc.modelspace()
    add_plan_pairs(msp, door_gap=(1000, 1900))
    add_block(doc, "DOOR", 900, 50)
    add_block(doc, "WIN", 900, 200)
    msp.add_blockref("DOOR", (4075, 1000), dxfattribs={"layer": "PORTES", "rotation": 90})
    msp.add_blockref("WIN", (5000, -100), dxfattribs={"layer": "FENETRES"})
    res = read(save(doc, tmp_path / "openings.dxf"))
    plan = res.plans[0]
    assert len(plan.openings) == 2
    door = next(o for o in plan.openings if o.kind is OpeningKind.DOOR)
    window = next(o for o in plan.openings if o.kind is OpeningKind.WINDOW)
    for o in (door, window):
        assert o.width_m == pytest.approx(0.900, abs=0.001)
    assert door.host_wall is not None
    host = plan.walls[door.host_wall].centerline.coords
    assert all(abs(p[0] - 4050) <= 5 for p in host)  # the partition
    assert window.host_wall is not None
    assert all(abs(p[1]) <= 5 for p in plan.walls[window.host_wall].centerline.coords)
    assert len(plan.rooms) == 2  # door span closes the partition faces
    _assert_contract(res)


def test_D08_openings_arc_door(tmp_path: Path) -> None:
    doc = new_doc()
    msp = doc.modelspace()
    add_plan_pairs(msp, door_gap=(1000, 1900))
    msp.add_arc((4050, 1000), 900, 90, 180, dxfattribs={"layer": "PORTES"})
    # an arc next to a door insert is part of that door, not a second door
    add_block(doc, "DOOR", 900, 50)
    msp.add_blockref("DOOR", (-50, 2000), dxfattribs={"layer": "PORTES", "rotation": 90})
    msp.add_arc((0, 2000), 900, 0, 90, dxfattribs={"layer": "PORTES"})
    res = read(save(doc, tmp_path / "arc.dxf"))
    plan = res.plans[0]
    assert len(plan.openings) == 2
    arc_door = next(o for o in plan.openings if o.segment.coords[0] == (4050.0, 1000.0))
    assert arc_door.kind is OpeningKind.DOOR
    assert arc_door.width_m == pytest.approx(0.9)
    assert arc_door.host_wall is not None


def test_D09_multi_plan(tmp_path: Path) -> None:
    doc = new_doc()
    msp = doc.modelspace()
    add_plan_pairs(msp)  # bottom
    add_plan_pairs(msp, dy=30000)  # top
    for a, b in [
        ((200000, 200000), (201000, 200000)),
        ((201000, 200000), (200500, 200800)),
        ((200500, 200800), (200000, 200000)),
    ]:
        msp.add_line(a, b, dxfattribs={"layer": "MUR"})
    res = read(save(doc, tmp_path / "multi.dxf"))
    assert len(res.plans) == 2
    assert [p.plan_index for p in res.plans] == [0, 1]
    top, bottom = res.plans
    assert min(pt[1] for w in top.walls for pt in w.centerline.coords) > 25000
    assert max(pt[1] for w in bottom.walls for pt in w.centerline.coords) < 6000
    assert_walls_match(bottom, GT_WALLS)
    assert any("ignored fragment" in w for w in res.warnings)
    _assert_contract(res)


def test_D09_multi_plan_top_left_first(tmp_path: Path) -> None:
    doc = new_doc()
    msp = doc.modelspace()
    add_plan_pairs(msp, dx=30000)  # right
    add_plan_pairs(msp)  # left, same height
    res = read(save(doc, tmp_path / "side.dxf"))
    assert len(res.plans) == 2
    assert min(pt[0] for w in res.plans[0].walls for pt in w.centerline.coords) < 1000


def test_D10_blocks_and_xrefs(tmp_path: Path) -> None:
    doc = new_doc()
    blk = doc.blocks.new("PLAN")
    add_plan_pairs(blk, scale=0.5)
    msp = doc.modelspace()
    msp.add_blockref("PLAN", (20000, 1000), dxfattribs={"rotation": 90, "xscale": 2, "yscale": 2})
    xref = doc.blocks.new("MISSING_REF")
    xref.block.dxf.flags |= 4
    xref.block.dxf.xref_path = "C:\\projets\\missing_ref.dxf"
    msp.add_blockref("MISSING_REF", (0, 0))
    res = read(save(doc, tmp_path / "blocks.dxf"))
    assert len(res.plans) == 1, res.warnings
    assert_walls_match(res.plans[0], transform_gt(GT_WALLS, 90, 1.0, (20000, 1000)))
    assert "missing xref MISSING_REF" in res.warnings
    _assert_contract(res)


def test_D10_xref_bound_and_layer0_inherits(tmp_path: Path) -> None:
    ref = new_doc()
    add_plan_pairs(ref.modelspace())
    save(ref, tmp_path / "ground floor.dxf")
    doc = new_doc()
    xref = doc.blocks.new("GF")
    xref.block.dxf.flags |= 4
    xref.block.dxf.xref_path = "..\\elsewhere\\ground floor.dxf"
    msp = doc.modelspace()
    msp.add_blockref("GF", (0, 0))
    # a block drawn on layer 0 inserted on a door layer
    nested = doc.blocks.new("NESTED")
    nested.add_arc((0, 0), 900, 90, 180)  # layer 0 → takes the INSERT layer (PORTES)
    msp.add_blockref("NESTED", (4050, 1000), dxfattribs={"layer": "PORTES_ARC"})
    main = save(doc, tmp_path / "main.dxf")
    lm = layer_map_for(ezdxf.readfile(main), ["MUR", "PORTES_ARC"])
    res = read(tmp_path / "main.dxf", layer_map=lm)
    assert len(res.plans) == 1, res.warnings
    assert_walls_match(res.plans[0], GT_WALLS)
    assert "MUR" in res.layer_names
    assert len(res.plans[0].openings) == 1


def test_D10_xref_not_dxf_and_circular(tmp_path: Path) -> None:
    (tmp_path / "plan.dwg").write_bytes(b"AC1032")
    doc = new_doc()
    x = doc.blocks.new("DWGREF")
    x.block.dxf.flags |= 4
    x.block.dxf.xref_path = "plan.dwg"
    doc.modelspace().add_blockref("DWGREF", (0, 0))
    me = doc.blocks.new("SELF")
    me.block.dxf.flags |= 4
    me.block.dxf.xref_path = "self.dxf"
    doc.modelspace().add_blockref("SELF", (0, 0))
    bad = tmp_path / "broken.dxf"
    bad.write_text("not a dxf", encoding="utf-8")
    b = doc.blocks.new("BROKEN")
    b.block.dxf.flags |= 4
    b.block.dxf.xref_path = "broken.dxf"
    doc.modelspace().add_blockref("BROKEN", (0, 0))
    res = read(save(doc, tmp_path / "self.dxf"))
    assert res.plans == ()
    assert any("DWGREF is not a DXF" in w for w in res.warnings)
    assert any("SELF: circular" in w for w in res.warnings)
    assert any("BROKEN: cannot read" in w for w in res.warnings)


def test_D13_contract_valid(tmp_path: Path) -> None:
    doc = new_doc()
    msp = doc.modelspace()
    add_plan_pairs(msp, door_gap=(1000, 1900))
    add_block(doc, "DOOR", 900, 50)
    msp.add_blockref("DOOR", (4075, 1000), dxfattribs={"layer": "PORTES", "rotation": 90})
    msp.add_text("BUREAU", dxfattribs={"layer": "TEXTE", "insert": (500, 500)})
    msp.add_text(
        "centered",
        dxfattribs={"layer": "TEXTE", "insert": (0, 0), "align_point": (5000, 500), "halign": 1},
    )
    add_plan_width(msp.doc.blocks.new("W"))
    msp.add_blockref("W", (0, 40000))
    res = read(save(doc, tmp_path / "all.dxf"))
    assert len(res.plans) == 2
    _assert_contract(res)
    centered = next(t for p in res.plans for t in p.texts if t.text == "centered")
    assert centered.insert == (5000.0, 500.0)
    metric = res.plans[0].to_metric()
    assert metric.units_label == "m"
