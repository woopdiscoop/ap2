"""Ticket 0.1 eval section 5: portability, encoding, logging (P01, P03-P05).

P02 lives in tests/test_no_absolute_paths.py.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

import pytest
import yaml

from ale.config import load_config, resolve_config_path
from ale.logging_setup import (
    JsonLineFormatter,
    attach_workspace_log,
    configure_logging,
    shutdown_logging,
)
from ale.paths import display, normalise, relativise, resolve_against

REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_NAME = re.compile(r"^ale-\d{8}\.log$")


def test_P01_cp1252_console(run_ale, tmp_path: Path) -> None:
    target = tmp_path / "Réf Łódź"
    proc = run_ale(["init", "--workspace", str(target)], PYTHONIOENCODING="cp1252")
    stderr = proc.stderr.decode("cp1252", errors="replace")
    assert proc.returncode == 0, stderr
    assert "Traceback" not in stderr
    assert "UnicodeEncodeError" not in stderr
    stdout = proc.stdout.decode("cp1252", errors="replace")
    assert "workspace created" in stdout
    assert "?" in stdout  # 'Ł' replaced, not crashed
    assert (target / "ale.toml").is_file()


def test_P01_cp1252_console_status_message(run_ale, tmp_path: Path) -> None:
    """Status output must not crash on a cp1252 console with a Unicode workspace."""
    target = tmp_path / "Łódź ws"
    assert run_ale(["init", "--workspace", str(target)]).returncode == 0
    proc = run_ale(["status", "--workspace", str(target)], PYTHONIOENCODING="cp1252")
    assert proc.returncode == 0
    stderr = proc.stderr.decode("cp1252", errors="replace")
    assert "Traceback" not in stderr
    assert "UnicodeEncodeError" not in stderr
    assert "TOTAL" in proc.stdout.decode("cp1252", errors="replace")


def test_P03_utf8_io(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    text = '# Références\n[tools]\n# été\noda_file_converter = "Outils/ODA été.exe"\n'
    (ws / "ale.toml").write_bytes(text.encode("utf-8"))
    cfg = load_config(ws / "ale.toml")
    assert cfg.tools.oda_file_converter == "Outils/ODA été.exe"
    assert resolve_config_path(ws, cfg.tools.oda_file_converter) == ws / "Outils" / "ODA été.exe"
    # A UTF-8 BOM (Windows Notepad) is tolerated.
    (ws / "ale.toml").write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    assert load_config(ws / "ale.toml") == cfg


def test_P04_log_file(invoke, make_ws, ap: Path, doctor_env: Path) -> None:
    make_ws(ap)
    result = invoke(["doctor", "--workspace", str(ap)])
    assert result.exit_code == 0, result.output
    logs = [p for p in (ap / "logs").iterdir() if LOG_NAME.match(p.name)]
    assert len(logs) == 1
    raw = logs[0].read_bytes()
    assert b"\r\n" not in raw
    lines = raw.decode("utf-8").splitlines()
    assert lines
    for line in lines:
        record = json.loads(line)
        assert {"ts", "level", "logger", "event", "msg"} <= set(record)
        assert record["logger"].startswith("ale")
        assert record["ts"].endswith("Z")
    assert any(json.loads(line)["event"] == "doctor.check" for line in lines)


def test_P04_log_file_formatter_and_levels(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("WARNING")
    assert attach_workspace_log(tmp_path / "missing") is None
    path = attach_workspace_log(tmp_path)
    assert path is not None
    log = logging.getLogger("ale.test")
    log.info("hidden on console", extra={"event": "t.info", "count": 3, "where": tmp_path})
    try:
        raise ValueError("boom é")
    except ValueError:
        log.exception("failed")
    shutdown_logging()
    records = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["event"] == "t.info"
    assert records[0]["count"] == 3
    assert records[0]["where"] == str(tmp_path)
    assert records[1]["event"] == "log"
    assert "boom é" in records[1]["exc"]
    err = capsys.readouterr().err
    assert "hidden on console" not in err
    assert "failed" in err
    formatted = JsonLineFormatter().format(logging.makeLogRecord({"msg": "x", "name": "ale"}))
    assert json.loads(formatted)["msg"] == "x"


def test_P04_log_level_from_config(invoke, make_ws, tmp_path: Path, doctor_env: Path) -> None:
    ws = make_ws(tmp_path / "ws")
    text = (
        (ws / "ale.toml").read_text(encoding="utf-8").replace('level = "INFO"', 'level = "DEBUG"')
    )
    (ws / "ale.toml").write_text(text, encoding="utf-8")
    result = invoke(["doctor", "--workspace", str(ws)])
    assert "doctor.check" not in result.stderr  # console is human-readable
    assert "DEBUG ale.doctor: python: ok" in result.stderr
    # An explicit --log-level wins over [logging].level.
    result = invoke(["--log-level", "ERROR", "doctor", "--workspace", str(ws)])
    assert "DEBUG" not in result.stderr


def test_P05_ci_matrix() -> None:
    data = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    triggers = data.get("on", data.get(True))  # YAML 1.1 parses `on` as True
    assert "push" in triggers
    assert "pull_request" in triggers
    jobs = list(data["jobs"].values())
    assert len(jobs) == 1
    job = jobs[0]
    matrix = job["strategy"]["matrix"]
    assert sorted(matrix["os"]) == sorted(["windows-latest", "macos-latest", "ubuntu-latest"])
    assert [str(v) for v in matrix["python"]] == ["3.11", "3.12", "3.13"]
    assert "matrix.os" in job["runs-on"]
    runs = [step.get("run", "") for step in job["steps"]]
    expected = [
        'pip install -e ".[dev,excel,cad,pdf,raster,vlm,ui]"',
        "ruff check .",
        "ruff format --check .",
        "mypy",
        "pytest --cov=ale --cov-report=term",
    ]
    positions = []
    for command in expected:
        hits = [i for i, run in enumerate(runs) if command in run.splitlines()]
        assert hits, f"missing CI step: {command}"
        positions.append(hits[0])
    assert positions == sorted(positions)
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    assert "secrets." not in text


def test_P03_utf8_io_path_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RD 0.1 section 10 helpers (support for P01/P03/C06)."""
    nfd = "Re\u0301fe\u0301rences"
    assert display(Path(nfd) / "Plans 2024") == str(Path("Références") / "Plans 2024")
    assert relativise(tmp_path / "a" / "b é", tmp_path) == "a/b é"
    assert relativise(Path("elsewhere"), tmp_path) == "elsewhere"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert normalise("~/ws ä") == tmp_path / "ws ä"
    assert resolve_against(tmp_path / "ws", "~/tool.exe") == tmp_path / "tool.exe"
    absolute = (tmp_path / "abs.exe").resolve()
    assert resolve_against(tmp_path / "ws", str(absolute)) == absolute
    if sys.platform == "win32":
        assert resolve_against(tmp_path, "D:\\x\\y.exe") == Path("D:/x/y.exe")
        assert resolve_against(tmp_path, "D:/x/y.exe") == Path("D:\\x\\y.exe")
