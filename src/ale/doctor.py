"""Environment check behind ``ale doctor`` (RD 0.1 section 9).

Never executes an external program and never touches the network: tools are only
*located* (configured path, environment variable, ``PATH``, Windows Program Files).
The VLM key check reads only the *presence* of the environment variable.
"""

from __future__ import annotations

import importlib
import logging
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ale.paths import display, expand, resolve_against
from ale.workspace import SUBFOLDERS, Workspace

__all__ = [
    "EXTRAS",
    "TOOLS",
    "Check",
    "DoctorReport",
    "ToolSpec",
    "find_tool",
    "newest_by_version",
    "run_checks",
]

log = logging.getLogger(__name__)

MIN_PYTHON = (3, 11)

#: Optional modules: (import name, display name, extra providing it).
EXTRAS: tuple[tuple[str, str, str], ...] = (
    ("ezdxf", "ezdxf", "cad"),
    ("fitz", "fitz (PyMuPDF)", "pdf"),
    ("cv2", "cv2 (OpenCV)", "raster"),
    ("PIL", "PIL (Pillow)", "raster"),
    ("pandas", "pandas", "excel"),
    ("openpyxl", "openpyxl", "excel"),
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    config_key: str
    env_var: str
    executable: str
    #: Windows Program Files glob, relative to ``%ProgramFiles%``.
    program_files_glob: str
    hint: str


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="ODA File Converter",
        config_key="oda_file_converter",
        env_var="ALE_ODA_PATH",
        executable="ODAFileConverter",
        program_files_glob="ODA/ODAFileConverter*/ODAFileConverter.exe",
        hint="install the free ODA File Converter and set [tools].oda_file_converter in ale.toml",
    ),
    ToolSpec(
        name="AutoCAD accoreconsole",
        config_key="accoreconsole",
        env_var="ALE_ACCORECONSOLE_PATH",
        executable="accoreconsole",
        program_files_glob="Autodesk/AutoCAD */accoreconsole.exe",
        hint="install AutoCAD (accoreconsole) and set [tools].accoreconsole in ale.toml",
    ),
)


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    required: bool
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        """True if every *required* check is ok."""
        return all(c.status == "ok" for c in self.checks if c.required)

    def to_dict(self) -> dict[str, Any]:
        return {"checks": [asdict(c) for c in self.checks], "ok": self.ok}


def _check_python() -> Check:
    version = ".".join(str(v) for v in sys.version_info[:3])
    ok = sys.version_info[:2] >= MIN_PYTHON
    detail = version if ok else f"{version} (Python >= 3.11 required)"
    return Check("python", "ok" if ok else "fail", True, detail)


def _writable(folder: Path) -> str | None:
    """None if a temp file can be created and deleted in ``folder``, else the reason."""
    if not folder.is_dir():
        return "folder missing"
    try:
        fd, name = tempfile.mkstemp(prefix=".ale-doctor-", dir=folder)
        os.close(fd)
        Path(name).unlink()
    except OSError as exc:
        return exc.strerror or str(exc)
    return None


def _check_workspace(ws: Workspace) -> Check:
    problems: list[str] = []
    for parts in ((), *SUBFOLDERS):
        reason = _writable(ws.path(*parts))
        if reason is not None:
            label = "/".join(parts) or "."
            problems.append(f"{label} not writable ({reason})")
    if problems:
        return Check("workspace", "fail", True, "; ".join(problems))
    return Check("workspace", "ok", True, display(ws.root))


def _check_extra(module: str, label: str, extra: str) -> Check:
    try:
        importlib.import_module(module)
    except Exception:
        return Check(f"extra {label}", "missing", False, f'pip install "ale[{extra}]"')
    return Check(f"extra {label}", "ok", False, "importable")


def _version_key(name: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", name))


def newest_by_version(candidates: list[Path]) -> Path | None:
    """The candidate whose parent folder name carries the highest version number."""
    if not candidates:
        return None
    return max(candidates, key=lambda p: (_version_key(p.parent.name), p.parent.name))


def _program_files_candidates(program_files: Path, pattern: str) -> list[Path]:
    return sorted(p for p in program_files.glob(pattern) if p.is_file())


def find_tool(
    spec: ToolSpec,
    configured: str,
    workspace_root: Path,
    environ: Mapping[str, str] | None = None,
    is_windows: bool | None = None,
) -> tuple[Path | None, str]:
    """Locate a tool without executing it.

    Returns ``(path, how)`` when found, or ``(None, reason)`` when missing.
    """
    env = os.environ if environ is None else environ
    windows = (os.name == "nt") if is_windows is None else is_windows

    # (1) path configured in ale.toml (relative to the workspace).
    if configured:
        path = resolve_against(workspace_root, configured)
        if path.is_file():
            return path, "ale.toml"
        return None, f"configured path not found: {display(path)}"

    # (2) environment variable.
    env_value = env.get(spec.env_var, "")
    if env_value:
        path = resolve_against(workspace_root, env_value)
        if path.is_file():
            return path, spec.env_var

    # (3) PATH.
    which = shutil.which(spec.executable, path=env.get("PATH"))
    if which:
        return expand(which), "PATH"

    # (4) Windows only: %ProgramFiles%, newest version wins.
    program_files = env.get("ProgramFiles", "")
    if windows and program_files:
        newest = newest_by_version(
            _program_files_candidates(Path(program_files), spec.program_files_glob)
        )
        if newest is not None:
            return newest, "ProgramFiles"

    return None, "not found"


def _check_tool(spec: ToolSpec, ws: Workspace, environ: Mapping[str, str]) -> Check:
    configured = str(getattr(ws.config.tools, spec.config_key))
    path, how = find_tool(spec, configured, ws.root, environ)
    if path is not None:
        return Check(spec.name, "found", False, display(path))
    return Check(spec.name, "missing", False, f"{how}; {spec.hint}")


def _check_vlm(ws: Workspace, environ: Mapping[str, str]) -> Check:
    vlm = ws.config.vlm
    if not vlm.provider:
        return Check("VLM", "disabled", False, 'provider is "" (VLM disabled)')
    # Presence only: the value is never read into a variable, printed or logged.
    if vlm.api_key_env in environ:
        return Check("VLM", "key present", False, f"environment variable {vlm.api_key_env} is set")
    return Check("VLM", "key missing", False, f"set the environment variable {vlm.api_key_env}")


def run_checks(ws: Workspace, environ: Mapping[str, str] | None = None) -> DoctorReport:
    """Run every check of RD 0.1 section 9 against an opened workspace."""
    env = os.environ if environ is None else environ
    checks: list[Check] = [_check_python(), _check_workspace(ws)]
    checks.extend(_check_extra(module, label, extra) for module, label, extra in EXTRAS)
    checks.extend(_check_tool(spec, ws, env) for spec in TOOLS)
    checks.append(_check_vlm(ws, env))
    for check in checks:
        log.debug(
            "%s: %s",
            check.name,
            check.status,
            extra={"event": "doctor.check", "check": check.name, "status": check.status},
        )
    return DoctorReport(tuple(checks))
