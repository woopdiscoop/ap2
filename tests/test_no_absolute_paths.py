"""P02: no absolute path literals in ``src/ale`` (RD 0.1 section 10).

Every ``.py`` file under ``src/ale`` is parsed with :mod:`ast`; every string constant
that is not a docstring must not look like an absolute path.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "ale"
ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\[^\\]|/[A-Za-z0-9_.~-]|~[\\/])")

_DOC_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, _DOC_OWNERS) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                ids.add(id(first.value))
    return ids


def find_absolute_paths(source: str, filename: str = "<string>") -> list[tuple[int, str]]:
    """(line, value) of every non-docstring string constant matching the pattern."""
    tree = ast.parse(source, filename=filename)
    docstrings = _docstring_nodes(tree)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and ABSOLUTE.match(node.value)
        ):
            hits.append((node.lineno, node.value))
    return hits


def test_P02_no_absolute_paths() -> None:
    files = sorted(SRC.rglob("*.py"))
    assert len(files) >= 10
    violations = []
    for path in files:
        for line, value in find_absolute_paths(path.read_text(encoding="utf-8"), str(path)):
            violations.append(f"{path.relative_to(SRC.parent).as_posix()}:{line}: {value!r}")
    assert not violations, "absolute path literals:\n" + "\n".join(violations)


def test_P02_no_absolute_paths_checker_catches_planted_violation() -> None:
    planted = '''
"""Module docstring may mention /usr/bin and C:\\\\Windows freely."""

OK = "relative/path"
URLISH = "ale.toml"
WIN = "C:\\\\Program Files\\\\ODA"
WIN_FWD = "D:/Références/Plans 2024"
UNC = "\\\\\\\\server\\\\share"
POSIX = "/opt/oda"
HOME = "~/tools"
FSTR = f"/etc/{OK}"


def f() -> str:
    """Docstring: /var/log is fine here."""
    return "/tmp/x"


class C:
    """Docstring: ~/x is fine here."""

    attr = "~\\\\x"
'''
    hits = find_absolute_paths(planted)
    values = sorted(v for _, v in hits)
    assert values == sorted(
        [
            "C:\\Program Files\\ODA",
            "D:/Références/Plans 2024",
            "\\\\server\\share",
            "/opt/oda",
            "~/tools",
            "/etc/",
            "/tmp/x",
            "~\\x",
        ]
    )
    # Not flagged: docstrings, relative paths, plain names, a lone "/" or "~".
    assert not find_absolute_paths('X = "/"\nY = "~"\nZ = "a/b"\nW = "C:"\n')
