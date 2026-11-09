"""Schema and migrations of ``corpus.sqlite`` (Ticket 1.1 RD section 3).

``ale init`` creates the database at ``user_version = 0`` with only the ``ale_meta``
table. :func:`migrate` brings it to :data:`SCHEMA_VERSION` (2) and is a no-op when the
database is already current. ``ale_meta`` is never touched.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "SCHEMA_VERSION",
    "CorpusDbError",
    "CorpusStatus",
    "add_event",
    "connect",
    "migrate",
    "read_status",
    "utc_now",
]

SCHEMA_VERSION = 2

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS inputs (
    id INTEGER PRIMARY KEY,
    root TEXT NOT NULL UNIQUE,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    sha256 TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    ext TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    excluded INTEGER NOT NULL DEFAULT 0,
    meta_json TEXT
);
CREATE TABLE IF NOT EXISTS file_paths (
    sha256 TEXT NOT NULL REFERENCES files,
    input_id INTEGER NOT NULL REFERENCES inputs,
    rel_path TEXT NOT NULL,
    mtime_ns INTEGER NOT NULL,
    size INTEGER NOT NULL,
    seen_at TEXT NOT NULL,
    PRIMARY KEY (input_id, rel_path)
);
CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL REFERENCES files,
    page INTEGER NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (sha256, page)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    sha256 TEXT,
    page INTEGER,
    event TEXT NOT NULL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS file_paths_sha256 ON file_paths (sha256);
CREATE INDEX IF NOT EXISTS events_event ON events (event);
"""


_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS review_flags (
    sha256 TEXT NOT NULL,
    page INTEGER NOT NULL,
    plan_index INTEGER NOT NULL,
    flag TEXT NOT NULL,
    PRIMARY KEY (sha256, page, plan_index, flag),
    FOREIGN KEY (sha256, page) REFERENCES units (sha256, page)
);
"""


class CorpusDbError(Exception):
    """``corpus.sqlite`` cannot be used (unknown schema version, I/O error)."""


def utc_now() -> str:
    """Current UTC time, ISO-8601 with ``Z`` (second precision)."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect(db_path: Path) -> sqlite3.Connection:
    """Open ``corpus.sqlite`` read-write with foreign keys on."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Migrate to :data:`SCHEMA_VERSION`; returns the version found before migrating."""
    found = _user_version(conn)
    if found > SCHEMA_VERSION:
        raise CorpusDbError(
            f"corpus.sqlite: schema version {found} is newer than supported ({SCHEMA_VERSION})"
        )
    if found < SCHEMA_VERSION:
        schema = (_SCHEMA_V1 if found < 1 else "") + _SCHEMA_V2
        conn.executescript(f"BEGIN;\n{schema}\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;")
    return found


def add_event(
    conn: sqlite3.Connection,
    event: str,
    sha256: str | None = None,
    page: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append one row to ``events`` (``detail`` stored as JSON)."""
    text = None if detail is None else json.dumps(detail, ensure_ascii=False, sort_keys=True)
    conn.execute(
        "INSERT INTO events (ts, sha256, page, event, detail) VALUES (?, ?, ?, ?, ?)",
        (utc_now(), sha256, page, event, text),
    )


@dataclass(frozen=True)
class CorpusStatus:
    """What ``ale status`` shows."""

    schema_version: int
    inputs: int
    files: int
    last_ingest: str | None
    #: (kind, status, count), sorted by kind then status.
    units: tuple[tuple[str, str, int], ...] = field(default_factory=tuple)

    @property
    def total_units(self) -> int:
        return sum(count for _, _, count in self.units)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "inputs": self.inputs,
            "files": self.files,
            "last_ingest": self.last_ingest,
            "total_units": self.total_units,
            "units": [
                {"kind": kind, "status": status, "count": count}
                for kind, status, count in self.units
            ],
        }


def read_status(db_path: Path) -> CorpusStatus:
    """Read the corpus counts without writing (a not-yet-migrated DB reads as empty)."""
    uri = db_path.resolve().as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            version = _user_version(conn)
            if version < 1:
                return CorpusStatus(schema_version=version, inputs=0, files=0, last_ingest=None)
            inputs = int(conn.execute("SELECT COUNT(*) FROM inputs").fetchone()[0])
            files = int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
            last = conn.execute("SELECT MAX(ts) FROM events WHERE event = 'ingest_end'").fetchone()
            rows = conn.execute(
                "SELECT kind, status, COUNT(*) FROM units GROUP BY kind, status "
                "ORDER BY kind, status"
            ).fetchall()
    except sqlite3.Error as exc:
        raise CorpusDbError(f"corpus.sqlite: cannot be read ({exc})") from exc
    return CorpusStatus(
        schema_version=version,
        inputs=inputs,
        files=files,
        last_ingest=last[0],
        units=tuple((str(k), str(s), int(c)) for k, s, c in rows),
    )
