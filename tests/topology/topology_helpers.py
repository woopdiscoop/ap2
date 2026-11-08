"""Helpers of the Ticket 3.2 tests (written independently of ``ale.topology``)."""

from __future__ import annotations

from pathlib import Path

from program_helpers import RULEBOOK_TEST, load_test_rulebook, program_to_xlsx, site_to_yaml

from ale.config import AleConfig
from ale.contracts.models import Program, SiteSpec
from ale.program import prepare_input
from ale.program.models import PreparedInput

__all__ = ["RULEBOOK_TEST", "load_test_rulebook", "prepare"]


def prepare(tmp: Path, program: Program, site: SiteSpec) -> PreparedInput:
    """``prepare_input`` on ``program`` / ``site`` written into ``tmp``."""
    tmp.mkdir(parents=True, exist_ok=True)
    xlsx = program_to_xlsx(program, tmp / "programme.xlsx")
    yml = site_to_yaml(site, tmp / "site.yaml")
    return prepare_input(xlsx, yml, RULEBOOK_TEST, AleConfig())
