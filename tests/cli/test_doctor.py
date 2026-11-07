"""Ticket 0.1 eval section 4: `ale doctor` (D01-D09).

Every test runs with PATH reduced to the interpreter folder and ProgramFiles pointed
at an empty tmp folder (fixture `doctor_env`).
"""

from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from ale.doctor import TOOLS, find_tool, newest_by_version

ODA_HINT = "install the free ODA File Converter and set [tools].oda_file_converter in ale.toml"
EXE_SUFFIX = ".exe" if sys.platform == "win32" else ""


def doctor_json(invoke, ws: Path) -> tuple[int, dict[str, Any]]:
    result = invoke(["doctor", "--json", "--workspace", str(ws)])
    return result.exit_code, json.loads(result.stdout)


def by_name(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["name"]: c for c in report["checks"]}


def set_config(ws: Path, old: str, new: str) -> None:
    path = ws / "ale.toml"
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def make_dummy_exe(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / name
    exe.write_bytes(b"#!/bin/sh\nexit 0\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return exe


# --- shared bodies (reused by D06 and D09) ------------------------------------------


def body_d01(invoke, make_ws, root: Path) -> None:
    ws = make_ws(root / "ws_d01")
    result = invoke(["doctor", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    assert ODA_HINT in result.stdout
    assert "[tools].accoreconsole" in result.stdout
    assert 'pip install "ale[cad]"' in result.stdout
    code, report = doctor_json(invoke, ws)
    assert code == 0
    checks = by_name(report)
    assert checks["python"]["status"] == "ok"
    assert checks["workspace"]["status"] == "ok"
    assert checks["ODA File Converter"]["status"] == "missing"
    assert ODA_HINT in checks["ODA File Converter"]["detail"]
    assert checks["AutoCAD accoreconsole"]["status"] == "missing"
    assert "install" in checks["AutoCAD accoreconsole"]["detail"]
    assert checks["VLM"]["status"] == "disabled"
    for name, check in checks.items():
        if name.startswith("extra "):
            assert check["required"] is False
            assert check["status"] in {"ok", "missing"}
            if check["status"] == "missing":
                assert check["detail"].startswith('pip install "ale[')


def body_d02(invoke, make_ws, root: Path) -> None:
    ws = make_ws(root / "ws_d02")
    code, report = doctor_json(invoke, ws)
    assert code == 0
    assert set(report) == {"checks", "ok"}
    assert report["ok"] is True
    assert isinstance(report["checks"], list) and report["checks"]
    for check in report["checks"]:
        assert set(check) == {"name", "status", "required", "detail"}
        assert isinstance(check["required"], bool)
    required = {c["name"] for c in report["checks"] if c["required"]}
    assert required == {"python", "workspace"}


def body_d03(invoke, make_ws, root: Path) -> None:
    ws = make_ws(root / "ws_d03")
    dummy = root / "tools d03" / "ODAFileConverter.exe"
    dummy.parent.mkdir(parents=True)
    dummy.write_bytes(b"")
    set_config(
        ws, 'oda_file_converter = ""', f"oda_file_converter = {json.dumps(dummy.as_posix())}"
    )
    _, report = doctor_json(invoke, ws)
    oda = by_name(report)["ODA File Converter"]
    assert oda["status"] == "found"
    assert Path(oda["detail"]) == dummy

    dummy.unlink()
    code, report = doctor_json(invoke, ws)
    assert code == 0
    oda = by_name(report)["ODA File Converter"]
    assert oda["status"] == "missing"
    assert "configured path not found" in oda["detail"]
    assert dummy.name in oda["detail"]


def body_d04(invoke, make_ws, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = make_ws(root / "ws_d04")
    env_exe = make_dummy_exe(root / "env tool", "ODAFileConverter" + EXE_SUFFIX)
    with monkeypatch.context() as m:
        m.setenv("ALE_ODA_PATH", str(env_exe))
        _, report = doctor_json(invoke, ws)
    oda = by_name(report)["ODA File Converter"]
    assert oda["status"] == "found"
    assert Path(oda["detail"]) == env_exe

    path_dir = root / "path tools"
    path_exe = make_dummy_exe(path_dir, "ODAFileConverter" + EXE_SUFFIX)
    acc_exe = make_dummy_exe(path_dir, "accoreconsole" + EXE_SUFFIX)
    with monkeypatch.context() as m:
        m.setenv("PATH", os.pathsep.join([str(path_dir), os.environ["PATH"]]))
        _, report = doctor_json(invoke, ws)
    checks = by_name(report)
    assert checks["ODA File Converter"]["status"] == "found"
    assert Path(checks["ODA File Converter"]["detail"]).name.lower() == path_exe.name.lower()
    assert checks["AutoCAD accoreconsole"]["status"] == "found"
    assert Path(checks["AutoCAD accoreconsole"]["detail"]).name.lower() == acc_exe.name.lower()


# --- tests ----------------------------------------------------------------------------


def test_D01_clean_machine(invoke, make_ws, tmp_path: Path, doctor_env: Path) -> None:
    body_d01(invoke, make_ws, tmp_path)


def test_D02_json_shape(invoke, make_ws, tmp_path: Path, doctor_env: Path) -> None:
    body_d02(invoke, make_ws, tmp_path)


def test_D03_configured_tool(invoke, make_ws, tmp_path: Path, doctor_env: Path) -> None:
    body_d03(invoke, make_ws, tmp_path)


def test_D04_env_and_path_detection(
    invoke, make_ws, tmp_path: Path, doctor_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body_d04(invoke, make_ws, tmp_path, monkeypatch)


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only (ProgramFiles glob)")
def test_D05_programfiles_glob(invoke, make_ws, tmp_path: Path, doctor_env: Path) -> None:
    ws = make_ws(tmp_path / "ws")
    old = make_dummy_exe(doctor_env / "ODA" / "ODAFileConverter 25.4.0", "ODAFileConverter.exe")
    new = make_dummy_exe(doctor_env / "ODA" / "ODAFileConverter 26.1.0", "ODAFileConverter.exe")
    _, report = doctor_json(invoke, ws)
    oda = by_name(report)["ODA File Converter"]
    assert oda["status"] == "found"
    assert Path(oda["detail"]) == new
    assert Path(oda["detail"]) != old


def test_D05_programfiles_glob_logic_any_os(tmp_path: Path) -> None:
    """Same rule as D05, exercised on every OS through `find_tool(is_windows=True)`."""
    pf = tmp_path / "Program Files"
    for version in ("25.4.0", "26.1.0", "9.9.9"):
        make_dummy_exe(pf / "ODA" / f"ODAFileConverter {version}", "ODAFileConverter.exe")
    make_dummy_exe(pf / "Autodesk" / "AutoCAD 2024", "accoreconsole.exe")
    make_dummy_exe(pf / "Autodesk" / "AutoCAD 2025", "accoreconsole.exe")
    env = {"PATH": str(tmp_path / "empty"), "ProgramFiles": str(pf)}
    oda, acc = TOOLS
    path, how = find_tool(oda, "", tmp_path, env, is_windows=True)
    assert how == "ProgramFiles"
    assert path == pf / "ODA" / "ODAFileConverter 26.1.0" / "ODAFileConverter.exe"
    path, _ = find_tool(acc, "", tmp_path, env, is_windows=True)
    assert path == pf / "Autodesk" / "AutoCAD 2025" / "accoreconsole.exe"
    # Not on Windows -> the glob is never consulted.
    assert find_tool(oda, "", tmp_path, env, is_windows=False) == (None, "not found")
    assert newest_by_version([]) is None


def test_D06_never_executes(
    invoke, make_ws, tmp_path: Path, doctor_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("ale doctor must not execute anything")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "call", forbidden)
    monkeypatch.setattr(subprocess, "check_output", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", forbidden)
    body_d01(invoke, make_ws, tmp_path)
    body_d02(invoke, make_ws, tmp_path)
    body_d03(invoke, make_ws, tmp_path)
    body_d04(invoke, make_ws, tmp_path, monkeypatch)


def test_D07_secret_hygiene(
    invoke, make_ws, tmp_path: Path, doctor_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-TEST-SECRET-123"
    ws = make_ws(tmp_path / "ws")
    set_config(ws, 'provider = ""', 'provider = "x"')
    monkeypatch.setenv("ALE_VLM_API_KEY", secret)
    outputs = []
    for args in (
        ["--log-level", "DEBUG", "doctor", "--workspace", str(ws)],
        ["--log-level", "DEBUG", "doctor", "--json", "--workspace", str(ws)],
    ):
        result = invoke(args)
        assert result.exit_code == 0, result.output
        outputs.append(result.stdout + result.stderr)
    report = json.loads(invoke(["doctor", "--json", "--workspace", str(ws)]).stdout)
    assert by_name(report)["VLM"]["status"] == "key present"
    for text in outputs:
        assert secret not in text
    logs = list((ws / "logs").glob("*.log"))
    assert logs
    for path in ws.rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes(), path

    monkeypatch.delenv("ALE_VLM_API_KEY")
    report = json.loads(invoke(["doctor", "--json", "--workspace", str(ws)]).stdout)
    vlm = by_name(report)["VLM"]
    assert vlm["status"] == "key missing"
    assert "ALE_VLM_API_KEY" in vlm["detail"]


def test_D08_broken_workspace(invoke, make_ws, tmp_path: Path, doctor_env: Path) -> None:
    ws = make_ws(tmp_path / "ws")
    (ws / "ale.toml").write_text("[grid]\nmodule_mm = 'big'\n", encoding="utf-8")
    result = invoke(["doctor", "--workspace", str(ws)])
    assert result.exit_code == 4
    assert result.stderr.startswith("ale.toml: grid.module_mm:")


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        ("missing_folder", "workspace folder not found"),
        ("missing_toml", "ale.toml not found"),
        ("missing_db", "corpus.sqlite not found"),
        ("not_sqlite", "cannot be opened"),
        ("no_meta_table", "table ale_meta is missing"),
    ],
)
def test_D08_broken_workspace_variants(
    invoke, make_ws, tmp_path: Path, doctor_env: Path, damage: str, message: str
) -> None:
    import sqlite3
    from contextlib import closing

    ws = make_ws(tmp_path / "ws")
    target = ws
    if damage == "missing_folder":
        target = tmp_path / "nowhere"
    elif damage == "missing_toml":
        (ws / "ale.toml").unlink()
    elif damage == "missing_db":
        (ws / "corpus.sqlite").unlink()
    elif damage == "not_sqlite":
        (ws / "corpus.sqlite").write_bytes(b"this is not a database" * 100)
    else:
        with closing(sqlite3.connect(ws / "corpus.sqlite")) as conn:
            conn.execute("DROP TABLE ale_meta")
            conn.commit()
    result = invoke(["doctor", "--workspace", str(target)])
    assert result.exit_code == 4
    assert message in result.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX chmod semantics only")
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores directory permissions"
)
def test_D08_broken_workspace_readonly_cache(
    invoke, make_ws, tmp_path: Path, doctor_env: Path
) -> None:
    ws = make_ws(tmp_path / "ws")
    cache = ws / "cache"
    cache.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        code, report = doctor_json(invoke, ws)
    finally:
        cache.chmod(stat.S_IRWXU)
    assert code == 1
    assert report["ok"] is False
    assert by_name(report)["workspace"]["status"] == "fail"


def test_D08_broken_workspace_unwritable_simulated(
    invoke, make_ws, tmp_path: Path, doctor_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same rule as the chmod variant, simulated so it also runs as root / on Windows."""
    ws = make_ws(tmp_path / "ws")
    real_mkstemp = tempfile.mkstemp

    def mkstemp(*args: Any, **kwargs: Any) -> tuple[int, str]:
        if Path(kwargs["dir"]) == ws / "cache":
            raise PermissionError(13, "Permission denied")
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(tempfile, "mkstemp", mkstemp)
    (ws / "rulebook").rmdir()
    code, report = doctor_json(invoke, ws)
    assert code == 1
    assert report["ok"] is False
    workspace = by_name(report)["workspace"]
    assert workspace["status"] == "fail"
    assert "cache not writable (Permission denied)" in workspace["detail"]
    assert "rulebook not writable (folder missing)" in workspace["detail"]
    human = invoke(["doctor", "--workspace", str(ws)])
    assert human.exit_code == 1
    assert "FAILED" in human.stdout


def test_D09_no_network(
    invoke, make_ws, tmp_path: Path, doctor_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    body_d01(invoke, make_ws, tmp_path)


def test_D01_clean_machine_extras_reported_when_importable(
    invoke, make_ws, tmp_path: Path, doctor_env: Path, show_extras
) -> None:
    """Companion of D01: an importable extra is reported ok (not required)."""
    show_extras()
    ws = make_ws(tmp_path / "ws")
    code, report = doctor_json(invoke, ws)
    assert code == 0
    extras = {n: c for n, c in by_name(report).items() if n.startswith("extra ")}
    assert len(extras) == 6
    assert all(c["status"] == "ok" and c["required"] is False for c in extras.values())
