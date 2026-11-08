"""``ingest(...)``: register an input folder into ``corpus.sqlite`` (Ticket 1.1 RD section 6).

Idempotent: a second run on an unchanged folder adds nothing. Files are recognised by
content (SHA-256); re-hashing is skipped when ``(input, rel_path, size, mtime_ns)`` is
unchanged. The input folder is only ever read.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ale.contracts.enums import FileStatus
from ale.corpus.classify import Classification, classify_file
from ale.corpus.db import CorpusDbError, add_event, connect, migrate, utc_now
from ale.corpus.meta import MetaRow, parse_meta
from ale.corpus.scan import ScannedFile, is_inside, scan, sha256_file
from ale.doctor import TOOLS, find_tool
from ale.paths import PathLike, display, normalise
from ale.workspace import CORPUS_FILENAME, Workspace, WorkspaceError

__all__ = [
    "DEFAULT_INCLUDE",
    "IngestReport",
    "check_input",
    "dwg_tool_available",
    "ingest",
]

log = logging.getLogger(__name__)

DEFAULT_INCLUDE: tuple[str, ...] = ("jpg", "jpeg", "png", "tif", "tiff", "pdf", "dwg", "dxf")


@dataclass
class IngestReport:
    input_root: str = ""
    files_seen: int = 0
    files_new: int = 0
    files_unchanged: int = 0
    duplicates: int = 0
    units_new: int = 0
    #: Units of the files seen in this run, by kind / by status (after meta is applied).
    units_by_kind: dict[str, int] = field(default_factory=dict)
    units_by_status: dict[str, int] = field(default_factory=dict)
    #: (rel_path, reason) of FAILED units of the files seen and of unreadable entries.
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped_archives: list[str] = field(default_factory=list)
    meta_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_root": self.input_root,
            "files_seen": self.files_seen,
            "files_new": self.files_new,
            "files_unchanged": self.files_unchanged,
            "duplicates": self.duplicates,
            "units_new": self.units_new,
            "units_by_kind": dict(self.units_by_kind),
            "units_by_status": dict(self.units_by_status),
            "failed": [list(item) for item in self.failed],
            "skipped_archives": list(self.skipped_archives),
            "meta_warnings": list(self.meta_warnings),
        }


def check_input(workspace_root: Path, input_root: Path) -> None:
    """Raise :class:`WorkspaceError` unless ``input_root`` is a folder disjoint from the
    workspace (neither inside the other)."""
    if not input_root.is_dir():
        raise WorkspaceError(f"input folder not found: {display(input_root)}")
    if is_inside(workspace_root, input_root):
        raise WorkspaceError(
            f"the workspace {display(workspace_root)} lies inside the input folder "
            f"{display(input_root)}; the input folder is read-only"
        )
    if is_inside(input_root, workspace_root):
        raise WorkspaceError(
            f"the input folder {display(input_root)} lies inside the workspace "
            f"{display(workspace_root)}"
        )


def dwg_tool_available(ws: Workspace, environ: Mapping[str, str] | None = None) -> bool:
    """True if ODA File Converter or accoreconsole is located (``ale doctor`` rules)."""
    for spec in TOOLS:
        configured = str(getattr(ws.config.tools, spec.config_key))
        path, _ = find_tool(spec, configured, ws.root, environ)
        if path is not None:
            return True
    return False


@dataclass
class _Context:
    conn: sqlite3.Connection
    input_id: int
    min_paths: int
    dwg_ok: bool
    report: IngestReport
    #: rel_path -> sha256 of every file seen in this run.
    seen: dict[str, str] = field(default_factory=dict)

    def classify(self, f: ScannedFile) -> Classification:
        return classify_file(
            f.path, f.ext, pdf_vector_min_paths=self.min_paths, dwg_tool_available=self.dwg_ok
        )


def _insert_units(ctx: _Context, sha: str, cls: Classification, rel_path: str) -> int:
    now = utc_now()
    ctx.conn.executemany(
        "INSERT INTO units (sha256, page, kind, status, reason, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(sha, u.page, u.kind.value, u.status.value, u.reason, now) for u in cls.units],
    )
    if cls.kind_mismatch:
        detail = {
            "rel_path": rel_path,
            "extension": cls.expected.value if cls.expected else None,
            "content": cls.content.value if cls.content else None,
        }
        add_event(ctx.conn, "kind_mismatch", sha, None, detail)
        log.warning(
            "%s: extension says %s, content is %s",
            rel_path,
            detail["extension"],
            detail["content"],
            extra={"event": "corpus.kind_mismatch", "rel_path": rel_path},
        )
    return len(cls.units)


def _maybe_reclassify(ctx: _Context, sha: str, f: ScannedFile) -> None:
    """Re-classify a known file whose units all wait for a tool that is now available."""
    statuses = {r[0] for r in ctx.conn.execute("SELECT status FROM units WHERE sha256 = ?", (sha,))}
    if statuses != {FileStatus.NEEDS_TOOL.value}:
        return
    cls = ctx.classify(f)
    if any(u.status is FileStatus.NEEDS_TOOL for u in cls.units):
        return
    ctx.conn.execute("DELETE FROM units WHERE sha256 = ?", (sha,))
    count = _insert_units(ctx, sha, cls, f.rel_path)
    ctx.report.units_new += count
    add_event(ctx.conn, "reclassified", sha, None, {"rel_path": f.rel_path, "units": count})


def _upsert_path(ctx: _Context, sha: str, f: ScannedFile, existed: bool) -> None:
    now = utc_now()
    if existed:
        ctx.conn.execute(
            "UPDATE file_paths SET sha256 = ?, mtime_ns = ?, size = ?, seen_at = ? "
            "WHERE input_id = ? AND rel_path = ?",
            (sha, f.mtime_ns, f.size, now, ctx.input_id, f.rel_path),
        )
    else:
        ctx.conn.execute(
            "INSERT INTO file_paths (sha256, input_id, rel_path, mtime_ns, size, seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sha, ctx.input_id, f.rel_path, f.mtime_ns, f.size, now),
        )


def _process_file(ctx: _Context, f: ScannedFile) -> None:
    report = ctx.report
    row = ctx.conn.execute(
        "SELECT sha256, size, mtime_ns FROM file_paths WHERE input_id = ? AND rel_path = ?",
        (ctx.input_id, f.rel_path),
    ).fetchone()
    if row is not None and row[1] == f.size and row[2] == f.mtime_ns:
        sha = str(row[0])
        ctx.conn.execute(
            "UPDATE file_paths SET seen_at = ? WHERE input_id = ? AND rel_path = ?",
            (utc_now(), ctx.input_id, f.rel_path),
        )
        report.files_seen += 1
        report.files_unchanged += 1
        ctx.seen[f.rel_path] = sha
        _maybe_reclassify(ctx, sha, f)
        return
    try:
        sha = sha256_file(f.path)
    except OSError as exc:
        report.failed.append((f.rel_path, f"cannot read file ({exc.strerror or exc})"))
        return
    report.files_seen += 1
    ctx.seen[f.rel_path] = sha
    known = ctx.conn.execute("SELECT 1 FROM files WHERE sha256 = ?", (sha,)).fetchone()
    if known is not None:
        _upsert_path(ctx, sha, f, existed=row is not None)
        if row is not None and row[0] == sha:  # touched, same bytes
            report.files_unchanged += 1
        else:
            report.duplicates += 1
            add_event(ctx.conn, "duplicate", sha, None, {"rel_path": f.rel_path})
        _maybe_reclassify(ctx, sha, f)
        return
    cls = ctx.classify(f)
    ctx.conn.execute(
        "INSERT INTO files (sha256, size, ext, first_seen) VALUES (?, ?, ?, ?)",
        (sha, f.size, f.ext, utc_now()),
    )
    _upsert_path(ctx, sha, f, existed=row is not None)
    report.files_new += 1
    report.units_new += _insert_units(ctx, sha, cls, f.rel_path)
    event = "modified" if row is not None else "new"
    detail: dict[str, Any] = {"rel_path": f.rel_path}
    if row is not None:
        detail["previous_sha256"] = row[0]
    add_event(ctx.conn, event, sha, None, detail)


def _resolve_meta_target(row: MetaRow, seen: Mapping[str, str], warnings: list[str]) -> str | None:
    where = f"plans_meta.csv line {row.line}"
    name = display(row.filename.replace("\\", "/")).removeprefix("./")
    if name in seen:
        return seen[name]
    if "/" not in name:
        shas = {sha for rel, sha in seen.items() if rel.rsplit("/", 1)[-1] == name}
        if len(shas) == 1:
            return shas.pop()
        if len(shas) > 1:
            warnings.append(f"{where}: file name {name!r} is ambiguous, row not applied")
            return None
    warnings.append(f"{where}: no ingested file matches {name!r}, row not applied")
    return None


def _apply_meta(ctx: _Context, rows: Sequence[MetaRow], warnings: list[str]) -> None:
    conn = ctx.conn
    for row in rows:
        sha = _resolve_meta_target(row, ctx.seen, warnings)
        if sha is None:
            continue
        if row.page is not None:
            unit = conn.execute(
                "SELECT 1 FROM units WHERE sha256 = ? AND page = ?", (sha, row.page)
            ).fetchone()
            if unit is None:
                warnings.append(
                    f"plans_meta.csv line {row.line}: page {row.page} not found, row not applied"
                )
                continue
        text = conn.execute("SELECT meta_json FROM files WHERE sha256 = ?", (sha,)).fetchone()[0]
        meta: dict[str, Any] = json.loads(text) if text else {}
        if row.fields:
            if row.page is None:
                meta.update(row.fields)
            else:
                meta.setdefault("pages", {}).setdefault(str(row.page), {}).update(row.fields)
            conn.execute(
                "UPDATE files SET meta_json = ? WHERE sha256 = ?",
                (json.dumps(meta, ensure_ascii=False, sort_keys=True), sha),
            )
        if row.exclude:
            now = utc_now()
            if row.page is None:
                conn.execute("UPDATE files SET excluded = 1 WHERE sha256 = ?", (sha,))
                conn.execute(
                    "UPDATE units SET status = ?, reason = ?, updated_at = ? "
                    "WHERE sha256 = ? AND status != ?",
                    (FileStatus.EXCLUDED.value, "plans_meta.csv", now, sha, "EXCLUDED"),
                )
            else:
                conn.execute(
                    "UPDATE units SET status = ?, reason = ?, updated_at = ? "
                    "WHERE sha256 = ? AND page = ? AND status != ?",
                    (FileStatus.EXCLUDED.value, "plans_meta.csv", now, sha, row.page, "EXCLUDED"),
                )
            add_event(conn, "excluded", sha, row.page, {"line": row.line})
    conn.commit()


def _summarise(ctx: _Context) -> None:
    report = ctx.report
    first_path: dict[str, str] = {}
    for rel, sha in sorted(ctx.seen.items()):
        first_path.setdefault(sha, rel)
    by_kind: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    failed: list[tuple[str, str]] = []
    for sha, rel in sorted(first_path.items(), key=lambda item: item[1]):
        units = ctx.conn.execute(
            "SELECT page, kind, status, reason FROM units WHERE sha256 = ? ORDER BY page", (sha,)
        ).fetchall()
        for page, kind, status, reason in units:
            by_kind[kind] += 1
            by_status[status] += 1
            if status == FileStatus.FAILED.value:
                prefix = f"page {page}: " if len(units) > 1 else ""
                failed.append((rel, prefix + str(reason)))
    report.units_by_kind = dict(sorted(by_kind.items()))
    report.units_by_status = dict(sorted(by_status.items()))
    report.failed = failed + report.failed


def _input_id(conn: sqlite3.Connection, root: str) -> int:
    row = conn.execute("SELECT id FROM inputs WHERE root = ?", (root,)).fetchone()
    if row is not None:
        return int(row[0])
    cur = conn.execute("INSERT INTO inputs (root, added_at) VALUES (?, ?)", (root, utc_now()))
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


def ingest(
    workspace: Workspace,
    input_dir: PathLike,
    include: Iterable[str] = DEFAULT_INCLUDE,
    recursive: bool = True,
    meta: PathLike | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> IngestReport:
    """Scan ``input_dir`` and register its files and units into the workspace corpus.

    Raises :class:`WorkspaceError` (nothing written) if the input is not a folder or
    overlaps the workspace, or if ``corpus.sqlite`` cannot be used.
    """
    input_root = normalise(input_dir)
    check_input(workspace.root, input_root)
    root_text = display(input_root)
    meta_parse = parse_meta(normalise(meta)) if meta is not None else None
    env = os.environ if environ is None else environ
    report = IngestReport(input_root=root_text)
    try:
        conn = connect(workspace.path(CORPUS_FILENAME))
    except sqlite3.Error as exc:  # pragma: no cover - open_workspace checked the file
        raise WorkspaceError(f"{CORPUS_FILENAME}: cannot be opened ({exc})") from exc
    with closing(conn):
        try:
            migrate(conn)
        except (CorpusDbError, sqlite3.Error) as exc:
            raise WorkspaceError(f"{CORPUS_FILENAME}: {exc}") from exc
        ctx = _Context(
            conn=conn,
            input_id=_input_id(conn, root_text),
            min_paths=workspace.config.extract.pdf_vector_min_paths,
            dwg_ok=dwg_tool_available(workspace, env),
            report=report,
        )
        add_event(conn, "ingest_start", None, None, {"input": root_text})
        conn.commit()
        result = scan(input_root, include, recursive)
        report.failed.extend(result.errors)
        for rel in result.skipped_archives:
            log.info(
                "archive not opened: %s",
                rel,
                extra={"event": "corpus.skipped_archive", "rel_path": rel},
            )
            add_event(conn, "skipped_archive", None, None, {"rel_path": rel})
        report.skipped_archives = list(result.skipped_archives)
        for f in result.files:
            _process_file(ctx, f)
            conn.commit()
        if meta_parse is not None:
            report.meta_warnings = list(meta_parse.warnings)
            _apply_meta(ctx, meta_parse.rows, report.meta_warnings)
        _summarise(ctx)
        summary = {
            k: v
            for k, v in report.to_dict().items()
            if k not in ("failed", "skipped_archives", "meta_warnings")
        }
        add_event(conn, "ingest_end", None, None, summary)
        conn.commit()
    log.info(
        "ingested %s: %d files seen, %d new, %d units new",
        root_text,
        report.files_seen,
        report.files_new,
        report.units_new,
        extra={"event": "corpus.ingest", **summary},
    )
    return report
