"""Ticket 1.6 evaluation J1-J6 (synthetic ``PlanGeometry`` objects)."""

from __future__ import annotations

import pytest
from join_helpers import box_walls, dim_texts, doors, plan, room

from ale.config import AleConfig
from ale.contracts.enums import ScaleMethod, SourceKind
from ale.contracts.models import LabelledPolygon, PlanGeometry
from ale.join import resolve_scale, review_flags

CFG = AleConfig()


def _rich(kind: SourceKind, **kw: object) -> PlanGeometry:
    """A plan offering dimension texts (0.01 /unit) and doors (0.9/80 /unit)."""
    return plan(
        kind,
        walls=box_walls(),
        texts=dim_texts(),
        openings=doors([80.0, 80.0, 80.0]),
        **kw,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- J1


def test_J1_hierarchy() -> None:
    # Level 1: CAD drawing units untouched (value and confidence), even with meta.
    cad = _rich(SourceKind.DXF, scale=0.001, method=ScaleMethod.DRAWING_UNITS, confidence=0.9)
    out = resolve_scale(cad, meta={"units": "m"}, config=CFG)
    assert (out.scale_m_per_unit, out.scale_method, out.scale_confidence) == (
        0.001,
        ScaleMethod.DRAWING_UNITS,
        0.9,
    )
    # Level 2: meta beats the reader's title block, dimensions and doors.
    pdf_tb = _rich(SourceKind.PDF_VECTOR, scale=0.5, method=ScaleMethod.TITLE_BLOCK, confidence=0.8)
    out = resolve_scale(pdf_tb, meta={"scale_1_to": 50}, config=CFG)
    assert out.scale_method is ScaleMethod.META_CSV
    assert out.scale_m_per_unit == pytest.approx(50 * 0.0254 / 72, rel=1e-12)
    assert out.scale_confidence == 1.0
    # Level 3: title block beats dimensions and doors.
    out = resolve_scale(pdf_tb, meta=None, config=CFG)
    assert (out.scale_m_per_unit, out.scale_method, out.scale_confidence) == (
        0.5,
        ScaleMethod.TITLE_BLOCK,
        0.8,
    )
    # Level 4: dimension texts beat doors.
    out = resolve_scale(_rich(SourceKind.RASTER), meta=None, config=CFG)
    assert out.scale_method is ScaleMethod.DIMENSION_TEXT
    assert out.scale_m_per_unit == pytest.approx(0.01, rel=0.005)
    assert out.scale_confidence == 0.7
    # Level 5: doors only.
    door_only = plan(SourceKind.RASTER, walls=box_walls(), openings=doors([80.0] * 3))
    out = resolve_scale(door_only, meta=None, config=CFG)
    assert out.scale_method is ScaleMethod.DOOR_MEDIAN
    assert out.scale_m_per_unit == pytest.approx(0.9 / 80.0)
    # Level 6: nothing.
    out = resolve_scale(plan(SourceKind.RASTER, walls=box_walls()), meta=None, config=CFG)
    assert out.scale_method is ScaleMethod.UNKNOWN
    assert out.scale_m_per_unit is None
    assert out.scale_confidence == 0.0


def test_J1_cad_drawing_units_untouched_geometry() -> None:
    cad = _rich(SourceKind.DWG, scale=0.001, method=ScaleMethod.DRAWING_UNITS, confidence=1.0)
    out = resolve_scale(cad, meta={"units": "cm"}, config=CFG)
    assert out.walls == cad.walls
    assert out.texts == cad.texts
    assert out.rooms == cad.rooms
    assert [o.width_native for o in out.openings] == [o.width_native for o in cad.openings]


# --------------------------------------------------------------------------- J2


def test_J2_meta_pdf() -> None:
    out = resolve_scale(plan(SourceKind.PDF_VECTOR), meta={"scale_1_to": 50}, config=CFG)
    assert out.scale_method is ScaleMethod.META_CSV
    assert out.scale_m_per_unit == 50 * 0.0254 / 72
    assert out.scale_confidence == 1.0


def test_J2_meta_raster() -> None:
    out = resolve_scale(plan(SourceKind.RASTER), meta={"dpi": 300, "scale_1_to": 100}, config=CFG)
    assert out.scale_method is ScaleMethod.META_CSV
    assert out.scale_m_per_unit == 100 * 0.0254 / 300
    assert out.scale_confidence == 1.0


def test_J2_meta_csv_strings() -> None:
    out = resolve_scale(
        plan(SourceKind.RASTER), meta={"dpi": "300", "scale_1_to": " 100 "}, config=CFG
    )
    assert out.scale_m_per_unit == 100 * 0.0254 / 300


# --------------------------------------------------------------------------- J3


def test_J3_dimensions() -> None:
    p = plan(SourceKind.RASTER, walls=box_walls(), texts=dim_texts(outlier=True))
    out = resolve_scale(p, meta=None, config=CFG)
    assert out.scale_method is ScaleMethod.DIMENSION_TEXT
    assert out.scale_m_per_unit == pytest.approx(0.01, rel=0.005)
    assert out.scale_confidence == 0.7


def test_J3_outlier_ignored_but_not_enough_without_third_text() -> None:
    # Only 2 consistent texts + the outlier: no cluster of 3 → not used.
    texts = dim_texts(outlier=True)
    del texts[2]
    out = resolve_scale(plan(SourceKind.RASTER, walls=box_walls(), texts=texts), config=CFG)
    assert out.scale_method is ScaleMethod.UNKNOWN


# --------------------------------------------------------------------------- J4


def test_J4_doors() -> None:
    p = plan(SourceKind.RASTER, openings=doors([90.0, 92.0, 88.0, 300.0]))
    out = resolve_scale(p, meta=None, config=CFG)
    assert out.scale_method is ScaleMethod.DOOR_MEDIAN
    assert out.scale_m_per_unit == pytest.approx(0.9 / 90.0, rel=1e-12)
    assert out.scale_confidence == 0.5
    assert any("outlier" in w for w in out.warnings)


def test_J4_two_doors_not_used() -> None:
    out = resolve_scale(plan(SourceKind.RASTER, openings=doors([90.0, 92.0])), config=CFG)
    assert out.scale_method is ScaleMethod.UNKNOWN
    assert all(o.width_m is None for o in out.openings)


# --------------------------------------------------------------------------- J5


@pytest.mark.parametrize(
    ("p", "meta"),
    [
        (_rich(SourceKind.RASTER), None),
        (plan(SourceKind.RASTER, openings=doors([90.0, 92.0, 88.0, 300.0])), None),
        (_rich(SourceKind.PDF_VECTOR), {"scale_1_to": 100}),
        (_rich(SourceKind.DXF, scale=0.001, method=ScaleMethod.DRAWING_UNITS), None),
    ],
)
def test_J5_widths(p: PlanGeometry, meta: dict[str, object] | None) -> None:
    out = resolve_scale(p, meta=meta, config=CFG)
    s = out.scale_m_per_unit
    assert s is not None
    assert out.openings
    for op in out.openings:
        assert op.width_m == op.width_native * s
    # The contract validator accepts the result (round trip) and to_metric works.
    assert PlanGeometry.model_validate(out.model_dump()) == out
    metric = out.to_metric()
    for a, b in zip(out.openings, metric.openings, strict=True):
        assert b.width_m == pytest.approx(a.width_m)


# --------------------------------------------------------------------------- J6

_S = 0.01  # m per px


def _scaled(
    rooms: list[LabelledPolygon],
    method: ScaleMethod = ScaleMethod.META_CSV,
    conf: float = 1.0,
) -> PlanGeometry:
    return plan(SourceKind.RASTER, rooms=rooms, scale=_S, method=method, confidence=conf)


@pytest.mark.parametrize(
    ("p", "expected"),
    [
        (plan(SourceKind.RASTER, rooms=[room("a", 300, 400)]), ("scale_unknown",)),
        (
            _scaled([room("a", 300, 400)], ScaleMethod.DOOR_MEDIAN, 0.5),
            ("scale_low_confidence",),
        ),
        (_scaled([room("a", 300, 400)]), ()),
        (_scaled([room("a", 300, 400, area_text_m2=13.0)]), ("area_mismatch",)),
        (_scaled([room("a", 300, 400, area_text_m2=12.5)]), ()),
        (
            _scaled([room(f"r{i}", 300, 400, x=400.0 * i, typed=i >= 4) for i in range(10)]),
            ("many_untyped",),
        ),
        (
            _scaled([room(f"r{i}", 300, 400, x=400.0 * i, typed=i >= 3) for i in range(10)]),
            (),
        ),
        (_scaled([room("a", 300, 400), room("t", 90, 90, x=500)]), ("tiny_rooms",)),
        (
            _scaled(
                [room("a", 300, 400, area_text_m2=20.0, typed=False), room("t", 90, 90, x=500)],
                ScaleMethod.DIMENSION_TEXT,
                0.3,
            ),
            ("scale_low_confidence", "area_mismatch", "many_untyped", "tiny_rooms"),
        ),
        (
            plan(SourceKind.RASTER, rooms=[room("t", 1, 1, typed=False, area_text_m2=5.0)]),
            ("scale_unknown", "many_untyped"),
        ),
    ],
)
def test_J6_flags(p: PlanGeometry, expected: tuple[str, ...]) -> None:
    assert review_flags(p, CFG) == expected


def test_J6_review_confidence_from_config() -> None:
    p = _scaled([room("a", 300, 400)], ScaleMethod.DOOR_MEDIAN, 0.5)
    low = AleConfig.model_validate({"extract": {"review_confidence": 0.4}})
    assert review_flags(p, low) == ()
    assert review_flags(p, CFG) == ("scale_low_confidence",)


def test_J6_flags_after_resolution() -> None:
    p = plan(
        SourceKind.RASTER,
        openings=doors([90.0, 92.0, 88.0]),
        rooms=[room("a", 300, 400)],
    )
    assert review_flags(p, CFG) == ("scale_unknown",)
    assert review_flags(resolve_scale(p, meta=None, config=CFG), CFG) == ("scale_low_confidence",)
