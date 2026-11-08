"""Ticket 1.6 edge cases: meta parsing, dimension heuristics, robustness."""

from __future__ import annotations

import pytest
from join_helpers import box_walls, dim_texts, doors, plan, room, text, wall, window

import ale.join.review as review_mod
import ale.join.scale as scale_mod
from ale.config import AleConfig
from ale.contracts.enums import Frame, ScaleMethod, SourceKind
from ale.join import REVIEW_FLAGS, resolve_scale, review_flags
from ale.join.review import polygon_area

CFG = AleConfig()


# --------------------------------------------------------------------------- meta


@pytest.mark.parametrize(
    ("units", "expected"),
    [("m", 1.0), ("MM", 0.001), (" cm ", 0.01), ("inch", 0.0254), ("ft", 0.3048)],
)
def test_meta_cad_units(units: str, expected: float) -> None:
    out = resolve_scale(plan(SourceKind.DXF), meta={"units": units}, config=CFG)
    assert out.scale_method is ScaleMethod.META_CSV
    assert out.scale_m_per_unit == expected


def test_meta_cad_unknown_unit_warns() -> None:
    out = resolve_scale(plan(SourceKind.DWG), meta={"units": "parsec"}, config=CFG)
    assert out.scale_method is ScaleMethod.UNKNOWN
    assert any("units='parsec'" in w for w in out.warnings)


def test_meta_cad_without_units_ignored() -> None:
    out = resolve_scale(plan(SourceKind.DWG), meta={"units": "", "x": 1}, config=CFG)
    assert out.scale_method is ScaleMethod.UNKNOWN


@pytest.mark.parametrize("bad", ["abc", -50, 0, float("nan"), True, [50]])
def test_meta_bad_scale_warns(bad: object) -> None:
    out = resolve_scale(plan(SourceKind.PDF_VECTOR), meta={"scale_1_to": bad}, config=CFG)
    assert out.scale_method is ScaleMethod.UNKNOWN
    assert any("scale_1_to" in w for w in out.warnings)


def test_meta_empty_values_are_absent() -> None:
    out = resolve_scale(plan(SourceKind.PDF_VECTOR), meta={"scale_1_to": "  "}, config=CFG)
    assert out.scale_method is ScaleMethod.UNKNOWN
    assert not any("scale_1_to" in w for w in out.warnings)


def test_meta_comma_decimal() -> None:
    out = resolve_scale(plan(SourceKind.PDF_VECTOR), meta={"scale_1_to": "50,0"}, config=CFG)
    assert out.scale_m_per_unit == 50 * 0.0254 / 72


def test_meta_raster_needs_dpi() -> None:
    p = plan(SourceKind.RASTER, openings=doors([90.0] * 3))
    out = resolve_scale(p, meta={"scale_1_to": 100}, config=CFG)
    assert out.scale_method is ScaleMethod.DOOR_MEDIAN  # falls through
    assert any("needs dpi" in w for w in out.warnings)


def test_meta_scanned_pdf_uses_render_dpi() -> None:
    cfg = AleConfig.model_validate({"extract": {"raster_dpi": 200}})
    out = resolve_scale(plan(SourceKind.PDF_SCANNED), meta={"scale_1_to": 100}, config=cfg)
    assert out.scale_m_per_unit == 100 * 0.0254 / 200
    out = resolve_scale(
        plan(SourceKind.PDF_SCANNED), meta={"scale_1_to": 100, "dpi": 300}, config=cfg
    )
    assert out.scale_m_per_unit == 100 * 0.0254 / 300


def test_meta_units_label_pt_overrides_kind() -> None:
    p = plan(SourceKind.PDF_SCANNED, units_label="pt")
    out = resolve_scale(p, meta={"scale_1_to": 50}, config=CFG)
    assert out.scale_m_per_unit == 50 * 0.0254 / 72


def test_default_config_and_meta() -> None:
    out = resolve_scale(plan(SourceKind.PDF_VECTOR))
    assert out.scale_method is ScaleMethod.UNKNOWN


# --------------------------------------------------------------------------- dimensions


