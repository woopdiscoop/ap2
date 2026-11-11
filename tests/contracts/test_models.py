"""Tests M01-M12: data models."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from types import SimpleNamespace
from typing import Any

import pytest
import shapely
from pydantic import BaseModel, ValidationError

import ale.contracts
from ale.contracts.area_rule import AreaCheck, AreaTolerance
from ale.contracts.corridor_plan import (
    BandPlan,
    BlockPlan,
    ConnectorBay,
    CorridorPlan,
    FingerBay,
    PiecePlan,
    RoomBay,
)
from ale.contracts.enums import (
    Bearing,
    Fidelity,
    Frame,
    LabelSource,
    MacroZone,
    OpeningKind,
    ScaleMethod,
    SourceKind,
    fidelity_of,
)
from ale.contracts.footprint import Junction, decompose_footprint
from ale.contracts.geometry import (
    LineString,
    ModulePolygon,
    ModuleRect,
    Polygon,
    polygon_from_shapely,
    to_shapely,
)
from ale.contracts.models import (
    Adjacency,
    AdjEntry,
    CoreOffset,
    CoreSpec,
    Entrance,
    GridSpec,
    LabelledPolygon,
    Layout,
    Opening,
    PlacedRoom,
    PlanGeometry,
    PolishExpression,
    Program,
    Quantiles,
    RoomSpec,
    Rulebook,
    SiteSpec,
    TextItem,
    TypeStats,
    Wall,
)
from ale.contracts.serialization import canonical_json, dump_yaml, load_yaml
from ale.contracts.taxonomy import LabelMatch, load_taxonomy

MODELS: dict[str, type[BaseModel]] = {
    "RoomSpec": RoomSpec,
    "Program": Program,
    "SiteSpec": SiteSpec,
    "Layout": Layout,
    "PlanGeometry": PlanGeometry,
    "Rulebook": Rulebook,
    "PolishExpression": PolishExpression,
}


# --------------------------------------------------------------------------- M01 / M02


@pytest.mark.parametrize("name", list(MODELS))
def test_M01_roundtrip_json(name: str, samples: dict[str, BaseModel]) -> None:
    x = samples[name]
    back = MODELS[name].model_validate_json(canonical_json(x))
    assert back == x
    assert canonical_json(back) == canonical_json(x)


@pytest.mark.parametrize("name", ["Rulebook", "Program", "SiteSpec"])
def test_M02_roundtrip_yaml(name: str, samples: dict[str, BaseModel]) -> None:
    x = samples[name]
    text = dump_yaml(x)
    back = load_yaml(MODELS[name], text)
    assert back == x
    assert dump_yaml(load_yaml(MODELS[name], dump_yaml(x))) == dump_yaml(x)


def test_M02_yaml_field_order_and_dates(h: SimpleNamespace) -> None:
    text = dump_yaml(h.make_rulebook())
    keys = [line.split(":")[0] for line in text.splitlines() if not line.startswith(" ")]
    assert keys == list(Rulebook.model_fields)
    # A hand-written unquoted ISO date stays a string.
    edited = text.replace("date: '2026-11-07'", "date: 2026-11-07")
    assert "date: 2026-11-07" in edited
    assert load_yaml(Rulebook, edited).date == "2026-11-07"
    # YAML ints are accepted for float fields.
    prog = load_yaml(Program, dump_yaml(h.make_program()).replace("12.5", "12"))
    assert prog.rooms[0].target_area_m2 == 12.0


# --------------------------------------------------------------------------- M03 / M04


def _room_kwargs(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "R1",
        "name": "Bureau",
        "type": "office",
        "target_area_m2": 12.0,
        "macro_zone": MacroZone.ADMINISTRATIVE,
    }
    base.update(over)
    return base


def test_M03_strict_ints() -> None:
    for bad in (1.0, "1", True):
        with pytest.raises(ValidationError):
            ModuleRect(x=bad, y=0, w=1, h=1)
    assert RoomSpec(**_room_kwargs(target_area_m2=12)).target_area_m2 == 12.0
    for bad_area in ("12", True):
        with pytest.raises(ValidationError):
            RoomSpec(**_room_kwargs(target_area_m2=bad_area))
    for bad_q in (2.0, "2", True):
        with pytest.raises(ValidationError):
            RoomSpec(**_room_kwargs(quantity=bad_q))
    with pytest.raises(ValidationError):
        RoomSpec(**_room_kwargs(needs_facade=1))
    with pytest.raises(ValidationError):
        RoomSpec(**_room_kwargs(name=5))
    with pytest.raises(ValidationError):
        GridSpec(module_mm=600.0)


def _all_contract_models() -> list[type[BaseModel]]:
    found: dict[str, type[BaseModel]] = {}
    for info in pkgutil.iter_modules(ale.contracts.__path__):
        mod = importlib.import_module(f"ale.contracts.{info.name}")
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if issubclass(obj, BaseModel) and obj.__module__ == mod.__name__:
                found[obj.__qualname__] = obj
    return list(found.values())


def _instances(h: SimpleNamespace) -> list[BaseModel]:
    plan = h.make_plan()
    layout = h.make_layout()
    rb = h.make_rulebook()
    tax = load_taxonomy()
    return [
        *h.make_room_specs(),
        h.make_program(),
        h.make_site(),
        Entrance(point=(0.0, 0.0), label="Principale", main=True),
        CoreSpec(id="C1", rect=(1.0, 1.0, 2.0, 2.0), kind="stair"),
        Junction(parent=0, child=1, kind="J1", cut=((0, 0), (0, 1)), facing_block="A"),
        layout,
        layout.grid,
        layout.rooms[0],
        layout.metrics,
        layout.metrics.violations[0],
        layout.footprint,
        layout.residue[0],
        h.make_polish(),
        plan,
        plan.walls[0],
        plan.walls[0].centerline,
        plan.openings[0],
        plan.rooms[0],
        plan.rooms[0].polygon,
        plan.texts[0],
        rb,
        rb.types["office"],
        rb.types["office"].aspect,
        rb.adjacency,
        rb.adjacency.pairs[0],
        rb.core_offset,
        tax,
        tax.types[0],
        tax.normalize_label("BUREAU"),
        AreaTolerance(),
        AreaCheck(valid=True, placed_m2=1.0, delta_m2=0.0, delta_pct=0.0, overshoot_m2=0.0),
        *_corridor_instances(),
    ]


def _corridor_instances() -> list[BaseModel]:
    """Instances of the A.1 amendment models (corridor_plan, footprint)."""
    finger = FingerBay(left=("R2",), right=("R3#01",))
    block = BlockPlan(bays=(RoomBay(room="R1"), finger))
    corridor = CorridorPlan(
        pieces=(
            PiecePlan(
                bands=(
                    BandPlan(block_a=block, block_b=BlockPlan(bays=(FingerBay(junction=True),))),
                    BandPlan(block_a=BlockPlan(), block_b=BlockPlan()),
                ),
                connector="end",
            ),
            PiecePlan(
                bands=(
                    BandPlan(block_a=BlockPlan(), block_b=BlockPlan(bays=(RoomBay(room="R4"),))),
                )
            ),
        )
    )
    pieces = decompose_footprint(
        ModulePolygon(exterior=((0, 0), (480, 0), (480, 180), (300, 180), (300, 300), (0, 300)))
    )
    return [
        corridor,
        corridor.pieces[0],
        corridor.pieces[0].bands[0],
        block,
        block.bays[0],
        finger,
        ConnectorBay(),
        corridor.locate("R3#01"),
        pieces,
        pieces.pieces[0],
    ]


def test_M04_frozen_extra(h: SimpleNamespace) -> None:
    models = _all_contract_models()
    assert len(models) >= 29
    for cls in models:
        assert cls.model_config.get("extra") == "forbid", cls
        assert cls.model_config.get("frozen") is True, cls
        assert cls.model_config.get("strict") is not True, cls
    covered = set()
    for inst in _instances(h):
        cls = type(inst)
        covered.add(cls)
        first = next(iter(cls.model_fields))
        with pytest.raises(ValidationError):
            setattr(inst, first, getattr(inst, first))
        data = inst.model_dump()
        assert cls.model_validate(data) == inst
        with pytest.raises(ValidationError, match="colour"):
            cls.model_validate({**data, "colour": "red"})
    # Config models (ale.contracts.config) are owned and tested by Ticket 0.1: they are checked
    # by the forbid/frozen/strict loop above but need no sample instance here.
    assert covered == {m for m in models if m.__module__ != "ale.contracts.config"}


# --------------------------------------------------------------------------- M05 program


def test_M05_program_rules() -> None:
    def prog(*rooms: dict[str, Any]) -> Program:
        return Program(rooms=tuple(RoomSpec(**r) for r in rooms))

    with pytest.raises(ValidationError, match="duplicate room ids"):
        prog(_room_kwargs(), _room_kwargs())
    with pytest.raises(ValidationError, match="unknown id"):
        prog(_room_kwargs(adjacent_to=("R9",)))
    with pytest.raises(ValidationError, match="unknown id"):
        prog(_room_kwargs(avoid=("R9",)))
    with pytest.raises(ValidationError, match="itself"):
        RoomSpec(**_room_kwargs(adjacent_to=("R1",)))
    with pytest.raises(ValidationError, match="itself"):
        RoomSpec(**_room_kwargs(avoid=("R1",)))
    with pytest.raises(ValidationError, match="avoids"):
        prog(_room_kwargs(adjacent_to=("R2",)), _room_kwargs(id="R2", avoid=("R1",)))
    with pytest.raises(ValidationError, match="floor"):
        RoomSpec(**_room_kwargs(floor=-1))  # A.4: floors >= 0 are accepted (was: only 0)
    assert RoomSpec(**_room_kwargs(floor=1)).floor == 1
    with pytest.raises(ValidationError, match="both in adjacent_to and avoid"):
        RoomSpec(**_room_kwargs(adjacent_to=("R2",), avoid=("R2",)))
    with pytest.raises(ValidationError, match="duplicates"):
        RoomSpec(**_room_kwargs(adjacent_to=("R2", "R2")))
    with pytest.raises(ValidationError):
        Program(rooms=())
    for bad in (
        {"id": "bad id"},
        {"id": "x" * 33},
        {"name": "   "},
        {"name": "x" * 121},
        {"target_area_m2": 0},
        {"target_area_m2": 10_001},
        {"quantity": 0},
        {"quantity": 501},
        {"orientation_override": {}},
        {"orientation_override": {"N": 1.5}},
        {"min_width_m": 0},
    ):
        with pytest.raises(ValidationError):
            RoomSpec(**_room_kwargs(**bad))
    assert RoomSpec(**_room_kwargs(name="  Bureau  ")).name == "Bureau"

    p = prog(_room_kwargs(quantity=12), _room_kwargs(id="R2"))
    ids = [i for i, _ in p.instances()]
    assert ids == [f"R1#{k:02d}" for k in range(1, 13)] + ["R2"]
    assert ids[0] == "R1#01"
    assert ids[11] == "R1#12"
    assert all(spec.id == "R1" for _, spec in p.instances()[:12])
    assert [i for i, _ in prog(_room_kwargs()).instances()] == ["R1"]
    assert [i for i, _ in prog(_room_kwargs(quantity=3)).instances()] == ["R1#1", "R1#2", "R1#3"]


def test_M05_site_rules(h: SimpleNamespace) -> None:
    site = h.make_site()
    data = site.model_dump()
    with pytest.raises(ValidationError, match="rectilinear"):
        SiteSpec.model_validate(
            {**data, "footprint": {"exterior": [(0, 0), (10, 0), (5, 8)], "holes": []}}
        )
    with pytest.raises(ValidationError, match="access_edge"):
        SiteSpec.model_validate({**data, "access_edge": 6})
    with pytest.raises(ValidationError, match="access_edge"):
        SiteSpec.model_validate({**data, "access_edge": -1})
    with pytest.raises(ValidationError):
        SiteSpec.model_validate({**data, "north_angle_deg": 360.0})


# --------------------------------------------------------------------------- M06 / M07 geometry


@pytest.mark.parametrize(
    "pts",
    [
        [(0, 0), (4, 0), (5, 3), (0, 3)],  # non-rectilinear
        [(0, 0), (0, 3), (4, 3), (4, 0)],  # clockwise
        [(0, 0), (4, 0), (4, 4), (2, 4), (2, -2), (0, -2)],  # self-intersecting
        [(0, 0), (2, 0), (4, 0), (4, 3), (0, 3)],  # collinear vertex
        [(0, 0), (4, 0), (4, 3)],  # 3 vertices
        [(0, 0), (4, 0), (4, 0), (4, 3), (0, 3)],  # duplicate vertex
        [(0, 0), (4, 0), (4, 3), (0, 3), (0, 0)],  # closed ring
        [(0.0, 0), (4, 0), (4, 3), (0, 3)],  # non-int
    ],
)
def test_M06_module_polygon_rejected(pts: list[tuple[int, int]]) -> None:
    with pytest.raises(ValidationError):
        ModulePolygon(exterior=pts)


def test_M06_module_polygon() -> None:
    poly = ModulePolygon(exterior=[(0, 0), (10, 0), (10, 4), (6, 4), (6, 8), (0, 8)])
    assert poly.area_cells() == 64
    assert len(poly.edges()) == 6
    assert poly.edges()[-1] == ((0, 8), (0, 0))
    assert to_shapely(poly).area == 64


def test_M06_float_geometry() -> None:
    with pytest.raises(ValidationError, match="consecutive duplicate"):
        LineString(coords=((0, 0), (0, 0), (1, 1)))
    with pytest.raises(ValidationError):
        LineString(coords=((0, 0),))
    with pytest.raises(ValidationError, match="closed"):
        Polygon(exterior=((0, 0), (1, 0), (1, 1), (0, 0)))
    with pytest.raises(ValidationError, match="at least 3"):
        Polygon(exterior=((0, 0), (1, 0)))
    with pytest.raises(ValidationError, match="hole 0"):
        Polygon(exterior=((0, 0), (9, 0), (9, 9), (0, 9)), holes=(((1, 1), (2, 2)),))
    with pytest.raises(ValidationError, match="invalid polygon"):
        Polygon(exterior=((0, 0), (2, 2), (2, 0), (0, 2)))  # bow-tie
    with pytest.raises(ValidationError):
        Polygon(exterior=(("0", 0), (1, 0), (1, 1)))
    poly = Polygon(exterior=((0, 0), (4, 0), (4, 4), (0, 4)), holes=(((1, 1), (1, 2), (2, 2)),))
    shp = to_shapely(poly)
    assert shp.area == pytest.approx(15.5)
    assert polygon_from_shapely(shp) == poly
    cw = shapely.Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])
    assert polygon_from_shapely(cw).exterior == ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0))
    ls = LineString(coords=((0, 0), (3, 4)))
    assert to_shapely(ls).length == 5.0
    assert to_shapely(ModuleRect(1, 2, 3, 4)).bounds == (1.0, 2.0, 4.0, 6.0)
    with pytest.raises(TypeError):
        to_shapely("nope")  # type: ignore[arg-type]


def test_M07_rect_overlap() -> None:
    a = ModuleRect(0, 0, 4, 4)
    assert a.intersection_cells(ModuleRect(2, 2, 4, 4)) == 4
    assert a.intersection_cells(ModuleRect(4, 0, 2, 2)) == 0  # touching edge
    assert a.intersection_cells(ModuleRect(0, 4, 2, 2)) == 0  # touching edge
    assert a.intersection_cells(ModuleRect(10, 10, 2, 2)) == 0  # disjoint
    assert a.intersection_cells(a) == 16
    assert (a.x2(), a.y2(), a.area_cells()) == (4, 4, 16)
    assert ModuleRect(1, 2, 3, 4) == ModuleRect(x=1, y=2, w=3, h=4)
    with pytest.raises(TypeError):
        ModuleRect(1, 2, 3, 4, 5)
    with pytest.raises(TypeError):
        ModuleRect(1, 2, 3, x=4)
    with pytest.raises(ValidationError):
        ModuleRect(0, 0, 0, 1)


# --------------------------------------------------------------------------- M08 placed room


def test_M08_placed_room() -> None:
    g600 = GridSpec(module_mm=600)
    room = PlacedRoom(
        instance_id="R1", spec_id="R1", rect=ModuleRect(0, 0, 4, 6), target_area_m2=7.5
    )
    assert room.area_m2(g600) == 8.64
    assert GridSpec().module_mm == 100
    assert room.aspect_ratio() == 1.5
    assert room.bbox_m(g600) == (0.0, 0.0, 2.4, 3.6)
    delta = room.area_delta_m2(g600)
    assert delta == pytest.approx(1.14, abs=1e-9)
    circ = PlacedRoom(
        instance_id="circ-001", spec_id=None, rect=ModuleRect(0, 0, 2, 9), target_area_m2=None
    )
    assert circ.area_delta_m2(g600) is None
    assert circ.aspect_ratio() == 4.5
    for bad in (99, 1201):
        with pytest.raises(ValidationError):
            GridSpec(module_mm=bad)


def test_M08_layout_rules(h: SimpleNamespace) -> None:
    layout = h.make_layout()
    data = layout.model_dump()
    rooms = data["rooms"]
    with pytest.raises(ValidationError, match="sorted"):
        Layout.model_validate({**data, "rooms": list(reversed(rooms))})
    with pytest.raises(ValidationError, match="duplicate instance ids"):
        Layout.model_validate({**data, "rooms": [rooms[0], rooms[0]]})
    circ = dict(data["circulation"][0], spec_id="R1")
    with pytest.raises(ValidationError, match="spec_id None"):
        Layout.model_validate({**data, "circulation": [circ]})
    with pytest.raises(ValidationError):
        Layout.model_validate({**data, "schema_version": "ale.layout/2"})


# --------------------------------------------------------------------------- M09 polish


@pytest.mark.parametrize(
    "expr", ["a b V", "a b V c H", "a b c V H", "a b H c H", "a", "R1#01 c-2 V"]
)
def test_M09_polish_valid(expr: str) -> None:
    assert PolishExpression(tokens=tuple(expr.split())).tokens == tuple(expr.split())


@pytest.mark.parametrize("expr", ["a b", "a V", "a b V V", "a b c H H", "a a V", "", "a b X$ V H"])
def test_M09_polish_invalid(expr: str) -> None:
    with pytest.raises(ValidationError):
        PolishExpression(tokens=tuple(expr.split()))


def test_M09_polish_expression() -> None:
    assert PolishExpression(tokens=("a", "b", "V", "c", "H")).leaves() == ("a", "b", "c")


# --------------------------------------------------------------------------- M10 plan geometry


def test_M10_plan_geometry(h: SimpleNamespace) -> None:
    plan = h.make_plan()
    data = plan.model_dump()
    with pytest.raises(ValidationError, match="UNKNOWN"):
        PlanGeometry.model_validate({**data, "scale_method": ScaleMethod.UNKNOWN})
    with pytest.raises(ValidationError, match="UNKNOWN"):
        PlanGeometry.model_validate({**data, "scale_m_per_unit": None})
    bad_open = dict(data["openings"][0], host_wall=5)
    with pytest.raises(ValidationError, match="host_wall"):
        PlanGeometry.model_validate({**data, "openings": [bad_open]})
    inconsistent = dict(data["openings"][0], width_m=1.2)
    with pytest.raises(ValidationError, match="inconsistent"):
        PlanGeometry.model_validate({**data, "openings": [inconsistent]})
    with pytest.raises(ValidationError, match="duplicate room polygon ids"):
        PlanGeometry.model_validate({**data, "rooms": [data["rooms"][0], data["rooms"][0]]})
    with pytest.raises(ValidationError):
        PlanGeometry.model_validate({**data, "source_sha256": "AB" * 32})

    m = plan.to_metric()
    assert m.frame is Frame.Y_UP
    assert m.units_label == "m"
    assert m.scale_m_per_unit == 1.0
    assert m.scale_method is ScaleMethod.SCALE_BAR
    assert m.scale_confidence == 0.8
    assert m.walls[0].centerline.coords[0] == (1.0, -0.5)
    assert m.walls[0].thickness == 0.2
    assert m.openings[0].width_m == 0.9
    assert m.openings[1].width_m == 1.2
    assert m.rooms[0].polygon.exterior[0] == (1.0, -0.5)
    assert m.rooms[0].type == "office"
    assert m.texts[0].insert == (3.0, -3.0)
    assert m.texts[0].rotation_deg == -90.0
    assert m.texts[0].height == 0.025

    up = h.make_plan(Frame.Y_UP).to_metric()
    assert up.walls[0].centerline.coords[0] == (1.0, 0.5)
    assert up.texts[0].rotation_deg == 90.0

    unknown = PlanGeometry.model_validate(
        {**data, "scale_m_per_unit": None, "scale_method": ScaleMethod.UNKNOWN}
    )
    with pytest.raises(ValueError, match="known scale"):
        unknown.to_metric()


def test_M10_extraction_parts() -> None:
    seg3 = LineString(coords=((0, 0), (1, 0), (2, 0)))
    with pytest.raises(ValidationError, match="exactly 2 points"):
        Opening(kind=OpeningKind.DOOR, segment=seg3, width_native=1.0)
    seg = LineString(coords=((0, 0), (1, 0)))
    with pytest.raises(ValidationError):
        Opening(kind=OpeningKind.DOOR, segment=seg, width_native=0)
    poly = Polygon(exterior=((0, 0), (1, 0), (1, 1)))
    with pytest.raises(ValidationError, match="label_source"):
        LabelledPolygon(id="p", polygon=poly, type="office")
    with pytest.raises(ValidationError, match="label_source"):
        LabelledPolygon(id="p", polygon=poly, label_source=LabelSource.VLM)
    with pytest.raises(ValidationError):
        LabelledPolygon(id="p", polygon=poly, confidence=1.5)
    assert LabelledPolygon(id="p", polygon=poly, type="unknown", label_source=LabelSource.VLM)
    with pytest.raises(ValidationError):
        TextItem(text="x", insert=(0, 0), source="DWG")
    assert Wall(centerline=seg).thickness is None
    assert fidelity_of(SourceKind.DWG) is Fidelity.CAD
    assert fidelity_of(SourceKind.DXF) is Fidelity.CAD
    assert fidelity_of(SourceKind.PDF_VECTOR) is Fidelity.PDF_VECTOR
    assert fidelity_of(SourceKind.PDF_SCANNED) is Fidelity.RASTER
    assert fidelity_of(SourceKind.RASTER) is Fidelity.RASTER


# --------------------------------------------------------------------------- M11 / M12 rulebook


def test_M11_rulebook_rules(h: SimpleNamespace) -> None:
    with pytest.raises(ValidationError):
        Quantiles(p10=2, p50=1.5, p90=3)
    orient = {b: 0.0 for b in Bearing}
    good_q = Quantiles(p10=1.0, p50=1.5, p90=2.0)
    with pytest.raises(ValidationError, match=r"aspect\.p10"):
        TypeStats(aspect=Quantiles(p10=0.9, p50=1.5, p90=2), area_m2=good_q, orientation=orient)
    with pytest.raises(ValidationError, match=r"aspect\.p90"):
        TypeStats(aspect=Quantiles(p10=1, p50=1.5, p90=6.5), area_m2=good_q, orientation=orient)
    with pytest.raises(ValidationError, match=r"area_m2\.p10"):
        TypeStats(aspect=good_q, area_m2=Quantiles(p10=0, p50=1, p90=2), orientation=orient)
    three = {Bearing.N: 0.0, Bearing.E: 0.0, Bearing.S: 0.0}
    with pytest.raises(ValidationError, match="4 bearings"):
        TypeStats(aspect=good_q, area_m2=good_q, orientation=three)
    with pytest.raises(ValidationError):
        TypeStats(aspect=good_q, area_m2=good_q, orientation={**orient, Bearing.N: 1.5})
    with pytest.raises(ValidationError):
        Quantiles(p10=1, p50=1, p90=1, n=-1)

    e = AdjEntry(a="sanitary", b="office", p=0.3)
    assert (e.a, e.b) == ("office", "sanitary")
    assert AdjEntry(a="office", b="office", p=0.3).a == "office"
    with pytest.raises(ValidationError):
        AdjEntry(a="office", b="kitchen", p=0.3)
    with pytest.raises(ValidationError):
        AdjEntry(a="office", b="sanitary", p=1.5)
    adj = Adjacency(
        default_p=0.05,
        pairs=(
            AdjEntry(a="storage", b="office", p=0.2),
            AdjEntry(a="meeting_room", b="office", p=0.7),
            AdjEntry(a="archive", b="office", p=0.4),
        ),
    )
    assert [(p.a, p.b) for p in adj.pairs] == [
        ("archive", "office"),
        ("meeting_room", "office"),
        ("office", "storage"),
    ]
    with pytest.raises(ValidationError, match="duplicate"):
        Adjacency(
            default_p=0.1,
            pairs=(
                AdjEntry(a="office", b="sanitary", p=0.1),
                AdjEntry(a="sanitary", b="office", p=0.2),
            ),
        )
    assert adj.p("office", "meeting_room") == adj.p("meeting_room", "office") == 0.7
    assert adj.p("office", "lift") == 0.05
    with pytest.raises(ValidationError):
        CoreOffset(dx_norm=0.6, dy_norm=0)

    data = h.make_rulebook().model_dump()
    for bad in (
        {"author": None},
        {"author": ""},
        {"date": None},
        {"date": "07/11/2026"},
        {"date": "2026-13-45"},
        {"version": ""},
        {"kind": "guess"},
    ):
        with pytest.raises(ValidationError):
            Rulebook.model_validate({**data, **bad})
    mined = Rulebook.model_validate({**data, "kind": "mined", "author": None, "date": None})
    assert mined.author is None
    for bad_key in ("circulation", "outdoor_space", "unknown", "kitchen"):
        types = {**data["types"], bad_key: data["types"]["office"]}
        with pytest.raises(ValidationError):
            Rulebook.model_validate({**data, "types": types})
    rb = h.make_rulebook()
    assert rb.missing_types(["stair", "office", "lift", "stair"]) == ("lift", "stair")


def test_M12_rulebook_hash(h: SimpleNamespace, tmp_path: Any) -> None:
    rb = h.make_rulebook()
    digest = rb.content_sha256()
    assert len(digest) == 64
    path = tmp_path / "rb.json"
    path.write_bytes(canonical_json(rb))
    code = (
        "import sys; from ale.contracts.models import Rulebook; "
        "print(Rulebook.model_validate_json(open(sys.argv[1], 'rb').read()).content_sha256())"
    )
    proc = h.run_module(["-c", code, str(path)])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == digest
    assert h.make_rulebook(p_office_meeting=0.61).content_sha256() != digest
    changed_default = rb.model_copy(
        update={"adjacency": rb.adjacency.model_copy(update={"default_p": 0.2})}
    )
    assert changed_default.content_sha256() != digest


def test_label_match_model() -> None:
    m = LabelMatch(key="office", rule="exact", matched_synonym="BUREAU", canonical_input="BUREAU")
    with pytest.raises(ValidationError):
        LabelMatch(key="office", rule="fuzzy", matched_synonym=None, canonical_input="")
    assert m.key == "office"
