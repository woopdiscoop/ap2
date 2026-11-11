"""Ticket X.2 evaluation Z01-Z06 (filled zones as rooms; synthetic PDFs built with PyMuPDF)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pymupdf
import pytest
import shapely
from pdf_helpers import (
    SHA,
    bar_chart_page,
    read,
    reference_page,
    save_page,
    text_page,
)
from zone_helpers import (
    CH,
    CW,
    GAP,
    area_of,
    area_str,
    draw_zone_grid,
    pt,
    sheet,
)

from ale.contracts.enums import ScaleMethod
from ale.contracts.serialization import canonical_json
from ale.pdfread import zones as zones_mod


def _read_grid(tmp: Path, **kw: Any) -> Any:
    return read(save_page(tmp / "z.pdf", sheet(lambda pg: draw_zone_grid(pg, 60, 80, **kw))))


def _poly(room: Any) -> shapely.Polygon:
    return shapely.Polygon(room.polygon.exterior, room.polygon.holes)


def test_Z01_zones(tmp_path: Path) -> None:
    res = _read_grid(tmp_path)
    assert res.is_plan_likely and res.plan_score == 1.0
    assert len(res.plans) == 1
    plan = res.plans[0]
    assert len(plan.rooms) == 12
    assert [r.area_text_m2 for r in plan.rooms] == pytest.approx([area_of(k) for k in range(12)])
    assert [r.id for r in plan.rooms] == [f"r{k:03d}" for k in range(1, 13)]
    assert {r.raw_label for r in plan.rooms} == {
        "fill=#CCE5FF",
        "fill=#FFD9B2",
        "fill=#BFFFBF",
        "fill=#FFCCE5",
    }
    assert plan.scale_method is ScaleMethod.TITLE_BLOCK
    assert plan.scale_m_per_unit is not None
    metric = plan.to_metric()
    assert len(metric.rooms) == 12
    # the polygons are the zones: (CW - 0.4) x (CH - 0.4) m
    for r in metric.rooms:
        a = shapely.Polygon(r.polygon.exterior, r.polygon.holes).area
        assert a == pytest.approx((CW - 2 * GAP) * (CH - 2 * GAP), rel=0.01)
    assert any("filled zones" in w for w in res.warnings)


def test_Z01_name_and_scale_unknown(tmp_path: Path) -> None:
    def build(page: Any) -> None:
        rects = draw_zone_grid(page, 60, 80, 3, 1)
        page.insert_text((rects[0].x0 + 8, rects[0].y0 + 14), "BUREAU", fontname="helv", fontsize=8)

    res = read(save_page(tmp_path / "n.pdf", build))  # no scale text
    plan = res.plans[0]
    assert plan.scale_method is ScaleMethod.UNKNOWN
    assert [r.area_text_m2 for r in plan.rooms] == pytest.approx([area_of(k) for k in range(3)])
    assert plan.rooms[0].type == "office" and plan.rooms[0].raw_label == "BUREAU"


def test_Z02_rotated_text(tmp_path: Path) -> None:
    res = _read_grid(tmp_path, rotate=True)
    plan = res.plans[0]
    assert len(plan.rooms) == 12
    assert [r.area_text_m2 for r in plan.rooms] == pytest.approx([area_of(k) for k in range(12)])


def test_Z02_nearest_area_text_wins(tmp_path: Path) -> None:
    def build(page: Any) -> None:
        rects = draw_zone_grid(page, 60, 80, 3, 1)
        r = rects[0]  # a second, far area text inside the first zone
        page.insert_text((r.x0 + 4, r.y0 + 10), "99,99 m²", fontname="helv", fontsize=6)

    plan = read(save_page(tmp_path / "n.pdf", sheet(build))).plans[0]
    assert plan.rooms[0].area_text_m2 == pytest.approx(area_of(0))


def test_Z03_frames(tmp_path: Path) -> None:
    res = _read_grid(tmp_path, frame=True, duplicate=True)
    plan = res.plans[0]
    assert len(plan.rooms) == 12  # the frame is dropped, duplicates merged
    one = _poly(plan.rooms[0]).area
    assert all(_poly(r).area == pytest.approx(one, rel=0.01) for r in plan.rooms)


def test_Z04_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # sha256 prefixes recorded from the pre-X.2 reader (plan + warnings + verdict)
    expected = {
        "lines": "2f3245fe7cae912d",
        "filled": "10ed1860bf87e641",
        "bar": "8cb3c195118f5684",
        "text": "8534d4b278e12d3f",
    }
    cases = {
        "lines": reference_page(),
        "filled": reference_page(filled=True),
        "bar": bar_chart_page,
        "text": text_page,
    }
    for key, build in cases.items():
        res = read(save_page(tmp_path / f"{key}.pdf", build))
        blob = canonical_json(res.plans[0]) if res.plans else b"none"
        blob = blob if isinstance(blob, bytes) else blob.encode()
        meta = repr((res.warnings, res.is_plan_likely, res.plan_score)).encode()
        assert hashlib.sha256(blob + meta).hexdigest()[:16] == expected[key], key
    # the zone path is never taken for wall-loop plans
    import ale.pdfread.read as read_mod

    def boom(*a: Any, **k: Any) -> Any:
        raise AssertionError("zones used")

    monkeypatch.setattr(read_mod, "trace_zones", boom)
    assert read(save_page(tmp_path / "again.pdf", reference_page())).is_plan_likely


def test_Z05_score(tmp_path: Path) -> None:
    sys.path.insert(0, str(Path(__file__).parent.parent / "score"))
    pytest.importorskip("openpyxl")
    from score_helpers import save_programme, spec
    from typer.testing import CliRunner

    from ale.cli import app

    doc = pymupdf.open()
    page = doc.new_page(width=1500, height=700)
    draw_zone_grid(page, 30, 80, 3, 2, start=0)
    draw_zone_grid(page, 30 + 3 * CW * 28.35 + 200, 80, 3, 2, start=6)
    page.insert_text((30, 30), "ÉCHELLE 1:100", fontname="helv", fontsize=9)
    pdf = tmp_path / "sheet.pdf"
    doc.save(pdf)
    doc.close()
    prog = save_programme(
        tmp_path / "p.xlsx", [spec(f"R{k:02d}", f"Pièce {k}", area_of(k)) for k in range(12)]
    )
    try:
        runner = CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        runner = CliRunner()
    out = tmp_path / "out"
    res = runner.invoke(
        app, ["score", "--plan", str(pdf), "--programme", str(prog), "--out", str(out)]
    )
    assert res.exit_code == 0, res.output
    data = json.loads((out / "score.json").read_text(encoding="utf-8"))
    assert data["coverage"]["matched"] == 12
    assert data["coverage"]["unmatched_lines"] == []
    assert [p["plan"] for p in data["totals"]["plans"]] == [1, 2]
    by_line = {m["line"]: m for m in data["matches"]}
    for k in range(12):
        m = by_line[f"R{k:02d}"]
        assert m["area_m2"] == pytest.approx(area_of(k), abs=0.01)
        assert m["plan"] == (1 if k < 6 else 2)
        assert m["area_source"] == "texte"


def test_Z06_gates() -> None:
    root = Path(__file__).resolve().parents[2]
    res = subprocess.run(
        [sys.executable, "-m", "ale.contracts.lock", "--check"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr


def test_zone_filters(tmp_path: Path) -> None:
    from ale.pdfread.rooms import RoomText

    def sq(x: float, y: float, w: float, h: float, col: Any) -> Any:
        return zones_mod.ZoneFill(((x, y), (x + w, y), (x + w, y + h), (x, y + h)), col)

    blue = (0.5, 0.6, 1.0)
    fills = [
        sq(0, 0, 50, 50, (1.0, 1.0, 1.0)),  # white
        sq(100, 0, 50, 50, (0.0, 0.0, 0.0)),  # wall material
        sq(200, 0, 50, 1, blue),  # sliver
        sq(300, 0, 1, 1, blue),  # tiny
        sq(0, 0, 600, 900, blue),  # page background
        zones_mod.ZoneFill(((0, 0), (50, 0), (50, 50), (0, 25)), blue),  # not orthogonal
        zones_mod.ZoneFill(((0, 0), (50, 50), (50, 0), (0, 50)), blue),  # bow-tie, invalid
        sq(100, 100, 50, 50, blue),
    ]
    warnings: list[str] = []
    rooms = zones_mod.trace_zones(
        fills, [RoomText("5,00 m2", (120.0, 120.0))], None, warnings, page_area=600 * 900
    )
    assert len(rooms) == 1 and rooms[0].area_text_m2 == 5.0
    assert rooms[0].raw_label == "fill=#8099FF"
    # scaled at 0.05 m/pt: at least 200 pt2 (0.5 m2) and 6 pt (0.3 m) on the short side
    assert len(zones_mod.trace_zones([sq(0, 0, 10, 10, blue)], [], 0.05, [])) == 0
    assert len(zones_mod.trace_zones([sq(0, 0, 15, 15, blue)], [], 0.05, [])) == 1


def test_zones_credible_needs_texts() -> None:
    from ale.contracts.geometry import Polygon
    from ale.contracts.models import LabelledPolygon

    ring = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    poly = Polygon(exterior=ring, holes=())
    bare = [LabelledPolygon(id=f"r{i}", polygon=poly, raw_label="fill=#FFFFFF") for i in range(3)]
    assert not zones_mod.zones_credible(bare)
    assert not zones_mod.zones_credible(bare[:2])
    named = [b.model_copy(update={"area_text_m2": 5.0}) for b in bare]
    assert zones_mod.zones_credible(named)


def test_bar_chart_with_texts_is_not_a_plan(tmp_path: Path) -> None:
    res = read(save_page(tmp_path / "bar.pdf", bar_chart_page))
    assert not res.is_plan_likely and res.plans == ()


def test_pt_helper_is_metric() -> None:
    assert pt(0, 0, 1, 0)[0] == pytest.approx(72 / 2.54 * 0.01 * 100)
    assert area_str(0) == "11,00 m²" and SHA
