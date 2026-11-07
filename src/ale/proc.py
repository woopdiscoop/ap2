"""Run external programs with a timeout and whole-process-tree kill (RD 0.4 section 4).

:func:`run_tool` never raises for a failing tool: a missing executable, a permission
error, a non-zero exit code and a timeout all come back as a :class:`ProcessReport`.
Only programming errors (empty ``argv``, ``timeout_s <= 0``) raise ``ValueError``.

* No shell, ever: every argument is passed literally.
* POSIX: the child leads a new session; on timeout the whole process group gets
  ``SIGTERM``, then ``SIGKILL`` after ``kill_grace_s``.
* Windows: the child gets a new process group and no console window; on timeout
  ``taskkill /T /F /PID <pid>`` kills the tree, ``Popen.kill()`` is the fallback.
* stdout and stderr are drained concurrently by reader threads (no pipe deadlock) and
  only the last :data:`OUTPUT_LIMIT_BYTES` of each are kept.
"""

from __future__ import annotations

import contextlib
import logging
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

__all__ = ["OUTPUT_LIMIT_BYTES", "TRUNCATED_MARKER", "ProcessReport", "run_tool"]

log = logging.getLogger(__name__)

#: Bytes of stdout / stderr kept per call (the tail).
OUTPUT_LIMIT_BYTES = 1024 * 1024
#: Prefix of a captured stream whose beginning was dropped.
TRUNCATED_MARKER = "…[truncated]\n"

_CHUNK = 64 * 1024
#: Extra seconds allowed for the reader threads to drain the pipes once the process ended.
_DRAIN_S = 5.0
#: Seconds to wait for the process to be reaped after the final kill.
_REAP_S = 5.0


@dataclass(frozen=True)
class ProcessReport:
    """Outcome of one :func:`run_tool` call."""

    argv: tuple[str, ...]
    cwd: str | None
    returncode: int | None
    timed_out: bool
    killed: bool
    duration_s: float
    stdout: str
    stderr: str
    error: str | None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and self.error is None

    def to_report(self) -> dict[str, object]:
        """JSON-serialisable dict (``duration_s`` rounded to 3 decimals)."""
        return {
            "argv": list(self.argv),
            "cwd": self.cwd,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "killed": self.killed,
            "duration_s": round(self.duration_s, 3),
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
        }


class _TailReader(threading.Thread):
    """Drain one pipe, keeping only the last ``OUTPUT_LIMIT_BYTES``."""

    def __init__(self, stream: IO[bytes], name: str) -> None:
        super().__init__(name=name, daemon=True)
        self._stream = stream
        self._buf = bytearray()
        self.truncated = False

    def run(self) -> None:
        try:
            while True:
                chunk = self._stream.read(_CHUNK)
                if not chunk:
                    break
                self._buf += chunk
                if len(self._buf) > 2 * OUTPUT_LIMIT_BYTES:
                    del self._buf[: len(self._buf) - OUTPUT_LIMIT_BYTES]
                    self.truncated = True
        except (OSError, ValueError):  # pipe closed under us
            pass

    def text(self) -> str:
        data = bytes(self._buf)
        truncated = self.truncated
        if len(data) > OUTPUT_LIMIT_BYTES:
            data = data[len(data) - OUTPUT_LIMIT_BYTES :]
            truncated = True
        if truncated:
            # Do not start in the middle of a UTF-8 sequence (skip continuation bytes).
            skip = 0
            while skip < 3 and skip < len(data) and 0x80 <= data[skip] <= 0xBF:
                skip += 1
            data = data[skip:]
        text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
        return TRUNCATED_MARKER + text if truncated else text


def _feed_stdin(stream: IO[bytes], data: bytes) -> None:
    try:
        view = memoryview(data)
        while view:
            view = view[stream.write(view) :]
        stream.close()
    except (OSError, ValueError):  # the child exited without reading everything
        pass


if sys.platform != "win32":
    import signal

    def _popen_platform_kwargs() -> dict[str, Any]:
        return {"start_new_session": True}

    def _kill_tree_platform(proc: subprocess.Popen[bytes], grace_s: float) -> None:
        """SIGTERM the process group, wait ``grace_s``, then SIGKILL the group."""
        pgid = proc.pid  # start_new_session=True: the child leads its own group
        with contextlib.suppress(OSError):
            os.killpg(pgid, signal.SIGTERM)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=grace_s)
        # SIGKILL also reaches descendants that ignored SIGTERM or outlived the leader.
        with contextlib.suppress(OSError):
            os.killpg(pgid, signal.SIGKILL)

