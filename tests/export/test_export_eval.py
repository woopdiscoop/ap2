"""Ticket 3.5 evaluation (eval.md X01-X10): export & report of a hand-built Layout."""

from __future__ import annotations

import builtins
import importlib
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import ezdxf
import pytest
from export_helpers import CIRC, COST, ROOMS, VIOLATIONS, fr2, fr2s, make_layout

from ale.config import AleConfig
from ale.contracts.models import Layout
from ale.contracts.serialization import canonical_json
from ale.contracts.taxonomy import load_taxonomy
from ale.contracts.version import CONTRACTS_VERSION
from ale.export import RunFiles, export_run
from ale.program.models import PreparedInput

SVG_NS = "{http://www.w3.org/2000/svg}"
NAMES = ("layout.json", "layout.dxf", "preview.svg", "report.md")
ZONE_COLOUR = {"PUBLIC": "#f4d35e", "ADMINISTRATIVE": "#9ad1d4", "SERVICES": "#c8c8c8"}
ZONE_FR = {"PUBLIC": "Public", "ADMINISTRATIVE": "Administratif", "SERVICES": "Services"}


def _export(layout: Layout, prepared: PreparedInput, out: Path, **kw: Any) -> RunFiles:
    return export_run(layout, prepared, out, rulebook_version="test-3.1", run_id="run-001", **kw)


def _with_origin(prepared: PreparedInput, origin: tuple[float, float]) -> PreparedInput:
    fp = prepared.footprint.model_copy(update={"origin_m": origin})
    return prepared.model_copy(update={"footprint": fp})


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9


def _polys(doc: Any, layer: str) -> list[list[tuple[float, float]]]:
    out = []
    for e in doc.modelspace().query(f'LWPOLYLINE[layer=="{layer}"]'):
        assert e.closed
        out.append([(p[0], p[1]) for p in e.get_points("xy")])
    return out


