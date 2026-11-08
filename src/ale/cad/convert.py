"""DWG → DXF conversion, cached as ``cache_dir/<sha256 of the DWG>.dxf``.

Converters, in order: the ODA File Converter, then AutoCAD ``accoreconsole`` with a
generated ``-DXFOUT`` script. Both are located with :func:`ale.doctor.find_tool` and run
through :func:`ale.proc.run_tool` (timeout ``tools.timeout_s``, whole-tree kill), on a
copy of the DWG in a temporary folder: the source DWG is never written.

The ODA command line is the one ``ezdxf.addons.odafc`` builds
(``<in dir> <out dir> <version> DXF <recurse> <audit> <filter>``); the converter is not
started through ``odafc`` itself because ``odafc`` has no timeout and no process-tree
kill. :func:`convert_dwg` never raises: a missing converter gives ``NEEDS_TOOL``, a
failing one ``FAILED``.
"""

from __future__ import annotations

import contextlib
import hashlib
import shutil
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ale.contracts.config import AleConfig
from ale.doctor import TOOLS, ToolSpec, find_tool
from ale.proc import ProcessReport, run_tool

__all__ = ["ODA_OUTPUT_VERSION", "ConvertResult", "convert_dwg", "file_sha256"]

#: DXF version written by the ODA File Converter.
ODA_OUTPUT_VERSION = "ACAD2018"

ConvertStatus = Literal["OK", "NEEDS_TOOL", "FAILED"]


@dataclass(frozen=True)
class ConvertResult:
    """Outcome of :func:`convert_dwg`."""

    status: ConvertStatus
    dxf_path: Path | None
    source_sha256: str | None
    cached: bool
    tool: str | None
    message: str
    process: dict[str, object] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "OK"


def file_sha256(path: Path) -> str:
    """SHA-256 (hex) of a file's bytes."""
    with path.open("rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def _spec(config_key: str) -> ToolSpec:
    return next(t for t in TOOLS if t.config_key == config_key)


def _launcher(exe: Path) -> list[str]:
    """argv prefix for ``exe`` (a ``.py`` converter runs under this interpreter)."""
    if exe.suffix.lower() == ".py":
        return [sys.executable, str(exe)]
    return [str(exe)]


def _oda_argv(exe: Path, in_dir: Path, out_dir: Path, filename: str) -> list[str]:
    argv = _launcher(exe)
    xvfb = shutil.which("xvfb-run") if sys.platform.startswith("linux") else None
    if xvfb is not None and exe.suffix.lower() != ".py":  # pragma: no cover - needs xvfb
        argv = [xvfb, "-a", *argv]
    return [*argv, str(in_dir), str(out_dir), ODA_OUTPUT_VERSION, "DXF", "0", "1", filename]


def _accore_script(out_dxf: Path) -> str:
    return "\n".join(["FILEDIA", "0", "-DXFOUT", f'"{out_dxf}"', "16", "QUIT", "Y", ""])


def _accore_argv(exe: Path, dwg: Path, script: Path) -> list[str]:
    switch_i, switch_s = (f"/{c}" for c in ("i", "s"))  # no literal that looks like a path
    return [*_launcher(exe), switch_i, str(dwg), switch_s, str(script)]


def _tail(text: str, n: int = 400) -> str:
    text = text.strip()
    return text if len(text) <= n else "…" + text[-n:]


def _describe(report: ProcessReport) -> str:
    if report.error is not None:
        return report.error
    if report.timed_out:
        return f"timed out after {report.duration_s:.1f} s"
    if report.returncode != 0:
        return f"exit code {report.returncode}: {_tail(report.stderr or report.stdout)}"
    return "no DXF produced"


def _install(produced: Path, target: Path) -> bool:
    if not produced.is_file() or produced.stat().st_size == 0:
        return False
    partial = target.with_name(target.name + ".part")
    shutil.copyfile(produced, partial)
    partial.replace(target)
    return True


def _run_converter(
    name: str, exe: Path, dwg: Path, sha: str, target: Path, timeout_s: float
) -> tuple[bool, str, ProcessReport | None]:
    work = Path(tempfile.mkdtemp(prefix="ale-dwg-"))
    try:
        in_dir, out_dir = work / "in", work / "out"
        in_dir.mkdir()
        out_dir.mkdir()
        local = in_dir / f"{sha}.dwg"
        shutil.copyfile(dwg, local)
        if name == "oda":
            argv = _oda_argv(exe, in_dir, out_dir, local.name)
        else:
            script = work / "dxfout.scr"
            script.write_text(_accore_script(out_dir / f"{sha}.dxf"), encoding="utf-8")
            argv = _accore_argv(exe, local, script)
        report = run_tool(argv, timeout_s=timeout_s, cwd=work)
        produced = out_dir / f"{sha}.dxf"
        if report.ok and _install(produced, target):
            return True, f"converted with {exe.name}", report
        return False, f"{exe.name}: {_describe(report)}", report
    except OSError as exc:
        return False, f"{exe.name}: {exc}", None
    finally:
        with contextlib.suppress(OSError):
            shutil.rmtree(work, ignore_errors=True)


def convert_dwg(
    dwg: Path,
    cache_dir: Path,
    config: AleConfig,
    *,
    workspace_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ConvertResult:
    """Convert ``dwg`` to ``cache_dir/<sha256>.dxf`` (reused when present); never raises.

    ``workspace_root`` resolves relative tool paths of ``config`` (default: ``cache_dir``);
    ``environ`` replaces ``os.environ`` for tool detection.
    """
    dwg = Path(dwg)
    try:
        sha = file_sha256(dwg)
    except OSError as exc:
        return ConvertResult("FAILED", None, None, False, None, f"cannot read {dwg.name}: {exc}")
    target = Path(cache_dir) / f"{sha}.dxf"
    if target.is_file() and target.stat().st_size > 0:
        return ConvertResult("OK", target, sha, True, None, "cached")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return ConvertResult("FAILED", None, sha, False, None, f"cannot create cache: {exc}")
    root = Path(workspace_root) if workspace_root is not None else Path(cache_dir)
    tools = config.tools
    candidates = (
        ("oda", _spec("oda_file_converter"), tools.oda_file_converter),
        ("accoreconsole", _spec("accoreconsole"), tools.accoreconsole),
    )
    failures: list[str] = []
    missing: list[str] = []
    last_report: ProcessReport | None = None
    for name, spec, configured in candidates:
        exe, how = find_tool(spec, configured, root, environ)
        if exe is None:
            missing.append(f"{spec.name}: {how}")
            continue
        ok, message, report = _run_converter(name, exe, dwg, sha, target, tools.timeout_s)
        last_report = report if report is not None else last_report
        if ok:
            return ConvertResult(
                "OK",
                target,
                sha,
                False,
                spec.name,
                message,
                None if report is None else report.to_report(),
            )
        failures.append(message)
    if not failures:
        return ConvertResult(
            "NEEDS_TOOL",
            None,
            sha,
            False,
            None,
            "no DWG converter found (" + "; ".join(missing) + ")",
        )
    return ConvertResult(
        "FAILED",
        None,
        sha,
        False,
        None,
        "; ".join(failures),
        None if last_report is None else last_report.to_report(),
    )