def test_dimension_cm_integers() -> None:
    texts = [text("360", 150.0, 10.0), text("480", -10.0, 200.0, rotation=90.0)]
    texts.append(text("360", 150.0, 490.0))
    out = resolve_scale(plan(SourceKind.RASTER, walls=box_walls(), texts=texts), config=CFG)
    assert out.scale_method is ScaleMethod.DIMENSION_TEXT
    assert out.scale_m_per_unit == pytest.approx(0.01)


def test_dimension_cad_mm_preferred_for_four_digits() -> None:
    walls = [
        wall((0.0, 0.0), (3600.0, 0.0)),
        wall((0.0, 0.0), (0.0, 4800.0)),
        wall((0.0, 4800.0), (3600.0, 4800.0)),
    ]
    texts = [
        text("3600", 1500.0, 100.0, height=100.0),
        text("4800", -100.0, 2000.0, height=100.0, rotation=90.0),
        text("3600", 1500.0, 4900.0, height=100.0),
    ]
    out = resolve_scale(plan(SourceKind.DXF, walls=walls, texts=texts), config=CFG)
    assert out.scale_method is ScaleMethod.DIMENSION_TEXT
    assert out.scale_m_per_unit == pytest.approx(0.001)


def test_dimension_cad_decimal_metres_preferred() -> None:
    walls = [wall((0.0, 0.0), (3.6, 0.0)), wall((0.0, 1.0), (3.6, 1.0))]
    texts = [
        text("3.60", 1.5, 0.05, height=0.1),
        text("3.60", 1.5, 0.95, height=0.1),
        text("3.60", 1.5, 1.05, height=0.1),
    ]
    out = resolve_scale(plan(SourceKind.DXF, walls=walls, texts=texts), config=CFG)
    assert out.scale_m_per_unit == pytest.approx(1.0)


def test_dimension_ignores_unusable_texts() -> None:
    texts = [
        text("3.60", 150.0, 10.0, height=None),  # no height
        text("3.60", 150.0, 10.0, height=0.0),  # zero height
        text("ROOM 3.60", 150.0, 10.0),  # not a plain number
        text("0", 150.0, 10.0),  # zero value
        text("3.60", 150.0, 100.0),  # too far from any wall
        text("3.60", 150.0, 10.0, rotation=45.0),  # not parallel
    ]
    out = resolve_scale(plan(SourceKind.RASTER, walls=box_walls(), texts=texts), config=CFG)
    assert out.scale_method is ScaleMethod.UNKNOWN


def test_dimension_without_walls() -> None:
    out = resolve_scale(plan(SourceKind.RASTER, texts=dim_texts()), config=CFG)
    assert out.scale_method is ScaleMethod.UNKNOWN


def test_dimension_implausible_scales_dropped() -> None:
    # 3600 px for "3.60": 0.001 m/px is plausible as m, the cm/mm readings are not.
    walls = [wall((0.0, 0.0), (3600.0, 0.0)), wall((0.0, 50.0), (3600.0, 50.0))]
    texts = [text("3.60", 100.0, 10.0), text("3.60", 100.0, 40.0), text("3.60", 100.0, 60.0)]
    out = resolve_scale(plan(SourceKind.RASTER, walls=walls, texts=texts), config=CFG)
    assert out.scale_m_per_unit == pytest.approx(0.001)


def test_dimension_largest_cluster_wins() -> None:
    walls = [wall((0.0, 100.0 * k), (360.0, 100.0 * k)) for k in range(5)]
    texts = [text("3.60", 100.0, 100.0 * k + 5) for k in range(4)]
    texts.append(text("7.20", 100.0, 405.0))
    out = resolve_scale(plan(SourceKind.RASTER, walls=walls, texts=texts), config=CFG)
    assert out.scale_m_per_unit == pytest.approx(0.01)


def test_dimension_y_down_rotation_is_native() -> None:
    p = plan(SourceKind.RASTER, walls=box_walls(), texts=dim_texts(), frame=Frame.Y_UP)
    out = resolve_scale(p, config=CFG)
    assert out.scale_m_per_unit == pytest.approx(0.01)


