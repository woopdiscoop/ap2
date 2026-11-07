"""Path helpers: normalisation, display and relativisation.

Everything uses :mod:`pathlib`; nothing here ever changes the process CWD.
"""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path

PathLike = str | os.PathLike[str]


def expand(value: PathLike) -> Path:
    """``Path(value)`` with ``~`` expanded (left as is if the home folder is unknown)."""
    path = Path(value)
    try:
        return path.expanduser()
    except RuntimeError:  # no home directory could be determined
        return path


def normalise(value: PathLike) -> Path:
    """Absolute, ``~``-expanded path for a user-supplied (CLI) path.

    Relative CLI paths are relative to the CWD, as the user typed them. Symlinks are
    not resolved so that messages show the path the user knows.
    """
    return expand(value).absolute()


def resolve_against(base: Path, value: PathLike) -> Path:
    """Resolve a path-valued configuration key against ``base`` (the workspace folder).

    Absolute (and ``~``) paths are kept; relative ones are joined to ``base`` and never
    interpreted against the process CWD.
    """
    path = expand(value)
    if path.is_absolute():
        return path
    return base / path


def display(path: PathLike) -> str:
    """The path as given by the OS, NFC-normalised, for messages."""
    return unicodedata.normalize("NFC", os.fspath(path))


def relativise(path: PathLike, base: Path) -> str:
    """``path`` relative to ``base`` with ``/`` separators when inside ``base``,
    otherwise its :func:`display` form."""
    p = Path(path)
    try:
        rel = p.relative_to(base)
    except ValueError:
        return display(p)
    return unicodedata.normalize("NFC", rel.as_posix())
