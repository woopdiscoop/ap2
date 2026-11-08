"""Helpers of the Ticket 3.4 tests (written independently of ``ale.optimize``)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_PROGRAM_TESTS = Path(__file__).resolve().parent.parent / "program"
if str(_PROGRAM_TESTS) not in sys.path:
    sys.path.insert(0, str(_PROGRAM_TESTS))

from program_helpers import (  # noqa: E402
    RULEBOOK_TEST,
    load_test_rulebook,
    program_to_xlsx,
    site_to_yaml,
)

from ale.config import AleConfig  # noqa: E402
from ale.contracts.models import Program, SiteSpec  # noqa: E402
from ale.program import prepare_input  # noqa: E402
from ale.program.models import PreparedInput  # noqa: E402

__all__ = [
    "RULEBOOK_TEST",
    "load_test_rulebook",
    "optimizer_config",
    "prepare",
    "write_inputs",
]


def write_inputs(tmp: Path, program: Program, site: SiteSpec) -> tuple[Path, Path]:
    """``programme.xlsx`` and ``site.yaml`` of ``program`` / ``site`` written into ``tmp``."""
    tmp.mkdir(parents=True, exist_ok=True)
    return program_to_xlsx(program, tmp / "programme.xlsx"), site_to_yaml(site, tmp / "site.yaml")


def prepare(tmp: Path, program: Program, site: SiteSpec) -> PreparedInput:
    """``prepare_input`` on ``program`` / ``site`` written into ``tmp``."""
    xlsx, yml = write_inputs(tmp, program, site)
    return prepare_input(xlsx, yml, RULEBOOK_TEST, AleConfig())


def optimizer_config(**optimizer: Any) -> AleConfig:
    """``AleConfig()`` with ``[optimizer]`` fields overridden."""
    cfg = AleConfig()
    return cfg.model_copy(update={"optimizer": cfg.optimizer.model_copy(update=optimizer)})
