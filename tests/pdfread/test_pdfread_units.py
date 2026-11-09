"""Unit tests of the Ticket 1.3 building blocks (scale tokens, walls, arcs, rooms, paths)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pymupdf
import pytest
import shapely
from pdf_helpers import SHA, read, save_page

from ale.contracts.config import AleConfig
from ale.contracts.enums import OpeningKind, ScaleMethod
from ale.contracts.geometry import LineString
from ale.contracts.models import Opening, Wall
from ale.pdfread import ScaleText, find_scale, m_per_pt, plan_likeness, read_pdf_page, scale_tokens
from ale.pdfread.read import _collect_drawings, _collect_texts, _Page
from ale.pdfread.rooms import RoomText, label_rooms, parse_area_text, polygonize_rooms
from ale.pdfread.walls import (
    FilledShape,
    StrokeSeg,
    build_doors,
    door_closures,
    extract_walls,
    fit_arc,
    merged_wall_count,
)

# --------------------------------------------------------------------------- scale


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1/100", (100,)),
        ("1:50", (50,)),
        ("Ech. 1/200", (200,)),
        ("ÉCHELLE 1:100", (100,)),
        ("échelle : 1/75", (75,)),
        ("SCALE 1:20", (20,)),
        ("Ech 1/33", (33,)),  # unusual value accepted after a keyword
        ("Planche 1/12", ()),  # bare, not a usual scale: a sheet number
        ("01/12/2024", ()),
        ("1/100/2", ()),
        ("1:100.5", ()),
        ("version 21:100", ()),
        ("1 : 100 et 1/500.", (100, 500)),
        ("rien", ()),
    ],
)
def test_scale_tokens(text: str, expected: tuple[int, ...]) -> None:
    assert scale_tokens(text) == expected


def test_find_scale_rules() -> None:
    assert m_per_pt(100) == 100 * 0.0254 / 72
    none = find_scale([ScaleText("PLAN", (0, 0, 10, 10))], (0, 0, 100, 100))
    assert none.method is ScaleMethod.UNKNOWN and none.m_per_unit is None
    same = find_scale(
        [ScaleText("1:100", (0, 0, 10, 10)), ScaleText("ECH 1/100", (500, 500, 510, 510))],
        (0, 0, 100, 100),
    )
    assert same.denominator == 100 and same.confidence == 0.9
    texts = [ScaleText("1:500", (500, 500, 510, 510)), ScaleText("1:50", (110, 0, 120, 10))]
    near = find_scale(texts, (0, 0, 100, 100))
    assert near.denominator == 50 and near.confidence == 0.6 and near.candidates == (500, 50)
    no_walls = find_scale(texts, None)
    assert no_walls.denominator == 500 and no_walls.confidence == 0.6


# --------------------------------------------------------------------------- plan score


def test_plan_likeness_formula() -> None:
    assert plan_likeness(4, 2, 600.0, 1000.0) == (True, 1.0)
    likely, score = plan_likeness(2, 1, 300.0, 1000.0)
    assert not likely and score == pytest.approx(0.5)
    assert plan_likeness(3, 5, 1e4, 1000.0)[0] is False
    assert plan_likeness(0, 0, 0.0, 0.0) == (False, pytest.approx(1 / 3))
    assert plan_likeness(100, 100, 1e9, 10.0) == (True, 1.0)


# --------------------------------------------------------------------------- walls


def _s(a: tuple[float, float], b: tuple[float, float], w: float = 0.5) -> StrokeSeg:
    return StrokeSeg((a, b), w)


def test_pairing_thresholds() -> None:
    assert extract_walls([_s((0, 0), (100, 0)), _s((0, 1.5), (100, 1.5))], []).walls == []
    assert extract_walls([_s((0, 0), (100, 0)), _s((0, 26), (100, 26))], []).walls == []
    # 2° apart: not parallel
    tilt = (100 * math.cos(math.radians(2)), 10 + 100 * math.sin(math.radians(2)))
    assert extract_walls([_s((0, 0), (100, 0)), _s((0, 10), tilt)], []).walls == []
    # overlap 40 % of the shorter: no pair
    assert extract_walls([_s((0, 0), (100, 0)), _s((80, 10), (130, 10))], []).walls == []
    # too short once paired
    assert extract_walls([_s((0, 0), (10, 0)), _s((0, 10), (10, 10))], []).walls == []
    res = extract_walls([_s((0, 0), (100, 0)), _s((100, 10), (0, 10))], [])
    assert len(res.walls) == 1
    wall = res.walls[0]
    assert wall.thickness == pytest.approx(10.0)
    assert {p[1] for p in wall.centerline.coords} == {5.0}
    # bins wrap around 180°: 179.9° and 0.1° are parallel
    a = (100 * math.cos(math.radians(179.6)), 100 * math.sin(math.radians(179.6)))
    res = extract_walls([_s((0, 0), (100, 0)), _s((100, 8), (100 + a[0], 8 + a[1]))], [])
    assert len(res.walls) == 1


def test_merged_wall_count() -> None:
    assert merged_wall_count([]) == 0
    pieces = [
        _wall((0, 0), (100, 0)),
        _wall((106, 0), (200, 0)),  # gap 6 ≤ thickness + 1: same wall
        _wall((300, 0.5), (200, 0.5)),  # touching, reversed, offset 0.5
        _wall((240, 0), (260, 0)),  # overlapping
        _wall((215, 0), (215, 100)),  # perpendicular
        _wall((0, 20), (100, 20)),  # parallel, 20 pt away
        _wall((330, 0), (400, 0)),  # gap 30: separate
    ]
    assert merged_wall_count(pieces) == 4


def test_degenerate_inputs() -> None:
    assert extract_walls([], []).walls == []
    assert extract_walls([_s((0, 0), (0, 0)), _s((0, 0), (math.nan, 1))], []).walls == []
    assert extract_walls([_s((0, 0), (100, 0))], []).walls == []


def test_thick_strokes_and_filled_shapes() -> None:
    thin = [_s((0, 50 * k), (40, 50 * k), 0.3) for k in range(5)]
    thick = _s((0, 400), (200, 400), 3.0)
    res = extract_walls([*thin, thick], [])
    assert len(res.walls) == 1 and res.walls[0].thickness == 3.0
    shapes = [
        FilledShape(((0, 0), (100, 0), (100, 10), (0, 10))),  # wall
        FilledShape(((0, 0), (10, 0), (10, 100), (0, 100))),  # vertical wall
        FilledShape(((0, 0), (40, 0), (40, 10), (0, 10))),  # aspect 4 < 5
        FilledShape(((0, 0), (300, 0), (300, 30), (0, 30))),  # 30 pt thick
        FilledShape(((0, 0), (1, 0))),  # not a polygon
        FilledShape(((0, 0), (10, 10), (10, 0), (0, 10))),  # bow tie (invalid)
        FilledShape(((0, 0), (5, 0), (10, 0))),  # zero area
    ]
    res = extract_walls([], shapes)
    assert [w.thickness for w in res.walls] == [10.0, 10.0]
    assert res.material and res.face_lines


def _quarter_beziers(c: tuple[float, float], r: float, start_deg: float, pieces: int) -> list[Any]:
    out = []
    step = math.radians(90.0 / pieces)
    k = 4.0 / 3.0 * math.tan(step / 4.0) * r
    for i in range(pieces):
        a0 = math.radians(start_deg) + i * step
        a1 = a0 + step
        p0 = (c[0] + r * math.cos(a0), c[1] + r * math.sin(a0))
        p3 = (c[0] + r * math.cos(a1), c[1] + r * math.sin(a1))
        c1 = (p0[0] - k * math.sin(a0), p0[1] + k * math.cos(a0))
        c2 = (p3[0] + k * math.sin(a1), p3[1] - k * math.cos(a1))
        out.append((p0, c1, c2, p3))
    return out


def test_fit_arc() -> None:
    for pieces in (1, 2, 3):
        arc = fit_arc(_quarter_beziers((10.0, 20.0), 30.0, 0.0, pieces))
        assert arc is not None
        assert arc.radius == pytest.approx(30.0, rel=1e-3)
        assert arc.sweep_deg == pytest.approx(90.0, abs=0.5)
        assert arc.center == pytest.approx((10.0, 20.0), abs=0.05)
    assert fit_arc([]) is None
    straight = ((0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0))
    assert fit_arc([straight]) is None  # collinear
    wobbly = ((0.0, 0.0), (0.0, 40.0), (40.0, -40.0), (40.0, 0.0))
    assert fit_arc([wobbly]) is None  # not circular


def _wall(a: tuple[float, float], b: tuple[float, float], t: float | None = 6.0) -> Wall:
    return Wall(centerline=LineString(coords=(a, b)), thickness=t)


def test_build_doors_rules() -> None:
    walls = [_wall((0, 0), (100, 0)), _wall((130, 0), (300, 0))]
    good = _quarter_beziers((100.0, 3.0), 30.0, 0.0, 1)  # hinge at the jamb, opens down
    small = _quarter_beziers((100.0, 3.0), 10.0, 0.0, 1)
    far = _quarter_beziers((100.0, 80.0), 30.0, 0.0, 1)
    doors = build_doors([good, small, far], walls)
    assert len(doors) == 1
    door = doors[0]
    assert door.width_native == pytest.approx(30.0, rel=1e-3)
    assert door.segment.coords[1][1] == pytest.approx(3.0, abs=0.1)  # end on the wall line
    assert door.host_wall in (0, 1)
    assert build_doors([good], []) == []
    closures = door_closures(doors, walls)
    assert len(closures) == 2
    no_thickness = [_wall((0, 0), (100, 0), None), _wall((130, 0), (300, 0), None)]
    assert len(door_closures(doors, no_thickness)) == 1
    unhosted = Opening(
        kind=OpeningKind.DOOR, segment=LineString(coords=((0, 0), (0, 30))), width_native=30.0
    )
    (seg,) = door_closures([unhosted], walls)
    assert seg[0][1] < 0.0 and seg[1][1] > 30.0


# --------------------------------------------------------------------------- rooms


def test_parse_area_text() -> None:
    assert parse_area_text("12,40 m²") == pytest.approx(12.4)
    assert parse_area_text("S=12.4m2") == pytest.approx(12.4)
    assert parse_area_text("0 m2") is None
    assert parse_area_text("BUREAU") is None


def test_polygonize_and_label() -> None:
    sq = [((0.0, 0.0), (300.0, 0.0)), ((300.0, 0.0), (300.0, 300.0))]
    sq += [((300.0, 300.0), (0.0, 300.0)), ((0.0, 300.0), (0.0, 0.0))]
    warnings: list[str] = []
    assert polygonize_rooms([], [], None, warnings) == []
    faces = polygonize_rooms(sq, [], None, warnings)
    assert len(faces) == 1
    # covered by wall material → dropped
    assert polygonize_rooms(sq, [shapely.box(0, 0, 300, 300)], None, warnings) == []
    # too small at 1:100 (300 pt square ≈ 112 m², ok; 1:1000 → 11 200 m², too big)
    assert len(polygonize_rooms(sq, [], m_per_pt(100), warnings)) == 1
    assert polygonize_rooms(sq, [], m_per_pt(1000), warnings) == []
    big = [((x, 0.0), (x, 10.0)) for x in range(70_000)]
    assert polygonize_rooms(big, [], None, warnings) == []
    assert warnings and warnings[-1].startswith("polygonize skipped")

    texts = [
        RoomText("12", (10.0, 10.0)),
        RoomText("SALLE DE REUNION 2", (150.0, 150.0)),
        RoomText("12,5 m²", (150.0, 170.0)),
        RoomText("BUREAU", (500.0, 500.0)),
    ]
    (room,) = label_rooms(faces, texts, warnings)
    assert room.id == "r001" and room.type == "meeting_room" and room.confidence == 1.0
    assert room.area_text_m2 == pytest.approx(12.5)
    (prefix,) = label_rooms(faces, [RoomText("BUREAU DU CHEF X", (5.0, 5.0))], warnings)
    assert prefix.type == "office" and prefix.confidence == 0.8
    (unk,) = label_rooms(faces, [RoomText("ZZZ", (5.0, 5.0))], warnings)
    assert unk.type is None and unk.label_source is None and unk.raw_label == "ZZZ"


# --------------------------------------------------------------------------- PDF paths


def test_collect_paths(tmp_path: Path) -> None:
    def build(page: Any) -> None:
        sh = page.new_shape()
        sh.draw_quad(pymupdf.Quad((10, 10), (110, 20), (9, 20), (109, 30)))
        sh.finish(fill=(0, 0, 0), color=(0, 0, 0), width=0.5)
        sh.draw_polyline([(200, 200), (300, 200), (300, 208), (200, 208)])
        sh.finish(fill=(0, 0, 0), color=None, closePath=True)
        sh.draw_polyline([(50, 400), (150, 400), (150, 480)])
        sh.finish(color=(0, 0, 0), width=0.5, closePath=True)
        sh.draw_line((0, 600), (50, 600))
        sh.draw_line((60, 600), (90, 600))  # disjoint subpath
        sh.draw_bezier((300, 300), (310, 310), (320, 310), (330, 300))
        sh.draw_line((330, 300), (340, 300))
        sh.draw_bezier((340, 300), (350, 310), (360, 310), (370, 300))
        sh.draw_bezier((400, 300), (410, 310), (420, 310), (430, 300))
        sh.finish(color=(0, 0, 0), width=0.5, closePath=False)
        sh.commit()
        page.insert_text((100, 700), "rotated", rotate=90, fontsize=9)

    path = save_page(tmp_path / "paths.pdf", build)
    doc = pymupdf.open(path)
    col = _Page()
    _collect_drawings(doc[0].get_drawings(), col)
    _collect_texts(doc[0].get_text("dict"), col)
    doc.close()
    assert len(col.filled) == 2
    assert len(col.chains) == 3
    closing = [s for s in col.strokes if s.seg == ((150.0, 480.0), (50.0, 400.0))]
    assert closing
    assert any(abs(t.rotation_deg) == pytest.approx(90.0) for t in col.texts)

    weird = _Page()
    _collect_drawings(
        [
            {"type": "s", "width": None, "items": [("l", (0, 0), (math.inf, 0)), ("c",), ("x",)]},
            {"type": "s", "width": 1.0, "items": [("c", (0, 0), (1, 1), (math.nan, 2), (3, 3))]},
            {"type": "f", "fill": (0, 0, 0), "items": [("re", pymupdf.Rect(0, 0, math.inf, 1), 1)]},
            {"type": "s", "width": 1.0, "items": [("l",)]},
        ],
        weird,
    )
    assert weird.strokes == [] and weird.chains == [] and weird.filled == []
    assert weird.warnings and weird.warnings[0].startswith("path skipped: IndexError")
    texts = _Page()
    _collect_texts(
        {
            "blocks": [
                {
                    "lines": [
                        {
                            "dir": (1, 0),
                            "spans": [{"text": "x", "origin": (0, 0), "bbox": (0, 0, math.inf, 1)}],
                        }
                    ]
                },
                {
                    "lines": [
                        {
                            "dir": (1, 0),
                            "spans": [{"text": "  ", "origin": (0, 0), "bbox": (0, 0, 1, 1)}],
                        }
                    ]
                },
                {"type": 1},
            ]
        },
        texts,
    )
    assert texts.texts == [] and texts.scale_texts == []


def test_truncation_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    import ale.pdfread.read as rd

    monkeypatch.setattr(rd, "MAX_PATH_ITEMS", 2)
    col = _Page()
    path = {"type": "s", "width": 1.0, "items": [("l", (0, 0), (1, 0))] * 2}
    _collect_drawings([path, path, path], col)
    assert col.warnings and "truncated" in col.warnings[0]
    monkeypatch.setattr(rd, "MAX_TEXT_SPANS", 1)
    span = {"text": "a", "origin": (0, 0), "bbox": (0, 0, 1, 1), "size": 5}
    col = _Page()
    _collect_texts({"blocks": [{"lines": [{"dir": (1, 0), "spans": [span, span]}]}]}, col)
    assert len(col.texts) == 1 and "truncated" in col.warnings[0]


def test_bad_arguments_and_internal_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = save_page(tmp_path / "e.pdf", lambda page: None)
    cfg = AleConfig()
    assert (
        read_pdf_page(path, 0, source_sha256="nope", config=cfg)
        .warnings[0]
        .startswith("invalid source_sha256")
    )
    assert (
        read_pdf_page(path, -1, source_sha256=SHA, config=cfg)
        .warnings[0]
        .startswith("invalid page")
    )
    import ale.pdfread.read as rd

    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(rd, "extract_walls", boom)
    res = read(path)
    assert res.plans == () and res.warnings[-1] == "extraction error: RuntimeError: boom"
    monkeypatch.setattr(rd, "_collect_drawings", boom)
    assert read(path).warnings[0].startswith("cannot parse page 0")
