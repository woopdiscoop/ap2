"""Ticket U.1 evaluation U101-U108 (Streamlit AppTest, small budgets, no network)."""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

pytest.importorskip("streamlit")
pytest.importorskip("openpyxl")
pytest.importorskip("pymupdf")
pytest.importorskip("ezdxf")

from streamlit.testing.v1 import AppTest

TESTS = Path(__file__).resolve().parents[1]
for sub in ("score", "program_annexe"):
    if str(TESTS / sub) not in sys.path:
        sys.path.insert(0, str(TESTS / sub))

import annexe_helpers as ah  # noqa: E402
from score_helpers import grid_of, save_programme, save_sheet, spec  # noqa: E402

from ale.cli import app as cli_app  # noqa: E402
from ale.ui import core  # noqa: E402

APP = str(Path(__file__).resolve().parents[2] / "src" / "ale" / "ui" / "app.py")
EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

if not hasattr(AppTest, "file_uploader"):  # pragma: no cover - old streamlit
    pytest.skip("AppTest without file_uploader support", allow_module_level=True)


def _app(tmp_path: Path, budget: float = 2.0) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["workspace"] = str(tmp_path / "ws")
    at.session_state["budget_s"] = budget
    return at.run()


def _upload(at: AppTest, key: str, path: Path) -> None:
    at.file_uploader(key=key).set_value((path.name, path.read_bytes(), XLSX))


def _annexe(tmp_path: Path) -> Path:
    sheet = ah.Sheet()
    sheet.add("PROGRAMME PHYSIQUE : SIEGE TEST")
    sheet.add(*ah.HEADER)
    sheet.blocks(ah.REGION_BLOCKS)
    return sheet.save(tmp_path / "annexe.xlsx")


def _errors(at: AppTest) -> list[str]:
    return [str(e.value) for e in at.error]


def test_U101_launch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(cli_app, ["ui", "--help"])
    assert res.exit_code == 0 and "--port" in res.output and "--workspace" in res.output

    real_find = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda n, *a: None if n == "streamlit" else real_find(n, *a)
    )
    res = runner.invoke(cli_app, ["ui"])
    assert res.exit_code == 3
    assert 'installez l\'extra ui : pip install -e ".[ui]"' in res.output
    monkeypatch.undo()

    calls: list[Any] = []

    def fake_call(cmd: list[str], env: dict[str, str]) -> int:
        calls.append((cmd, env))
        return 0

    monkeypatch.setattr(subprocess, "call", fake_call)
    res = runner.invoke(cli_app, ["ui", "--workspace", str(tmp_path / "w"), "--port", "8600"])
    assert res.exit_code == 0
    cmd, env = calls[0]
    assert cmd[1:4] == ["-m", "streamlit", "run"] and cmd[4].endswith("app.py")
    assert cmd[cmd.index("--server.port") + 1] == "8600"
    assert env["ALE_WORKSPACE"] == str(tmp_path / "w")


def test_U102_programme(tmp_path: Path) -> None:
    at = _app(tmp_path)
    _upload(at, "prog_file", _annexe(tmp_path))
    at.run()
    assert not at.exception
    assert not [e for e in _errors(at) if "illisible" in e]  # (site-check findings are content)
    assert at.selectbox(key="building").options == ["SIEGE TEST"]
    metrics = {m.label: str(m.value) for m in at.metric}
    assert metrics["Lignes"] == "9"
    assert metrics["Espaces (instances)"] == "17"
    assert metrics["Surface utile (m²)"] == "492.00"
    assert len(at.dataframe) == 1 and len(at.dataframe[0].value) == 9
    assert "Télécharger le programme ALE (xlsx)" in [b.label for b in at.download_button]
    saved = Path(at.session_state["program_path"])
    assert saved.is_file() and saved.suffix == ".xlsx"


def test_U103_site(tmp_path: Path) -> None:
    at = _app(tmp_path)
    assert not at.exception and not _errors(at)
    assert len(at.image) == 1  # rectangle preview
    text = Path(at.session_state["site_path"]).read_text(encoding="utf-8")
    from ale.program import read_site

    spec_, issues = read_site(Path(at.session_state["site_path"]))
    assert spec_ is not None and not issues and "footprint" in text
    at.radio(key="site_mode").set_value("plot")
    at.run()
    assert not at.exception and not _errors(at)
    plot, issues = read_site(Path(at.session_state["site_path"]))
    assert plot is not None and plot.mode == "plot" and plot.setbacks == (3.0,) * 4
    assert len(at.image) == 1
    at.radio(key="site_shape").set_value("L")
    at.run()
    assert not at.exception and not _errors(at)
    ell, _ = read_site(Path(at.session_state["site_path"]))
    assert ell is not None and len(ell.footprint.exterior) == 6


