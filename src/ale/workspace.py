"""Create, open and validate an ALE workspace (RD 0.1 sections 7 and 8)."""

from __future__ import annotations

import enum
import logging
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from ale import __version__
from ale.config import CONFIG_FILENAME, AleConfig, ConfigError, load_config
from ale.paths import PathLike, display, normalise

__all__ = [
    "CORPUS_FILENAME",
    "FORMAT_VERSION",
    "LAYER_MAP_FILENAME",
    "SUBFOLDERS",
    "InitResult",
    "Workspace",
    "WorkspaceError",
    "init_workspace",
    "is_workspace",
    "open_workspace",
]

log = logging.getLogger(__name__)

FORMAT_VERSION = 1
LAYER_MAP_FILENAME = "layer_map.yaml"
CORPUS_FILENAME = "corpus.sqlite"
META_TABLE = "ale_meta"

#: Every sub-folder of a workspace, parents before children.
SUBFOLDERS: tuple[tuple[str, ...], ...] = (
    ("cache",),
    ("cache", "dxf"),
    ("cache", "raster"),
    ("cache", "vlm"),
    ("extracted",),
    ("rulebook",),
    ("logs",),
)


class WorkspaceError(Exception):
    """Invalid or unusable workspace (CLI exit code 4).

    ``lines`` holds the message lines to show, e.g. one ``ale.toml: key: msg`` per
    configuration error.
    """

    def __init__(self, message: str | list[str]) -> None:
        lines = [message] if isinstance(message, str) else list(message)
        super().__init__("\n".join(lines))
        self.lines = lines


class InitResult(enum.Enum):
    CREATED = "created"
    ALREADY_INITIALISED = "already_initialised"


@dataclass(frozen=True)
class Workspace:
    """An opened, validated workspace."""

    root: Path
    config: AleConfig

    def path(self, *parts: str) -> Path:
        """Path of a workspace sub-folder or file, e.g. ``ws.path("cache", "dxf")``."""
        return self.root.joinpath(*parts)


def _template_text(name: str) -> str:
    return resources.files("ale").joinpath("templates", name).read_text(encoding="utf-8")


def is_workspace(path: Path) -> bool:
    """True if ``path`` looks like an ALE workspace (``ale.toml`` and ``corpus.sqlite``)."""
    return (path / CONFIG_FILENAME).is_file() and (path / CORPUS_FILENAME).is_file()


def _create_folders(root: Path) -> list[Path]:
    created: list[Path] = []
    for parts in SUBFOLDERS:
        folder = root.joinpath(*parts)
        if not folder.is_dir():
            folder.mkdir(parents=True, exist_ok=True)
            created.append(folder)
    return created


def _create_corpus(db_path: Path) -> None:
    created_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rows = [
        ("workspace_id", str(uuid.uuid4())),
        ("created_at", created_at),
        ("ale_version", __version__),
        ("format_version", str(FORMAT_VERSION)),
    ]
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA user_version = 0")
        conn.execute(f"CREATE TABLE {META_TABLE} (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.executemany(f"INSERT INTO {META_TABLE} (key, value) VALUES (?, ?)", rows)
        conn.commit()


def init_workspace(path: PathLike) -> tuple[Path, InitResult]:
    """Create a workspace at ``path`` (RD 0.1 section 7).

    Returns the absolute root and whether it was created or already initialised.
    Raises :class:`WorkspaceError` (and changes nothing) if ``path`` is a file or a
    non-empty folder that is not a workspace.
    """
    root = normalise(path)
    if root.exists():
        if not root.is_dir():
            raise WorkspaceError(f"not a folder: {display(root)}")
        if is_workspace(root):
            created = _create_folders(root)
            log.debug(
                "workspace already initialised",
                extra={"event": "workspace.init.exists", "created_folders": len(created)},
            )
            return root, InitResult.ALREADY_INITIALISED
        if any(root.iterdir()):
            raise WorkspaceError(
                f"folder is not empty and is not an ALE workspace: {display(root)}"
            )
    else:
        root.mkdir(parents=True)

    for name in (CONFIG_FILENAME, LAYER_MAP_FILENAME):
        (root / name).write_text(_template_text(name), encoding="utf-8", newline="\n")
    _create_corpus(root / CORPUS_FILENAME)
    _create_folders(root)
    log.debug("workspace created", extra={"event": "workspace.init.created"})
    return root, InitResult.CREATED


def _check_corpus(db_path: Path) -> None:
    if not db_path.is_file():
        raise WorkspaceError(f"{CORPUS_FILENAME} not found in workspace")
    uri = db_path.resolve().as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                (META_TABLE,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise WorkspaceError(f"{CORPUS_FILENAME}: cannot be opened ({exc})") from exc
    if row is None:
        raise WorkspaceError(f"{CORPUS_FILENAME}: table {META_TABLE} is missing")


def open_workspace(path: PathLike) -> Workspace:
    """Open and validate a workspace (RD 0.1 section 8); raises :class:`WorkspaceError`."""
    root = normalise(path)
    if not root.is_dir():
        raise WorkspaceError(f"workspace folder not found: {display(root)}")
    config_path = root / CONFIG_FILENAME
    if not config_path.is_file():
        raise WorkspaceError(f"{CONFIG_FILENAME} not found in workspace {display(root)}")
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        raise WorkspaceError(exc.lines) from exc
    if config.workspace.format_version != FORMAT_VERSION:  # pragma: no cover - model enforces
        raise WorkspaceError(
            f"{CONFIG_FILENAME}: workspace.format_version: unsupported version "
            f"{config.workspace.format_version}"
        )
    _check_corpus(root / CORPUS_FILENAME)
    return Workspace(root=root, config=config)
