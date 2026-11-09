"""Static, offline review table and native-coordinate SVG previews (Ticket I.1)."""

from __future__ import annotations

import hashlib
import html
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ale.contracts.models import PlanGeometry
from ale.corpus.extract import _open_corpus, _write_atomic, plan_path
from ale.labels import plan_extent
from ale.workspace import Workspace, WorkspaceError


@dataclass(frozen=True)
class ReviewReport:
    path: Path
    plans: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {"path": str(self.path), "plans": list(self.plans)}


def _preview(plan: PlanGeometry) -> str:
    """Convert Y_DOWN native data to y-up, then display with the SVG y-axis flipped."""
    extent = plan_extent(plan)
    x0, y0, x1, y1 = extent or (0.0, 0.0, 1.0, 1.0)
    sign = -1 if plan.frame.value == "Y_DOWN" else 1
    if sign == -1:
        y0, y1 = -y1, -y0
    width, height = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    margin = max(width, height) * 0.02

    def points(coords: tuple[tuple[float, float], ...]) -> str:
        return " ".join(f"{x:.8g},{sign * y:.8g}" for x, y in coords)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Plan" '
        f'data-frame="Y_UP" viewBox="{x0 - margin:.8g} {-y1 - margin:.8g} '
        f'{width + 2 * margin:.8g} {height + 2 * margin:.8g}">',
        '<g transform="scale(1,-1)">',
    ]
    for room in plan.rooms:
        color = "#bdbdbd"
        if room.type is not None:
            hue = int(hashlib.sha256(room.type.encode("utf-8")).hexdigest()[:8], 16) % 360
            color = f"hsl({hue},55%,75%)"
        rings = (room.polygon.exterior, *room.polygon.holes)
        path = " ".join(f"M {points(ring)} Z" for ring in rings)
        parts.append(f'<path d="{path}" fill="{color}" fill-rule="evenodd"/>')
    for wall in plan.walls:
        parts.append(
            f'<polyline points="{points(wall.centerline.coords)}" fill="none" '
            'stroke="black" stroke-width="1.5" vector-effect="non-scaling-stroke"/>'
        )
    for opening in plan.openings:
        if opening.kind.value == "DOOR":
            parts.append(
                f'<polyline points="{points(opening.segment.coords)}" fill="none" '
                'stroke="red" stroke-width="2" vector-effect="non-scaling-stroke"/>'
            )
    parts.append("</g></svg>")
    return "".join(parts)


def run_review(ws: Workspace, *, all_plans: bool = False) -> ReviewReport:
    """Write the review page; data/flags come from extracted units and their plan files.

    One source alias (lexicographically first rel_path) represents deduplicated files.
    Missing/corrupt plan files are reported as workspace errors, not silently omitted.
    """
    rows: list[dict[str, Any]] = []
    with closing(_open_corpus(ws)) as conn:
        units = conn.execute(
            "SELECT u.sha256, u.page, u.kind, MIN(p.rel_path) FROM units u "
            "LEFT JOIN file_paths p ON p.sha256 = u.sha256 WHERE u.status = 'EXTRACTED' "
            "GROUP BY u.sha256, u.page, u.kind ORDER BY MIN(p.rel_path), u.page, u.sha256"
        ).fetchall()
        for sha, page, kind, rel_path in units:
            base = ws.path("extracted", str(sha), str(page))
            paths = sorted(base.glob("*/plan.json"), key=lambda p: p.parent.name)
            if not paths:
                raise WorkspaceError(f"No extracted plan.json for {rel_path}, page {page}")
            for path in paths:
                try:
                    plan = PlanGeometry.model_validate_json(path.read_bytes())
                    if (
                        plan.source_sha256 != sha
                        or plan.page != page
                        or plan.source_kind.value != kind
                        or path != plan_path(ws, sha, page, plan.plan_index)
                    ):
                        raise ValueError("plan identity does not match corpus path")
                except (OSError, ValueError) as exc:
                    raise WorkspaceError(f"Cannot review {path}: {exc}") from exc
                flags = [
                    str(r[0])
                    for r in conn.execute(
                        "SELECT flag FROM review_flags WHERE sha256 = ? AND page = ? "
                        "AND plan_index = ? ORDER BY flag",
                        (sha, page, plan.plan_index),
                    )
                ]
                if not all_plans and not flags:
                    continue
                typed = sum(r.type is not None for r in plan.rooms)
                rows.append(
                    {
                        "sha256": sha,
                        "rel_path": rel_path or sha,
                        "page": page,
                        "plan_index": plan.plan_index,
                        "kind": kind,
                        "scale_method": plan.scale_method.value,
                        "scale_confidence": plan.scale_confidence,
                        "room_count": len(plan.rooms),
                        "typed": typed,
                        "untyped": len(plan.rooms) - typed,
                        "flags": flags,
                        "preview_svg": _preview(plan),
                    }
                )
    rows.sort(key=lambda r: (r["rel_path"], r["page"], r["plan_index"], r["sha256"]))
    columns = (
        "rel_path",
        "page",
        "plan_index",
        "kind",
        "scale_method",
        "scale_confidence",
        "room_count",
        "typed",
        "untyped",
        "flags",
    )
    parts = [
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>ALE — revue des plans</title><style>",
        "body{font-family:sans-serif;margin:2rem}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccc;padding:.5rem;text-align:left}svg{width:320px;height:240px}",
        "</style></head><body><h1>Revue des plans</h1>",
        "<p>Pièces colorées par type, non typées en gris ; murs noirs, portes rouges.</p>",
        "<table><thead><tr>",
        *(f'<th scope="col">{html.escape(c)}</th>' for c in columns),
        '<th scope="col">Aperçu</th></tr></thead><tbody>',
    ]
    for row in rows:
        parts.append('<tr class="plan">')
        for column in columns:
            value = row[column]
            text = ", ".join(value) if isinstance(value, list) else str(value)
            parts.append(f"<td>{html.escape(text)}</td>")
        parts.append(f"<td>{row['preview_svg']}</td></tr>")
    parts.append("</tbody></table></body></html>")
    target = ws.path("review", "index.html")
    try:
        _write_atomic(target, "".join(parts).encode("utf-8"))
    except OSError as exc:
        raise WorkspaceError(f"Cannot write {target}: {exc}") from exc
    return ReviewReport(target, tuple(rows))