def _expected_rect(
    r: tuple[int, int, int, int], ox: float = 0.0, oy: float = 0.0
) -> list[tuple[float, float]]:
    x, y, w, h = r
    x0, y0, x1, y1 = x * 0.1 + ox, y * 0.1 + oy, (x + w) * 0.1 + ox, (y + h) * 0.1 + oy
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _same_ring(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> bool:
    return len(a) == len(b) and all(
        _close(p[0], q[0]) and _close(p[1], q[1]) for p, q in zip(a, b, strict=True)
    )


# --------------------------------------------------------------------------- X01


def test_X01_files(tmp_path: Path, layout: Layout, prepared: PreparedInput) -> None:
    out = tmp_path / "runs" / "run-001"
    files = _export(layout, prepared, out)
    assert files.layout_json == out / "layout.json"
    assert files.layout_dxf == out / "layout.dxf"
    assert files.preview_svg == out / "preview.svg"
    assert files.report_md == out / "report.md"
    before = {n: (out / n).read_bytes() for n in NAMES}
    assert all(before.values())
    with pytest.raises(FileExistsError):
        _export(layout, prepared, out)
    assert {n: (out / n).read_bytes() for n in NAMES} == before


@pytest.mark.parametrize("name", NAMES)
def test_X01_refuses_any_existing_file(
    tmp_path: Path, layout: Layout, prepared: PreparedInput, name: str
) -> None:
    (tmp_path / name).write_bytes(b"x")
    with pytest.raises(FileExistsError):
        _export(layout, prepared, tmp_path, dxf=False)
    assert sorted(p.name for p in tmp_path.iterdir()) == [name]


# --------------------------------------------------------------------------- X02


def test_X02_json(tmp_path: Path, layout: Layout, prepared: PreparedInput) -> None:
    files = _export(layout, prepared, tmp_path, dxf=False)
    data = files.layout_json.read_bytes()
    assert data == canonical_json(layout)
    assert Layout.model_validate_json(data) == layout


# --------------------------------------------------------------------------- X03


def test_X03_dxf_audit(tmp_path: Path, layout: Layout, prepared: PreparedInput) -> None:
    files = _export(layout, prepared, tmp_path)
    assert files.layout_dxf is not None
    doc = ezdxf.readfile(files.layout_dxf)
    auditor = doc.audit()
    assert len(auditor.errors) == 0
    assert len(auditor.fixes) == 0
    assert doc.header["$INSUNITS"] == 6
    assert doc.dxfversion == "AC1032"  # R2018
    expected = {"ALE_FOOTPRINT": 7, "ALE_ROOM": 5, "ALE_CIRC": 8, "ALE_LABEL": 2, "ALE_GRID": 9}
    for name, colour in expected.items():
        assert doc.layers.has_entry(name), name
        layer = doc.layers.get(name)
        assert layer.color == colour, name
        assert layer.is_off() == (name == "ALE_GRID"), name


def test_X03_dxf_footprint_and_grid(
    tmp_path: Path, layout: Layout, prepared: PreparedInput
) -> None:
    files = _export(layout, prepared, tmp_path)
    assert files.layout_dxf is not None
    doc = ezdxf.readfile(files.layout_dxf)
    (fp,) = _polys(doc, "ALE_FOOTPRINT")
    assert _same_ring(fp, [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    lines = list(doc.modelspace().query('LINE[layer=="ALE_GRID"]'))
    # 12-module spacing over 0..100 → 0, 12, ..., 96: 9 vertical + 9 horizontal lines.
    xs = sorted({round(e.dxf.start.x, 6) for e in lines if e.dxf.start.x == e.dxf.end.x})
    ys = sorted({round(e.dxf.start.y, 6) for e in lines if e.dxf.start.y == e.dxf.end.y})
    assert xs == [round(k * 1.2, 6) for k in range(9)]
    assert ys == xs
    for e in lines:
        for p in (e.dxf.start, e.dxf.end):
            assert -1e-9 <= p.x <= 10 + 1e-9
            assert -1e-9 <= p.y <= 10 + 1e-9


# --------------------------------------------------------------------------- X04


def test_X04_dxf_geometry(tmp_path: Path, layout: Layout, prepared: PreparedInput) -> None:
    files = _export(layout, prepared, tmp_path)
    assert files.layout_dxf is not None
    doc = ezdxf.readfile(files.layout_dxf)
    rooms = _polys(doc, "ALE_ROOM")
    circ = _polys(doc, "ALE_CIRC")
    assert len(rooms) + len(circ) == len(layout.rooms) + len(layout.circulation)
    for layer_polys, rects in ((rooms, [r[2] for r in ROOMS.values()]), (circ, CIRC.values())):
        for r in rects:
            exp = _expected_rect(r)
            matches = [p for p in layer_polys if _same_ring(p, exp)]
            assert len(matches) == 1, r
    for poly in rooms + circ:
        assert len(poly) == 4
        area2 = sum(
            poly[i][0] * poly[(i + 1) % 4][1] - poly[(i + 1) % 4][0] * poly[i][1] for i in range(4)
        )
        assert area2 > 0  # CCW


# --------------------------------------------------------------------------- X05


def test_X05_dxf_labels(tmp_path: Path, layout: Layout, prepared: PreparedInput) -> None:
    files = _export(layout, prepared, tmp_path)
    assert files.layout_dxf is not None
    doc = ezdxf.readfile(files.layout_dxf)
    mtexts = list(doc.modelspace().query('MTEXT[layer=="ALE_LABEL"]'))
    assert len(mtexts) == len(layout.rooms)
    specs = {r.id: r for r in prepared.program.rooms}
    tax = load_taxonomy()
    by_text = {m.text: m for m in mtexts}
    for iid, (sid, target, (x, y, w, h)) in ROOMS.items():
        spec = specs[sid]
        name = spec.name + (f" #{iid.split('#')[1]}" if spec.quantity > 1 else "")
        area = w * h / 100
        third = f"{fr2(area)} m² (Δ {fr2s(area - target)})"
        text = "\\P".join([name, tax.get(spec.type).label_fr, third])
        assert text in by_text, text
        m = by_text[text]
        assert _close(m.dxf.insert.x, (x + w / 2) * 0.1)
        assert _close(m.dxf.insert.y, (y + h / 2) * 0.1)
        assert m.dxf.char_height == pytest.approx(0.25)
        assert m.dxf.attachment_point == 5
    # The spec's example: a 12 m² office placed at exactly 12 m².
    assert any(m.text.split("\\P")[2] == "12,00 m² (Δ +0,00)" for m in mtexts)
    assert any(m.text.split("\\P")[0] == "Bureau #1" for m in mtexts)


# --------------------------------------------------------------------------- X06


def test_X06_dxf_disabled(tmp_path: Path, layout: Layout, prepared: PreparedInput) -> None:
    files = _export(layout, prepared, tmp_path, dxf=False)
    assert files.layout_dxf is None
    assert not (tmp_path / "layout.dxf").exists()
    report = files.report_md.read_text(encoding="utf-8")
    assert "DXF non généré" in report
    assert "désactivé" in report


def test_X06_dxf_ezdxf_missing(
    tmp_path: Path, layout: Layout, prepared: PreparedInput, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "ezdxf" or name.startswith("ezdxf."):
            raise ImportError("no ezdxf")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    for mod in [m for m in sys.modules if m == "ezdxf" or m.startswith("ezdxf.")]:
        monkeypatch.delitem(sys.modules, mod)
    monkeypatch.setattr(importlib, "import_module", lambda n, *a: fake_import(n))
    files = _export(layout, prepared, tmp_path)
    assert files.layout_dxf is None
    assert not (tmp_path / "layout.dxf").exists()
    report = files.report_md.read_text(encoding="utf-8")
    assert "DXF non généré" in report
    assert "ezdxf" in report


def test_X06_write_dxf_without_ezdxf_raises(
    tmp_path: Path, layout: Layout, prepared: PreparedInput, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ale.export import dxf as dxf_mod

    monkeypatch.setitem(sys.modules, "ezdxf", None)  # import → ImportError
    assert dxf_mod.load_ezdxf() is None
    with pytest.raises(ImportError):
        dxf_mod.write_dxf(layout, prepared, tmp_path / "x.dxf")


# --------------------------------------------------------------------------- X07


def test_X07_svg(tmp_path: Path, layout: Layout, prepared: PreparedInput) -> None:
    files = _export(layout, prepared, tmp_path, dxf=False)
    root = ET.parse(files.preview_svg).getroot()
    assert root.tag == f"{SVG_NS}svg"
    assert root.get("version") == "1.1"
    vb = [float(v) for v in (root.get("viewBox") or "").split()]
    # Footprint bbox 0..10 x 0..10 m, y flipped: (xmin, -ymax, w, h).
    assert vb == [0.0, -10.0, 10.0, 10.0]
    rects = list(root.iter(f"{SVG_NS}rect"))
    assert len(rects) == len(layout.rooms) + len(layout.circulation)
    specs = {r.id: r for r in prepared.program.rooms}
    by_id = {r.get("id"): r for r in rects}
    for iid, (sid, _t, (x, y, w, h)) in ROOMS.items():
        rect = by_id[f"room-{iid}"]
        assert rect.get("fill") == ZONE_COLOUR[specs[sid].macro_zone.value]
        assert float(rect.get("x") or "nan") == pytest.approx(x * 0.1)
        assert float(rect.get("y") or "nan") == pytest.approx(-(y + h) * 0.1)
        assert float(rect.get("width") or "nan") == pytest.approx(w * 0.1)
        assert float(rect.get("height") or "nan") == pytest.approx(h * 0.1)
    for iid in CIRC:
        assert by_id[f"circ-{iid}"].get("fill") == "#eeeeee"
    arrows = [g for g in root.iter(f"{SVG_NS}g") if g.get("id") == "north-arrow"]
    assert len(arrows) == 1
    assert any(t.text == "N" for t in arrows[0].iter(f"{SVG_NS}text"))
    fp = [e for e in root.iter(f"{SVG_NS}polygon") if e.get("id") == "footprint"]
    assert len(fp) == 1 and fp[0].get("stroke") == "#000000"
    labels = [g for g in root.iter(f"{SVG_NS}g") if g.get("id") == "labels"]
    assert labels[0].get("font-size") == "0.25"
    texts = ["".join(t.itertext()) for t in labels[0].iter(f"{SVG_NS}text")]
    assert len(texts) == len(layout.rooms)
    assert any("Hall d'entrée" in t and "12,00 m²" in t for t in texts)


def _arrow_tip(path_d: str) -> tuple[tuple[float, float], tuple[float, float]]:
    nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", path_d)]
    return (nums[0], nums[1]), (nums[2], nums[3])


@pytest.mark.parametrize(("angle", "direction"), [(0.0, (0, -1)), (90.0, (1, 0))])
def test_X07_north_arrow_direction(
    tmp_path: Path,
    layout: Layout,
    prepared: PreparedInput,
    angle: float,
    direction: tuple[int, int],
) -> None:
    site = prepared.site.model_copy(update={"north_angle_deg": angle})
    prep = prepared.model_copy(update={"site": site})
    files = _export(layout, prep, tmp_path, dxf=False)
    root = ET.parse(files.preview_svg).getroot()
    (arrow,) = [g for g in root.iter(f"{SVG_NS}g") if g.get("id") == "north-arrow"]
    shaft = next(iter(arrow.iter(f"{SVG_NS}path")))
    (tx, ty), (hx, hy) = _arrow_tip(shaft.get("d") or "")
    dx, dy = hx - tx, hy - ty
    norm = (dx * dx + dy * dy) ** 0.5
    assert dx / norm == pytest.approx(direction[0], abs=1e-3)
    assert dy / norm == pytest.approx(direction[1], abs=1e-3)
    # Top-right quadrant of the viewBox (SVG y = -10 .. 0).
    assert tx > 5 and hx > 5 and ty < -5 and hy < -5


# --------------------------------------------------------------------------- X08

SECTIONS = [
    "# Rapport de génération — run-001",
    "## Résumé",
    "## Surfaces",
    "## Contraintes non respectées",
    "## Coût",
    "## Fichiers",
]


def _section(text: str, title: str) -> list[str]:
    lines = text.splitlines()
    start = lines.index(title) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return [ln for ln in lines[start:end] if ln.strip()]


def _table(lines: list[str]) -> list[list[str]]:
    rows = [ln for ln in lines if ln.startswith("|")]
    return [[c.strip() for c in r.strip("|").split("|")] for r in rows[2:]]


def test_X08_report_sections(tmp_path: Path, layout: Layout, prepared: PreparedInput) -> None:
    files = _export(layout, prepared, tmp_path)
    raw = files.report_md.read_bytes()
    assert b"\r" not in raw
    text = raw.decode("utf-8")
    heads = [ln for ln in text.splitlines() if ln.startswith("# ") or ln.startswith("## ")]
    assert heads == SECTIONS


def test_X08_report_summary(tmp_path: Path, layout: Layout, prepared: PreparedInput) -> None:
    text = _export(layout, prepared, tmp_path).report_md.read_text(encoding="utf-8")
    summary = "\n".join(_section(text, "## Résumé"))
    net = sum(spec.target_area_m2 for _, spec in prepared.instances)
    placed = sum(r[2][2] * r[2][3] / 100 for r in ROOMS.values())
    circ = sum(r[2] * r[3] / 100 for r in CIRC.values())
    for needle in (
        "7",
        "test-3.1",
        CONTRACTS_VERSION,
        "0,10 m",
        "100,00 m²",
        f"{fr2(net)} m²",
        f"{fr2(placed)} m²",
        f"{fr2(circ)} m² ({fr2(circ)} %",  # footprint = 100 m², so the ratio equals the area
        f"{fr2(layout.metrics.total_overshoot_m2)} m²",
        fr2(layout.metrics.total_cost),
    ):
        assert needle in summary, needle


def test_X08_report_surfaces(tmp_path: Path, layout: Layout, prepared: PreparedInput) -> None:
    text = _export(layout, prepared, tmp_path).report_md.read_text(encoding="utf-8")
    rows = _table(_section(text, "## Surfaces"))
    assert [r[0] for r in rows] == sorted(ROOMS)
    specs = {r.id: r for r in prepared.program.rooms}
    tax = load_taxonomy()
    codes: dict[str, set[str]] = {}
    for v in VIOLATIONS:
        for iid in v.instance_ids:
            codes.setdefault(iid, set()).add(v.code)
    for row in rows:
        iid = row[0]
        sid, target, (x, y, w, h) = ROOMS[iid]
        spec = specs[sid]
        area = w * h / 100
        delta = area - target
        facade = x == 0 or y == 0 or x + w == 100 or y + h == 100
        expected = [
            iid,
            spec.name + (f" #{iid.split('#')[1]}" if spec.quantity > 1 else ""),
            tax.get(spec.type).label_fr,
            ZONE_FR[spec.macro_zone.value],
            fr2(target),
            fr2(area),
            fr2s(delta),
            fr2s(delta / target * 100),
            f"{fr2(max(w, h) / 10)} \u00d7 {fr2(min(w, h) / 10)}",
            "oui" if facade else "non",
            ", ".join(sorted(codes[iid])) if iid in codes else "OK",
        ]
        assert row == expected, iid


def test_X08_report_violations_and_cost(
    tmp_path: Path, layout: Layout, prepared: PreparedInput
) -> None:
    text = _export(layout, prepared, tmp_path).report_md.read_text(encoding="utf-8")
    viol = _section(text, "## Contraintes non respectées")
    assert viol[0] == "### AREA_UNDER (1)"
    assert viol[1] == f"- `R03#2` : {VIOLATIONS[0].detail}"
    assert viol[2] == "### ASPECT (2)"
    assert viol[3:5] == [
        f"- `R06` : {VIOLATIONS[1].detail}",
        f"- `R07` : {VIOLATIONS[2].detail}",
    ]
    cost = _table(_section(text, "## Coût"))
    w = AleConfig().optimizer.weights.model_dump()
    for row in cost[:-1]:
        term = row[0]
        value = COST[term]
        if term in w:
            assert row[1:] == [fr2(value), fr2(w[term]), fr2(w[term] * value)]
        else:
            assert row[1:] == [fr2(value), "—", "—"]
    assert [r[0] for r in cost[:-1]] == sorted(COST)
    assert cost[-1] == ["**Total**", "", "", fr2(layout.metrics.total_cost)]
    files = "\n".join(_section(text, "## Fichiers"))
    for name in NAMES:
        assert f"`{name}`" in files


def test_X08_report_no_violation(tmp_path: Path, prepared: PreparedInput) -> None:
    layout = make_layout(violations=())
    text = _export(layout, prepared, tmp_path).report_md.read_text(encoding="utf-8")
    assert _section(text, "## Contraintes non respectées") == ["Aucune."]
    rows = _table(_section(text, "## Surfaces"))
    assert all(r[-1] == "OK" for r in rows)


def test_X08_report_cost_weights_from_config(
    tmp_path: Path, layout: Layout, prepared: PreparedInput
) -> None:
    cfg = AleConfig.model_validate({"optimizer": {"weights": {"aspect": 4.0}}})
    text = _export(layout, prepared, tmp_path, config=cfg).report_md.read_text(encoding="utf-8")
    cost = {r[0]: r for r in _table(_section(text, "## Coût"))}
    assert cost["aspect"][1:] == ["3,25", "4,00", "13,00"]


# --------------------------------------------------------------------------- X09


def test_X09_origin_offset(tmp_path: Path, layout: Layout, prepared: PreparedInput) -> None:
    base = _export(layout, prepared, tmp_path / "a")
    moved = _export(layout, _with_origin(prepared, (0.05, 0.0)), tmp_path / "b")
    assert base.layout_dxf is not None and moved.layout_dxf is not None
    da, db = ezdxf.readfile(base.layout_dxf), ezdxf.readfile(moved.layout_dxf)
    for layer in ("ALE_FOOTPRINT", "ALE_ROOM", "ALE_CIRC"):
        pa, pb = _polys(da, layer), _polys(db, layer)
        assert len(pa) == len(pb) > 0
        for ra, rb in zip(pa, pb, strict=True):
            assert _same_ring([(x + 0.05, y) for x, y in ra], rb)
    for r in [r[2] for r in ROOMS.values()]:
        assert any(_same_ring(p, _expected_rect(r, 0.05)) for p in _polys(db, "ALE_ROOM"))
    ma = list(da.modelspace().query("MTEXT"))
    mb = list(db.modelspace().query("MTEXT"))
    for a, b in zip(ma, mb, strict=True):
        assert _close(b.dxf.insert.x, a.dxf.insert.x + 0.05)
        assert _close(b.dxf.insert.y, a.dxf.insert.y)
    la = list(da.modelspace().query("LINE"))
    lb = list(db.modelspace().query("LINE"))
    assert len(la) == len(lb) > 0
    for a, b in zip(la, lb, strict=True):
        assert _close(b.dxf.start.x, a.dxf.start.x + 0.05)
        assert _close(b.dxf.end.x, a.dxf.end.x + 0.05)
        assert _close(b.dxf.start.y, a.dxf.start.y)


# --------------------------------------------------------------------------- X10


def _entities(path: Path) -> list[tuple[Any, ...]]:
    doc = ezdxf.readfile(path)
    out: list[tuple[Any, ...]] = []
    for e in doc.modelspace():
        kind = e.dxftype()
        if kind == "LWPOLYLINE":
            geo: Any = tuple(tuple(p) for p in e.get_points("xy"))
        elif kind == "MTEXT":
            geo = (e.text, tuple(e.dxf.insert))
        else:
            geo = (tuple(e.dxf.start), tuple(e.dxf.end))
        out.append((kind, e.dxf.layer, geo))
    return out


def test_X10_deterministic(tmp_path: Path, layout: Layout, prepared: PreparedInput) -> None:
    a = _export(layout, prepared, tmp_path / "a")
    b = _export(layout, prepared, tmp_path / "b")
    for name in ("layout.json", "preview.svg", "report.md"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    assert a.layout_dxf is not None and b.layout_dxf is not None
    ea, eb = _entities(a.layout_dxf), _entities(b.layout_dxf)
    assert ea == eb and len(ea) > 0


# --------------------------------------------------------------------------- extra


def test_l_footprint_and_coarse_module(tmp_path: Path, prepared: PreparedInput) -> None:
    """Module 200 mm, L footprint: grid step ceil(1.2/0.2) = 6 modules; facade on the notch."""
    from ale.contracts.geometry import ModuleRect
    from ale.contracts.models import LayoutMetrics, PlacedRoom

    fp = ((0, 0), (50, 0), (50, 30), (30, 30), (30, 50), (0, 50))
    layout = Layout.model_validate(
        {
            **make_layout().model_dump(),
            "grid": {"module_mm": 200},
            "footprint": {"exterior": fp},
            "rooms": (
                PlacedRoom(
                    instance_id="R01",
                    spec_id="R01",
                    rect=ModuleRect(29, 30, 1, 1),
                    target_area_m2=12.0,
                ).model_dump(),
                PlacedRoom(
                    instance_id="R02",
                    spec_id="R02",
                    rect=ModuleRect(10, 10, 5, 5),
                    target_area_m2=None,
                ).model_dump(),
                PlacedRoom(
                    instance_id="R99",
                    spec_id="ZZ",
                    rect=ModuleRect(0, 0, 2, 2),
                    target_area_m2=None,
                ).model_dump(),
            ),
            "circulation": (),
            "residue": (),
            "metrics": LayoutMetrics(
                total_cost=0.0,
                cost_breakdown={},
                total_overshoot_m2=0.0,
                circulation_area_m2=0.0,
                residue_area_m2=0.0,
                violations=(),
            ).model_dump(),
        }
    )
    files = _export(layout, prepared, tmp_path)
    assert files.layout_dxf is not None
    doc = ezdxf.readfile(files.layout_dxf)
    xs = sorted(
        {
            round(e.dxf.start.x, 6)
            for e in doc.modelspace().query('LINE[layer=="ALE_GRID"]')
            if e.dxf.start.x == e.dxf.end.x
        }
    )
    assert xs == [round(k * 1.2, 6) for k in range(9)]  # 0..48 modules step 6 → 0..9.6 m
    (ring,) = _polys(doc, "ALE_FOOTPRINT")
    assert len(ring) == 6
    rows = {
        r[0]: r
        for r in _table(_section(files.report_md.read_text(encoding="utf-8"), "## Surfaces"))
    }
    assert rows["R01"][9] == "oui"  # touches the reflex corner edges
    assert rows["R02"][9] == "non"
    # R02 has no target on the placed room: falls back to the spec target (9 m²).
    assert rows["R02"][4] == "9,00" and rows["R02"][5] == "1,00"
    assert rows["R02"][6] == "-8,00"
    # Unknown spec: the instance id stands in for the name, no type/zone/target.
    assert rows["R99"][1:5] == ["R99", "—", "—", "—"]
    assert rows["R99"][6:8] == ["—", "—"]
    svg = files.preview_svg.read_text(encoding="utf-8")
    assert 'id="room-R99"' in svg and "#dddddd" in svg
