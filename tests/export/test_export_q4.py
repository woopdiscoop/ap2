"""Ticket Q.4 (D04, report): rooms whose proportion > amax is imposed by the depth rule."""

from __future__ import annotations

from pathlib import Path

from export_helpers import make_layout

from ale.config import AleConfig
from ale.contracts.models import Violation
from ale.export import export_run
from ale.program.models import PreparedInput

TITLE = "## Proportion > 2 imposée par la règle de profondeur"
SOFT_TITLE = "## Profondeur depuis la façade dépassée (non bloquant)"


def _report(
    tmp: Path, prepared: PreparedInput, violations: tuple[Violation, ...], cfg: AleConfig
) -> str:
    layout = make_layout(violations=violations)
    files = export_run(layout, prepared, tmp, rulebook_version="t", run_id="run-q4", config=cfg)
    return files.report_md.read_text(encoding="utf-8")


def test_D04_report_depth_aspect(tmp_path: Path, prepared: PreparedInput) -> None:
    cfg = AleConfig.model_validate({"facade": {"max_depth_m": 7.2, "max_depth_hard": True}})
    viol = (
        Violation(code="ASPECT_DEPTH", instance_ids=("R06",), detail="R06: aspect 5.333 > 2"),
        Violation(code="FACADE_DEPTH", instance_ids=("R07",), detail="R07: depth 16 > 12"),
    )
    text = _report(tmp_path / "a", prepared, viol, cfg)
    lines = text.splitlines()
    assert (
        "- Profondeur max. depuis la façade : 7,20 m (double pour une pièce traversante)" in lines
    )
    start = lines.index(TITLE)
    assert lines.index("## Contraintes non respectées") < start < lines.index("## Coût")
    body = lines[start + 1 : lines.index("## Coût")]
    assert any("la profondeur prime" in ln for ln in body)
    rooms = [ln for ln in body if ln.startswith("- `")]
    assert rooms == ["- `R06` Rangement : 4,80 \u00d7 0,90 m, proportion 5,33"]
    assert "### ASPECT_DEPTH (1)" in lines and "### FACADE_DEPTH (1)" in lines
    assert SOFT_TITLE not in lines


def test_D08_report_soft_depth(tmp_path: Path, prepared: PreparedInput) -> None:
    cfg = AleConfig.model_validate({"facade": {"max_depth_m": 7.2}})
    assert cfg.facade.max_depth_hard is False
    viol = (Violation(code="FACADE_DEPTH", instance_ids=("R07",), detail="R07: depth 16 > 12"),)
    lines = _report(tmp_path / "s", prepared, viol, cfg).splitlines()
    assert (
        "- Profondeur max. depuis la façade : 7,20 m (double pour une pièce traversante ; "
        "indicative, dépassement non bloquant)"
    ) in lines
    start = lines.index(SOFT_TITLE)
    assert lines.index("## Contraintes non respectées") < start < lines.index("## Coût")
    body = lines[start + 1 : lines.index("## Coût")]
    assert [ln for ln in body if ln.startswith("- `")] == ["- `R07` : R07: depth 16 > 12"]
    assert "### FACADE_DEPTH (1)" in lines
    # No finding: no section.
    assert SOFT_TITLE not in _report(tmp_path / "t", prepared, (), cfg)


def test_D04_report_without_depth_rule(tmp_path: Path, prepared: PreparedInput) -> None:
    text = _report(tmp_path / "b", prepared, (), AleConfig())
    assert TITLE not in text
    assert "Profondeur max." not in text
    # A violation of an unknown room is still listed.
    cfg = AleConfig.model_validate({"facade": {"max_depth_m": 7.2, "max_depth_hard": True}})
    viol = (Violation(code="ASPECT_DEPTH", instance_ids=("ghost",), detail="x"),)
    text = _report(tmp_path / "c", prepared, viol, cfg)
    assert "- `ghost`" in text.splitlines()
