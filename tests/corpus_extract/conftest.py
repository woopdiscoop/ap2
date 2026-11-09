"""Fixtures of the Ticket 1.2c tests (``ale layers`` / ``ale extract`` for CAD)."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

# Reuse the DXF builders of tests/cad and the byte builders of tests/corpus.
_TESTS = Path(__file__).resolve().parents[1]
for _sub in ("cad", "corpus", "pdfread", "raster"):
    if str(_TESTS / _sub) not in sys.path:
        sys.path.insert(0, str(_TESTS / _sub))

from extract_helpers import Invoke  # noqa: E402

from ale.cli import app  # noqa: E402
from ale.logging_setup import LOGGER_NAME, shutdown_logging  # noqa: E402

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
