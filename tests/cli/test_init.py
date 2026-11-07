"""Ticket 0.1 eval section 2: `ale init` (I01-I07)."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import sys
import uuid
from contextlib import closing
from pathlib import Path

import pytest
from pydantic import BaseModel

from ale.config import load_config
from ale.contracts.config import AleConfig

EXPECTED_TREE = {
    "ale.toml",
    "layer_map.yaml",
    "corpus.sqlite",
    "cache",
    "cache/dxf",
    "cache/raster",
    "cache/vlm",
    "extracted",
    "rulebook",
    "logs",
}
KEY_LINE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=")


def leaf_count(model: BaseModel) -> int:
    total = 0
    for name in type(model).model_fields:
        value = getattr(model, name)
        total += leaf_count(value) if isinstance(value, BaseModel) else 1
    return total


def tree(root: Path) -> set[str]:
    """Relative paths under root, ignoring files inside logs/."""
    rels = {p.relative_to(root).as_posix() for p in root.rglob("*")}
    return {r for r in rels if not r.startswith("logs/")}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


def assert_exact_tree(root: Path) -> None:
    assert tree(root) == EXPECTED_TREE
    for rel in EXPECTED_TREE - {"ale.toml", "layer_map.yaml", "corpus.sqlite"}:
        assert (root / rel).is_dir()
    for p in (root / "logs").rglob("*"):
        assert p.is_file()


def check_idempotent(run, root: Path) -> None:
    """Shared body of I04 / I07: `run(root) -> (exit_code, stdout)`."""
    files = ("ale.toml", "layer_map.yaml", "corpus.sqlite")
    before = {name: sha256(root / name) for name in files}
    (root / "cache" / "vlm").rmdir()
    code, out = run(root)
    assert code == 0
    assert "workspace already initialised" in out
    assert {name: sha256(root / name) for name in files} == before
    assert (root / "cache" / "vlm").is_dir()
    assert_exact_tree(root)

    edited = (
        (root / "ale.toml")
        .read_text(encoding="utf-8")
        .replace("module_mm = 100", "module_mm = 300")
    )
    (root / "ale.toml").write_text(edited, encoding="utf-8", newline="\n")
    code, _ = run(root)
    assert code == 0
    assert (root / "ale.toml").read_text(encoding="utf-8") == edited
    assert load_config(root / "ale.toml").grid.module_mm == 300


def test_I01_exact_tree(invoke, ap: Path) -> None:
    result = invoke(["init", "--workspace", str(ap)])
    assert result.exit_code == 0, result.output
    assert_exact_tree(ap)


def test_I02_corpus_db(make_ws, ap: Path) -> None:
    make_ws(ap)
    with closing(sqlite3.connect(ap / "corpus.sqlite")) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert tables == ["ale_meta"]
        cols = [(r[1], r[2], r[3], r[5]) for r in conn.execute("PRAGMA table_info(ale_meta)")]
        assert cols == [("key", "TEXT", 0, 1), ("value", "TEXT", 1, 0)]
        meta = dict(conn.execute("SELECT key, value FROM ale_meta").fetchall())
    assert set(meta) == {"workspace_id", "created_at", "ale_version", "format_version"}
    assert uuid.UUID(meta["workspace_id"]).version == 4
    assert str(uuid.UUID(meta["workspace_id"])) == meta["workspace_id"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z", meta["created_at"])
    assert meta["ale_version"] == "0.1.0"
    assert meta["format_version"] == "1"


def test_I03_template_config_valid(make_ws, ap: Path) -> None:
    make_ws(ap)
    assert load_config(ap / "ale.toml") == AleConfig()
    lines = (ap / "ale.toml").read_text(encoding="utf-8").splitlines()
    keys = 0
    for i, line in enumerate(lines):
        if KEY_LINE.match(line):
            keys += 1
            assert i > 0 and lines[i - 1].lstrip().startswith("#"), f"no comment above: {line}"
    assert keys == leaf_count(AleConfig()) == 44  # every key of RD 0.1 section 6
    layer_map = (ap / "layer_map.yaml").read_text(encoding="utf-8")
    assert layer_map == (
        "# Map CAD layer names to roles. Proposed by `ale layers`; edit and keep.\n"
        "# Roles: wall, door, window, room_label, area_label, zone, furniture, ignore\n"
        "version: 1\n"
        "layers: {}\n"
    )


def test_I04_idempotent(invoke, make_ws, ap: Path) -> None:
    make_ws(ap)

    def run(root: Path) -> tuple[int, str]:
        result = invoke(["init", "--workspace", str(root)])
        return result.exit_code, result.stdout

    check_idempotent(run, ap)


def test_I05_refuses_foreign_dir(invoke, tmp_path: Path) -> None:
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_bytes(b"my notes\n")
    before = snapshot(foreign)
    result = invoke(["init", "--workspace", str(foreign)])
    assert result.exit_code == 4
    assert "not empty" in result.stderr
    assert snapshot(foreign) == before


def test_I05_refuses_foreign_dir_file_target(invoke, tmp_path: Path) -> None:
    target = tmp_path / "a_file"
    target.write_bytes(b"x")
    result = invoke(["init", "--workspace", str(target)])
    assert result.exit_code == 4
    assert target.read_bytes() == b"x"


def test_I06_empty_existing_dir(invoke, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = invoke(["init", "--workspace", str(empty)])
    assert result.exit_code == 0, result.output
    assert "workspace created" in result.stdout
    assert_exact_tree(empty)


@pytest.mark.parametrize(
    "sep",
    [
        "/",
        pytest.param(
            "\\",
            marks=[
                pytest.mark.windows_only,
                pytest.mark.skipif(sys.platform != "win32", reason="Windows-only separator"),
            ],
        ),
    ],
)
def test_I07_awkward_paths(run_ale, ap: Path, sep: str) -> None:
    def as_arg(root: Path) -> str:
        return root.as_posix() if sep == "/" else str(root).replace("/", "\\")

    def run(root: Path) -> tuple[int, str]:
        proc = run_ale(["init", "--workspace", as_arg(root)], PYTHONIOENCODING="utf-8")
        assert b"Traceback" not in proc.stderr, proc.stderr
        return proc.returncode, proc.stdout.decode("utf-8")

    code, _ = run(ap)
    assert code == 0
    assert_exact_tree(ap)
    check_idempotent(run, ap)
