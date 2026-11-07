"""Fixtures of the Ticket 3.1 tests (program & site ingestion)."""

from __future__ import annotations

from pathlib import Path

import pytest
from program_helpers import RULEBOOK_TEST, load_test_rulebook

from ale.contracts.models import Rulebook


@pytest.fixture(scope="session")
def rulebook_path() -> Path:
    return RULEBOOK_TEST


@pytest.fixture(scope="session")
def rulebook() -> Rulebook:
    return load_test_rulebook()
