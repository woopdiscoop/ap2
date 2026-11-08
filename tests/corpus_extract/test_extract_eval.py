"""Ticket 1.2c eval (W01-W08): ``ale layers`` and ``ale extract`` for DXF / DWG."""

from __future__ import annotations

from pathlib import Path

import pytest
from corpus_helpers import dwg_bytes, pdf_one_page, png_bytes, snapshot, write
from extract_helpers import (
    GT_ROOMS,
    Invoke,
    event_count,
    execute,
    mtimes,
    plan_doc,
    query,
    save_doc,
    unit_of,
)

import ale.corpus.extract as extract_mod
from ale.cad import load_layer_map, save_layer_map
from ale.cad.layers import LayerMap, LayerRole
from ale.contracts.enums import SourceKind
from ale.contracts.models import PlanGeometry
from ale.corpus.extract import plan_path
from ale.corpus.ingest import ingest
from ale.workspace import Workspace

FAKE_ODA = """\
import shutil, sys
from pathlib import Path
in_dir, out_dir, version, kind, recurse, audit, name = sys.argv[1:8]
shutil.copyfile({prepared!r}, Path(out_dir) / (Path(name).stem + ".dxf"))
"""


def _ws_args(ws: Workspace) -> list[str]:
    return ["--workspace", str(ws.root)]


def _map_layers(invoke: Invoke, ws: Workspace) -> None:
    """``ale layers`` first: unmapped layers are ignored by the reader."""
    result = invoke(["layers", *_ws_args(ws)])
    assert result.exit_code == 0, result.output


def _load_plan(path: Path) -> PlanGeometry:
    return PlanGeometry.model_validate_json(path.read_bytes())


# ---------------------------------------------------------------------- W01


def test_W01_layers_cmd(tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke) -> None:
    inp = tmp_path / "input"
    save_doc(plan_doc(labels=True), inp / "a.dxf")
    save_doc(plan_doc(extra_layers=("PORTES", "Mobilier")), inp / "sub" / "b.dxf")
    ingest(tmp_workspace, inp)
    before = snapshot(inp)
    save_layer_map(LayerMap(layers={"MUR": LayerRole.IGNORE}), tmp_workspace.path("layer_map.yaml"))

    result = invoke(["layers", *_ws_args(tmp_workspace)])

    assert result.exit_code == 0, result.output
    lm = load_layer_map(tmp_workspace.path("layer_map.yaml"))
    assert lm.layers == {
        "MUR": LayerRole.IGNORE,  # user entry kept
        "Mobilier": LayerRole.FURNITURE,
        "PORTES": LayerRole.DOOR,
        "TEXTE LOCAUX": LayerRole.ROOM_LABEL,
    }
    text = tmp_workspace.path("layer_map.yaml").read_text(encoding="utf-8")
    keys = [ln.split(":")[0].strip() for ln in text.splitlines() if ln.startswith("  ")]
    assert keys == sorted(keys)
    out = result.stdout
    assert "CALQUE" in out and "RÔLE" in out and "FICHIERS" in out
    rows = {ln.split()[0]: ln for ln in out.splitlines() if ln.startswith(("MUR", "PORTES"))}
    assert rows["MUR"].split()[1:] == ["ignore", "2"]
    assert rows["PORTES"].split()[1:] == ["door", "1", "nouveau"]
    assert "Mobilier" in out and "TEXTE LOCAUX" in out
    assert snapshot(inp) == before  # the input folder is never written


def test_W01_layers_nothing_to_do(tmp_workspace: Workspace, invoke: Invoke) -> None:
    before = tmp_workspace.path("layer_map.yaml").read_bytes()
    result = invoke(["layers", *_ws_args(tmp_workspace)])
    assert result.exit_code == 0, result.output
    assert "Aucun calque" in result.stdout
    assert tmp_workspace.path("layer_map.yaml").read_bytes() == before


