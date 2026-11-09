"""Ticket I.2 V201, V205-V209: the VLM wired into ``ale extract`` (provider mocked, no network)."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

cv2 = pytest.importorskip("cv2")
pymupdf = pytest.importorskip("pymupdf")
pytest.importorskip("PIL")

import numpy as np  # noqa: E402
from extract_helpers import Invoke, execute, plan_doc, query, save_doc, unit_of  # noqa: E402

import ale.corpus.extract as extract_mod  # noqa: E402
from ale.contracts.config import AleConfig  # noqa: E402
from ale.contracts.enums import Frame, LabelSource  # noqa: E402
from ale.contracts.models import PlanGeometry  # noqa: E402
from ale.corpus.extract import MISSING_KEY_WARNING, ExtractReport, plan_path, run_extract  # noqa: E402
from ale.corpus.ingest import ingest  # noqa: E402
from ale.labels import VlmCache, cache_key, label_plan  # noqa: E402
from ale.labels.bbox import native_to_normalized  # noqa: E402
from ale.labels.provider import PROMPT_VERSION  # noqa: E402
from ale.labels.providers import VlmProviderError, make_provider, prepare_image  # noqa: E402
from ale.labels.render import plan_image  # noqa: E402
from ale.workspace import Workspace, open_workspace  # noqa: E402

EMPTY = json.dumps({"rooms": []})


# ---------------------------------------------------------------------- helpers


@dataclass
class BoxProvider:
    """Mock VLM: canned answer per image (sha256 of the PNG), ``EMPTY`` otherwise."""

    answers: dict[str, str] = field(default_factory=dict)
    fail_on: set[str] = field(default_factory=set)
    model_id: str = "mock-vlm-1"
    images: list[bytes] = field(default_factory=list)

    def label_image(self, image_png: bytes, prompt: str, *, temperature: float) -> str:
        self.images.append(image_png)
        digest = hashlib.sha256(image_png).hexdigest()
        if digest in self.fail_on:
            raise VlmProviderError("API error 529 (simulated)")
        return self.answers.get(digest, EMPTY)

    @property
    def calls(self) -> int:
        return len(self.images)


def use_provider(monkeypatch: pytest.MonkeyPatch, provider: Any) -> list[AleConfig]:
    """``make_provider`` in extract returns ``provider``; returns the configs it saw."""
    seen: list[AleConfig] = []

    def fake(config: AleConfig) -> Any:
        seen.append(config)
        return provider

    monkeypatch.setattr(extract_mod, "make_provider", fake)
    return seen


def set_vlm(ws: Workspace, provider: str = "anthropic") -> Workspace:
    path = ws.path("ale.toml")
    text = path.read_text(encoding="utf-8")
    assert 'provider = ""' in text
    path.write_text(text.replace('provider = ""', f'provider = "{provider}"', 1), encoding="utf-8")
    return open_workspace(ws.root)


def write_png(path: Path, image: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, data = cv2.imencode(".png", image)
    assert ok
    path.write_bytes(data.tobytes())
    return path


def raster_plan_image(scale: float = 1.0) -> Any:
    from raster_helpers import plan_image as reference

    image = reference()
    image[200:240, 500:508] = 0  # close the door gaps (as in the I.1 tests)
    image[396:404, 780:830] = 0
    if scale != 1.0:
        h, w = image.shape
        image = cv2.resize(
            image, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_NEAREST
        )
    return image


def unlabelled_pdf(path: Path) -> Path:
    from pdf_helpers import draw_door, draw_plan_lines, draw_title

    path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as doc:
        page = doc.new_page(width=595, height=842)
        draw_plan_lines(page)
        draw_door(page)
        draw_title(page)
        doc.save(path)
    return path


def corpus(root: Path) -> dict[str, Path]:
    """A DXF, a raster and a vector PDF plan, all with untyped rooms."""
    return {
        "plan.dxf": save_doc(plan_doc(), root / "plan.dxf"),
        "plan.png": write_png(root / "plan.png", raster_plan_image()),
        "plan.pdf": unlabelled_pdf(root / "plan.pdf"),
    }


def scanned_pdf(path: Path) -> Path:
    png = cv2.imencode(".png", raster_plan_image())[1].tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as doc:
        page = doc.new_page(width=288, height=192)  # 1200 x 800 px at 300 dpi
        page.insert_image(page.rect, stream=png)
        doc.save(path)
    return path


def load(ws: Workspace, name: str) -> PlanGeometry:
    sha, page, *_ = unit_of(ws, name)
    return PlanGeometry.model_validate_json(plan_path(ws, sha, page, 0).read_bytes())


def outputs(ws: Workspace) -> dict[str, bytes]:
    root = ws.path("extracted")
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("plan.json"))}


def reset(ws: Workspace) -> None:
    """Select the extracted units again (what a forced re-extraction does)."""
    execute(ws, "UPDATE units SET status = 'NEW' WHERE status = 'EXTRACTED'")


def answers_for(ws: Workspace, sources: dict[str, Path]) -> dict[str, tuple[str, str]]:
    """For each source: (image digest, answer boxing its first untyped room as "Bureau").

    Computed from the text-labelled plans of a previous (``no_vlm``) extraction.
    """
    out: dict[str, tuple[str, str]] = {}
    for name, source in sources.items():
        plan = load(ws, name)
        png, extent = plan_image(plan, config=ws.config, source=source)
        prepared = prepare_image(png)
        target = next(r for r in plan.rooms if r.type is None)
        xs = [p[0] for p in target.polygon.exterior]
        ys = [p[1] for p in target.polygon.exterior]
        norm = native_to_normalized(
            (min(xs), min(ys), max(xs), max(ys)),
            image_size=prepared.size,
            extent=extent,
            frame=Frame(plan.frame),
        )
        bbox = [round(v) for v in norm]
        answer = json.dumps({"rooms": [{"label": "Bureau", "bbox": bbox, "confidence": 0.9}]})
        out[name] = (hashlib.sha256(prepared.png).hexdigest(), answer)
    return out


def primed(
    ws: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Workspace, dict[str, Path], dict[str, tuple[str, str]]]:
    """Ingested corpus, a text-only extraction, the mock answers, units reset, VLM on."""
    sources = corpus(tmp_path / "input")
    ingest(ws, tmp_path / "input")
    report = run_extract(ws, no_vlm=True)
    assert report.extracted == 3 and report.vlm_enabled is False
    answers = answers_for(ws, sources)
    reset(ws)
    return set_vlm(ws), sources, answers


def vlm_rooms(plan: PlanGeometry) -> list[str]:
    return [r.id for r in plan.rooms if r.label_source is LabelSource.VLM]


# ---------------------------------------------------------------------- V201


def _i1_label(
    ws: Workspace,
    plan: PlanGeometry,
    vlm: object,
    report: ExtractReport,
    *,
    source: Path,
    bitmap: object,
) -> PlanGeometry:
    """The I.1 labelling step, verbatim (text only)."""
    labelled = label_plan(
        plan, image=None, provider=None, cache=VlmCache.for_workspace(ws), config=ws.config
    )
    return labelled.plan.model_copy(
        update={"warnings": tuple(dict.fromkeys((*labelled.plan.warnings, *labelled.warnings)))}
    )


def test_V201_default_off(
    tmp_workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus(tmp_path / "input")  # untyped rooms: DXF, raster, vector PDF
    save_doc(plan_doc(labels=True), tmp_path / "input" / "labelled.dxf")
    scanned_pdf(tmp_path / "input" / "scan.pdf")
    ingest(tmp_workspace, tmp_path / "input")
    assert tmp_workspace.config.vlm.provider == ""
    assert make_provider(tmp_workspace.config) is None
    reference = tmp_path / "reference_ws"
    shutil.copytree(tmp_workspace.root, reference)

    script = (
        "import sys\n"
        "from ale.corpus.extract import run_extract\n"
        "from ale.workspace import open_workspace\n"
        "r = run_extract(open_workspace(sys.argv[1]))\n"
        "print(r.extracted, r.vlm_enabled, r.vlm_calls, 'anthropic' in sys.modules)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script, str(tmp_workspace.root)],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    assert done.stdout.split() == ["5", "False", "0", "False"]  # no anthropic import

    # The same corpus through the I.1 labelling step: byte-equal plan.json files.
    monkeypatch.setattr(extract_mod, "_label", _i1_label)
    ref_ws = open_workspace(reference)
    assert run_extract(ref_ws).extracted == 5
    new, old = outputs(tmp_workspace), outputs(ref_ws)
    assert len(new) == 5 and new == old
    assert not list(tmp_workspace.path("cache").glob("vlm/*"))


# ---------------------------------------------------------------------- end to end per kind


def test_vlm_labels_every_source_kind(
    tmp_workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, _, answers = primed(tmp_workspace, tmp_path, monkeypatch)
    provider = BoxProvider(answers=dict(answers.values()))
    seen = use_provider(monkeypatch, provider)

    report = run_extract(ws)

    assert len(seen) == 1 and seen[0].vlm.provider == "anthropic"  # built once per run
    assert report.extracted == 3 and report.vlm_enabled
    assert (report.vlm_plans, report.vlm_cache_hits, report.vlm_errors) == (3, 0, 0)
    assert report.vlm_calls == provider.calls == 3
    for name in ("plan.dxf", "plan.png", "plan.pdf"):
        plan = load(ws, name)
        labelled = [r for r in plan.rooms if r.label_source is LabelSource.VLM]
        assert len(labelled) == 1 and labelled[0].type == "office", name
        assert labelled[0].id == next(r.id for r in plan.rooms if r.type is not None)


# ---------------------------------------------------------------------- V205


def test_V205_prepared_image(
    tmp_workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = write_png(tmp_path / "input" / "big.png", raster_plan_image(scale=2.5))
    assert cv2.imread(str(source)).shape[:2] == (2000, 3000)
    ingest(tmp_workspace, tmp_path / "input")
    ws = set_vlm(tmp_workspace)
    provider = BoxProvider()
    use_provider(monkeypatch, provider)
    given: list[bytes] = []
    real = extract_mod.label_plan

    def spy(plan: PlanGeometry, **kwargs: Any) -> Any:
        if kwargs["image"] is not None:
            given.append(kwargs["image"])
        return real(plan, **kwargs)

    monkeypatch.setattr(extract_mod, "label_plan", spy)

    report = run_extract(ws)

    assert report.extracted == 1 and report.vlm_plans == 1
    plan = load(ws, "big.png")
    expected = prepare_image(plan_image(plan, config=ws.config, source=source)[0])
    assert max(expected.size) == 1568 and expected.size == (1568, 1045)
    assert given == [expected.png]  # one downscale, exactly these bytes
    assert provider.images == [expected.png]  # what the provider sends is what was mapped
    key = cache_key(
        source_sha256=plan.source_sha256,
        page=0,
        plan_index=0,
        prompt_version=PROMPT_VERSION,
        model_id=provider.model_id,
        image=expected.png,
    )
    assert ws.path("cache", "vlm", f"{key}.txt").read_text(encoding="utf-8") == EMPTY


# ---------------------------------------------------------------------- V206


def test_V206_missing_key(
    tmp_workspace: Workspace,
    tmp_path: Path,
    invoke: Invoke,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("ALE_VLM_API_KEY", raising=False)
    sources = corpus(tmp_path / "input")
    ingest(tmp_workspace, tmp_path / "input")
    ws = set_vlm(tmp_workspace)
    assert ws.config.vlm.provider == "anthropic"

    with caplog.at_level(logging.WARNING, logger="ale"):
        result = invoke(["extract", "--workspace", ws.root])

    assert result.exit_code == 0, result.output
    assert result.stdout.count(MISSING_KEY_WARNING) == 1
    assert result.stdout.startswith(f"avertissement : {MISSING_KEY_WARNING}")
    assert "VLM :" not in result.stdout
    assert "extraites : 3" in result.stdout
    for name in sources:
        assert not vlm_rooms(load(ws, name))
    assert not list(ws.path("cache").glob("vlm/*"))
    again = run_extract(ws)  # the library reports it too, once per run
    assert again.vlm_warning == MISSING_KEY_WARNING and not again.vlm_enabled


# ---------------------------------------------------------------------- V207


def test_V207_provider_error(
    tmp_workspace: Workspace,
    tmp_path: Path,
    invoke: Invoke,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws, _, answers = primed(tmp_workspace, tmp_path, monkeypatch)
    failing = answers["plan.dxf"][0]
    provider = BoxProvider(answers=dict(answers.values()), fail_on={failing})
    use_provider(monkeypatch, provider)

    result = invoke(["extract", "--workspace", ws.root])

    assert result.exit_code == 0, result.output
    assert "VLM : 3 plan(s) envoyé(s), 0 réponse(s) du cache, 1 erreur(s)" in result.stdout
    assert "extraites : 3" in result.stdout
    dxf = load(ws, "plan.dxf")
    assert not vlm_rooms(dxf) and all(r.type is None for r in dxf.rooms)  # text-labelled
    assert any("VLM provider call failed: VlmProviderError" in w for w in dxf.warnings)
    for name in ("plan.png", "plan.pdf"):
        plan = load(ws, name)
        assert len(vlm_rooms(plan)) == 1
        assert not any("VLM provider" in w for w in plan.warnings)
    statuses = query(ws, "SELECT DISTINCT status FROM units")
    assert statuses == [("EXTRACTED",)]


# ---------------------------------------------------------------------- V208


def test_V208_cache(
    tmp_workspace: Workspace,
    tmp_path: Path,
    invoke: Invoke,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws, _, answers = primed(tmp_workspace, tmp_path, monkeypatch)
    first_provider = BoxProvider(answers=dict(answers.values()))
    use_provider(monkeypatch, first_provider)
    first = invoke(["extract", "--workspace", ws.root])
    assert first.exit_code == 0, first.output
    assert first_provider.calls == 3
    assert "VLM : 3 plan(s) envoyé(s), 0 réponse(s) du cache, 0 erreur(s)" in first.stdout
    out_first = outputs(ws)

    reset(ws)  # second, forced extraction of the same units
    second_provider = BoxProvider()  # would answer EMPTY: any call would change the output
    use_provider(monkeypatch, second_provider)
    second = invoke(["extract", "--workspace", ws.root])

    assert second.exit_code == 0, second.output
    assert second_provider.calls == 0
    assert "VLM : 0 plan(s) envoyé(s), 3 réponse(s) du cache, 0 erreur(s)" in second.stdout
    assert outputs(ws) == out_first
    assert all(len(vlm_rooms(PlanGeometry.model_validate_json(b))) == 1 for b in out_first.values())


# ---------------------------------------------------------------------- V209


def test_V209_no_vlm_flag(
    tmp_workspace: Workspace,
    tmp_path: Path,
    invoke: Invoke,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws, sources, answers = primed(tmp_workspace, tmp_path, monkeypatch)
    provider = BoxProvider(answers=dict(answers.values()))
    seen = use_provider(monkeypatch, provider)

    result = invoke(["extract", "--workspace", ws.root, "--no-vlm"])

    assert result.exit_code == 0, result.output
    assert provider.calls == 0 and seen == []
    assert "VLM" not in result.stdout and "extraites : 3" in result.stdout
    for name in sources:
        assert not vlm_rooms(load(ws, name))


# ---------------------------------------------------------------------- other paths


def test_unknown_provider_disables_vlm(tmp_workspace: Workspace, tmp_path: Path) -> None:
    corpus(tmp_path / "input")
    ingest(tmp_workspace, tmp_path / "input")
    ws = set_vlm(tmp_workspace, provider="nope")

    report = run_extract(ws)

    assert report.extracted == 3 and not report.vlm_enabled
    assert report.vlm_warning is not None
    assert report.vlm_warning.startswith("VLM indisponible (unknown VLM provider 'nope'")
    assert report.to_dict()["vlm_warning"] == report.vlm_warning


def test_render_failure_keeps_text_labels(
    tmp_workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, sources, answers = primed(tmp_workspace, tmp_path, monkeypatch)
    provider = BoxProvider(answers=dict(answers.values()))
    use_provider(monkeypatch, provider)

    def broken(*args: object, **kwargs: object) -> tuple[bytes, tuple[float, ...]]:
        raise RuntimeError("no renderer")

    monkeypatch.setattr(extract_mod, "plan_image", broken)

    report = run_extract(ws)

    assert report.extracted == 3 and provider.calls == 0
    assert (report.vlm_plans, report.vlm_cache_hits, report.vlm_errors) == (0, 0, 0)
    for name in sources:
        plan = load(ws, name)
        assert not vlm_rooms(plan)
        assert any("VLM skipped: plan image not rendered (RuntimeError" in w for w in plan.warnings)


def test_fully_text_labelled_plan_is_not_rendered(
    tmp_workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pdf_helpers import reference_page, save_page

    (tmp_path / "input").mkdir()
    save_page(tmp_path / "input" / "labelled.pdf", reference_page())
    ingest(tmp_workspace, tmp_path / "input")
    ws = set_vlm(tmp_workspace)
    provider = BoxProvider()
    use_provider(monkeypatch, provider)
    rendered: list[object] = []
    monkeypatch.setattr(extract_mod, "plan_image", lambda *a, **k: rendered.append(a))

    report = run_extract(ws)

    assert report.extracted == 1 and report.vlm_enabled
    assert rendered == [] and provider.calls == 0 and report.vlm_plans == 0
    plan = load(ws, "labelled.pdf")
    assert all(r.label_source is LabelSource.PDF_TEXT for r in plan.rooms)


def test_scanned_pdf_uses_traced_bitmap(
    tmp_workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scanned_pdf(tmp_path / "input" / "scan.pdf")
    ingest(tmp_workspace, tmp_path / "input")
    ws = set_vlm(tmp_workspace)
    provider = BoxProvider()
    use_provider(monkeypatch, provider)
    bitmaps: list[Any] = []
    real: Callable[..., Any] = extract_mod.plan_image

    def spy(plan: PlanGeometry, **kwargs: Any) -> Any:
        bitmaps.append(kwargs["bitmap"])
        return real(plan, **kwargs)

    monkeypatch.setattr(extract_mod, "plan_image", spy)

    report = run_extract(ws)

    assert report.by_kind == {"PDF_SCANNED": 1} and report.vlm_plans == 1
    assert len(bitmaps) == 1 and isinstance(bitmaps[0], np.ndarray)
    assert bitmaps[0].shape == (800, 1200)
    sent = cv2.imdecode(np.frombuffer(provider.images[0], dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    assert np.array_equal(sent, bitmaps[0])