def test_U104_plans(tmp_path: Path) -> None:
    at = _app(tmp_path, budget=2.0)
    _upload(at, "plans_program", EXAMPLES / "p08_programme.xlsx")
    at.file_uploader(key="plans_site").set_value(
        ("p08_site.yaml", (EXAMPLES / "p08_site.yaml").read_bytes(), "text/yaml")
    )
    at.file_uploader(key="rulebook_file").set_value(
        ("rb.yaml", (EXAMPLES / "rulebook_seed_draft.yaml").read_bytes(), "text/yaml")
    )
    at.run()
    at.number_input(key="n_variants").set_value(2)
    at.button(key="run_generate").click()
    at.run()
    assert not at.exception and not _errors(at), _errors(at)
    assert len(at.image) >= 2  # the site-less page shows the 2 previews
    assert len(at.dataframe) == 1 and len(at.dataframe[0].value) == 2
    zipped = Path(at.session_state["plans_dir"])
    data = core.zip_folder(zipped)
    assert data and "summary.md" in zipfile.ZipFile(io.BytesIO(data)).namelist()
    labels = [b.label for b in at.download_button]
    assert "Tout télécharger (zip)" in labels and "Télécharger DXF" in labels


def test_U105_score(tmp_path: Path) -> None:
    drawn = [20.0, 40.0, 60.0, 80.0]
    pdf = save_sheet(tmp_path / "s.pdf", [grid_of(drawn, 2)])
    prog = save_programme(
        tmp_path / "p.xlsx", [spec(k, f"Bureau {k}", v) for k, v in zip("ABCD", drawn, strict=True)]
    )
    at = _app(tmp_path)
    at.file_uploader(key="score_plan").set_value((pdf.name, pdf.read_bytes(), "application/pdf"))
    _upload(at, "score_prog", prog)
    at.run()
    at.button(key="run_score").click()
    at.run()
    assert not at.exception and not _errors(at), _errors(at)
    md = " ".join(str(m.value) for m in at.markdown)
    assert "conforme" in md and "|" in md


def _plot_site(tmp_path: Path) -> Path:
    p = tmp_path / "plot.yaml"
    p.write_text(
        "footprint: [[0, 0], [30, 0], [30, 24], [0, 24]]\nnorth_angle_deg: 0\naccess_edge: 0\n"
        "mode: plot\nsetbacks: [3, 3, 3, 3]\n"
        "entrances:\n- {point: [15, 0], label: E, main: true}\n",
        encoding="utf-8",
    )
    return p


def test_U106_form_guard(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(core, "form_available", lambda: False)
    at = _app(tmp_path)
    assert not at.exception and not _errors(at)
    assert any("disponible après la fusion de G.3" in str(i.value) for i in at.info)
    monkeypatch.undo()

    at = _app(tmp_path)
    at.session_state["program_path"] = str(EXAMPLES / "p08_programme.xlsx")
    at.session_state["site_path"] = str(_plot_site(tmp_path))
    at.number_input(key="form_n").set_value(2)
    at.button(key="form_run").click()
    at.run()
    assert not at.exception and not _errors(at), _errors(at)
    assert any("2 candidat(s)" in str(m.value) for m in at.markdown)
    assert [b.key for b in at.button if str(b.key).startswith("use_form_")] == [
        "use_form_01",
        "use_form_02",
    ]
    at.button(key="use_form_02").click()
    at.run()
    assert Path(at.session_state["site_path"]).name == "form_02.yaml"


def test_U107_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"this is not a workbook")
    at = _app(tmp_path)
    _upload(at, "prog_file", bad)
    at.run()
    assert not at.exception
    assert _errors(at)
    at.radio(key="prog_kind").set_value("Modèle ALE")
    at.run()
    assert not at.exception and _errors(at)
    # the app keeps running: a good upload afterwards works
    at.radio(key="prog_kind").set_value("Annexe (programme physique)")
    _upload(at, "prog_file", _annexe(tmp_path))
    at.run()
    assert not at.exception and len(at.dataframe) == 1
    # invalid site yaml
    at.file_uploader(key="site_file").set_value(("s.yaml", b"footprint: [1, 2", "text/yaml"))
    at.run()
    assert not at.exception and _errors(at)


def test_U108_gates() -> None:
    from ale.contracts.lock import main as lock_main

    assert lock_main(["--check"]) == 0
    root = Path(__file__).resolve().parents[2]
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8").splitlines()
    assert any(line.strip() == 'pip install -e ".[dev,excel,cad,pdf,raster,vlm,ui]"' for line in ci)
    py = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'ui = ["streamlit>=1.30"]' in py and '"streamlit>=1.30",' in py
    # ruff, format, mypy strict and the ale.ui coverage (>= 80 %) are run as gate commands
    # and recorded in eval_report.md.
