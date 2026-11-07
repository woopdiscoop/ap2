"""Program & site ingestion (Ticket 3.1): ``programme.xlsx`` + ``site.yaml`` → ``PreparedInput``.

Public API: :func:`prepare_input`, :func:`read_program`, :func:`read_site`,
:func:`to_module_footprint`, :func:`check_feasibility` and the models of
:mod:`ale.program.models`. Requires the ``excel`` extra (openpyxl); DXF sites need ``cad``.
"""

from __future__ import annotations

from ale.program.excel import read_program
from ale.program.feasibility import check_feasibility
from ale.program.models import (
    FeasibilityReport,
    InputError,
    Issue,
    ModuleFootprint,
    PreparedInput,
    ProgramReport,
    RoomFit,
)
from ale.program.prepare import load_rulebook, prepare_input
from ale.program.site import read_site, to_module_footprint

__all__ = [
    "FeasibilityReport",
    "InputError",
    "Issue",
    "ModuleFootprint",
    "PreparedInput",
    "ProgramReport",
    "RoomFit",
    "check_feasibility",
    "load_rulebook",
    "prepare_input",
    "read_program",
    "read_site",
    "to_module_footprint",
]
