"""Ticket 1.3 evaluation P1-P6 (PDFs generated with PyMuPDF; no corpus file is used)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pymupdf
import pytest
import shapely
from pdf_helpers import (
    DOOR_M,
    GT_AREAS_M2,
    M_PER_PT,
    SHA,
    P,
    bar_chart_page,
    draw_door,
    draw_labels,
    draw_plan_lines,
    random_segments_page,
    read,
    reference_page,
    save_page,
    text_page,
)

from ale.contracts.enums import Frame, LabelSource, OpeningKind, ScaleMethod, SourceKind
from ale.contracts.models import PlanGeometry
from ale.contracts.serialization import canonical_json


def _area(poly: Any) -> float:
    return float(shapely.Polygon(poly.exterior, poly.holes).area)


def _check_rooms(plan: PlanGeometry) -> None:
    metric = plan.to_metric()
    by_type = {r.type: r for r in metric.rooms}
    assert set(by_type) == set(GT_AREAS_M2)
    for key, gt in GT_AREAS_M2.items():
        room = by_type[key]
        assert room.label_source is LabelSource.PDF_TEXT
        assert room.confidence == 1.0
        assert abs(_area(room.polygon) - gt) <= 0.02 * gt


def test_P1_two_room_plan(tmp_path: Path) -> None:
    res = read(save_page(tmp_path / "plan.pdf", reference_page()))
    assert res.is_plan_likely and res.plan_score == 1.0
    assert len(res.plans) == 1
    plan = res.plans[0]
    assert len(plan.rooms) == 2
    assert {r.type for r in plan.rooms} == {"office", "meeting_room"}
    assert plan.scale_method is ScaleMethod.TITLE_BLOCK
    assert plan.scale_confidence == 0.9
    assert plan.scale_m_per_unit is not None
    assert abs(plan.scale_m_per_unit - 0.0254 * 100 / 72) <= 1e-9
    _check_rooms(plan)
    metric = plan.to_metric()
    assert len(metric.openings) == 1
    door = metric.openings[0]
    assert door.kind is OpeningKind.DOOR and door.host_wall is not None
    assert door.width_m is not None and abs(door.width_m - DOOR_M) <= 0.03 * DOOR_M
    walls = [w.thickness for w in plan.walls]
    assert all(t is not None and abs(t * M_PER_PT - 0.2) < 0.01 for t in walls)
    meeting = next(r for r in plan.rooms if r.type == "meeting_room")
    assert meeting.raw_label == "S. RÉUNION" and meeting.area_text_m2 == pytest.approx(33.64)


def test_P2_filled_walls(tmp_path: Path) -> None:
    res = read(save_page(tmp_path / "filled.pdf", reference_page(filled=True)))
    assert res.is_plan_likely is True and len(res.plans) == 1
    assert len(res.plans[0].walls) == 6  # one rectangle per façade + 2 partition pieces
    plan = res.plans[0]
    assert len(plan.rooms) == 2
    _check_rooms(plan)
    lines = read(save_page(tmp_path / "lines.pdf", reference_page())).plans[0]
    for a, b in zip(plan.to_metric().rooms, lines.to_metric().rooms, strict=True):
        assert a.type == b.type
        assert abs(_area(a.polygon) - _area(b.polygon)) <= 0.02 * _area(b.polygon)


def _two_scales(page: Any) -> None:
    draw_plan_lines(page)
    draw_door(page)
    draw_labels(page)
    page.insert_text(P(0.0, 7.2), "PLAN RDC 1:100", fontname="helv", fontsize=9)
    sh = page.new_shape()  # corner inset (site plan) with its own scale
    sh.draw_rect(pymupdf.Rect(430, 700, 570, 820))
    sh.finish(width=0.5, color=(0, 0, 0))
    sh.commit()
    page.insert_text((440, 810), "Plan de situation 1:500", fontname="helv", fontsize=7)


def test_P3_scale_choice(tmp_path: Path) -> None:
    res = read(save_page(tmp_path / "two.pdf", _two_scales))
    plan = res.plans[0]
    assert plan.scale_m_per_unit == pytest.approx(100 * 0.0254 / 72, abs=1e-12)
    assert plan.scale_confidence == 0.6
    assert plan.scale_method is ScaleMethod.TITLE_BLOCK

    none = read(save_page(tmp_path / "none.pdf", reference_page(title=None)))
    plan = none.plans[0]
    assert plan.scale_method is ScaleMethod.UNKNOWN and plan.scale_m_per_unit is None
    assert plan.scale_confidence == 0.0
    assert all(o.width_m is None for o in plan.openings)
    assert "scale unknown: no scale text found" in none.warnings


def test_P4_not_a_plan(tmp_path: Path) -> None:
    for name, build in (("text", text_page), ("bars", bar_chart_page)):
        res = read(save_page(tmp_path / f"{name}.pdf", build))
        assert res.is_plan_likely is False, name
        assert res.plans == (), name
        assert 0.0 <= res.plan_score < 1.0


def test_P5_robustness(tmp_path: Path) -> None:
    empty = read(save_page(tmp_path / "empty.pdf", lambda page: None))
    assert empty.plans == () and not empty.is_plan_likely and empty.plan_score == 0.0

    t0 = time.monotonic()
    rnd = read(save_page(tmp_path / "random.pdf", random_segments_page(20_000)))
    assert time.monotonic() - t0 < 20.0
    assert isinstance(rnd.is_plan_likely, bool)

    doc = pymupdf.open()
    doc.new_page()
    enc = tmp_path / "enc.pdf"
    doc.save(enc, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    doc.close()
    res = read(enc)
    assert res.plans == () and res.warnings == ("encrypted PDF (password required)",)

    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.7\n" + bytes(range(256)) * 20)
    res = read(corrupt)
    assert res.plans == () and res.warnings

    garbage = tmp_path / "garbage.pdf"
    garbage.write_bytes(b"not a pdf at all")
    assert read(garbage).plans == ()
    assert read(tmp_path / "missing.pdf").warnings[0].startswith("cannot read file")
    assert "out of range" in read(save_page(tmp_path / "one.pdf", lambda p: None), 3).warnings[0]


def test_P6_contract(tmp_path: Path) -> None:
    plans: list[PlanGeometry] = []
    for name, build in (
        ("lines", reference_page()),
        ("filled", reference_page(filled=True)),
        ("noscale", reference_page(title=None)),
        ("two", _two_scales),
    ):
        plans.extend(read(save_page(tmp_path / f"{name}.pdf", build)).plans)
    assert len(plans) == 4
    for plan in plans:
        assert plan.frame is Frame.Y_DOWN
        assert plan.source_kind is SourceKind.PDF_VECTOR
        assert plan.source_sha256 == SHA and plan.page == 0 and plan.plan_index == 0
        data = canonical_json(plan)
        again = PlanGeometry.model_validate_json(data)
        assert canonical_json(again) == data
        assert all(t.source == "PDF" for t in plan.texts)
