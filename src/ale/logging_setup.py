"""Logging for the ``ale.*`` namespace (RD 0.1 section 11).

* Console handler on stderr, human-readable, level from ``--log-level`` (or
  ``[logging].level``).
* When a workspace is open: ``logs/ale-YYYYMMDD.log`` (UTC date), JSON lines with
  ``ts``, ``level``, ``logger``, ``event``, ``msg`` plus extras, level DEBUG, UTF-8.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO, cast

__all__ = [
    "LOGGER_NAME",
    "JsonLineFormatter",
    "attach_workspace_log",
    "configure_logging",
    "set_console_level",
    "shutdown_logging",
]

LOGGER_NAME = "ale"
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

_STANDARD_ATTRS = frozenset(
    logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None).__dict__
) | {"message", "asctime", "taskName", "event"}


def _utc_iso(timestamp: float) -> str:
    stamp = datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="milliseconds")
    return stamp.replace("+00:00", "Z")


class JsonLineFormatter(logging.Formatter):
    """One JSON object per record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _utc_iso(record.created),
            "level": record.levelname,
            "logger": record.name,
            "event": str(getattr(record, "event", "log")),
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class _ConsoleHandler(logging.Handler):
    """Writes to the *current* ``sys.stderr`` (which test runners may swap)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stream: TextIO = sys.stderr
            stream.write(self.format(record) + "\n")
            stream.flush()
        except Exception:  # pragma: no cover - logging must never raise
            self.handleError(record)


class _Utf8FileHandler(logging.FileHandler):
    """UTF-8 file handler writing ``\\n`` line endings on every OS."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, mode="a", encoding="utf-8", delay=True)

    def _open(self) -> Any:
        return cast(Any, Path(self.baseFilename).open(self.mode, encoding="utf-8", newline="\n"))


def _logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def _close_handlers(logger: logging.Logger, kind: type[logging.Handler]) -> None:
    for handler in list(logger.handlers):
        if isinstance(handler, kind):
            logger.removeHandler(handler)
            handler.close()


def configure_logging(level: str = "INFO") -> None:
    """(Re)initialise the ``ale`` logger with a single console handler."""
    logger = _logger()
    _close_handlers(logger, logging.Handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    console = _ConsoleHandler(level=level.upper())
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(console)


def set_console_level(level: str) -> None:
    for handler in _logger().handlers:
        if isinstance(handler, _ConsoleHandler):
            handler.setLevel(level.upper())


def attach_workspace_log(logs_dir: Path) -> Path | None:
    """Add the JSON-lines file handler in ``logs_dir``; returns the log file path.

    Does nothing (returns ``None``) if ``logs_dir`` does not exist: opening a workspace
    never creates folders.
    """
    if not logs_dir.is_dir():
        return None
    logger = _logger()
    _close_handlers(logger, _Utf8FileHandler)
    path = logs_dir / f"ale-{datetime.now(UTC):%Y%m%d}.log"
    handler = _Utf8FileHandler(path)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(JsonLineFormatter())
    logger.addHandler(handler)
    return path


def shutdown_logging() -> None:
    """Close the workspace log file (so the folder can be deleted, also on Windows)."""
    _close_handlers(_logger(), _Utf8FileHandler)
