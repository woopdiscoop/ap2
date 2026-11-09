"""X.1 force selection and VLM cache reuse; all sources generated, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from extract_helpers import Invoke, event_count, execute, plan_doc, query, save_doc, unit_of

from ale.corpus.extract import run_extract
from ale.corpus.ingest import ingest
from ale.workspace import Workspace


def _corpus(ws: Workspace, root: Path) -> None:
    pytest.importorskip("cv2")
    pytest.importorskip("pymupdf")
    pytest.importorskip("ezdxf")
    from corpus_helpers import png_bytes, write
    from test_extract_vlm import corpus, scanned_pdf

    corpus(root)  # DXF, vector PDF and raster plan
    scanned_pdf(root / "scan.pdf")
    write(root / "blank.png", png_bytes())  # legitimate non-plan, remains excluded
    ingest(ws, root)
    result = run_extract(ws, no_vlm=True)
    assert (result.selected, result.extracted, result.excluded) == (5, 4, 1)


def _outputs(ws: Workspace) -> dict[str, bytes]:
    root = ws.path("extracted")
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("plan.json")}


def _flags(ws: Workspace) -> list[tuple[object, ...]]:
    return query(ws, "SELECT * FROM review_flags ORDER BY sha256, page, plan_index, flag")


def test_X01_force_all(tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke) -> None:
    _corpus(tmp_workspace, tmp_path / "input")
    before, flags = _outputs(tmp_workspace), _flags(tmp_workspace)
    units = query(tmp_workspace, "SELECT sha256, page, status FROM units ORDER BY sha256, page")
    assert {u[2] for u in units} == {"EXTRACTED", "EXCLUDED"}
    assert event_count(tmp_workspace, "extract_forced") == 0

    result = invoke(["extract", "--workspace", tmp_workspace.root, "--force", "--no-vlm"])

    assert result.exit_code == 0, result.output
    assert "unités sélectionnées : 5" in result.stdout
    assert "extraites : 4" in result.stdout and "exclues : 1" in result.stdout
    assert _outputs(tmp_workspace) == before
    assert _flags(tmp_workspace) == flags
    assert (
        query(tmp_workspace, "SELECT sha256, page, status FROM units ORDER BY sha256, page")
        == units
    )
    forced = query(
        tmp_workspace,
        "SELECT sha256, page, detail FROM events WHERE event='extract_forced' "
        "ORDER BY sha256, page",
    )
    assert [
        (sha, page, json.loads(detail)["previous_status"]) for sha, page, detail in forced
    ] == units


def test_X02_force_kind(tmp_workspace: Workspace, tmp_path: Path, invoke: Invoke) -> None:
    _corpus(tmp_workspace, tmp_path / "input")
    # Poison only the non-PDF rows to detect even an accidental rewrite at second precision.
    execute(tmp_workspace, "UPDATE units SET updated_at='untouched' WHERE kind NOT LIKE 'PDF_%'")
    untouched = query(tmp_workspace, "SELECT * FROM units WHERE kind NOT LIKE 'PDF_%' ORDER BY id")
    before, flags = _outputs(tmp_workspace), _flags(tmp_workspace)
    event_id = query(tmp_workspace, "SELECT MAX(id) FROM events")[0][0]

    result = invoke(
        ["extract", "--workspace", tmp_workspace.root, "--force", "--kind", "pdf", "--no-vlm"]
    )

    assert result.exit_code == 0, result.output
    assert "unités sélectionnées : 2" in result.stdout
    assert (
        query(tmp_workspace, "SELECT * FROM units WHERE kind NOT LIKE 'PDF_%' ORDER BY id")
        == untouched
    )
    assert _outputs(tmp_workspace) == before and _flags(tmp_workspace) == flags
    new_events = query(
        tmp_workspace,
        "SELECT e.event, u.kind FROM events e JOIN units u "
        "ON u.sha256=e.sha256 AND u.page=e.page WHERE e.id > ?",
        (event_id,),
    )
    assert sorted(new_events) == sorted(
        [
            (event, kind)
            for event in ("extract_forced", "extracted")
            for kind in ("PDF_SCANNED", "PDF_VECTOR")
        ]
    )


def test_X03_exclusive(tmp_workspace: Workspace, invoke: Invoke) -> None:
    before = {
        p.relative_to(tmp_workspace.root): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_workspace.root.rglob("*")
        if p.is_file()
    }
    result = invoke(["extract", "--workspace", tmp_workspace.root, "--force", "--only-new"])
    assert result.exit_code == 2
    assert "--force et --only-new sont incompatibles" in result.output
    with pytest.raises(ValueError, match="incompatibles"):
        run_extract(tmp_workspace, force=True, only_new=True)
    after = {
        p.relative_to(tmp_workspace.root): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_workspace.root.rglob("*")
        if p.is_file()
    }
    assert after == before


def test_X04_force_cache(
    tmp_workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invoke: Invoke
) -> None:
    pytest.importorskip("cv2")
    pytest.importorskip("pymupdf")
    pytest.importorskip("ezdxf")
    from test_extract_vlm import BoxProvider, primed, use_provider

    ws, _, answers = primed(tmp_workspace, tmp_path, monkeypatch)
    first = BoxProvider(answers={digest: answer for digest, answer in answers.values()})
    use_provider(monkeypatch, first)
    result = invoke(["extract", "--workspace", ws.root])
    assert result.exit_code == 0 and first.calls == 3
    before, flags = _outputs(ws), _flags(ws)
    cache = {p.name: p.read_bytes() for p in ws.path("cache", "vlm").iterdir()}
    assert len(cache) == 3
    second = BoxProvider(fail_on=set(first.answers))  # a cache miss would now fail visibly
    use_provider(monkeypatch, second)

    result = invoke(["extract", "--workspace", ws.root, "--force"])

    assert result.exit_code == 0, result.output
    assert second.calls == 0
    assert "0 plan(s) envoyé(s), 3 réponse(s) du cache, 0 erreur(s)" in result.stdout
    assert _outputs(ws) == before and _flags(ws) == flags
    assert {p.name: p.read_bytes() for p in ws.path("cache", "vlm").iterdir()} == cache
    assert event_count(ws, "extract_forced") == 3


@pytest.mark.parametrize("status", ["NEW", "FAILED", "NEEDS_TOOL", "EXTRACTED", "EXCLUDED"])
def test_force_selects_every_status(tmp_workspace: Workspace, tmp_path: Path, status: str) -> None:
    pytest.importorskip("ezdxf")
    save_doc(plan_doc(), tmp_path / "input/plan.dxf")
    ingest(tmp_workspace, tmp_path / "input")
    execute(tmp_workspace, "UPDATE units SET status=?", (status,))
    report = run_extract(tmp_workspace, force=True, kind="dxf", no_vlm=True)
    assert (report.selected, report.extracted, report.failed) == (1, 1, 0)
    assert event_count(tmp_workspace, "extract_forced") == 1


def test_force_replaces_changed_plan_and_stale_flags(
    tmp_workspace: Workspace, tmp_path: Path
) -> None:
    pytest.importorskip("ezdxf")
    save_doc(plan_doc(), tmp_path / "input/plan.dxf")
    ingest(tmp_workspace, tmp_path / "input")
    assert run_extract(tmp_workspace, no_vlm=True).extracted == 1
    expected, flags = _outputs(tmp_workspace), _flags(tmp_workspace)
    path = next(tmp_workspace.path("extracted").rglob("plan.json"))
    path.write_bytes(b"stale output")
    sha, page, *_ = unit_of(tmp_workspace, "plan.dxf")
    execute(tmp_workspace, "INSERT INTO review_flags VALUES (?, ?, 0, 'obsolete')", (sha, page))
    report = run_extract(tmp_workspace, force=True, no_vlm=True)
    assert report.extracted == report.files_written == 1
    assert _outputs(tmp_workspace) == expected and _flags(tmp_workspace) == flags
    assert not list(path.parent.glob("*.tmp"))


def test_force_records_failed_attempt(tmp_workspace: Workspace, tmp_path: Path) -> None:
    pytest.importorskip("ezdxf")
    source = save_doc(plan_doc(), tmp_path / "input/plan.dxf")
    ingest(tmp_workspace, tmp_path / "input")
    source.unlink()
    result = run_extract(tmp_workspace, force=True, no_vlm=True)
    assert result.failed == 1
    assert event_count(tmp_workspace, "extract_forced") == 1
    assert event_count(tmp_workspace, "extract_failed") == 1
