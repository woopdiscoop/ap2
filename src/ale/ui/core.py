"""Streamlit-free helpers of the local interface (Ticket U.1).

Everything here calls the same functions as the CLI commands; errors are turned into
:class:`UiError` carrying a French message.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import tempfile
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import typer
import yaml

from ale.config import AleConfig
from ale.contracts.models import Program, SiteSpec
from ale.workspace import Workspace, WorkspaceError, init_workspace, open_workspace

__all__ = [
    "DRAFT_RULEBOOK",
    "UiError",
    "build_config",
    "build_site",
    "default_rulebook",
    "ensure_workspace",
    "form_available",
    "load_site_yaml",
    "new_run_dir",
    "outline",
    "program_table",
    "program_totals",
    "run_cli_function",
    "save_upload",
    "site_svg",
    "zip_folder",
]

DRAFT_RULEBOOK = Path(__file__).resolve().parents[3] / "examples" / "rulebook_seed_draft.yaml"


def default_rulebook(ws: Workspace) -> Path | None:
    """First ``<workspace>/rulebook/*.yaml``, else the repository's draft rulebook, else None."""
    found = sorted(ws.path("rulebook").glob("*.y*ml"))
    if found:
        return found[0]
    return DRAFT_RULEBOOK if DRAFT_RULEBOOK.is_file() else None


class UiError(Exception):
    """A problem to show to the user (French message)."""


def ensure_workspace(path: str) -> Workspace:
    """Open the workspace, creating it with ``ale init`` defaults when missing."""
    if not path.strip():
        raise UiError("Indiquez un dossier de travail.")
    try:
        root, _ = init_workspace(Path(path.strip()))
        return open_workspace(root)
    except WorkspaceError as exc:
        raise UiError("Dossier de travail inutilisable : " + " ; ".join(exc.lines)) from exc
    except OSError as exc:
        raise UiError(f"Dossier de travail inutilisable : {exc}") from exc


def build_config(
    base: AleConfig, *, module_mm: int, never_below: bool, budget_s: float
) -> AleConfig:
    """Workspace config with the sidebar choices (module, area tolerance, time budget)."""
    area = base.area
    if never_below:  # AREP-MS : jamais en dessous du programme
        area = area.model_copy(update={"tol_down_pct": 0.0, "tol_up_pct": 10.0})
    return base.model_copy(
        update={
            "grid": base.grid.model_copy(update={"module_mm": module_mm}),
            "area": area,
            "optimizer": base.optimizer.model_copy(update={"time_budget_s": budget_s}),
        }
    )


def save_upload(folder: Path, name: str, data: bytes) -> Path:
    """Write an uploaded file under ``folder`` with a safe name."""
    safe = re.sub(r"[^\w.\-]+", "_", Path(name).name) or "fichier"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / safe
    target.write_bytes(data)
    return target


def new_run_dir(ws: Workspace, kind: str) -> Path:
    """A fresh ``runs/<kind>_<timestamp>`` folder name (not created)."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return ws.path("runs", f"{kind}_{stamp}")


def zip_folder(folder: Path) -> bytes:
    """All files of ``folder`` as a zip archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(folder).as_posix())
    return buf.getvalue()


def form_available() -> bool:
    """True when the ``ale.form`` package (Ticket G.3) can be imported."""
    return importlib.util.find_spec("ale.form") is not None


def run_cli_function(fn: Callable[..., None], **kwargs: Any) -> str:
    """Call a CLI command function; return its stdout. A non-zero exit raises :class:`UiError`
    with the command's own message (stderr)."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            fn(**kwargs)
        except typer.Exit as exc:
            code = int(exc.exit_code)
    if code != 0:
        raise UiError(err.getvalue().strip() or f"échec (code {code}).")
    return out.getvalue()


# ------------------------------------------------------------------ programme
def program_table(program: Program) -> list[dict[str, Any]]:
    """Rows id / nom / type / zone / façade / quantité / m² for display."""
    return [
        {
            "id": r.id,
            "nom": r.name,
            "type": r.type,
            "zone": str(getattr(r.macro_zone, "value", r.macro_zone)),
            "façade": "oui" if r.needs_facade else "non",
            "quantité": r.quantity,
            "m² unitaire": r.target_area_m2,
            "m² total": round(r.target_area_m2 * r.quantity, 2),
        }
        for r in program.rooms
    ]


def program_totals(program: Program) -> tuple[int, int, float]:
    """(lines, instances, total m²)."""
    inst = sum(r.quantity for r in program.rooms)
    m2 = sum(r.target_area_m2 * r.quantity for r in program.rooms)
    return len(program.rooms), inst, round(m2, 2)


# ------------------------------------------------------------------ site
def _rect(x: float, y: float, w: float, h: float) -> list[tuple[float, float]]:
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def outline(shape: str, w1: float, d1: float, w2: float, d2: float) -> list[tuple[float, float]]:
    """Rectangle ``w1 x d1``, or an L: rectangle 1 plus rectangle 2 (``w2 x d2``) on its left."""
    if shape == "rect":
        return _rect(0.0, 0.0, w1, d1)
    if w2 >= w1 or d2 <= d1:
        raise UiError("Forme en L : le second rectangle doit être plus étroit et plus profond.")
    return [(0.0, 0.0), (w1, 0.0), (w1, d1), (w2, d1), (w2, d2), (0.0, d2)]


def build_site(
    pts: list[tuple[float, float]],
    *,
    north_angle: float,
    access_edge: int,
    entrance: tuple[float, float] | None,
    cores: list[tuple[float, float, float, float]],
    mode: str,
    setbacks: list[float] | None,
) -> tuple[SiteSpec, str]:
    """A validated site (through ``read_site``) and its YAML text."""
    data: dict[str, Any] = {
        "footprint": [[x, y] for x, y in pts],
        "north_angle_deg": north_angle,
        "access_edge": access_edge,
        "mode": "plot" if mode == "plot" else "footprint",
    }
    if entrance:
        data["entrances"] = [{"point": list(entrance), "label": "Entrée", "main": True}]
    if cores:
        data["cores"] = [
            {"id": f"N{i + 1}", "rect": list(c), "kind": "core"} for i, c in enumerate(cores)
        ]
    if mode == "plot" and setbacks:
        data["setbacks"] = setbacks
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    checked = load_site_yaml(text)
    return checked, text


def site_svg(spec: SiteSpec) -> str:
    """Small SVG preview: outline, access edge, entrances and cores (y up)."""
    ext = spec.footprint.exterior
    xs = [p[0] for p in ext]
    ys = [p[1] for p in ext]
    pad = 2.0
    x0, y0 = min(xs) - pad, min(ys) - pad
    w, h = max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad

    def fy(y: float) -> float:
        return round(y0 + h - (y - y0), 3)

    pts = " ".join(f"{x},{fy(y)}" for x, y in ext)
    n = len(ext)
    a, b = ext[spec.access_edge], ext[(spec.access_edge + 1) % n]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0} {y0} {w} {h}" width="480">',
        f'<polygon points="{pts}" fill="#eef3f8" stroke="#333" stroke-width="0.2"/>',
        f'<line x1="{a[0]}" y1="{fy(a[1])}" x2="{b[0]}" y2="{fy(b[1])}" stroke="#d62728" '
        'stroke-width="0.5"/>',
    ]
    for c in spec.cores:
        cx, cy, cw, ch = c.rect
        parts.append(
            f'<rect x="{cx}" y="{fy(cy + ch)}" width="{cw}" height="{ch}" fill="#999" '
            'stroke="#333" stroke-width="0.1"/>'
        )
    for e in spec.entrances:
        parts.append(f'<circle cx="{e.point[0]}" cy="{fy(e.point[1])}" r="0.5" fill="#2ca02c"/>')
    parts.append("</svg>")
    return "".join(parts)


def load_site_yaml(text: str) -> SiteSpec:
    """Validate an uploaded ``site.yaml`` with ``read_site``."""
    from ale.program import read_site

    try:
        yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise UiError(f"YAML illisible : {exc}") from exc
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "site.yaml"
        p.write_text(text, encoding="utf-8")
        spec, issues = read_site(p)
    if spec is None:
        raise UiError("Site invalide : " + " ; ".join(i.message for i in issues))
    return spec
