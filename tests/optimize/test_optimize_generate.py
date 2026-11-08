"""Ticket 3.4 eval O07-O09: ``generate`` and ``ale generate``."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from optimize_helpers import RULEBOOK_TEST, optimizer_config, write_inputs
from program_helpers import write_x07
from typer.testing import CliRunner, Result

from ale.cli import app
from ale.contracts.models import Program, SiteSpec
from ale.geometry import Failure, Realization
from ale.logging_setup import shutdown_logging
from ale.optimize import generate
from ale.program.models import InputError

# ``ale.optimize.generate`` the module (the package attribute is the function).
gen_mod = importlib.import_module("ale.optimize.generate")

RUN_FILES = ("layout.json", "layout.dxf", "preview.svg", "report.md")


def _runner() -> CliRunner:
    try:  # click < 8.2 needs mix_stderr=False to expose result.stderr separately
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


def _invoke(args: list[str]) -> Result:
    try:
        return _runner().invoke(app, args)
    finally:
        shutdown_logging()


def _workspace(tmp: Path, budget_s: float) -> Path:
    """A workspace created by ``ale init`` whose ``[optimizer].time_budget_s`` is small."""
    root = tmp / "ws"
    res = _invoke(["init", "--workspace", str(root)])
    assert res.exit_code == 0, res.output
    toml = root / "ale.toml"
    text = toml.read_text(encoding="utf-8")
    assert "time_budget_s = 120.0" in text
    toml.write_text(text.replace("time_budget_s = 120.0", f"time_budget_s = {budget_s}"))
    return root


@pytest.fixture
def p25_inputs(tmp_path: Path, program_25: Program, site_rect: SiteSpec) -> tuple[Path, Path]:
    return write_inputs(tmp_path / "in", program_25, site_rect)


# ------------------------------------------------------------------------------ O07
@pytest.mark.timeout(120)
def test_O07_generate_cli(tmp_path: Path, p25_inputs: tuple[Path, Path]) -> None:
    xlsx, yml = p25_inputs
    ws = _workspace(tmp_path, 3.0)
    out = tmp_path / "run é"
    res = _invoke(
        [
            "generate",
            "--program",
            str(xlsx),
            "--site",
            str(yml),
            "--rulebook",
            str(RULEBOOK_TEST),
            "--out",
            str(out),
            "--variants",
            "3",
            "--seed",
            "1",
            "--workspace",
            str(ws),
        ]
    )
    assert res.exit_code == 0, res.output + res.stderr
    for k in (1, 2, 3):
        folder = out / f"variant_{k:02d}"
        for name in RUN_FILES:
            assert (folder / name).is_file(), folder / name
        assert f"run é-v{k}" in (folder / "report.md").read_text(encoding="utf-8")
    summary = (out / "summary.md").read_text(encoding="utf-8")
    rows = [line for line in summary.splitlines() if line.startswith("| 0")]
    assert [r.split("|")[1].strip() for r in rows] == ["01", "02", "03"]
    assert "Variante" in summary and "Coût final" in summary and "Circulation" in summary
    assert "synthèse" in res.stdout


@pytest.mark.timeout(120)
def test_generate_cli_default_seed(tmp_path: Path, p25_inputs: tuple[Path, Path]) -> None:
    xlsx, yml = p25_inputs
    ws = _workspace(tmp_path, 1.0)
    toml = ws / "ale.toml"
    text = toml.read_text(encoding="utf-8")
    toml.write_text(text.replace("seed = 42", "seed = 5"), encoding="utf-8")
    out = tmp_path / "out"
    args = ["generate", "--program", str(xlsx), "--site", str(yml)]
    args += ["--rulebook", str(RULEBOOK_TEST), "--out", str(out), "--workspace", str(ws)]
    res = _invoke(args)
    assert res.exit_code == 0, res.output + res.stderr
    assert "Graine de base : 5" in (out / "summary.md").read_text(encoding="utf-8")
    # A second run into the same folder refuses to overwrite: exit 1.
    again = _invoke(args)
    assert again.exit_code == 1
    assert "ÉCHEC" in again.stderr


# ------------------------------------------------------------------------------ O08
def test_O08_generate_errors(tmp_path: Path, site_rect: SiteSpec, program_25: Program) -> None:
    _, yml = write_inputs(tmp_path / "in", program_25, site_rect)
    bad = write_x07(tmp_path / "in" / "bad.xlsx")
    out = tmp_path / "out"
    res = _invoke(
        [
            "generate",
            "--program",
            str(bad),
            "--site",
            str(yml),
            "--rulebook",
            str(RULEBOOK_TEST),
            "--out",
            str(out),
        ]
    )
    assert res.exit_code == 1, res.output
    err = res.stderr
    assert "Erreurs (" in err
    assert "ÉCHEC : corrigez les erreurs ci-dessus." in err
    for code in ("E_EMPTY_ID", "E_DUP_ID", "E_ZONE"):
        assert f"[{code}]" in err
    assert "ligne " in err
    assert not out.exists()


def test_generate_api_raises_input_error(
    tmp_path: Path, site_rect: SiteSpec, program_25: Program
) -> None:
    _, yml = write_inputs(tmp_path / "in", program_25, site_rect)
    bad = write_x07(tmp_path / "in" / "bad.xlsx")
    with pytest.raises(InputError):
        generate(
            bad,
            yml,
            RULEBOOK_TEST,
            tmp_path / "out",
            seed=1,
            variants=1,
            config=optimizer_config(),
        )
    assert not (tmp_path / "out").exists()


# ------------------------------------------------------------------------------ O09
@pytest.mark.timeout(120)
def test_O09_variants_distinct(tmp_path: Path, p25_inputs: tuple[Path, Path]) -> None:
    xlsx, yml = p25_inputs
    cfg = optimizer_config(time_budget_s=2.0)
    res = generate(xlsx, yml, RULEBOOK_TEST, tmp_path / "out", seed=1, variants=3, config=cfg)
    assert res.succeeded == 3
    assert [v.seed for v in res.variants] == [1, 2, 3]
    layouts = {
        (v.out_dir / "layout.json").read_bytes() for v in res.variants if v.out_dir is not None
    }
    distinct = [v for v in res.variants if v.duplicate_of is None]
    assert len(distinct) >= 2
    assert len(layouts) >= 2
    for v in res.variants:
        assert v.final_hard is not None and v.initial_hard is not None
        assert v.final_hard <= v.initial_hard
        assert v.circulation_pct is not None and 0.0 < v.circulation_pct < 100.0


# ------------------------------------------------------------- failures and duplicates
def test_generate_failed_and_duplicate_variants(
    tmp_path: Path, p25_inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    xlsx, yml = p25_inputs
    real_seed = gen_mod.seed_plan
    real_anneal = gen_mod.anneal
    first: list[object] = []

    def fake_seed(prepared, rulebook, config, *, seed, time_budget_s):  # type: ignore[no-untyped-def]
        res = real_seed(prepared, rulebook, config, seed=seed, time_budget_s=time_budget_s)
        if seed == 11:  # the second variant fails to seed
            failing = Realization(
                layout=None, failures=(Failure(code="PLAN_OVERFLOW", detail="x | y"),), depths=()
            )
            return res.model_copy(update={"realization": failing})
        return res

    def same_anneal(prepared, rulebook, config, start, *, seed):  # type: ignore[no-untyped-def]
        if not first:
            first.append(real_anneal(prepared, rulebook, config, start, seed=seed))
        return first[0]

    monkeypatch.setattr(gen_mod, "seed_plan", fake_seed)
    monkeypatch.setattr(gen_mod, "anneal", same_anneal)
    cfg = optimizer_config(max_iter=3)
    res = generate(xlsx, yml, RULEBOOK_TEST, tmp_path / "out", seed=10, variants=3, config=cfg)
    status = [v.status for v in res.variants]
    assert status == ["ok", "failed", "ok"]
    assert res.variants[1].failures == ("PLAN_OVERFLOW: x | y",)
    assert res.variants[0].duplicate_of is None
    assert res.variants[2].duplicate_of == 1
    summary = res.summary.read_text(encoding="utf-8")
    assert "échec" in summary and "doublon de la variante 01" in summary
    assert "x / y" in summary  # pipes escaped in the table


def test_generate_cli_all_failed(
    tmp_path: Path, p25_inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    xlsx, yml = p25_inputs
    real_seed = gen_mod.seed_plan

    def failing_seed(prepared, rulebook, config, *, seed, time_budget_s):  # type: ignore[no-untyped-def]
        res = real_seed(prepared, rulebook, config, seed=seed, time_budget_s=time_budget_s)
        return res.model_copy(
            update={
                "realization": Realization(
                    layout=None, failures=(Failure(code="DEPTH", detail="none"),), depths=()
                )
            }
        )

    monkeypatch.setattr(gen_mod, "seed_plan", failing_seed)
    out = tmp_path / "out"
    res = _invoke(
        [
            "generate",
            "--program",
            str(xlsx),
            "--site",
            str(yml),
            "--rulebook",
            str(RULEBOOK_TEST),
            "--out",
            str(out),
            "--seed",
            "2",
        ]
    )
    assert res.exit_code == 1
    assert "échec" in res.stdout
    assert "DEPTH: none" in (out / "summary.md").read_text(encoding="utf-8")
    assert not (out / "variant_01").exists()


def test_generate_rejects_zero_variants(tmp_path: Path, p25_inputs: tuple[Path, Path]) -> None:
    xlsx, yml = p25_inputs
    with pytest.raises(ValueError, match="variants"):
        generate(
            xlsx, yml, RULEBOOK_TEST, tmp_path / "o", seed=0, variants=0, config=optimizer_config()
        )
