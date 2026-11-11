"""``prepare_input``: program + site + rulebook → validated ``PreparedInput`` (RD 3.1 §7).

Public API for Tickets 3.2-3.5. All three inputs are always read so that every issue
is reported at once; the feasibility pre-check runs only when the three parsed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from ale.contracts.config import AleConfig
from ale.contracts.models import GridSpec, Program, Rulebook, SiteSpec
from ale.contracts.serialization import load_yaml
from ale.program.excel import read_program
from ale.program.feasibility import check_feasibility, rulebook_coverage
from ale.program.models import (
    FeasibilityReport,
    InputError,
    Issue,
    ModuleFootprint,
    PreparedInput,
    ProgramReport,
    make_issue,
)
from ale.program.site import read_site, to_module_footprint

__all__ = ["InputCheck", "check_inputs", "convex_corners", "load_rulebook", "prepare_input"]


def load_rulebook(path: Path) -> tuple[Rulebook | None, tuple[Issue, ...]]:
    """Read a rulebook YAML file; contract errors become ``E_RULEBOOK_INVALID`` issues."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        issue = make_issue("E_FILE_UNREADABLE", f"Rulebook illisible : {exc}.", value=str(path))
        return None, (issue,)
    try:
        return load_yaml(Rulebook, text), ()
    except yaml.YAMLError as exc:
        return None, (make_issue("E_RULEBOOK_INVALID", f"YAML invalide : {exc}."),)
    except ValidationError as exc:
        issues = tuple(
            make_issue(
                "E_RULEBOOK_INVALID",
                f"Rulebook invalide ({'.'.join(str(p) for p in err['loc']) or 'racine'}) : "
                f"{err['msg']}.",
            )
            for err in exc.errors(include_url=False)
        )
        return None, issues


@dataclass
class InputCheck:
    """Everything learnt from the three inputs (also used by ``ale program check``)."""

    program: Program | None = None
    report: ProgramReport = field(default_factory=ProgramReport)
    site: SiteSpec | None = None
    footprint: ModuleFootprint | None = None
    rulebook: Rulebook | None = None
    feasibility: FeasibilityReport | None = None
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        """Issues of severity ``error``."""
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        """Issues of severity ``warning``."""
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def structure(self) -> tuple[int, int, int] | None:
        """``(pieces, junctions, courtyards)`` of the module footprint (X.3), if it decomposes."""
        if self.footprint is None:
            return None
        from ale.contracts.footprint import decompose_footprint

        try:
            fp = decompose_footprint(self.footprint.polygon)
        except ValueError:  # outside the grammar (more than 12 pieces)
            return None
        return len(fp.pieces), len(fp.junctions), len(self.footprint.polygon.holes)

    @property
    def anchors(self) -> tuple[tuple[str, str, str], ...]:
        """``(room id, name, anchor)`` of every anchored room of the program (A.4)."""
        if self.program is None:
            return ()
        return tuple((r.id, r.name, r.anchor) for r in self.program.rooms if r.anchor is not None)


def convex_corners(site: SiteSpec) -> int:
    """Number of convex (left-turn) vertices of the exterior ring of a CCW rectilinear site."""
    ring = site.footprint.exterior
    n = len(ring)
    count = 0
    for i in range(n):
        a, b, c = ring[i - 1], ring[i], ring[(i + 1) % n]
        if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) > 0:
            count += 1
    return count


def _floor_issues(program: Program, rows: dict[str, int]) -> list[Issue]:
    """The v1 engines are single-floor: rooms on several levels are refused (A.4)."""
    floors = sorted({r.floor for r in program.rooms})
    if len(floors) <= 1:
        return []
    first = program.rooms[0].floor
    other = next(r for r in program.rooms if r.floor != first)
    levels = ", ".join(map(str, floors))
    return [
        make_issue(
            "E_FLOORS_MULTIPLE",
            f"Le programme comporte des pièces sur plusieurs niveaux ({levels}) "
            "alors que le moteur ne gère qu'un seul niveau : placez toutes les pièces "
            "sur le même niveau.",
            row=rows.get(other.id),
            column="Niveau",
            value=other.floor,
        )
    ]


