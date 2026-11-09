"""D12 robustness, D14 real-corpus smoke (optional), D15 gates (lock part)."""

from __future__ import annotations

import os
import random
import tempfile
import time
from pathlib import Path

import ezdxf
import pytest
from cad_helpers import SHA, add_plan_pairs, layer_map_for, new_doc, read, save

from ale.cad import LayerMap, convert_dwg, read_cad
from ale.cad.rooms import polygonize_rooms
from ale.cad.walls import extract_walls
from ale.contracts.config import AleConfig
from ale.contracts.enums import SourceKind
from ale.contracts.lock import main as lock_main
from ale.doctor import TOOLS, find_tool


def test_D12_robustness_degenerate_files(tmp_path: Path) -> None:
    empty = read(save(new_doc(), tmp_path / "empty.dxf"))
    assert empty.plans == () and "no walls found" in empty.warnings

    doc = new_doc()
    doc.modelspace().add_text("ONLY TEXT", dxfattribs={"layer": "TEXTE"})
    doc.modelspace().add_mtext("", dxfattribs={"layer": "TEXTE"})
    only_text = read(save(doc, tmp_path / "text.dxf"))
    assert only_text.plans == () and "TEXTE" in only_text.layer_names

    doc = new_doc()
    msp = doc.modelspace()
    add_plan_pairs(msp)
    bow_tie = [(100, 100), (4000, 4900), (4000, 100), (100, 4900)]
    msp.add_lwpolyline(bow_tie, close=True, dxfattribs={"layer": "ZONES"})
    bow = read(save(doc, tmp_path / "bow.dxf"))
    assert len(bow.plans) == 1
    assert len(bow.plans[0].rooms) == 2  # make_valid: two triangles

    garbage = tmp_path / "garbage.dxf"
    garbage.write_bytes(b"\x00\x01 not a dxf at all")
    res = read_cad(garbage, source_sha256=SHA, layer_map=LayerMap(), config=AleConfig())
    assert res.plans == () and res.warnings
    missing = read_cad(
        tmp_path / "absent.dxf", source_sha256=SHA, layer_map=LayerMap(), config=AleConfig()
    )
    assert missing.plans == () and "cannot" in missing.warnings[0]


def test_D12_robustness_random_lines(tmp_path: Path) -> None:
    rng = random.Random(12)
    doc = new_doc()
    msp = doc.modelspace()
    for _ in range(10_000):
        x, y = rng.uniform(0, 100_000), rng.uniform(0, 100_000)
        msp.add_line(
            (x, y),
            (x + rng.uniform(-2000, 2000), y + rng.uniform(-2000, 2000)),
            dxfattribs={"layer": "MUR"},
        )
    msp.add_line((5, 5), (5, 5), dxfattribs={"layer": "MUR"})  # zero length
    path = save(doc, tmp_path / "random.dxf")
    t0 = time.monotonic()
    res = read(path)
    # CI runners under coverage take ~21-24 s; 60 s still proves the runtime is bounded.
    assert time.monotonic() - t0 < 60.0
    assert isinstance(res.warnings, tuple)