# --------------------------------------------------------------------------- existing scales


@pytest.mark.parametrize("method", [ScaleMethod.DIMENSION_TEXT, ScaleMethod.DOOR_MEDIAN])
def test_existing_derived_scale_kept(method: ScaleMethod) -> None:
    p = plan(SourceKind.RASTER, scale=0.02, method=method, confidence=0.4)
    out = resolve_scale(p, config=CFG)
    assert (out.scale_m_per_unit, out.scale_method, out.scale_confidence) == (0.02, method, 0.4)


def test_existing_meta_csv_kept_without_meta() -> None:
    p = plan(SourceKind.PDF_VECTOR, scale=0.02, method=ScaleMethod.META_CSV, confidence=1.0)
    assert resolve_scale(p, config=CFG).scale_m_per_unit == 0.02


def test_scale_bar_treated_like_title_block() -> None:
    p = plan(
        SourceKind.PDF_VECTOR,
        walls=box_walls(),
        texts=dim_texts(),
        scale=0.02,
        method=ScaleMethod.SCALE_BAR,
        confidence=0.9,
    )
    out = resolve_scale(p, config=CFG)
    assert out.scale_method is ScaleMethod.SCALE_BAR


def test_idempotent_and_warnings_deduplicated() -> None:
    p = plan(SourceKind.RASTER, openings=[*doors([90.0, 92.0, 88.0, 300.0]), window(120.0)])
    once = resolve_scale(p, config=CFG)
    twice = resolve_scale(once, config=CFG)
    assert twice == once
    unknown = resolve_scale(plan(SourceKind.RASTER), config=CFG)
    assert resolve_scale(unknown, config=CFG).warnings == unknown.warnings


def test_rescale_refreshes_widths() -> None:
    p = plan(
        SourceKind.PDF_VECTOR,
        openings=doors([90.0]),
        scale=0.5,
        method=ScaleMethod.TITLE_BLOCK,
        confidence=0.8,
    )
    p = resolve_scale(p, config=CFG)
    assert p.openings[0].width_m == 45.0
    out = resolve_scale(p, meta={"scale_1_to": 50}, config=CFG)
    assert out.openings[0].width_m == 90.0 * (50 * 0.0254 / 72)


def test_doors_all_rejected_not_used() -> None:
    # median 50 → 1 and 1000 rejected, only 2 kept.
    out = resolve_scale(plan(openings=doors([1.0, 50.0, 50.0, 1000.0])), config=CFG)
    assert out.scale_method is ScaleMethod.UNKNOWN


def test_windows_do_not_count_as_doors() -> None:
    out = resolve_scale(plan(openings=[window(90.0)] * 3), config=CFG)
    assert out.scale_method is ScaleMethod.UNKNOWN


# --------------------------------------------------------------------------- robustness


def test_resolve_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("kaput")

    monkeypatch.setattr(scale_mod, "_choose", boom)
    p = plan(SourceKind.RASTER)
    out = resolve_scale(p, config=CFG)
    assert out.scale_method is ScaleMethod.UNKNOWN
    assert any("RuntimeError: kaput" in w for w in out.warnings)


def test_review_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object) -> float:
        raise RuntimeError("kaput")

    monkeypatch.setattr(review_mod, "polygon_area", boom)
    p = plan(
        SourceKind.RASTER,
        rooms=[room("a", 1, 1)],
        scale=0.01,
        method=ScaleMethod.META_CSV,
        confidence=1.0,
    )
    assert review_flags(p, CFG) == ()


def test_review_default_config_and_no_rooms() -> None:
    assert review_flags(plan(SourceKind.RASTER)) == ("scale_unknown",)
    assert set(REVIEW_FLAGS) >= set(review_flags(plan(SourceKind.RASTER)))


def test_polygon_area_with_hole() -> None:
    from ale.contracts.geometry import Polygon

    poly = Polygon(
        exterior=((0, 0), (10, 0), (10, 10), (0, 10)),
        holes=(((2, 2), (4, 2), (4, 4), (2, 4)),),
    )
    assert polygon_area(poly) == 96.0