def _anchor_issues(program: Program, site: SiteSpec, rows: dict[str, int]) -> list[Issue]:
    """Warnings on anchors that the site cannot honour (A.4)."""
    out: list[Issue] = []
    entrance_rooms = [r for r in program.rooms if r.anchor == "entrance"]
    corner_rooms = [r for r in program.rooms if r.anchor == "corner"]
    if entrance_rooms and not site.entrances:
        out.append(
            make_issue(
                "W_ANCHOR_NO_ENTRANCE",
                f"La pièce « {entrance_rooms[0].id} » est ancrée à l'entrée mais le site "
                "ne définit aucune entrée (clé entrances de site.yaml).",
                row=rows.get(entrance_rooms[0].id),
                column="Ancrage",
                value="entrée",
            )
        )
    corners = convex_corners(site)
    n_corner = sum(r.quantity for r in corner_rooms)
    if n_corner > corners:
        out.append(
            make_issue(
                "W_ANCHOR_CORNERS",
                f"{n_corner} pièces ancrées en coin pour {corners} coins saillants de l'emprise.",
                column="Ancrage",
                value="coin",
            )
        )
    if site.mode == "plot":
        out.append(
            make_issue(
                "W_SITE_PLOT_MODE",
                "Site en mode « plot » : les moteurs actuels traitent le polygone comme "
                "l'emprise du bâtiment et ignorent les retraits.",
                value="plot",
            )
        )
    return out


def check_inputs(
    program_path: Path, site_path: Path, rulebook_path: Path, config: AleConfig
) -> InputCheck:
    """Read and check the three inputs, collecting every issue (never raises on content)."""
    grid = GridSpec(module_mm=config.grid.module_mm)
    out = InputCheck()
    out.program, out.report = read_program(Path(program_path))
    out.issues.extend(out.report.issues)

    out.site, site_issues = read_site(Path(site_path))
    out.issues.extend(site_issues)
    if out.site is not None:
        try:
            out.footprint = to_module_footprint(out.site, grid)
        except InputError as exc:
            out.issues.extend(exc.issues)

    if out.program is not None:
        out.issues.extend(_floor_issues(out.program, out.report.rows))
        if out.site is not None:
            out.issues.extend(_anchor_issues(out.program, out.site, out.report.rows))

    out.rulebook, rulebook_issues = load_rulebook(Path(rulebook_path))
    out.issues.extend(rulebook_issues)

    if out.program is not None and out.footprint is not None and out.rulebook is not None:
        out.feasibility = check_feasibility(
            out.program, out.footprint, out.rulebook, config, rows=out.report.rows
        )
        out.issues.extend(out.feasibility.issues)
    elif out.rulebook is not None:
        # The program did not parse: still report rulebook coverage of the resolved types.
        out.issues.extend(rulebook_coverage(out.report.types, out.rulebook))
    return out


def prepare_input(
    program_path: Path, site_path: Path, rulebook_path: Path, config: AleConfig
) -> PreparedInput:
    """Validated, generation-ready bundle; raises ``InputError`` (all issues) on any error."""
    check = check_inputs(program_path, site_path, rulebook_path, config)
    if (
        check.errors
        or check.program is None
        or check.site is None
        or check.footprint is None
        or check.rulebook is None
        or check.feasibility is None
    ):
        raise InputError(check.issues)
    return PreparedInput(
        program=check.program,
        instances=check.program.instances(),
        site=check.site,
        footprint=check.footprint,
        grid=GridSpec(module_mm=config.grid.module_mm),
        rulebook_version=check.rulebook.version,
        feasibility=check.feasibility,
        warnings=tuple(check.warnings),
    )