def test_D12_robustness_odd_entities(tmp_path: Path) -> None:
    doc = new_doc()
    msp = doc.modelspace()
    add_plan_pairs(msp)
    msp.add_blockref("NO_SUCH_BLOCK", (0, 0))
    doc.blocks.new("EMPTY_DOOR")
    msp.add_blockref("EMPTY_DOOR", (100, 100), dxfattribs={"layer": "PORTES"})
    msp.add_polyline3d([(0, 0, 0), (10, 0, 5)], dxfattribs={"layer": "MUR"})
    msp.add_lwpolyline([(0, 0)], dxfattribs={"layer": "MUR"})
    msp.add_lwpolyline([(0, 0), (10, 0)], dxfattribs={"layer": "ZONES"})
    msp.add_circle((0, 0), 100, dxfattribs={"layer": "MUR"})
    # deep self-nesting: A contains B contains ... (bounded depth)
    prev = None
    for k in range(20):
        blk = doc.blocks.new(f"N{k}")
        if prev is not None:
            blk.add_blockref(prev, (0, 0))
        else:
            blk.add_line((0, 0), (1, 1), dxfattribs={"layer": "MUR"})
        prev = f"N{k}"
    msp.add_blockref(prev, (900000, 900000))
    # zone insert carrying a label attribute → CAD_ZONE label
    zb = doc.blocks.new("ROOM")
    zb.add_lwpolyline([(0, 0), (3900, 0), (3900, 4800), (0, 4800)], close=True)
    ins = msp.add_blockref("ROOM", (100, 100), dxfattribs={"layer": "ZONES"})
    ins.add_attrib("NAME", "BUREAU", (500, 500))
    res = read(save(doc, tmp_path / "odd.dxf"))
    assert len(res.plans) == 1
    assert "missing block NO_SUCH_BLOCK" in res.warnings
    assert any("block nesting deeper" in w for w in res.warnings)
    room = res.plans[0].rooms[0]
    assert room.type == "office" and room.label_source is not None


def test_D12_internal_limits() -> None:
    warnings: list[str] = []
    many = [((float(i), 0.0), (float(i), 1.0)) for i in range(60_001)]
    assert polygonize_rooms(many, 0.001, warnings) == []
    assert any("polygonize skipped" in w for w in warnings)
    assert polygonize_rooms([((0.0, 0.0), (0.0, 0.0))], 0.001, warnings) == []
    # many parallel pairs: the collinear merge is skipped above its cap
    segs = []
    for i in range(2600):
        y = i * 1000.0
        segs.append(((0.0, y), (500.0, y)))
        segs.append(((0.0, y + 200.0), (500.0, y + 200.0)))
        segs.append(((10_000.0, y), (10_500.0, y)))
        segs.append(((10_000.0, y + 200.0), (10_500.0, y + 200.0)))
    res = extract_walls(segs, [], 0.001)
    assert any("merge skipped" in w for w in res.warnings)


def test_D14_real_corpus_smoke() -> None:
    corpus = os.environ.get("ALE_CORPUS_DIR", "")
    if not corpus:
        pytest.skip("ALE_CORPUS_DIR not set (optional smoke test, never in CI)")
    root = Path(corpus)
    dxfs = sorted(p for p in root.rglob("*") if p.suffix.lower() == ".dxf")
    dwgs = sorted(p for p in root.rglob("*") if p.suffix.lower() == ".dwg")
    print(f"\nD14: {len(dxfs)} DXF, {len(dwgs)} DWG under {root}")
    config = AleConfig()

    def report(path: Path, dxf: Path, kind: SourceKind) -> None:
        names = layer_map_for(ezdxf.readfile(dxf))
        res = read_cad(dxf, source_sha256=SHA, layer_map=names, config=config, source_kind=kind)
        walls = sum(len(p.walls) for p in res.plans)
        rooms = sum(len(p.rooms) for p in res.plans)
        print(f"  {path.name}: plans={len(res.plans)} walls={walls} rooms={rooms}")

    for p in dxfs:
        report(p, p, SourceKind.DXF)
    oda, how = find_tool(TOOLS[0], "", Path.cwd())
    if oda is None:
        print(f"  no ODA converter detected ({how}): {len(dwgs)} DWG not read")
        return
    with tempfile.TemporaryDirectory() as cache:
        for p in dwgs:
            conv = convert_dwg(p, Path(cache), config)
            if conv.dxf_path is None:
                print(f"  {p.name}: {conv.status} {conv.message}")
                continue
            report(p, conv.dxf_path, SourceKind.DWG)


def test_D15_gates() -> None:
    """Contracts untouched (lock --check); ruff/mypy/coverage run as commands (eval_report)."""
    assert lock_main(["--check"]) == 0
