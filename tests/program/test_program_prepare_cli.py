"""Ticket 3.1 section 4: ``prepare_input``, the template and the CLI (P01-P08)."""

from __future__ import annotations

import json
import logging
import math
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fixtures import load_program, load_site
from program_helpers import (
    HEADERS,
    X07_ROWS,
    program_to_xlsx,
    site_to_yaml,
    write_rulebook,
    write_site_yaml,
    write_x07,
)
from typer.testing import CliRunner

from ale.cli import app
from ale.contracts.config import AleConfig
from ale.contracts.enums import TypeCategory
from ale.contracts.models import Rulebook
from ale.contracts.serialization import canonical_json
from ale.contracts.taxonomy import load_taxonomy
from ale.logging_setup import LOGGER_NAME, shutdown_logging
from ale.program import InputError, prepare_input, read_program
from ale.program.prepare import load_rulebook
from ale.program.template import TEMPLATE_PATH, write_template
from ale.program.template import main as template_main
from ale.workspace import Workspace

openpyxl = pytest.importorskip("openpyxl")  # the 'excel' extra

REPO = Path(__file__).resolve().parents[2]
CONFIG = AleConfig()


@pytest.fixture(autouse=True)
def _restore_logger() -> Iterator[None]:
    """In-process CLI calls reconfigure the ``ale`` logger: restore it afterwards."""
    logger = logging.getLogger(LOGGER_NAME)
    saved = (list(logger.handlers), logger.level, logger.propagate)
    yield
    shutdown_logging()
    handlers, level, propagate = saved
    for handler in list(logger.handlers):
        if handler not in handlers:
            logger.removeHandler(handler)
            handler.close()
    for handler in handlers:
        if handler not in logger.handlers:
            logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = propagate


def fixture_files(tmp_path: Path, program: str, site: str) -> tuple[Path, Path]:
    xlsx = program_to_xlsx(load_program(program), tmp_path / f"{program}.xlsx")  # type: ignore[arg-type]
    yml = site_to_yaml(load_site(site), tmp_path / f"{site}.yaml")  # type: ignore[arg-type]
    return xlsx, yml


def rotated_site(tmp_path: Path) -> Path:
    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    pts = [[x * c - y * s, x * s + y * c] for x, y in [(0, 0), (10, 0), (10, 10), (0, 10)]]
    return write_site_yaml(tmp_path / "rotated.yaml", {"footprint": pts})


def without_type(rulebook: Rulebook, key: str, path: Path) -> Path:
    types = {k: v for k, v in rulebook.types.items() if k != key}
    return write_rulebook(rulebook.model_copy(update={"types": types}), path)


# --------------------------------------------------------------------------- P01-P03


def test_P01_prepare_ok(tmp_path: Path, rulebook_path: Path) -> None:
    xlsx, yml = fixture_files(tmp_path, "program_60", "site_L")
    prepared = prepare_input(xlsx, yml, rulebook_path, CONFIG)
    assert len(prepared.instances) == 60
    assert prepared.instances == load_program("program_60").instances()
    assert prepared.footprint.polygon.exterior == (
        (0, 0),
        (480, 0),
        (480, 180),
        (300, 180),
        (300, 300),
        (0, 300),
    )
    assert prepared.grid.module_mm == 100
    assert prepared.rulebook_version == "test-3.1"
    assert prepared.site == load_site("site_L")
    assert prepared.warnings == ()
    assert prepared.feasibility.required_m2 == pytest.approx(1135.16)


def test_P02_collects_all(tmp_path: Path, rulebook: Rulebook) -> None:
    xlsx = write_x07(tmp_path / "x07.xlsx")
    rb = without_type(rulebook, "office", tmp_path / "rb.yaml")
    with pytest.raises(InputError) as info:
        prepare_input(xlsx, rotated_site(tmp_path), rb, CONFIG)
    found = {i.code for i in info.value.issues}
    assert {code for code, _ in X07_ROWS} <= found
    assert "E_SITE_NOT_ORTHOGONAL" in found
    assert "E_TYPE_NOT_IN_RULEBOOK" in found
    assert "office" in str([i.message for i in info.value.issues])
    assert "E_SITE_NOT_ORTHOGONAL" in str(info.value)


_P03_SCRIPT = """
import sys
from pathlib import Path
from ale.contracts.config import AleConfig
from ale.contracts.serialization import canonical_json
from ale.program import prepare_input
p = prepare_input(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), AleConfig())
Path(sys.argv[4]).write_bytes(canonical_json(p))
"""


def test_P03_deterministic(tmp_path: Path, rulebook_path: Path) -> None:
    xlsx, yml = fixture_files(tmp_path, "program_60", "site_L")
    outputs = []
    for k in range(2):
        out = tmp_path / f"run{k}.json"
        subprocess.run(
            [sys.executable, "-c", _P03_SCRIPT, str(xlsx), str(yml), str(rulebook_path), str(out)],
            check=True,
            timeout=50,
        )
        outputs.append(out.read_bytes())
    assert outputs[0] == outputs[1]
    assert outputs[0] == canonical_json(prepare_input(xlsx, yml, rulebook_path, CONFIG))


