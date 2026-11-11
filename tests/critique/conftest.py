"""Fixtures of the Ticket R.6 tests: a real exported variant folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from critique_helpers import make_layout, prepare

from ale.contracts.models import Program, SiteSpec
from ale.export.run import export_run


@pytest.fixture
def variant(tmp_path: Path, program_8: Program, site_rect_small: SiteSpec) -> Path:
    (tmp_path / "prep").mkdir()
    prepared = prepare(tmp_path / "prep", program_8, site_rect_small)
    out = tmp_path / "variant"
    export_run(make_layout(), prepared, out, rulebook_version="test-3.1", run_id="run-001")
    return out


@pytest.fixture(scope="session")
def layout() -> Any:
    return make_layout()
