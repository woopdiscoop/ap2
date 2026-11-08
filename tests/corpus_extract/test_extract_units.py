"""Ticket 1.2c: unit tests of ``ale.corpus.extract`` (layer collection, errors, writes)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from extract_helpers import Invoke, plan_doc, save_doc

import ale.corpus.extract as extract_mod
from ale.corpus.extract import (
    ExtractReport,
    LayersReport,
    _write_atomic,
    model_space_layers,
    run_extract,
    run_layers,
)
from ale.workspace import Workspace, WorkspaceError


def test_model_space_layers_blocks(tmp_path: Path) -> None:
    from cad_helpers import new_doc

    doc = new_doc()
    inner = doc.blocks.new("INNER")
    inner.add_line((0, 0), (1, 0))  # layer 0: takes the layer of the INSERT
    inner.add_line((0, 0), (0, 1), dxfattribs={"layer": "IN_BLOCK"})
    outer = doc.blocks.new("OUTER")
    outer.add_blockref("INNER", (0, 0))  # INSERT on layer 0 inside OUTER
    outer.add_attdef("TAG", (0, 0))
    doc.blocks.new("NEVER_USED").add_line((0, 0), (1, 1), dxfattribs={"layer": "UNUSED"})
    msp = doc.modelspace()
    ref = msp.add_blockref("OUTER", (10, 10), dxfattribs={"layer": "PORTES"})
    ref.add_attrib("TAG", "x", (0, 0))  # attrib on layer 0 → PORTES
    ref.add_attrib("TAG", "y", (0, 0), dxfattribs={"layer": "ATTR"})
    msp.add_blockref("OUTER", (20, 20), dxfattribs={"layer": "PORTES"})  # seen twice
    msp.add_blockref("MISSING", (0, 0), dxfattribs={"layer": "M"})
    doc.add_xref_def("other.dxf", "XR")
    msp.add_blockref("XR", (0, 0), dxfattribs={"layer": "XREF_LAYER"})
    msp.add_line((0, 0), (5, 5), dxfattribs={"layer": "MUR"})
    path = save_doc(doc, tmp_path / "blocks.dxf")
    assert model_space_layers(path) == ("ATTR", "IN_BLOCK", "M", "MUR", "PORTES", "XREF_LAYER")


def test_model_space_layers_recover(tmp_path: Path) -> None:
    path = save_doc(plan_doc(extra_layers=("CLOISON",)), tmp_path / "ok.dxf")
    text = path.read_text(encoding="utf-8")
    # A corrupted header variable: readfile fails, ezdxf.recover copes.
    broken = tmp_path / "broken.dxf"
    broken.write_text(text.replace("$ACADVER", "$ACADVER_BROKEN", 1), encoding="utf-8")
    names = model_space_layers(broken)
    assert "CLOISON" in names and "MUR" in names
    with pytest.raises(OSError):
        model_space_layers(tmp_path / "missing.dxf")


def test_invalid_layer_map(tmp_workspace: Workspace, invoke: Invoke) -> None:
    tmp_workspace.path("layer_map.yaml").write_text(
        "version: 1\nlayers:\n  MUR: not_a_role\n", encoding="utf-8"
    )
    for command in ("layers", "extract"):
        result = invoke([command, "--workspace", str(tmp_workspace.root)])
        assert result.exit_code == 4, result.output
        assert "layer_map.yaml: invalid" in result.stderr


def test_missing_layer_map(tmp_workspace: Workspace) -> None:
    tmp_workspace.path("layer_map.yaml").unlink()
    assert run_extract(tmp_workspace) == ExtractReport()
    assert run_layers(tmp_workspace) == LayersReport()


def test_corpus_too_new(tmp_workspace: Workspace) -> None:
    with closing(sqlite3.connect(tmp_workspace.path("corpus.sqlite"))) as conn:
        conn.execute("PRAGMA user_version = 99")
        conn.commit()
    with pytest.raises(WorkspaceError, match=r"corpus\.sqlite"):
        run_extract(tmp_workspace)


def test_unknown_kind(tmp_workspace: Workspace) -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        run_extract(tmp_workspace, kind="svg")


def test_write_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "a" / "plan.json"
    assert _write_atomic(target, b"x\n") is True
    assert _write_atomic(target, b"x\n") is False
    assert _write_atomic(target, b"y\n") is True
    assert target.read_bytes() == b"y\n"

    def boom(self: Path, other: Path) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        _write_atomic(target, b"z\n")
    assert target.read_bytes() == b"y\n"
    assert sorted(p.name for p in target.parent.iterdir()) == ["plan.json"]


def test_report_to_dict() -> None:
    report = ExtractReport(selected=1, failed=1, problems=[("a.dxf", "no plan found")])
    data = report.to_dict()
    assert data["problems"] == [["a.dxf", "no plan found"]]
    assert extract_mod.KIND_FILTERS["pdf"] == ("PDF_VECTOR", "PDF_SCANNED")
