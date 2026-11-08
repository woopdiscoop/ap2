"""Fixtures of the Ticket 1.1 tests (corpus ingestion)."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from corpus_helpers import Invoke, dwg_bytes, dxf_bytes, jpeg_bytes, png_bytes, tiff_bytes, write
from typer.testing import CliRunner, Result

from ale.cli import app
from ale.logging_setup import LOGGER_NAME, shutdown_logging
from ale.workspace import Workspace

ALE_ENV_VARS = ("ALE_WORKSPACE", "ALE_ODA_PATH", "ALE_ACCORECONSOLE_PATH", "ALE_VLM_API_KEY")


@pytest.fixture(autouse=True)
def _no_cad_tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A machine without ODA File Converter / accoreconsole, whatever is installed."""
    for name in ALE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    program_files = tmp_path / "ProgramFiles"
    program_files.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent))
    monkeypatch.setenv("ProgramFiles", str(program_files))


@pytest.fixture(autouse=True)
def _restore_logger() -> Iterator[None]:
    """In-process CLI calls reconfigure the `ale` logger; put it back afterwards."""
    logger = logging.getLogger(LOGGER_NAME)
    saved = (list(logger.handlers), logger.level, logger.propagate)
    yield
    shutdown_logging()
    handlers, level, propagate = saved
    for handler in list(logger.handlers):
        if handler not in handlers:
            logger.removeHandler(handler)
            handler.close()
    for handler in handlers:
        if handler not in logger.handlers:
            logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = propagate


@pytest.fixture
def invoke() -> Invoke:
    """Run the CLI in-process; unexpected exceptions are re-raised."""
    try:  # click < 8.2 needs mix_stderr=False to expose result.stderr separately
        runner = CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        runner = CliRunner()

    def _invoke(args: Sequence[object]) -> Result:
        result = runner.invoke(app, [str(a) for a in args])
        if result.exception is not None and not isinstance(result.exception, SystemExit):
            raise result.exception
        return result

    return _invoke


@pytest.fixture
def input_dir(tmp_path: Path) -> Path:
    """An input folder with one file of each non-PDF kind."""
    root = tmp_path / "input"
    write(root / "a.png", png_bytes())
    write(root / "b.jpg", jpeg_bytes())
    write(root / "c.tif", tiff_bytes())
    write(root / "sub" / "d.dxf", dxf_bytes())
    write(root / "sub" / "e.dwg", dwg_bytes())
    return root


@pytest.fixture
def db(tmp_workspace: Workspace) -> Path:
    return tmp_workspace.path("corpus.sqlite")
