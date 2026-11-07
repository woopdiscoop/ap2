"""Repository-wide pytest fixtures (RD 0.4 section 5).

Session-scoped: the fixture programs and sites, ``fixture_pairs``, ``taxonomy`` and
``default_config``. Function-scoped: ``tmp_workspace`` and ``fake_clock``.
No markers are registered here (they live in ``pyproject.toml``).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fixtures import FIXTURE_PAIRS, FakeClock, load_program, load_site
from typer.testing import CliRunner

from ale.cli import app
from ale.config import AleConfig
from ale.contracts.models import Program, SiteSpec
from ale.contracts.taxonomy import Taxonomy, load_taxonomy
from ale.logging_setup import LOGGER_NAME, shutdown_logging
from ale.workspace import Workspace, open_workspace

#: Folder name of ``tmp_workspace`` (space and accent on purpose).
TMP_WORKSPACE_NAME = "ws é"


@pytest.fixture(scope="session")
def program_8() -> Program:
    return load_program("program_08")


@pytest.fixture(scope="session")
def program_25() -> Program:
    return load_program("program_25")


@pytest.fixture(scope="session")
def program_60() -> Program:
    return load_program("program_60")


@pytest.fixture(scope="session")
def site_rect_small() -> SiteSpec:
    return load_site("site_rect_small")


@pytest.fixture(scope="session")
def site_rect() -> SiteSpec:
    return load_site("site_rect")


@pytest.fixture(scope="session")
def site_l() -> SiteSpec:
    return load_site("site_L")


@pytest.fixture(scope="session")
def fixture_pairs() -> tuple[tuple[str, str], ...]:
    return FIXTURE_PAIRS


@pytest.fixture(scope="session")
def taxonomy() -> Taxonomy:
    return load_taxonomy()


@pytest.fixture(scope="session")
def default_config() -> AleConfig:
    return AleConfig()


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Iterator[Workspace]:
    """A fresh workspace created by ``ale init`` in ``tmp_path / "ws é"``, opened."""
    logger = logging.getLogger(LOGGER_NAME)
    saved = (list(logger.handlers), logger.level, logger.propagate)
    root = tmp_path / TMP_WORKSPACE_NAME
    result = CliRunner().invoke(app, ["init", "--workspace", str(root)])
    try:
        assert result.exit_code == 0, result.output
        yield open_workspace(root)
    finally:
        # `ale init` reconfigures the `ale` logger; close the log file, restore the rest.
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
def fake_clock() -> FakeClock:
    return FakeClock(1000.0)