def test_W01_layers_skips(
    tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing source, unconvertible DWG, unreadable DXF, excluded unit: skipped with a warning."""
    inp = tmp_path / "input"
    save_doc(plan_doc(), inp / "gone.dxf")
    save_doc(plan_doc(extra_layers=("CLOISON",)), inp / "excl.dxf")
    write(inp / "bad.dxf", b"  0\nSECTION\n  2\nENTITIES\n  0\nLINE\n  8\n")
    write(inp / "plan.dwg", dwg_bytes())
    meta = write(tmp_path / "meta.csv", b"filename,exclude\nexcl.dxf,1\n")
    ingest(tmp_workspace, inp, meta=meta)
    # The DWG waits for a tool; make it NEW to exercise the conversion attempt.
    execute(tmp_workspace, "UPDATE units SET status = 'NEW' WHERE kind = 'DWG'")
    (inp / "gone.dxf").unlink()
    monkeypatch.setattr(
        extract_mod, "model_space_layers", _raise_on_bad(extract_mod.model_space_layers)
    )
    result = invoke(["layers", *_ws_args(tmp_workspace)])
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert "gone.dxf: source file not found" in out
    assert "plan.dwg: DWG not converted (NEEDS_TOOL" in out
    assert "bad.dxf: cannot read layers" in out
    assert "Aucun calque" in out
    assert "CLOISON" not in out


def _raise_on_bad(orig):  # type: ignore[no-untyped-def]
    def wrapper(path: Path) -> tuple[str, ...]:
        if path.name == "bad.dxf":
            raise ValueError("broken")
        return orig(path)  # type: ignore[no-any-return]

    return wrapper


# ---------------------------------------------------------------------- W02 / W03


def test_W02_extract_dxf(tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke) -> None:
    inp = tmp_path / "input"
    save_doc(plan_doc(labels=True), inp / "a.dxf")
    save_doc(plan_doc(), inp / "b é.dxf")
    ingest(tmp_workspace, inp)
    _map_layers(invoke, tmp_workspace)
    before = snapshot(inp)
    result = invoke(["extract", *_ws_args(tmp_workspace), "--kind", "dxf"])
    assert result.exit_code == 0, result.output
    assert "Extraction terminée" in result.stdout
    assert "extraites : 2" in result.stdout
    for rel in ("a.dxf", "b é.dxf"):
        sha, page, kind, status, reason = unit_of(tmp_workspace, rel)
        assert (kind, status, reason) == ("DXF", "EXTRACTED", None)
        path = tmp_workspace.path("extracted", sha, "0", "0", "plan.json")
        assert path == plan_path(tmp_workspace, sha, page, 0)
        plan = _load_plan(path)
        assert plan.source_sha256 == sha
        assert plan.source_kind is SourceKind.DXF
        assert len(plan.rooms) == GT_ROOMS
    assert event_count(tmp_workspace, "extracted") == 2
    assert snapshot(inp) == before


def test_W03_multi_plan_paths(tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke) -> None:
    inp = tmp_path / "input"
    save_doc(plan_doc(copies=2), inp / "two.dxf")
    ingest(tmp_workspace, inp)
    _map_layers(invoke, tmp_workspace)
    result = invoke(["extract", *_ws_args(tmp_workspace)])
    assert result.exit_code == 0, result.output
    sha = unit_of(tmp_workspace, "two.dxf")[0]
    base = tmp_workspace.path("extracted", sha)
    assert sorted(p.relative_to(base).as_posix() for p in base.rglob("plan.json")) == [
        "0/0/plan.json",
        "0/1/plan.json",
    ]
    for i in (0, 1):
        plan = _load_plan(base / "0" / str(i) / "plan.json")
        assert plan.plan_index == i
        assert len(plan.rooms) == GT_ROOMS


# ---------------------------------------------------------------------- W04


def test_W04_failures(
    tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cad_helpers import new_doc

    inp = tmp_path / "input"
    save_doc(new_doc(), inp / "empty.dxf")
    save_doc(plan_doc(), inp / "raises.dxf")
    save_doc(plan_doc(extra_layers=("X",)), inp / "ok.dxf")
    ingest(tmp_workspace, inp)
    _map_layers(invoke, tmp_workspace)
    bad_sha = unit_of(tmp_workspace, "raises.dxf")[0]
    orig = extract_mod.read_cad

    def fake_read_cad(path: Path, **kw: object):  # type: ignore[no-untyped-def]
        if kw["source_sha256"] == bad_sha:
            raise RuntimeError("boom")
        return orig(path, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(extract_mod, "read_cad", fake_read_cad)
    result = invoke(["extract", *_ws_args(tmp_workspace)])
    assert result.exit_code == 0, result.output
    assert unit_of(tmp_workspace, "empty.dxf")[3:] == ("FAILED", "no plan found")
    assert unit_of(tmp_workspace, "raises.dxf")[3:] == ("FAILED", "RuntimeError: boom")
    assert unit_of(tmp_workspace, "ok.dxf")[3] == "EXTRACTED"
    assert event_count(tmp_workspace, "extract_failed") == 2
    assert event_count(tmp_workspace, "extracted") == 1
    assert "échecs : 2" in result.stdout
    assert "RuntimeError: boom" in result.stdout


def test_W04_missing_source(tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke) -> None:
    inp = tmp_path / "input"
    save_doc(plan_doc(), inp / "gone.dxf")
    ingest(tmp_workspace, inp)
    _map_layers(invoke, tmp_workspace)
    (inp / "gone.dxf").unlink()
    result = invoke(["extract", *_ws_args(tmp_workspace)])
    assert result.exit_code == 0, result.output
    status, reason = unit_of(tmp_workspace, "gone.dxf")[3:]
    assert status == "FAILED"
    assert reason is not None and reason.startswith("FileNotFoundError: source file not found")


# ---------------------------------------------------------------------- W05


def _fake_oda(tmp_path: Path, prepared: Path) -> Path:
    script = tmp_path / "tools" / "fake_oda.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(FAKE_ODA.format(prepared=str(prepared)), encoding="utf-8")
    return script


def test_W05_dwg_paths(
    tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = save_doc(plan_doc(extra_layers=("PORTES",)), tmp_path / "prep" / "prepared.dxf")
    script = _fake_oda(tmp_path, prepared)
    inp = tmp_path / "input"
    write(inp / "plan.dwg", dwg_bytes())
    write(inp / "other.dwg", dwg_bytes(b"AC1027"))
    monkeypatch.setenv("ALE_ODA_PATH", str(script))
    ingest(tmp_workspace, inp)
    _map_layers(invoke, tmp_workspace)
    assert unit_of(tmp_workspace, "plan.dwg")[3] == "NEW"

    # `ale layers` converts the DWG and reads its layers.
    result = invoke(["layers", *_ws_args(tmp_workspace)])
    assert result.exit_code == 0, result.output
    assert "PORTES" in result.stdout
    assert load_layer_map(tmp_workspace.path("layer_map.yaml")).role("PORTES") is LayerRole.DOOR

    # Extraction reuses the cached conversion.
    sha = unit_of(tmp_workspace, "plan.dwg")[0]
    result = invoke(["extract", *_ws_args(tmp_workspace), "--kind", "dwg"])
    assert result.exit_code == 0, result.output
    assert unit_of(tmp_workspace, "plan.dwg")[3] == "EXTRACTED"
    assert unit_of(tmp_workspace, "other.dwg")[3] == "EXTRACTED"
    assert tmp_workspace.path("cache", "dxf", f"{sha}.dxf").is_file()
    plan = _load_plan(plan_path(tmp_workspace, sha, 0, 0))
    assert plan.source_kind is SourceKind.DWG
    assert plan.source_sha256 == sha
    assert len(plan.rooms) == GT_ROOMS

    # A DWG ingested while a converter existed, extracted without one.
    write(inp / "late.dwg", dwg_bytes(b"AC1024"))
    ingest(tmp_workspace, inp)
    monkeypatch.delenv("ALE_ODA_PATH")
    result = invoke(["extract", *_ws_args(tmp_workspace)])
    assert result.exit_code == 0, result.output
    _sha, _page, kind, status, reason = unit_of(tmp_workspace, "late.dwg")
    assert (kind, status) == ("DWG", "NEEDS_TOOL")
    assert reason is not None and "no DWG converter found" in reason
    assert "outil manquant : 1" in result.stdout


def test_W05_dwg_no_converter_at_ingest(
    tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke
) -> None:
    inp = tmp_path / "input"
    write(inp / "plan.dwg", dwg_bytes())
    ingest(tmp_workspace, inp)
    _map_layers(invoke, tmp_workspace)
    assert unit_of(tmp_workspace, "plan.dwg")[3] == "NEEDS_TOOL"
    result = invoke(["extract", *_ws_args(tmp_workspace)])
    assert result.exit_code == 0, result.output
    assert unit_of(tmp_workspace, "plan.dwg")[3] == "NEEDS_TOOL"
    assert event_count(tmp_workspace, "extracted") == 0


def test_W05_dwg_conversion_fails(
    tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "tools" / "fail_oda.py"
    script.parent.mkdir(parents=True)
    script.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    inp = tmp_path / "input"
    write(inp / "plan.dwg", dwg_bytes())
    monkeypatch.setenv("ALE_ODA_PATH", str(script))
    ingest(tmp_workspace, inp)
    _map_layers(invoke, tmp_workspace)
    result = invoke(["extract", *_ws_args(tmp_workspace)])
    assert result.exit_code == 0, result.output
    status, reason = unit_of(tmp_workspace, "plan.dwg")[3:]
    assert status == "FAILED"
    assert reason is not None and reason.startswith("DWG conversion failed: ")


# ---------------------------------------------------------------------- W06


def test_W06_idempotent(tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke) -> None:
    from cad_helpers import new_doc

    inp = tmp_path / "input"
    save_doc(plan_doc(copies=2, labels=True), inp / "a.dxf")
    save_doc(new_doc(), inp / "empty.dxf")
    ingest(tmp_workspace, inp)
    _map_layers(invoke, tmp_workspace)
    assert invoke(["extract", *_ws_args(tmp_workspace)]).exit_code == 0
    extracted = tmp_workspace.path("extracted")
    first = mtimes(extracted)
    first_bytes = {k: (extracted / k).read_bytes() for k in first}
    assert len(first) == 2
    n_events = event_count(tmp_workspace)

    # Second --only-new run: nothing touched.
    result = invoke(["extract", *_ws_args(tmp_workspace), "--only-new"])
    assert result.exit_code == 0, result.output
    assert "unités sélectionnées : 0" in result.stdout
    assert mtimes(extracted) == first
    assert event_count(tmp_workspace) == n_events

    # Without the flag: only the FAILED unit is retried.
    result = invoke(["extract", *_ws_args(tmp_workspace)])
    assert result.exit_code == 0, result.output
    assert "unités sélectionnées : 1" in result.stdout
    assert event_count(tmp_workspace, "extract_failed") == 2
    assert event_count(tmp_workspace, "extracted") == 1
    assert mtimes(extracted) == first

    # Re-extracting the same unit gives identical bytes and rewrites nothing.
    sha = unit_of(tmp_workspace, "a.dxf")[0]
    execute(tmp_workspace, "UPDATE units SET status = 'NEW' WHERE sha256 = ?", (sha,))
    assert invoke(["extract", *_ws_args(tmp_workspace), "--only-new"]).exit_code == 0
    assert mtimes(extracted) == first
    assert {k: (extracted / k).read_bytes() for k in first} == first_bytes


def test_W06_same_bytes_other_workspace(
    tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke, make_ws2: Workspace
) -> None:
    inp = tmp_path / "input"
    save_doc(plan_doc(copies=2, labels=True), inp / "a.dxf")
    for ws in (tmp_workspace, make_ws2):
        ingest(ws, inp)
        _map_layers(invoke, ws)
        assert invoke(["extract", *_ws_args(ws)]).exit_code == 0
    a, b = tmp_workspace.path("extracted"), make_ws2.path("extracted")
    files = sorted(p.relative_to(a).as_posix() for p in a.rglob("plan.json"))
    assert files == sorted(p.relative_to(b).as_posix() for p in b.rglob("plan.json"))
    assert len(files) == 2
    for rel in files:
        assert (a / rel).read_bytes() == (b / rel).read_bytes()


@pytest.fixture
def make_ws2(tmp_path: Path, invoke: Invoke) -> Workspace:
    from ale.workspace import open_workspace

    root = tmp_path / "ws2"
    assert invoke(["init", "--workspace", str(root)]).exit_code == 0
    return open_workspace(root)


def test_W06_stale_plans_removed(tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke) -> None:
    inp = tmp_path / "input"
    save_doc(plan_doc(), inp / "a.dxf")
    ingest(tmp_workspace, inp)
    _map_layers(invoke, tmp_workspace)
    sha = unit_of(tmp_workspace, "a.dxf")[0]
    stale = plan_path(tmp_workspace, sha, 0, 1)
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"{}\n")
    assert invoke(["extract", *_ws_args(tmp_workspace)]).exit_code == 0
    assert not stale.parent.exists()
    assert plan_path(tmp_workspace, sha, 0, 0).is_file()


# ---------------------------------------------------------------------- W07


def test_W07_other_kinds(tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke) -> None:
    pytest.importorskip("pymupdf")
    inp = tmp_path / "input"
    write(inp / "p.pdf", pdf_one_page())
    write(inp / "r.png", png_bytes())
    ingest(tmp_workspace, inp)
    _map_layers(invoke, tmp_workspace)
    before = query(tmp_workspace, "SELECT sha256, page, kind, status, reason FROM units")
    assert {r[3] for r in before} == {"NEW"}
    n_events = event_count(tmp_workspace)

    result = invoke(["extract", *_ws_args(tmp_workspace)])
    assert result.exit_code == 0, result.output
    assert "non implémentées (PDF / raster) : 2" in result.stdout
    result = invoke(["extract", *_ws_args(tmp_workspace), "--kind", "pdf"])
    assert result.exit_code == 0, result.output
    assert "non implémentées (PDF / raster) : 1" in result.stdout
    result = invoke(["extract", *_ws_args(tmp_workspace), "--kind", "raster", "--only-new"])
    assert "non implémentées (PDF / raster) : 1" in result.stdout

    assert query(tmp_workspace, "SELECT sha256, page, kind, status, reason FROM units") == before
    assert event_count(tmp_workspace) == n_events
    assert not any(tmp_workspace.path("extracted").iterdir())


# ---------------------------------------------------------------------- W08


def test_W08_meta_units(tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke) -> None:
    inp = tmp_path / "input"
    save_doc(plan_doc(insunits=None, scale=0.1), inp / "cm.dxf")
    save_doc(plan_doc(insunits=None, scale=0.1, extra_layers=("X",)), inp / "page.dxf")
    save_doc(plan_doc(insunits=None, scale=0.1, extra_layers=("Y",)), inp / "none.dxf")
    meta = write(
        tmp_path / "plans_meta.csv",
        b"filename,page,units\ncm.dxf,,cm\npage.dxf,0,CM\n",
    )
    ingest(tmp_workspace, inp, meta=meta)
    _map_layers(invoke, tmp_workspace)
    result = invoke(["extract", *_ws_args(tmp_workspace)])
    assert result.exit_code == 0, result.output
    for rel in ("cm.dxf", "page.dxf"):
        sha = unit_of(tmp_workspace, rel)[0]
        plan = _load_plan(plan_path(tmp_workspace, sha, 0, 0))
        assert plan.scale_m_per_unit == pytest.approx(0.01)
        assert plan.units_label == "cm"
        assert len(plan.rooms) == GT_ROOMS
    # Same drawing without the metadata: units unknown, millimetre thresholds, no plan.
    assert unit_of(tmp_workspace, "none.dxf")[3:] == ("FAILED", "no plan found")
