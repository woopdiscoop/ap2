"""Builders of the Ticket 1.2c tests: DXF plans (millimetres unless stated) ingested into
a temporary workspace. Ground truth: the reference plan of ``cad_helpers`` has 2 rooms."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from typer.testing import Result

from ale.workspace import Workspace

Invoke = Callable[[Sequence[object]], Result]

#: Rooms per reference plan (``cad_helpers.add_plan_pairs``).
GT_ROOMS = 2


def plan_doc(
    *,
    insunits: int | None = 4,
    copies: int = 1,
    scale: float = 1.0,
    extra_layers: Sequence[str] = (),
    labels: bool = False,
) -> Any:
    """``copies`` reference plans 20 m apart, optional room labels and extra layers."""
    from cad_helpers import add_plan_pairs, new_doc

    doc = new_doc(insunits)
    msp = doc.modelspace()
    for i in range(copies):
        dx = i * 20000.0 * scale
        add_plan_pairs(msp, dx=dx, scale=scale)
        if labels:
            msp.add_text(
                "BUREAU", dxfattribs={"layer": "TEXTE LOCAUX", "height": 200.0 * scale}
            ).set_placement((dx + 2000.0 * scale, 2500.0 * scale))
    for k, layer in enumerate(extra_layers):
        y = (-3000.0 - 500.0 * k) * scale
        msp.add_line((0.0, y), (500.0 * scale, y), dxfattribs={"layer": layer})
    return doc


def save_doc(doc: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)
    return path


def query(ws: Workspace, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(ws.path("corpus.sqlite"))) as conn:
        return [tuple(r) for r in conn.execute(sql, params).fetchall()]


def execute(ws: Workspace, sql: str, params: tuple[Any, ...] = ()) -> None:
    with closing(sqlite3.connect(ws.path("corpus.sqlite"))) as conn:
        conn.execute(sql, params)
        conn.commit()


def unit_of(ws: Workspace, rel_path: str) -> tuple[str, int, str, str, str | None]:
    """(sha256, page, kind, status, reason) of the single unit of ``rel_path``."""
    rows = query(
        ws,
        "SELECT u.sha256, u.page, u.kind, u.status, u.reason FROM units u "
        "JOIN file_paths p ON p.sha256 = u.sha256 WHERE p.rel_path = ? ORDER BY u.page",
        (rel_path,),
    )
    assert len(rows) == 1, rows
    sha, page, kind, status, reason = rows[0]
    return str(sha), int(page), str(kind), str(status), reason


def event_count(ws: Workspace, event: str | None = None) -> int:
    if event is None:
        return int(query(ws, "SELECT COUNT(*) FROM events")[0][0])
    return int(query(ws, "SELECT COUNT(*) FROM events WHERE event = ?", (event,))[0][0])


def mtimes(root: Path) -> dict[str, int]:
    """mtime_ns of every file under ``root``."""
    return {
        p.relative_to(root).as_posix(): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()
    }