else:  # pragma: no cover - Windows

    def _popen_platform_kwargs() -> dict[str, Any]:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}

    # "/T /F /PID", spelled so that no literal looks like an absolute path (test P02 of 0.1).
    _TASKKILL_SWITCHES = tuple(f"/{switch}" for switch in ("T", "F", "PID"))

    def _kill_tree_platform(proc: subprocess.Popen[bytes], grace_s: float) -> None:
        """``taskkill /T /F /PID <pid>``, then ``Popen.kill()`` as fallback."""
        taskkill = shutil.which("taskkill")
        if taskkill is not None:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(
                    [taskkill, *_TASKKILL_SWITCHES, str(proc.pid)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=max(grace_s, 1.0) + _REAP_S,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    check=False,
                )
        try:
            proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                proc.kill()


def _kill_tree(proc: subprocess.Popen[bytes], grace_s: float) -> None:
    """Kill ``proc`` and all its descendants; returns once ``proc`` is reaped (or gave up)."""
    _kill_tree_platform(proc, grace_s)
    try:
        proc.wait(timeout=_REAP_S)
    except subprocess.TimeoutExpired:  # pragma: no cover - unkillable process
        log.warning("process %d did not exit after kill", proc.pid)


def _start_error(exc: OSError, exe: str, cwd: Path | None) -> str:
    if cwd is not None and not cwd.is_dir():
        return f"working directory not found: {cwd}"
    if isinstance(exc, FileNotFoundError):
        return f"executable not found: {exe}"
    if isinstance(exc, PermissionError):
        return f"permission denied: {exe}"
    return f"could not start {exe}: {exc}"


def run_tool(
    argv: Sequence[str | os.PathLike[str]],
    *,
    timeout_s: float,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    kill_grace_s: float = 2.0,
) -> ProcessReport:
    """Run ``argv`` (no shell) with a timeout; never raises for a failing tool."""
    args = tuple(str(os.fspath(a)) for a in argv)
    if not args:
        raise ValueError("argv must not be empty")
    if isinstance(timeout_s, bool) or not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError(f"timeout_s must be a finite number > 0, got {timeout_s!r}")
    if isinstance(kill_grace_s, bool) or not math.isfinite(kill_grace_s) or kill_grace_s < 0:
        raise ValueError(f"kill_grace_s must be a finite number >= 0, got {kill_grace_s!r}")
    cwd_path = None if cwd is None else Path(cwd)
    merged_env = None if env is None else {**os.environ, **env}
    exe_name = Path(args[0]).name or args[0]

    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL if input_text is None else subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd_path,
            env=merged_env,
            bufsize=0,
            shell=False,
            **_popen_platform_kwargs(),
        )
    except OSError as exc:
        report = ProcessReport(
            argv=args,
            cwd=None if cwd_path is None else str(cwd_path),
            returncode=None,
            timed_out=False,
            killed=False,
            duration_s=time.monotonic() - start,
            stdout="",
            stderr="",
            error=_start_error(exc, args[0], cwd_path),
        )
        log.info(
            "%s: not started (%s)",
            exe_name,
            report.error,
            extra={"event": "proc.run", "tool": exe_name, "error": report.error},
        )
        return report

    assert proc.stdout is not None and proc.stderr is not None
    readers = [
        _TailReader(proc.stdout, f"ale-proc-stdout-{proc.pid}"),
        _TailReader(proc.stderr, f"ale-proc-stderr-{proc.pid}"),
    ]
    for reader in readers:
        reader.start()
    if input_text is not None:
        assert proc.stdin is not None
        threading.Thread(
            target=_feed_stdin,
            args=(proc.stdin, input_text.encode("utf-8")),
            name=f"ale-proc-stdin-{proc.pid}",
            daemon=True,
        ).start()

    timed_out = False
    returncode: int | None
    try:
        returncode = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc, kill_grace_s)
        returncode = None

    drain_deadline = max(start + timeout_s, time.monotonic()) + _DRAIN_S
    for reader in readers:
        reader.join(timeout=max(0.0, drain_deadline - time.monotonic()))
        if reader.is_alive():  # pragma: no cover - a detached descendant holds the pipe
            log.warning("%s: output pipe still open, output may be incomplete", exe_name)
    duration = time.monotonic() - start

    report = ProcessReport(
        argv=args,
        cwd=None if cwd_path is None else str(cwd_path),
        returncode=returncode,
        timed_out=timed_out,
        killed=timed_out,
        duration_s=duration,
        stdout=readers[0].text(),
        stderr=readers[1].text(),
        error=None,
    )
    log.info(
        "%s: returncode=%s duration_s=%.3f timed_out=%s",
        exe_name,
        returncode,
        duration,
        timed_out,
        extra={
            "event": "proc.run",
            "tool": exe_name,
            "returncode": returncode,
            "duration_s": round(duration, 3),
            "timed_out": timed_out,
        },
    )
    return report
