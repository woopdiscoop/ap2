"""D11: DWG → DXF conversion with fake converters (no real ODA / AutoCAD)."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest
from cad_helpers import SHA, add_plan_pairs, layer_map_for, new_doc, save

from ale.cad import convert_dwg, read_cad
from ale.cad.convert import file_sha256
from ale.contracts.config import AleConfig, ToolsConfig
from ale.contracts.enums import SourceKind

NO_TOOLS_ENV: dict[str, str] = {"PATH": ""}

FAKE_ODA = """\
import shutil, sys, time
from pathlib import Path
log = Path({log!r})
with log.open("a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")
mode = {mode!r}
if mode == "sleep":
    time.sleep(30)
in_dir, out_dir, version, kind, recurse, audit, name = sys.argv[1:8]
assert (Path(in_dir) / name).is_file()
if mode == "copy":
    shutil.copyfile({prepared!r}, Path(out_dir) / (Path(name).stem + ".dxf"))
if mode == "fail":
    sys.stderr.write("conversion error")
    sys.exit(3)
"""

FAKE_ACCORE = """\
import shutil, sys
from pathlib import Path
args = sys.argv[1:]
script = Path(args[args.index("/s") + 1]).read_text(encoding="utf-8").splitlines()
assert script[2] == "-DXFOUT"
out = Path(script[3].strip('"'))
shutil.copyfile({prepared!r}, out)
"""


@pytest.fixture
def prepared(tmp_path: Path) -> Path:
    doc = new_doc()
    add_plan_pairs(doc.modelspace())
    return save(doc, tmp_path / "prepared.dxf")


@pytest.fixture
def dwg(tmp_path: Path) -> Path:
    path = tmp_path / "plan é.dwg"
    path.write_bytes(b"AC1032" + bytes(range(256)) * 4)
    return path


def _fake(tmp_path: Path, prepared: Path, mode: str) -> tuple[Path, Path]:
    log = tmp_path / f"oda-{mode}.log"
    script = tmp_path / f"fake_oda_{mode}.py"
    script.write_text(
        FAKE_ODA.format(log=str(log), mode=mode, prepared=str(prepared)), encoding="utf-8"
    )
    return script, log


def _runs(log: Path) -> int:
    return len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0


def test_D11_dwg_convert(tmp_path: Path, prepared: Path, dwg: Path) -> None:
    before = hashlib.sha256(dwg.read_bytes()).hexdigest()
    script, log = _fake(tmp_path, prepared, "copy")
    config = AleConfig(tools=ToolsConfig(oda_file_converter=str(script)))
    cache = tmp_path / "cache é"
    first = convert_dwg(dwg, cache, config, environ=NO_TOOLS_ENV)
    assert first.status == "OK", first.message
    assert first.ok and not first.cached
    assert first.dxf_path == cache / f"{before}.dxf"
    assert first.dxf_path.read_bytes() == prepared.read_bytes()
    assert first.tool == "ODA File Converter"
    assert _runs(log) == 1
    args = log.read_text(encoding="utf-8").split()
    assert args[2:7] == ["ACAD2018", "DXF", "0", "1", f"{before}.dwg"]
    second = convert_dwg(dwg, cache, config, environ=NO_TOOLS_ENV)
    assert second.status == "OK" and second.cached
    assert second.dxf_path == first.dxf_path
    assert _runs(log) == 1  # the tool did not run again
    assert hashlib.sha256(dwg.read_bytes()).hexdigest() == before
    # the converted DXF reads as a DWG-sourced plan
    res = read_cad(
        first.dxf_path,
        source_sha256=SHA,
        layer_map=layer_map_for(new_doc(), ["MUR"]),
        config=config,
        source_kind=SourceKind.DWG,
    )
    assert res.plans and res.plans[0].source_kind is SourceKind.DWG


def test_D11_dwg_convert_needs_tool(tmp_path: Path, dwg: Path) -> None:
    res = convert_dwg(dwg, tmp_path / "cache", AleConfig(), environ=NO_TOOLS_ENV)
    assert res.status == "NEEDS_TOOL"
    assert res.dxf_path is None
    assert "ODA File Converter" in res.message
    missing = AleConfig(tools=ToolsConfig(oda_file_converter=str(tmp_path / "nope.exe")))
    res2 = convert_dwg(dwg, tmp_path / "cache", missing, environ=NO_TOOLS_ENV)
    assert res2.status == "NEEDS_TOOL"
    assert "configured path not found" in res2.message


def test_D11_dwg_convert_timeout(tmp_path: Path, prepared: Path, dwg: Path) -> None:
    before = file_sha256(dwg)
    script, _log = _fake(tmp_path, prepared, "sleep")
    config = AleConfig(tools=ToolsConfig(oda_file_converter=str(script), timeout_s=1.0))
    t0 = time.monotonic()
    res = convert_dwg(dwg, tmp_path / "cache", config, environ=NO_TOOLS_ENV)
    assert time.monotonic() - t0 < 15.0
    assert res.status == "FAILED"
    assert "timed out" in res.message
    assert res.process is not None and res.process["timed_out"] is True
    assert not (tmp_path / "cache" / f"{before}.dxf").exists()
    assert file_sha256(dwg) == before


def test_D11_dwg_convert_failures(tmp_path: Path, prepared: Path, dwg: Path) -> None:
    for mode, text in (("fail", "exit code 3"), ("nothing", "no DXF produced")):
        script, _log = _fake(tmp_path, prepared, mode)
        config = AleConfig(tools=ToolsConfig(oda_file_converter=str(script)))
        res = convert_dwg(dwg, tmp_path / "cache", config, environ=NO_TOOLS_ENV)
        assert res.status == "FAILED"
        assert text in res.message
    gone = convert_dwg(tmp_path / "absent.dwg", tmp_path / "cache", AleConfig())
    assert gone.status == "FAILED" and gone.source_sha256 is None
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x", encoding="utf-8")
    res = convert_dwg(dwg, blocker / "cache", AleConfig(), environ=NO_TOOLS_ENV)
    assert res.status == "FAILED" and "cannot create cache" in res.message


def test_D11_dwg_convert_accoreconsole_fallback(tmp_path: Path, prepared: Path, dwg: Path) -> None:
    script = tmp_path / "fake_accore.py"
    script.write_text(FAKE_ACCORE.format(prepared=str(prepared)), encoding="utf-8")
    config = AleConfig(tools=ToolsConfig(accoreconsole=str(script)))
    res = convert_dwg(dwg, tmp_path / "cache", config, environ=NO_TOOLS_ENV)
    assert res.status == "OK", res.message
    assert res.tool == "AutoCAD accoreconsole"
    assert res.dxf_path is not None and res.dxf_path.read_bytes() == prepared.read_bytes()


def test_D11_relative_tool_path(tmp_path: Path, prepared: Path, dwg: Path) -> None:
    script, _log = _fake(tmp_path, prepared, "copy")
    config = AleConfig(tools=ToolsConfig(oda_file_converter=script.name))
    res = convert_dwg(
        dwg, tmp_path / "cache", config, workspace_root=tmp_path, environ=NO_TOOLS_ENV
    )
    assert res.status == "OK", res.message