# --------------------------------------------------------------------------- P04-P05


def _validations(ws: Any) -> list[tuple[Any, ...]]:
    return sorted(
        (dv.type, dv.operator, dv.formula1, str(dv.sqref), bool(dv.allow_blank))
        for dv in ws.data_validations.dataValidation
    )


def _cells(wb: Any) -> dict[str, list[tuple[Any, ...]]]:
    return {ws.title: [tuple(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}


def test_P04_template_content(tmp_path: Path) -> None:
    out = write_template(tmp_path / "t.xlsx")
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["Programme", "Exemple", "Aide", "Listes"]
    assert wb["Listes"].sheet_state == "hidden"
    assert all(wb[n].sheet_state == "visible" for n in ("Programme", "Exemple", "Aide"))
    ws = wb["Programme"]
    assert [c.value for c in ws[1]] == HEADERS
    assert all(c.font.bold for c in ws[1])
    assert ws.freeze_panes == "A2"

    by_col: dict[str, Any] = {}
    for dv in ws.data_validations.dataValidation:
        col = re.match(r"([A-Z]+)2:", str(dv.sqref))
        assert col is not None
        assert str(dv.sqref).endswith("500")
        by_col[col.group(1)] = dv
    type_dv = by_col["C"]
    assert type_dv.type == "list"
    sheet, rng = type_dv.formula1.lstrip("=").split("!")
    values = [c.value for row in wb[sheet][rng.replace("$", "")] for c in row]
    expected = [
        t.label_fr
        for t in load_taxonomy().types
        if t.category in (TypeCategory.ROOM, TypeCategory.VERTICAL)
    ]
    assert len(expected) == 72
    assert values == expected
    assert by_col["F"].formula1 == '"Public,Administratif,Services"'
    assert by_col["G"].formula1 == '"Oui,Non"'
    assert (by_col["D"].type, by_col["D"].operator, by_col["D"].formula1) == (
        "decimal",
        "greaterThan",
        "0",
    )
    assert (by_col["E"].type, by_col["E"].operator, by_col["E"].formula1) == (
        "whole",
        "greaterThanOrEqual",
        "1",
    )
    aide = [r for r in wb["Aide"].iter_rows(min_row=2, values_only=True)]
    assert [r[0] for r in aide] == HEADERS
    assert [r[1] for r in aide][:4] == ["Oui"] * 4

    committed = openpyxl.load_workbook(TEMPLATE_PATH)
    assert committed.sheetnames == wb.sheetnames
    assert _cells(committed) == _cells(wb)
    for name in wb.sheetnames:
        assert _validations(committed[name]) == _validations(wb[name])
        assert committed[name].sheet_state == wb[name].sheet_state


def test_P05_template_example_reads(tmp_path: Path) -> None:
    copy = tmp_path / "copie.xlsx"
    shutil.copyfile(TEMPLATE_PATH, copy)
    wb = openpyxl.load_workbook(copy)
    wb["Programme"].title = "Vide"
    wb["Exemple"].title = "Programme"
    wb.save(copy)
    program, report = read_program(copy)
    assert report.issues == ()
    assert program == load_program("program_08")


def test_template_module_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "sub" / "m.xlsx"
    assert template_main([str(out)]) == 0
    assert out.is_file()
    assert str(out) in capsys.readouterr().out


# --------------------------------------------------------------------------- P06-P08


def _runner() -> CliRunner:
    try:  # click < 8.2 needs mix_stderr=False to expose result.stderr separately
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


def _check_args(xlsx: Path, yml: Path, rb: Path, *extra: str) -> list[str]:
    return [
        "program",
        "check",
        "--program",
        str(xlsx),
        "--site",
        str(yml),
        "--rulebook",
        str(rb),
        *extra,
    ]


def test_P06_cli_check(tmp_path: Path, rulebook_path: Path) -> None:
    runner = _runner()
    xlsx, yml = fixture_files(tmp_path, "program_08", "site_rect_small")
    result = runner.invoke(app, _check_args(xlsx, yml, rulebook_path))
    assert result.exit_code == 0, result.output
    assert "fill" in result.stdout
    assert "0.8850" in result.stdout

    bad = write_x07(tmp_path / "x07.xlsx")
    result = runner.invoke(app, _check_args(bad, yml, rulebook_path))
    assert result.exit_code == 1, result.output
    lines = result.stdout.splitlines()
    for n, (code, _) in enumerate(X07_ROWS, start=2):
        assert any(code in line and f"ligne {n}," in line for line in lines), (code, n)

    result = runner.invoke(app, _check_args(bad, yml, rulebook_path, "--json"))
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert set(payload) == {"ok", "issues", "feasibility"}
    assert payload["ok"] is False
    assert payload["feasibility"] is None
    assert sorted((i["code"], i["row"]) for i in payload["issues"]) == sorted(
        (code, n) for n, (code, _) in enumerate(X07_ROWS, start=2)
    )

    result = runner.invoke(app, _check_args(xlsx, yml, rulebook_path, "--json"))
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["feasibility"]["fill_ratio"] == pytest.approx(0.885)


def test_cli_check_workspace_and_usage(
    tmp_path: Path, rulebook_path: Path, tmp_workspace: Workspace
) -> None:
    runner = _runner()
    xlsx, yml = fixture_files(tmp_path, "program_25", "site_rect_small")
    args = _check_args(xlsx, yml, rulebook_path, "--workspace", str(tmp_workspace.root))
    result = runner.invoke(app, args)
    assert result.exit_code == 1  # P25 does not fit the small site
    assert "E_NOT_FEASIBLE" in result.stdout
    assert "Faisabilité" in result.stdout

    result = runner.invoke(
        app, _check_args(xlsx, yml, rulebook_path, "--workspace", str(tmp_path / "nope"))
    )
    assert result.exit_code == 4

    result = runner.invoke(app, _check_args(tmp_path / "absent.xlsx", yml, rulebook_path))
    assert result.exit_code == 2

    warn = program_to_xlsx(load_program("program_08"), tmp_path / "w.xlsx")
    wb = openpyxl.load_workbook(warn)
    wb["Programme"]["Q1"] = "Budget"
    wb.save(warn)
    small = site_to_yaml(load_site("site_rect_small"), tmp_path / "small.yaml")
    result = runner.invoke(app, _check_args(warn, small, rulebook_path))
    assert result.exit_code == 0
    assert "W_UNKNOWN_COLUMN" in result.stdout
    assert "Avertissements (1)" in result.stdout


def test_P07_cli_template(tmp_path: Path) -> None:
    runner = _runner()
    out = tmp_path / "t.xlsx"
    result = runner.invoke(app, ["program", "template", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert out.is_file()
    assert openpyxl.load_workbook(out).sheetnames == ["Programme", "Exemple", "Aide", "Listes"]
    result = runner.invoke(app, ["program", "template", "--out", str(out)])
    assert result.exit_code != 0
    result = runner.invoke(app, ["program", "template", "--out", str(out), "--force"])
    assert result.exit_code == 0


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def test_P08_cli_registration_only() -> None:
    target = "src/ale/cli/__init__.py"
    if shutil.which("git") is None or _git("rev-parse", "--git-dir").returncode != 0:
        pytest.skip("not a git checkout")
    log = _git("log", "--format=%H", "-S", "ale.cli.commands.program", "--", target)
    commits = log.stdout.split()
    if commits:
        intro = commits[-1]
        if _git("rev-parse", "--verify", "--quiet", f"{intro}^").returncode != 0:
            pytest.skip("shallow clone: parent of the registering commit is unavailable")
        diff = _git("diff", f"{intro}^", intro, "--", target).stdout
    else:  # not committed yet: compare the working tree with HEAD
        diff = _git("diff", "HEAD", "--", target).stdout
    added = [ln for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln for ln in diff.splitlines() if ln.startswith("-") and not ln.startswith("---")]
    assert removed == []
    assert len(added) == 1, added
    assert "add_typer" in added[0]
    assert "program" in added[0]


# --------------------------------------------------------------------------- rulebook loading


def test_load_rulebook_errors(tmp_path: Path, rulebook: Rulebook) -> None:
    rb, issues = load_rulebook(tmp_path / "absent.yaml")
    assert rb is None
    assert [i.code for i in issues] == ["E_FILE_UNREADABLE"]
    bad = tmp_path / "bad.yaml"
    bad.write_text("types: [unclosed\n", encoding="utf-8")
    assert [i.code for i in load_rulebook(bad)[1]] == ["E_RULEBOOK_INVALID"]
    bad.write_text("version: x\nkind: seed\n", encoding="utf-8")
    rb, issues = load_rulebook(bad)
    assert rb is None
    assert issues and {i.code for i in issues} == {"E_RULEBOOK_INVALID"}
    good = write_rulebook(rulebook, tmp_path / "good.yaml")
    assert load_rulebook(good) == (rulebook, ())


def test_prepare_input_rejects_infeasible(tmp_path: Path, rulebook_path: Path) -> None:
    xlsx, yml = fixture_files(tmp_path, "program_25", "site_rect_small")
    with pytest.raises(InputError) as info:
        prepare_input(xlsx, yml, rulebook_path, CONFIG)
    assert [i.code for i in info.value.issues] == ["E_NOT_FEASIBLE"]
    tiny = write_site_yaml(
        tmp_path / "tiny.yaml", {"footprint": [[0, 0], [0.05, 0], [0.05, 0.05], [0, 0.05]]}
    )
    with pytest.raises(InputError) as info:
        prepare_input(xlsx, tiny, rulebook_path, CONFIG)
    assert [i.code for i in info.value.issues] == ["E_SITE_TOO_SMALL"]
    assert InputError([]).issues == ()
    assert str(InputError([])) == "invalid input"
