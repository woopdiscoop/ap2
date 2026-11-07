"""Fixtures for the Ticket 0.1 tests (CLI, workspace, config, doctor)."""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import sysconfig
import types
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

import ale.doctor
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
    """A clean machine: PATH reduced to the interpreter folder, ProgramFiles pointed at
    tmp, and the optional extras reported missing whatever is installed."""
    program_files = tmp_path / "ProgramFiles"
    program_files.mkdir()
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent))
    monkeypatch.setenv("ProgramFiles", str(program_files))
    hide_optional_extras(monkeypatch)
    return program_files


@pytest.fixture
def show_extras(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """Call to make the doctor see every optional extra as importable."""
    return lambda: hide_optional_extras(monkeypatch, hidden=False)


def hide_optional_extras(monkeypatch: pytest.MonkeyPatch, hidden: bool = True) -> None:
    """Make the doctor's import probe see the optional extras as missing (or, with
    ``hidden=False``, as importable). Patched only inside ``ale.doctor``."""
    extras = {module for module, _, _ in ale.doctor.EXTRAS}

    def import_module(name: str, package: str | None = None) -> object:
        if name in extras:
            if hidden:
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)
            return types.ModuleType(name)
        return importlib.import_module(name, package)

    monkeypatch.setattr(ale.doctor, "importlib", types.SimpleNamespace(import_module=import_module))


def subprocess_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ALE_ENV_VARS}
    env.update(extra)
    return env


def find_console_script() -> str | None:
    """The installed `ale` console script: the scheme's scripts dir (`Scripts\\ale.exe`
    on Windows), then the interpreter's folder, then PATH."""
    names = ("ale.exe", "ale") if sys.platform == "win32" else ("ale",)
    folders = [sysconfig.get_path("scripts"), str(Path(sys.executable).parent)]
    for folder in folders:
        for name in names:
            candidate = Path(folder) / name
            if candidate.is_file():
                return str(candidate)
    return shutil.which("ale")


@pytest.fixture
def run_ale() -> Callable[..., subprocess.CompletedProcess[bytes]]:
    """Run `python -m ale ...` (or the `ale` console script) as a real subprocess."""

    def _run(
        args: Sequence[str], script: bool = False, **env: str
    ) -> subprocess.CompletedProcess[bytes]:
        if script:
            exe = find_console_script()
            assert exe is not None, "console script `ale` not found (scripts dir or PATH)"
            cmd = [exe, *args]
        else:
            cmd = [sys.executable, "-m", "ale", *args]
        kwargs: dict[str, Any] = {"capture_output": True, "timeout": 50, "check": False}
        return subprocess.run(cmd, env=subprocess_env(**env), **kwargs)

    return _run
