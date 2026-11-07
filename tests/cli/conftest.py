"""Fixtures for the Ticket 0.1 tests (CLI, workspace, config, doctor)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from ale.cli import app
from ale.logging_setup import shutdown_logging

ALE_ENV_VARS = ("ALE_WORKSPACE", "ALE_ODA_PATH", "ALE_ACCORECONSOLE_PATH", "ALE_VLM_API_KEY")

Invoke = Callable[..., Result]


def _make_runner() -> CliRunner:
    try:  # click < 8.2 needs mix_stderr=False to expose result.stderr separately
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in ALE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield
    shutdown_logging()


@pytest.fixture
def ap(tmp_path: Path) -> Path:
    """The awkward path: accents, spaces, non-ASCII."""
    return tmp_path / "Références" / "Plans 2024" / "ws ä"


@pytest.fixture
def invoke() -> Invoke:
    """Run the CLI in-process; unexpected exceptions are re-raised."""
    runner = _make_runner()

    def _invoke(args: Sequence[str], env: dict[str, str] | None = None) -> Result:
        result = runner.invoke(app, [str(a) for a in args], env=env)
        if result.exception is not None and not isinstance(result.exception, SystemExit):
            raise result.exception
        return result

    return _invoke


@pytest.fixture
def make_ws(invoke: Invoke) -> Callable[[Path], Path]:
    """Initialise a workspace at the given path through `ale init`."""

    def _make(path: Path) -> Path:
        result = invoke(["init", "--workspace", str(path)])
        assert result.exit_code == 0, result.output
        return path

    return _make


@pytest.fixture
def doctor_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """PATH reduced to the interpreter folder, ProgramFiles pointed at tmp."""
    program_files = tmp_path / "ProgramFiles"
    program_files.mkdir()
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent))
    monkeypatch.setenv("ProgramFiles", str(program_files))
    return program_files


def subprocess_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ALE_ENV_VARS}
    env.update(extra)
    return env


@pytest.fixture
def run_ale() -> Callable[..., subprocess.CompletedProcess[bytes]]:
    """Run `python -m ale ...` (or the `ale` console script) as a real subprocess."""

    def _run(
        args: Sequence[str], script: bool = False, **env: str
    ) -> subprocess.CompletedProcess[bytes]:
        if script:
            exe = shutil.which("ale", path=str(Path(sys.executable).parent))
            assert exe is not None, "console script `ale` not installed next to the interpreter"
            cmd = [exe, *args]
        else:
            cmd = [sys.executable, "-m", "ale", *args]
        kwargs: dict[str, Any] = {"capture_output": True, "timeout": 50, "check": False}
        return subprocess.run(cmd, env=subprocess_env(**env), **kwargs)

    return _run
