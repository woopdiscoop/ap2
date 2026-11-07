"""Load ``ale.toml`` into :class:`~ale.contracts.config.AleConfig` and format errors.

Every error is reported as one line ``ale.toml: <dotted.key>: <message>``. TOML syntax
errors, which have no key, are reported as ``ale.toml: line <n>, column <m>: <message>``.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ale.contracts.config import AleConfig
from ale.paths import resolve_against

__all__ = [
    "CONFIG_FILENAME",
    "AleConfig",
    "ConfigError",
    "format_validation_error",
    "load_config",
    "parse_config",
    "resolve_config_path",
]

CONFIG_FILENAME = "ale.toml"

_TOML_POS = re.compile(r"\s*\(at line (\d+), column (\d+)\)\s*$")
_TOML_EOF = re.compile(r"\s*\(at end of document\)\s*$")


class ConfigError(Exception):
    """Invalid configuration; ``lines`` holds one formatted message per problem."""

    def __init__(self, lines: list[str]) -> None:
        super().__init__("\n".join(lines))
        self.lines = lines


def _line(key: str, message: str) -> str:
    return f"{CONFIG_FILENAME}: {key}: {message}"


def format_validation_error(error: ValidationError) -> list[str]:
    """One ``ale.toml: <dotted.key>: <message>`` line per pydantic error."""
    lines: list[str] = []
    for item in error.errors(include_url=False):
        key = ".".join(str(part) for part in item["loc"]) or "<root>"
        lines.append(_line(key, item["msg"]))
    return lines


def _format_toml_error(error: tomllib.TOMLDecodeError) -> str:
    message = str(error)
    match = _TOML_POS.search(message)
    if match:
        where = f"line {match.group(1)}, column {match.group(2)}"
        return _line(where, message[: match.start()] or "invalid TOML")
    match = _TOML_EOF.search(message)
    if match:
        return _line("end of document", message[: match.start()] or "invalid TOML")
    return _line("syntax", message)


def parse_config(text: str) -> AleConfig:
    """Parse TOML text into :class:`AleConfig`; raises :class:`ConfigError`."""
    try:
        data: dict[str, Any] = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError([_format_toml_error(exc)]) from exc
    try:
        return AleConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(format_validation_error(exc)) from exc


def load_config(path: Path) -> AleConfig:
    """Read ``path`` as UTF-8 (a BOM is tolerated) and parse it."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConfigError([_line("encoding", f"file is not valid UTF-8 ({exc.reason})")]) from exc
    except OSError as exc:
        raise ConfigError([_line("file", f"cannot read file ({exc.strerror or exc})")]) from exc
    return parse_config(text)


def resolve_config_path(workspace_root: Path, value: str) -> Path:
    """Resolve a path-valued config key against the workspace folder (never the CWD)."""
    return resolve_against(workspace_root, value)
