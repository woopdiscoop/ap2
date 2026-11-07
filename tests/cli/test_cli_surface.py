"""Ticket 0.1 eval section 1: packaging and CLI surface (S01-S06)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ale import __version__

STUB_OPTIONS: dict[str, list[str]] = {
    "ingest": ["--workspace", "--input", "--recursive", "--no-recursive", "--include", "--meta"],
    "extract": ["--workspace", "--only-new", "--kind", "dwg", "dxf", "pdf", "raster"],
    "layers": ["--workspace"],
    "review": ["--workspace"],
    "rulebook build": ["--workspace", "--seed-rulebook", "--min-support"],
    "generate": ["--program", "--site", "--rulebook", "--out", "--seed", "--variants"],
    "status": ["--workspace", "--json"],
}

STUB_TICKETS: dict[str, str] = {
    "ingest": "1.1",
    "extract": "1.2\u20131.4",
    "layers": "1.2",
    "review": "1.6",
    "rulebook build": "2.2",
    "generate": "3.1\u20133.5",
    "status": "1.1",
}


@pytest.fixture
def stub_files(tmp_path: Path) -> dict[str, Path]:
    files = tmp_path / "inputs"
    (files / "drawings").mkdir(parents=True)
    paths = {
        "input": files / "drawings",
        "meta": files / "meta.csv",
        "program": files / "program.xlsx",
        "site": files / "site.yaml",
        "rulebook": files / "rulebook.yaml",
        "seed_rulebook": files / "seed.yaml",
        "out": files / "out",
    }
    for key in ("meta", "program", "site", "rulebook", "seed_rulebook"):
        paths[key].write_bytes(b"x")
    return paths


def stub_args(command: str, ws: Path, f: dict[str, Path]) -> list[str]:
    w = ["--workspace", str(ws)]
    table: dict[str, list[str]] = {
        "ingest": [
            "ingest",
            *w,
            "--input",
            str(f["input"]),
            "--no-recursive",
            "--include",
            "pdf,dxf",
            "--meta",
            str(f["meta"]),
        ],
        "extract": ["extract", *w, "--only-new", "--kind", "pdf"],
        "layers": ["layers", *w],
        "review": ["review", *w],
        "rulebook build": [
            "rulebook",
            "build",
            *w,
            "--seed-rulebook",
            str(f["seed_rulebook"]),
            "--min-support",
            "3",
        ],
        "generate": [
            "generate",
            "--program",
            str(f["program"]),
            "--site",
            str(f["site"]),
            "--rulebook",
            str(f["rulebook"]),
            "--out",
            str(f["out"]),
            "--seed",
            "7",
            "--variants",
            "2",
        ],
        "status": ["status", *w, "--json"],
    }
    return table[command]


def test_S01_install_entrypoint(run_ale) -> None:
    for script in (False, True):
        proc = run_ale(["--version"], script=script)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.decode().strip() == "0.1.0"
    assert __version__ == "0.1.0"


def test_S02_help_lists_all(invoke) -> None:
    result = invoke(["--help"])
    assert result.exit_code == 0
    for name in (
        "init",
        "doctor",
        "ingest",
        "extract",
        "layers",
        "review",
        "rulebook",
        "generate",
        "status",
    ):
        assert name in result.stdout
    assert "--log-level" in result.stdout
    assert "--version" in result.stdout
    rb = invoke(["rulebook", "--help"])
    assert rb.exit_code == 0
    assert "build" in rb.stdout


@pytest.mark.parametrize(
    ("command", "options"),
    [
        ("init", ["--workspace"]),
        ("doctor", ["--workspace", "--json"]),
        *STUB_OPTIONS.items(),
    ],
)
def test_S03_stub_options(invoke, command: str, options: list[str]) -> None:
    result = invoke([*command.split(), "--help"])
    assert result.exit_code == 0, result.output
    for option in options:
        assert option in result.stdout, f"{command}: {option} missing from --help"


@pytest.mark.parametrize("command", list(STUB_TICKETS))
def test_S04_stub_exit_code(
    invoke, make_ws, tmp_path: Path, stub_files: dict[str, Path], command: str
) -> None:
    ws = make_ws(tmp_path / "ws")
    result = invoke(stub_args(command, ws, stub_files))
    assert result.exit_code == 3, result.output
    ticket = STUB_TICKETS[command]
    assert f"ale {command}: not implemented yet (Ticket {ticket})" in result.stderr


@pytest.mark.parametrize(
    ("command", "replace", "value"),
    [
        ("ingest", "--input", "@missing_dir"),
        ("generate", "--variants", "0"),
        ("rulebook build", "--min-support", "0"),
        ("extract", "--kind", "foo"),
        # Additional checks of the same rule (RD 0.1 section 5 option constraints).
        ("generate", "--program", "@site.yaml"),
        ("generate", "--site", "@program.xlsx"),
        ("generate", "--seed", "-1"),
        ("ingest", "--meta", "@missing.csv"),
        ("ingest", "--include", " , "),
        ("rulebook build", "--seed-rulebook", "@missing.yaml"),
    ],
)
def test_S05_option_validation(
    invoke,
    make_ws,
    tmp_path: Path,
    stub_files: dict[str, Path],
    command: str,
    replace: str,
    value: str,
) -> None:
    ws = make_ws(tmp_path / "ws")
    args = stub_args(command, ws, stub_files)
    # "@name" = a path next to the existing input files.
    resolved = str(stub_files["input"].parent / value[1:]) if value.startswith("@") else value
    args[args.index(replace) + 1] = resolved
    result = invoke(args)
    assert result.exit_code == 2, result.output


def test_S05_option_validation_missing_workspace(invoke) -> None:
    result = invoke(["layers"])
    assert result.exit_code == 2
    assert "workspace" in result.stderr.lower()


def test_S06_workspace_env(invoke, make_ws, ap: Path, tmp_path: Path, doctor_env: Path) -> None:
    make_ws(ap)
    # Env only: doctor uses AP.
    result = invoke(["doctor", "--json"], env={"ALE_WORKSPACE": str(ap)})
    assert result.exit_code == 0, result.output
    checks = {c["name"]: c for c in json.loads(result.stdout)["checks"]}
    assert checks["workspace"]["status"] == "ok"
    assert Path(checks["workspace"]["detail"]) == ap

    # Both: the flag wins (env points at a non-workspace).
    bogus = tmp_path / "not_a_workspace"
    result = invoke(["doctor", "--json", "--workspace", str(ap)], env={"ALE_WORKSPACE": str(bogus)})
    assert result.exit_code == 0, result.output
    assert Path(json.loads(result.stdout)["checks"][1]["detail"]) == ap

    # Both, reversed: the (bad) flag wins over the (good) env.
    result = invoke(["doctor", "--workspace", str(bogus)], env={"ALE_WORKSPACE": str(ap)})
    assert result.exit_code == 4
