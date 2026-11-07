"""Ticket 0.4 eval section 2: ``ale.proc`` (P01-P11) plus edge cases.

Every tool is ``sys.executable -c "<code>"`` so the tests run anywhere.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import ale.proc
from ale.proc import OUTPUT_LIMIT_BYTES, TRUNCATED_MARKER, ProcessReport, run_tool

PY = sys.executable
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only (Windows twin)")
SKIP_UNLESS_WINDOWS = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows-only twin of a POSIX test"
)

# Child prologue: UTF-8 stdout/stderr whatever the console code page.
UTF8 = (
    "import sys; sys.stdout.reconfigure(encoding='utf-8'); "
    "sys.stderr.reconfigure(encoding='utf-8'); "
)


def py(code: str, *args: str) -> list[str]:
    return [PY, "-c", code, *args]


def pid_alive(pid: int) -> bool:
    """Whether ``pid`` is a live (non-zombie) process."""
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    stat = Path(f"/proc/{pid}/stat")
    try:  # Linux: a zombie is dead (its parent may be a non-reaping container init)
        return stat.read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def wait_dead(pid: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.05)
    return not pid_alive(pid)


def force_kill(pid: int) -> None:
    if not pid_alive(pid):
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, check=False)
    else:
        import signal

        os.kill(pid, signal.SIGKILL)


def read_pid(path: Path) -> int:
    assert path.is_file(), "the child did not write its PID file before the timeout"
    return int(path.read_text(encoding="utf-8"))


WRITE_PID = (
    "def write_pid(path, pid):\n"
    "    import os\n"
    "    with open(path + '.tmp', 'w', encoding='utf-8') as f:\n"
    "        f.write(str(pid))\n"
    "    os.replace(path + '.tmp', path)\n"
)

GRANDCHILD = (
    WRITE_PID + "import subprocess, sys, time\n"
    "gc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "write_pid(sys.argv[1], gc.pid)\n"
    "time.sleep(60)\n"
)


def test_P01_success_unicode() -> None:
    report = run_tool(
        py(UTF8 + "print('é Ł 中'); sys.stderr.write('warn')"),
        timeout_s=30,
    )
    assert report.ok
    assert report.returncode == 0
    assert report.stdout == "é Ł 中\n"
    assert report.stderr == "warn"
    assert not report.timed_out
    assert not report.killed
    assert report.error is None


def test_P02_nonzero() -> None:
    report = run_tool(py("import sys; sys.exit(3)"), timeout_s=30)
    assert report.returncode == 3
    assert report.ok is False
    assert not report.timed_out
    assert report.error is None


def test_P03_timeout() -> None:
    report = run_tool(py("import time; time.sleep(60)"), timeout_s=0.5, kill_grace_s=0.5)
    assert report.timed_out
    assert report.killed
    assert report.returncode is None
    assert report.ok is False
    assert report.duration_s < 2.5


def _check_tree_kill(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    report = run_tool(py(GRANDCHILD, str(pid_file)), timeout_s=2.0, kill_grace_s=0.5)
    assert report.timed_out
    assert report.killed
    grandchild = read_pid(pid_file)
    try:
        assert wait_dead(grandchild, 3.0), f"grandchild {grandchild} survived the tree kill"
    finally:
        force_kill(grandchild)


@POSIX_ONLY
def test_P04_tree_kill(tmp_path: Path) -> None:
    _check_tree_kill(tmp_path)


@pytest.mark.windows_only
@SKIP_UNLESS_WINDOWS
def test_P04_tree_kill_windows(tmp_path: Path) -> None:
    _check_tree_kill(tmp_path)


@POSIX_ONLY
def test_P05_sigterm_ignored(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    code = (
        WRITE_PID + "import os, signal, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "write_pid(sys.argv[1], os.getpid())\n"
        "time.sleep(60)\n"
    )
    timeout_s, grace_s = 1.0, 0.5
    t0 = time.monotonic()
    report = run_tool(py(code, str(pid_file)), timeout_s=timeout_s, kill_grace_s=grace_s)
    child = read_pid(pid_file)
    try:
        remaining = t0 + timeout_s + grace_s + 1.0 - time.monotonic()
        assert wait_dead(child, max(remaining, 0.0)), "child ignoring SIGTERM survived"
    finally:
        force_kill(child)
    assert report.timed_out
    assert report.killed
    assert report.duration_s >= timeout_s + grace_s - 0.1  # SIGTERM ignored: grace elapsed


@pytest.mark.windows_only
@SKIP_UNLESS_WINDOWS
def test_P05_sigterm_ignored_windows(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    code = (
        WRITE_PID + "import os, signal, sys, time\n"
        "for name in ('SIGINT', 'SIGBREAK', 'SIGTERM'):\n"
        "    if hasattr(signal, name):\n"
        "        signal.signal(getattr(signal, name), signal.SIG_IGN)\n"
        "write_pid(sys.argv[1], os.getpid())\n"
        "time.sleep(60)\n"
    )
    timeout_s, grace_s = 1.0, 0.5
    t0 = time.monotonic()
    report = run_tool(py(code, str(pid_file)), timeout_s=timeout_s, kill_grace_s=grace_s)
    child = read_pid(pid_file)
    try:
        remaining = t0 + timeout_s + grace_s + 1.0 - time.monotonic()
        assert wait_dead(child, max(remaining, 0.0)), "child ignoring signals survived"
    finally:
        force_kill(child)
    assert report.timed_out
    assert report.killed


def test_P06_missing_exe() -> None:
    report = run_tool(["definitely-not-a-tool-xyz"], timeout_s=5)
    assert report.returncode is None
    assert report.error is not None
    assert report.error.startswith("executable not found")
    assert "definitely-not-a-tool-xyz" in report.error
    assert report.ok is False
    assert not report.timed_out
    assert not report.killed


def test_P07_no_shell() -> None:
    report = run_tool(
        [PY, "-c", "import sys; print(sys.argv[1])", "; echo HACKED"],
        timeout_s=30,
    )
    assert report.ok
    assert report.stdout == "; echo HACKED\n"


BIG = (
    "import sys\n"
    "n = 3 * 1024 * 1024\n"
    "sys.stdout.buffer.write(b'o' * (n - 3) + b'END'); sys.stdout.buffer.flush()\n"
    "sys.stderr.buffer.write(b'e' * (n - 3) + b'FIN'); sys.stderr.buffer.flush()\n"
)


def test_P08_big_output() -> None:
    t0 = time.monotonic()
    report = run_tool(py(BIG), timeout_s=10)
    assert time.monotonic() - t0 < 10
    assert report.ok
    assert not report.timed_out
    for stream, tail in ((report.stdout, "END"), (report.stderr, "FIN")):
        assert stream.startswith("…[truncated]")
        assert stream.startswith(TRUNCATED_MARKER)
        assert len(stream) <= OUTPUT_LIMIT_BYTES + len(TRUNCATED_MARKER)
        assert len(stream) == OUTPUT_LIMIT_BYTES + len(TRUNCATED_MARKER)
        assert stream.endswith(tail)


def test_P08_truncation_between_one_and_two_mib() -> None:
    code = "import sys; sys.stdout.buffer.write(b'a' * (3 * 512 * 1024))"
    report = run_tool(py(code), timeout_s=10)
    assert report.ok
    assert report.stdout == TRUNCATED_MARKER + "a" * OUTPUT_LIMIT_BYTES


def test_P08_truncation_respects_utf8_boundaries() -> None:
    # 2-byte characters plus one trailing ASCII byte: the cut lands inside a character.
    code = "import sys; sys.stdout.buffer.write(('é' * (1024 * 1024) + 'x').encode('utf-8'))"
    report = run_tool(py(code), timeout_s=10)
    assert report.ok
    assert report.stdout.startswith(TRUNCATED_MARKER)
    body = report.stdout[len(TRUNCATED_MARKER) :]
    assert "\ufffd" not in body
    assert body == "é" * ((OUTPUT_LIMIT_BYTES - 1) // 2) + "x"


def test_P08_small_output_not_truncated() -> None:
    report = run_tool(py("import sys; sys.stdout.write('a' * 1000)"), timeout_s=10)
    assert report.stdout == "a" * 1000


def test_P09_env_merge() -> None:
    code = "import os; print(os.environ.get('ALE_X')); print(os.environ.get('PATH'))"
    report = run_tool(py(code), timeout_s=30, env={"ALE_X": "1"})
    assert report.ok
    lines = report.stdout.splitlines()
    assert lines[0] == "1"
    assert lines[1] == os.environ["PATH"]


def test_P09_env_none_inherits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALE_INHERITED", "yes")
    report = run_tool(py("import os; print(os.environ['ALE_INHERITED'])"), timeout_s=30)
    assert report.stdout == "yes\n"


def test_P10_input_text() -> None:
    report = run_tool(
        py("import sys; sys.stdout.write(sys.stdin.read())"), timeout_s=30, input_text="abc"
    )
    assert report.ok
    assert report.stdout == "abc"


def test_P10_input_text_child_ignores_stdin() -> None:
    # The child exits without reading 8 MiB of input: a broken pipe must not raise.
    report = run_tool(py("pass"), timeout_s=30, input_text="z" * (8 * 1024 * 1024))
    assert report.returncode == 0


@pytest.mark.parametrize(
    ("argv", "kwargs"),
    [
        pytest.param([PY, "-c", "pass"], {"timeout_s": 0}, id="timeout_s=0"),
        pytest.param([], {"timeout_s": 5}, id="argv=[]"),
        pytest.param([PY, "-c", "pass"], {"timeout_s": -1}, id="timeout_s=-1"),
        pytest.param([PY, "-c", "pass"], {"timeout_s": float("nan")}, id="timeout_s=nan"),
        pytest.param([PY, "-c", "pass"], {"timeout_s": True}, id="timeout_s=True"),
        pytest.param([PY, "-c", "pass"], {"timeout_s": 5, "kill_grace_s": -1}, id="grace=-1"),
    ],
)
def test_P11_bad_args(argv: list[str], kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        run_tool(argv, **kwargs)


def test_cwd_and_pathlike_argv(tmp_path: Path) -> None:
    work = tmp_path / "dossier é"
    work.mkdir()
    script = work / "s.py"
    script.write_text("import os; print(os.getcwd())", encoding="utf-8")
    # UTF-8 child output: on Windows a pipe would otherwise get the ANSI code page.
    report = run_tool([Path(PY), script], timeout_s=30, cwd=work, env={"PYTHONUTF8": "1"})
    assert report.ok
    assert Path(report.stdout.strip()).resolve() == work.resolve()
    assert report.cwd == str(work)
    assert report.argv == (PY, str(script))


def test_missing_cwd(tmp_path: Path) -> None:
    report = run_tool(py("pass"), timeout_s=5, cwd=tmp_path / "nope")
    assert report.returncode is None
    assert report.error is not None
    assert report.error.startswith("working directory not found")
    assert report.cwd == str(tmp_path / "nope")


@POSIX_ONLY
def test_permission_denied(tmp_path: Path) -> None:
    tool = tmp_path / "tool.sh"
    tool.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    tool.chmod(0o644)  # no execute bit: EACCES even for root
    report = run_tool([tool], timeout_s=5)
    assert report.returncode is None
    assert report.error is not None
    assert report.error.startswith("permission denied")


def test_other_start_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise OSError(errno.E2BIG, "Argument list too long")

    monkeypatch.setattr(ale.proc.subprocess, "Popen", boom)
    report = run_tool(["some-tool"], timeout_s=5)
    assert report.returncode is None
    assert report.error is not None
    assert report.error.startswith("could not start some-tool")


def test_report_json_and_ok() -> None:
    report = run_tool(py(UTF8 + "print('é')"), timeout_s=30)
    data = report.to_report()
    text = json.dumps(data, ensure_ascii=False)
    assert json.loads(text) == data
    assert data["ok"] is True
    assert data["argv"] == list(report.argv)
    assert data["returncode"] == 0
    assert isinstance(data["duration_s"], float)
    assert set(data) == {
        "argv",
        "cwd",
        "returncode",
        "timed_out",
        "killed",
        "duration_s",
        "ok",
        "stdout",
        "stderr",
        "error",
    }
    failed = ProcessReport(("x",), None, None, False, False, 0.0, "", "", "executable not found: x")
    assert failed.ok is False
    json.dumps(failed.to_report())


@pytest.fixture
def proc_caplog(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> Any:
    # The CLI's configure_logging() may have set propagate=False on the `ale` logger.
    monkeypatch.setattr(logging.getLogger("ale"), "propagate", True)
    caplog.set_level(logging.DEBUG, logger="ale.proc")
    return caplog


def test_logging_one_info_line(proc_caplog: pytest.LogCaptureFixture) -> None:
    run_tool(py("import sys; sys.exit(2)"), timeout_s=30)
    records = [r for r in proc_caplog.records if r.name == "ale.proc"]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    message = records[0].getMessage()
    assert Path(PY).name in message
    assert "returncode=2" in message
    assert "timed_out=False" in message


def test_logging_not_started(proc_caplog: pytest.LogCaptureFixture) -> None:
    run_tool(["definitely-not-a-tool-xyz"], timeout_s=5)
    records = [r for r in proc_caplog.records if r.name == "ale.proc"]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert "definitely-not-a-tool-xyz" in records[0].getMessage()
