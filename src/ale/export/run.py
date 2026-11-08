"""``export_run``: write ``layout.json``, ``layout.dxf``, ``preview.svg``, ``report.md``."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ale.contracts.config import AleConfig
from ale.contracts.models import Layout
from ale.contracts.serialization import canonical_json
from ale.export import dxf as _dxf
from ale.export.report import DXF_NAME, JSON_NAME, REPORT_NAME, SVG_NAME, render_report
from ale.export.svg import render_svg
from ale.program.models import PreparedInput

__all__ = ["RunFiles", "export_run"]

DXF_DISABLED = "export DXF désactivé"
DXF_NO_EZDXF = "ezdxf n'est pas installé : extra « cad »"


class RunFiles(BaseModel):
    """Paths of the files written by :func:`export_run` (``layout_dxf`` None if skipped)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    layout_json: Path
    layout_dxf: Path | None
    preview_svg: Path
    report_md: Path


def _write_text(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def export_run(
    layout: Layout,
    prepared: PreparedInput,
    out_dir: Path,
    *,
    rulebook_version: str,
    run_id: str,
    dxf: bool = True,
    config: AleConfig | None = None,
) -> RunFiles:
    """Write the four run files into ``out_dir`` (created if missing).

    Raises ``FileExistsError`` (writing nothing) when ``out_dir`` already holds any of the
    four files. With ``dxf=False`` or without ezdxf, no DXF is written and the report says so.
    ``config`` supplies the cost weights shown in the report (defaults: ``AleConfig()``).
    """
    cfg = config if config is not None else AleConfig()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {name: out / name for name in (JSON_NAME, DXF_NAME, SVG_NAME, REPORT_NAME)}
    existing = sorted(name for name, p in paths.items() if p.exists())
    if existing:
        raise FileExistsError(f"{out} already contains {', '.join(existing)}")

    with paths[JSON_NAME].open("xb") as fh:
        fh.write(canonical_json(layout))

    dxf_note: str | None = None
    if not dxf:
        dxf_note = DXF_DISABLED
    elif _dxf.load_ezdxf() is None:
        dxf_note = DXF_NO_EZDXF
    else:
        _dxf.write_dxf(layout, prepared, paths[DXF_NAME])

    _write_text(paths[SVG_NAME], render_svg(layout, prepared))
    _write_text(
        paths[REPORT_NAME],
        render_report(
            layout,
            prepared,
            rulebook_version=rulebook_version,
            run_id=run_id,
            config=cfg,
            dxf_note=dxf_note,
        ),
    )
    return RunFiles(
        layout_json=paths[JSON_NAME],
        layout_dxf=None if dxf_note is not None else paths[DXF_NAME],
        preview_svg=paths[SVG_NAME],
        report_md=paths[REPORT_NAME],
    )
