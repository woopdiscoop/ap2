"""Data models of program & site ingestion (Ticket 3.1).

Units: areas in m², lengths in metres; ``ModuleFootprint.polygon`` is in integer modules
of the planning grid (``GridSpec``), origin at ``origin_m`` (metres, site drawing axes).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from ale.contracts.geometry import Float, ModulePolygon, Point2
from ale.contracts.models import GridSpec, Program, RoomSpec, SiteSpec

__all__ = [
    "ERROR_CODES",
    "EXTRA_ERROR_CODES",
    "WARNING_CODES",
    "FeasibilityReport",
    "InputError",
    "Issue",
    "ModuleFootprint",
    "PreparedInput",
    "ProgramReport",
    "RoomFit",
    "Severity",
    "make_issue",
]

_CONFIG = ConfigDict(extra="forbid", frozen=True)

#: Error codes of RD 3.1 section 4 (frozen list, site codes of section 5 included).
ERROR_CODES: frozenset[str] = frozenset(
    {
        "E_MISSING_COLUMN",
        "E_NO_ROOMS",
        "E_EMPTY_ID",
        "E_BAD_ID",
        "E_DUP_ID",
        "E_EMPTY_NAME",
        "E_UNKNOWN_TYPE",
        "E_FORBIDDEN_TYPE",
        "E_AREA",
        "E_QUANTITY",
        "E_ZONE",
        "E_FACADE",
        "E_ORIENTATION",
        "E_MIN_WIDTH",
        "E_REF_UNKNOWN",
        "E_SELF_REF",
        "E_REQ_AVOID_CONFLICT",
        "E_FLOOR",
        "E_ROOM_INFEASIBLE",
        "E_TYPE_NOT_IN_RULEBOOK",
        "E_NOT_FEASIBLE",
        "E_FACADE_INSUFFICIENT",
        "E_SITE_DXF",
        "E_SITE_UNITS",
        "E_SITE_DWG",
        "E_SITE_INVALID",
        "E_SITE_NOT_ORTHOGONAL",
        "E_SITE_TOO_SMALL",
        "E_SITE_ACCESS_EDGE",
    }
)

#: Codes the RD leaves unnamed: an unreadable input file, a malformed ``site.yaml``
#: (both/none of ``footprint``/``footprint_dxf``, unknown keys, bad values) and an
#: invalid rulebook file.
EXTRA_ERROR_CODES: frozenset[str] = frozenset(
    {"E_FILE_UNREADABLE", "E_SITE_SCHEMA", "E_RULEBOOK_INVALID"}
)

#: Warning codes of RD 3.1 section 4, plus ``W_FACADE_TIGHT`` (Q.2a).
WARNING_CODES: frozenset[str] = frozenset(
    {"W_SHEET_NAME", "W_UNKNOWN_COLUMN", "W_ZONE_DEFAULTED", "W_FACADE_TIGHT"}
)

Severity = Literal["error", "warning"]

_VALUE_MAX = 80


class Issue(BaseModel):
    """One validation finding.

    ``row`` is the 1-based Excel row (``None`` when not tied to a row), ``column`` the
    header text (``None`` when not tied to a column), ``value`` the ``repr`` of the cell
    (≤ 80 characters, ``None`` when there is no cell).
    """

    model_config = _CONFIG

    code: StrictStr
    severity: Severity
    row: StrictInt | None = None
    column: StrictStr | None = None
    message: StrictStr
    value: Annotated[StrictStr, Field(max_length=_VALUE_MAX)] | None = None


def _short_repr(value: object) -> str:
    text = repr(value)
    if len(text) > _VALUE_MAX:
        text = text[: _VALUE_MAX - 3] + "..."
    return text


_NO_VALUE = object()


def make_issue(
    code: str,
    message: str,
    *,
    row: int | None = None,
    column: str | None = None,
    value: object = _NO_VALUE,
) -> Issue:
    """Build an ``Issue``; the severity follows the code prefix (``W_`` → warning)."""
    severity: Severity = "warning" if code.startswith("W_") else "error"
    return Issue(
        code=code,
        severity=severity,
        row=row,
        column=column,
        message=message,
        value=None if value is _NO_VALUE else _short_repr(value),
    )


class ProgramReport(BaseModel):
    """Result of reading ``programme.xlsx``.

    ``rows`` maps each parsed room id to its Excel row; ``types`` lists (sorted) the
    room-type keys resolved on any row, even when the program as a whole is invalid.
    """

    model_config = _CONFIG

    sheet: StrictStr | None = None
    issues: tuple[Issue, ...] = ()
    rows: dict[StrictStr, StrictInt] = {}
    types: tuple[StrictStr, ...] = ()

    @property
    def errors(self) -> tuple[Issue, ...]:
        """Issues of severity ``error``."""
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[Issue, ...]:
        """Issues of severity ``warning``."""
        return tuple(i for i in self.issues if i.severity == "warning")

    @property
    def ok(self) -> bool:
        """``True`` when the report holds no error."""
        return not self.errors


class ModuleFootprint(BaseModel):
    """Site footprint on the planning grid.

    ``polygon`` in modules (origin = lower-left corner ``origin_m``, metres);
    ``access_edge`` indexes ``polygon.edges()``; ``sliver_loss_m2`` = metric area minus
    module area (m², ≥ 0).
    """

    model_config = _CONFIG

    polygon: ModulePolygon
    origin_m: Point2
    access_edge: Annotated[StrictInt, Field(ge=0)]
    sliver_loss_m2: Annotated[Float, Field(ge=0.0)]


class RoomFit(BaseModel):
    """Chosen buildable rectangle of a program row: sides in modules, overshoot in m²."""

    model_config = _CONFIG

    short: StrictInt
    long: StrictInt
    overshoot_m2: Float


class FeasibilityReport(BaseModel):
    """Feasibility pre-check (areas in m², lengths in metres, ``fill_ratio`` unitless).

    ``facade_usable_m``: grammar-aware façade capacity (Q.2a), metres.
    """

    model_config = _CONFIG

    net_m2: Float
    circulation_m2: Float
    overshoot_m2: Float
    required_m2: Float
    available_m2: Float
    footprint_m2: Float
    fill_ratio: Float
    facade_required_m: Float
    perimeter_m: Float
    facade_usable_m: Float
    per_room: dict[StrictStr, RoomFit]
    issues: tuple[Issue, ...] = ()


class PreparedInput(BaseModel):
    """Validated, generation-ready input bundle (public API for Tickets 3.2-3.5)."""

    model_config = _CONFIG

    program: Program
    instances: tuple[tuple[str, RoomSpec], ...]
    site: SiteSpec
    footprint: ModuleFootprint
    grid: GridSpec
    rulebook_version: StrictStr
    feasibility: FeasibilityReport
    warnings: tuple[Issue, ...]


class InputError(Exception):
    """Input bundle rejected; ``issues`` carries every issue found (errors and warnings)."""

    def __init__(self, issues: tuple[Issue, ...] | list[Issue]) -> None:
        self.issues: tuple[Issue, ...] = tuple(issues)
        errors = [i for i in self.issues if i.severity == "error"]
        lines = [f"{i.code}: {i.message}" for i in errors] or ["invalid input"]
        super().__init__("\n".join(lines))
