"""Contract lock file: SHA-256 of every file of the ``ale.contracts`` package.

Usage: ``python -m ale.contracts.lock [--check]``. Writes ``CONTRACTS.lock`` next to this
module with one line ``<sha256>  <relative path>`` per file (paths relative to the package
directory, POSIX separators, sorted; the lock file itself and ``__pycache__`` excluded).
``--check`` exits 1 on any difference and names the differing files.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Sequence
from pathlib import Path

__all__ = ["LOCK_NAME", "PACKAGE_DIR", "compute_lock", "diff_lock", "main", "parse_lock", "run"]

LOCK_NAME = "CONTRACTS.lock"
PACKAGE_DIR = Path(__file__).resolve().parent


def compute_lock(root: Path) -> dict[str, str]:
    """Map relative path → sha256 hex for every file under ``root`` (sorted by path)."""
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if not path.is_file() or "__pycache__" in rel.parts or rel.as_posix() == LOCK_NAME:
            continue
        entries[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(entries.items()))


def render_lock(entries: dict[str, str]) -> str:
    """Lock file text: ``<sha256>  <relative path>`` lines."""
    return "".join(f"{digest}  {rel}\n" for rel, digest in entries.items())


def parse_lock(text: str) -> dict[str, str]:
    """Parse lock file text into relative path → sha256."""
    entries: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, _, rel = line.partition("  ")
        entries[rel] = digest
    return entries


def diff_lock(expected: dict[str, str], actual: dict[str, str]) -> list[str]:
    """Human-readable differences between a recorded lock and the current files."""
    out: list[str] = []
    for rel in sorted(set(expected) | set(actual)):
        if rel not in actual:
            out.append(f"missing file: {rel}")
        elif rel not in expected:
            out.append(f"unlocked file: {rel}")
        elif expected[rel] != actual[rel]:
            out.append(f"changed file: {rel}")
    return out


def run(root: Path, check: bool) -> int:
    """Write the lock for ``root``, or with ``check`` verify it; return the exit code."""
    lock_path = root / LOCK_NAME
    actual = compute_lock(root)
    if not check:
        lock_path.write_text(render_lock(actual), encoding="utf-8", newline="\n")
        print(f"wrote {lock_path} ({len(actual)} files)")
        return 0
    if not lock_path.is_file():
        print(f"{LOCK_NAME} missing: {lock_path}")
        return 1
    problems = diff_lock(parse_lock(lock_path.read_text(encoding="utf-8")), actual)
    for p in problems:
        print(p)
    if problems:
        return 1
    print("OK")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(prog="python -m ale.contracts.lock")
    parser.add_argument("--check", action="store_true", help="exit 1 on any difference")
    args = parser.parse_args(argv)
    return run(PACKAGE_DIR, args.check)


if __name__ == "__main__":
    sys.exit(main())
