"""Shared test fixtures (RD 0.4 section 5): three programs, three sites, a fake clock.

The YAML files in ``data/`` are verbatim copies of the Ticket 0.4 fixtures. Tests use the
pytest fixtures of ``tests/conftest.py``; these helpers are for code that needs to load a
fixture by name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, get_args

from ale.contracts.models import Program, SiteSpec
from ale.contracts.serialization import load_yaml

__all__ = [
    "DATA_DIR",
    "FIXTURE_PAIRS",
    "PROGRAM_NAMES",
    "SITE_NAMES",
    "FakeClock",
    "ProgramName",
    "SiteName",
    "load_program",
    "load_site",
]

DATA_DIR = Path(__file__).resolve().parent / "data"

ProgramName = Literal["program_08", "program_25", "program_60"]
SiteName = Literal["site_rect_small", "site_rect", "site_L"]
PROGRAM_NAMES: tuple[str, ...] = get_args(ProgramName)
SITE_NAMES: tuple[str, ...] = get_args(SiteName)

#: (program, site) pairs that belong together.
FIXTURE_PAIRS: tuple[tuple[ProgramName, SiteName], ...] = (
    ("program_08", "site_rect_small"),
    ("program_25", "site_rect"),
    ("program_60", "site_L"),
)


def _read(name: str, allowed: tuple[str, ...]) -> str:
    if name not in allowed:
        raise ValueError(f"unknown fixture {name!r}; expected one of {allowed}")
    return (DATA_DIR / f"{name}.yaml").read_text(encoding="utf-8")


def load_program(name: ProgramName) -> Program:
    """Load one of the fixture programs (``program_08``, ``program_25``, ``program_60``)."""
    return load_yaml(Program, _read(name, PROGRAM_NAMES))


def load_site(name: SiteName) -> SiteSpec:
    """Load one of the fixture sites (``site_rect_small``, ``site_rect``, ``site_L``)."""
    return load_yaml(SiteSpec, _read(name, SITE_NAMES))


class FakeClock:
    """Manually advanced clock for :mod:`ale.guards` tests (starts at 1000.0 s)."""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = float(start)

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("a monotonic clock cannot go backwards")
        self._now += seconds
