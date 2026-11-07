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

__all__ = ["InputCheck", "check_inputs", "load_rulebook", "prepare_input"]


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
