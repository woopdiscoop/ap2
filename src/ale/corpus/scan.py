"""Walk the read-only input folder, filter and hash (Ticket 1.1 RD section 4).

Nothing here ever opens a file other than ``rb`` or changes anything under the input
folder. Symlinks (and Windows junctions) are not followed.
"""

from __future__ import annotations

import hashlib
import os
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "ARCHIVE_EXTENSIONS",
    "CHUNK_SIZE",
    "ScanResult",
    "ScannedFile",
    "is_inside",
    "scan",
    "sha256_file",
]

CHUNK_SIZE = 1024 * 1024
ARCHIVE_EXTENSIONS = frozenset({"zip", "rar"})


@dataclass(frozen=True)
class ScannedFile:
    path: Path
    #: Relative to the input root, ``/`` separators, NFC.
    rel_path: str
    #: Lower-case extension without the dot.
    ext: str
    size: int
    mtime_ns: int


@dataclass
class ScanResult:
    files: list[ScannedFile] = field(default_factory=list)
    skipped_archives: list[str] = field(default_factory=list)
    #: (rel_path, reason) of entries that could not be read (stat error, ...).
    errors: list[tuple[str, str]] = field(default_factory=list)


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _ext(name: str) -> str:
    _, dot, ext = name.rpartition(".")
    return ext.lower() if dot else ""


def _skipped_name(name: str) -> bool:
    return name.startswith(".") or name.startswith("~$")


def _is_link(entry: os.DirEntry[str]) -> bool:
    if entry.is_symlink():
        return True
    is_junction = getattr(entry, "is_junction", None)
    return bool(is_junction()) if is_junction is not None else False


def scan(root: Path, include: Iterable[str], recursive: bool = True) -> ScanResult:
    """Every regular file under ``root`` whose extension is in ``include``.

    Hidden entries (name starting with ``.``), ``~$*`` lock files and symlinks are
    skipped; ``.zip`` / ``.rar`` files are listed in ``skipped_archives`` instead.
    Results are sorted by ``rel_path``.
    """
    wanted = {e.strip().lstrip(".").lower() for e in include if e.strip()}
    result = ScanResult()
    stack: list[tuple[Path, str]] = [(root, "")]
    while stack:
        folder, prefix = stack.pop()
        try:
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError as exc:
            result.errors.append((prefix.rstrip("/") or ".", exc.strerror or str(exc)))
            continue
        for entry in entries:
            if _skipped_name(entry.name) or _is_link(entry):
                continue
            rel = _nfc(prefix + entry.name)
            try:
                if entry.is_dir(follow_symlinks=False):
                    if recursive:
                        stack.append((Path(entry.path), rel + "/"))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                ext = _ext(entry.name)
                if ext in ARCHIVE_EXTENSIONS:
                    result.skipped_archives.append(rel)
                    continue
                if ext not in wanted:
                    continue
                st = entry.stat(follow_symlinks=False)
            except OSError as exc:
                result.errors.append((rel, exc.strerror or str(exc)))
                continue
            result.files.append(ScannedFile(Path(entry.path), rel, ext, st.st_size, st.st_mtime_ns))
    result.files.sort(key=lambda f: f.rel_path)
    result.skipped_archives.sort()
    return result


def sha256_file(path: Path) -> str:
    """SHA-256 hex digest of ``path`` read in 1 MiB chunks (opened ``rb``)."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _key(path: Path) -> tuple[str, ...]:
    parts = path.resolve().parts
    return tuple(os.path.normcase(p) for p in parts)


def is_inside(inner: Path, outer: Path) -> bool:
    """True if ``inner`` is ``outer`` or lies below it (symlinks resolved, OS case rules)."""
    a, b = _key(inner), _key(outer)
    return a[: len(b)] == b
