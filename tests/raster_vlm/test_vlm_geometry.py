"""Ticket R.7 G701-G709: Claude reads the room geometry of raster plans (client mocked)."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("PIL")
pytest.importorskip("anthropic")

import shapely  # noqa: E402
from extract_helpers import query  # noqa: E402
from raster_helpers import GT_ROOMS, SHA, W  # noqa: E402
from raster_helpers import plan_image as reference_plan  # noqa: E402

import ale.corpus.extract as extract_mod  # noqa: E402
from ale.contracts.config import AleConfig  # noqa: E402
from ale.contracts.enums import Frame, SourceKind  # noqa: E402
from ale.contracts.models import LabelledPolygon, PlanGeometry  # noqa: E402
from ale.corpus.extract import ExtractReport, plan_path, run_extract  # noqa: E402
from ale.corpus.ingest import ingest  # noqa: E402
from ale.labels.bbox import native_to_normalized  # noqa: E402
from ale.labels.cache import VlmCache  # noqa: E402
from ale.labels.providers import AnthropicVlmProvider, VlmProviderError  # noqa: E402
from ale.labels.render import bitmap_image  # noqa: E402
from ale.raster import compare as compare_mod  # noqa: E402
from ale.raster import vlm_reader  # noqa: E402
from ale.raster.compare import Agreement, compare  # noqa: E402
from ale.raster.vlm_reader import (  # noqa: E402
    GEOMETRY_SCHEMA,
    MAX_ROOMS,
    read_rooms_vlm,
    to_labelled_polygons,
)
from ale.workspace import Workspace, open_workspace  # noqa: E402

EXTENT = (-0.5, -0.5, W - 0.5, 799.5)
CONFIG = AleConfig()
EMPTY = json.dumps({"rooms": []})


# ---------------------------------------------------------------------- helpers


def closed_plan() -> Any:
    image = reference_plan()
    image[200:240, 500:508] = 0  # close the door gaps (as in the I.1 tests)
    image[396:404, 780:830] = 0
    return image


def norm_poly(box: tuple[float, float, float, float], shift: float = 0.0) -> list[list[float]]:
    """Normalised ``[x, y]`` corners of a native box (optionally shifted in x)."""
    x0, y0, x1, y1 = box
    out: list[list[float]] = []
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        ny, nx, _, _ = native_to_normalized(
            (x + shift, y, x + shift, y),
            image_size=(1200, 800),
            extent=EXTENT,
            frame=Frame.Y_DOWN,
        )
        out.append([nx, ny])
    return out


def answer(polys: list[list[list[float]]]) -> str:
    rooms = [{"label": f"Salle {i}", "polygon": p, "confidence": 0.9} for i, p in enumerate(polys)]
    return json.dumps({"rooms": rooms})


@dataclass
class GeoProvider:
    """Mock provider: geometry answer (or an error), labelling answers stay empty."""

    geometry: str = EMPTY
    error: Exception | None = None
    model_id: str = "mock-geo-1"
    geo_calls: list[str] = field(default_factory=list)

    def label_image(self, image_png: bytes, prompt: str, *, temperature: float) -> str:
        return EMPTY

    def read_geometry(self, image_png: bytes, prompt: str) -> str:
        self.geo_calls.append(prompt)
        if self.error is not None:
            raise self.error
        return self.geometry


@dataclass
class LabelOnly:
    model_id: str = "label-only"
    calls: int = 0

    def label_image(self, image_png: bytes, prompt: str, *, temperature: float) -> str:
        self.calls += 1
        return EMPTY


def use_provider(monkeypatch: pytest.MonkeyPatch, provider: Any) -> None:
    monkeypatch.setattr(extract_mod, "make_provider", lambda config: provider)


def set_vlm(ws: Workspace) -> Workspace:
    path = ws.path("ale.toml")
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('provider = ""', 'provider = "anthropic"', 1), encoding="utf-8")
    return open_workspace(ws.root)


def ingested(ws: Workspace, tmp_path: Path) -> Workspace:
    root = tmp_path / "input"
    root.mkdir()
    ok, data = cv2.imencode(".png", closed_plan())
    assert ok
    (root / "plan.png").write_bytes(data.tobytes())
    ingest(ws, root)
    return ws


def plan_file(ws: Workspace) -> Path:
    sha, page = query(ws, "SELECT sha256, page FROM units")[0]
    return plan_path(ws, str(sha), int(page), 0)


def load(ws: Workspace) -> PlanGeometry:
    return PlanGeometry.model_validate_json(plan_file(ws).read_bytes())


def flags(ws: Workspace) -> list[str]:
    return [str(r[0]) for r in query(ws, "SELECT flag FROM review_flags ORDER BY flag")]


def run(ws: Workspace, monkeypatch: pytest.MonkeyPatch, provider: Any, **kw: Any) -> ExtractReport:
    use_provider(monkeypatch, provider)
    report = run_extract(set_vlm(ws), **kw)
    assert report.extracted == 1 and report.failed == 0
    return report


def room_boxes(plan: PlanGeometry) -> list[tuple[float, float, float, float]]:
    return sorted(shapely.Polygon(r.polygon.exterior).bounds for r in plan.rooms)


def synthetic_plan(rooms: list[tuple[float, float, float, float]]) -> PlanGeometry:
    return PlanGeometry(
        source_sha256=SHA,
        page=0,
        plan_index=0,
        source_kind=SourceKind.RASTER,
        frame=Frame.Y_DOWN,
        units_label="px",
        walls=(),
        openings=(),
        rooms=tuple(
            LabelledPolygon.model_validate(
                {"id": f"R{i + 1}", "polygon": {"exterior": [(a, b), (c, b), (c, d), (a, d)]}}
            )
            for i, (a, b, c, d) in enumerate(rooms)
        ),
        warnings=(),
    )


def counting_vlm(provider: Any, directory: Path) -> Any:
    return extract_mod._Vlm(
        extract_mod._CountingProvider(provider), extract_mod._CountingCache(directory)
    )


# ---------------------------------------------------------------------- G701


def test_G701_default_off(
    tmp_workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = ingested(tmp_workspace, tmp_path)
    assert ws.config.vlm.provider == ""
    calls: list[int] = []
    monkeypatch.setattr(extract_mod, "read_rooms_vlm", lambda *a, **k: calls.append(1))
    report = run_extract(ws)
    assert report.extracted == 1 and report.vlm_enabled is False and not calls
    assert (report.geometry_vlm, report.geometry_classical, report.geometry_errors) == (0, 0, 0)
    default = plan_file(ws).read_bytes()
    assert not list(ws.path("cache").glob("vlm/*"))
    monkeypatch.undo()

    # "Before": the geometry step removed. A labelling-only provider cannot read geometry,
    # so its plan is byte-identical to a run without the step.
    label_only = LabelOnly()
    use_provider(monkeypatch, label_only)
    with monkeypatch.context() as patch:
        patch.setattr(extract_mod, "_geometry", lambda ws, plan, *a, **k: (plan, None))
        run_extract(set_vlm(ws), force=True)
    before = plan_file(ws).read_bytes()
    run_extract(ws, force=True)
    assert plan_file(ws).read_bytes() == before
    assert before != b"" and default  # both runs wrote a plan
    assert label_only.calls >= 1  # labelling still works; geometry added no call


# ---------------------------------------------------------------------- G702


def test_G702_mapping() -> None:
    png, extent = bitmap_image(closed_plan())
    provider = GeoProvider(geometry=answer([norm_poly(b) for b in GT_ROOMS]))
    out = read_rooms_vlm(png, extent, Frame.Y_DOWN, provider, None, CONFIG)
    assert out.error is None and len(out.rooms) == 3
    for room, box in zip(out.rooms, GT_ROOMS, strict=True):
        assert room.polygon.bounds == pytest.approx(box, abs=0.5)
        assert room.polygon.area == pytest.approx((box[2] - box[0]) * (box[3] - box[1]), abs=1.0)
    assert provider.geo_calls and "geom-v1" in provider.geo_calls[0]
    contract = to_labelled_polygons(out.rooms)
    assert [r.id for r in contract] == ["R1", "R2", "R3"] and contract[0].raw_label == "Salle 0"


# ---------------------------------------------------------------------- G703 / G705


def test_G703_confirm(
    tmp_workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = ingested(tmp_workspace, tmp_path)
    run_extract(ws, no_vlm=True)
    baseline = load(ws)
    assert len(baseline.rooms) == 3
    provider = GeoProvider(geometry=answer([norm_poly(b) for b in GT_ROOMS]))
    report = run(ws, monkeypatch, provider, force=True)
    plan = load(ws)
    assert room_boxes(plan) == room_boxes(baseline)
    assert "géométrie : lecteur classique" in plan.warnings
    assert "géométrie : VLM" not in plan.warnings
    assert "GEOMETRY_DISAGREEMENT" not in flags(ws)
    counts = (report.geometry_classical, report.geometry_vlm, report.geometry_disagreements)
    assert counts == (1, 0, 0)
    assert len(provider.geo_calls) == 1


def test_G705_disagreement(
    tmp_workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = ingested(tmp_workspace, tmp_path)
    run_extract(ws, no_vlm=True)
    baseline = load(ws)
    shifted = [norm_poly(b, shift=0.43 * (b[2] - b[0])) for b in GT_ROOMS]
    report = run(ws, monkeypatch, GeoProvider(geometry=answer(shifted)), force=True)
    plan = load(ws)
    assert room_boxes(plan) == room_boxes(baseline)  # classical kept
    assert "géométrie : lecteur classique" in plan.warnings
    assert "GEOMETRY_DISAGREEMENT" in flags(ws)
    assert report.geometry_disagreements == 1
    # a later agreeing run replaces the flag instead of accumulating it
    agree = GeoProvider(geometry=answer([norm_poly(b) for b in GT_ROOMS]), model_id="mock-geo-2")
    run(ws, monkeypatch, agree, force=True)
    assert "GEOMETRY_DISAGREEMENT" not in flags(ws)


# ---------------------------------------------------------------------- G704


def test_G704_undersegmented(tmp_workspace: Workspace, tmp_path: Path) -> None:
    merged = synthetic_plan([(107.5, 107.5, 1092.5, 692.5)])
    quads = [
        (107.5, 107.5, 499.5, 400.0),
        (507.5, 107.5, 1092.5, 400.0),
        (107.5, 400.0, 499.5, 692.5),
        (507.5, 400.0, 1092.5, 692.5),
    ]
    provider = GeoProvider(geometry=answer([norm_poly(q) for q in quads]))
    report = ExtractReport()
    vlm = counting_vlm(provider, tmp_path / "c")
    plan, flag = extract_mod._geometry(
        tmp_workspace, merged, vlm, report, source=tmp_path / "x.png", bitmap=closed_plan()
    )
    assert flag is None and len(plan.rooms) == 4
    assert "géométrie : VLM" in plan.warnings
    assert [r.id for r in plan.rooms] == ["R1", "R2", "R3", "R4"]
    assert (report.geometry_vlm, report.vlm_calls, report.vlm_plans) == (1, 1, 1)
    # a second pass is answered by the cache
    again, _ = extract_mod._geometry(
        tmp_workspace, merged, vlm, report, source=tmp_path / "x.png", bitmap=closed_plan()
    )
    assert again == plan and len(provider.geo_calls) == 1 and report.vlm_cache_hits == 1


def test_decision_rules() -> None:
    a = [shapely.box(0, 0, 10, 10), shapely.box(10, 0, 20, 10)]
    halves = [
        shapely.box(0, 0, 10, 5),
        shapely.box(0, 5, 10, 10),
        shapely.box(10, 0, 20, 5),
        shapely.box(10, 5, 20, 10),
    ]
    agreement = compare(a, halves)
    assert agreement.matched == 2 and agreement.mean_iou == pytest.approx(0.5)
    assert agreement.choice() == "disagreement"  # 4 >= 1.5 * 2 but mean IoU 0.5 < 0.6
    near = [
        shapely.box(0, 0, 10, 8),
        shapely.box(10, 0, 20, 8),
        shapely.box(0, 8, 10, 10),
        shapely.box(10, 8, 20, 10),
        shapely.box(0, 0, 1, 1),
    ]
    agreement = compare(a, near)
    assert agreement.mean_iou == pytest.approx(0.8) and agreement.choice() == "classical"
    assert Agreement(2, 3, ((0, 0, 0.7), (1, 1, 0.7))).choice() == "vlm"
    assert Agreement(2, 2, ()).choice() == "disagreement"
    assert Agreement(0, 0, ()).choice() == "classical"
    assert Agreement(1, 4, ()).choice() == "vlm"


# ---------------------------------------------------------------------- G706


def test_G706_invalid() -> None:
    bowtie = [[100, 100], [500, 500], [500, 100], [100, 500]]
    outside = [[-200, -200], [300, -200], [300, 300], [-200, 300]]
    beyond = [[2000, 2000], [3000, 2000], [3000, 3000]]
    nan_poly = [[0, 0], [10, 0], [10, float("nan")]]
    items: list[Any] = [
        {"label": "A", "polygon": bowtie, "confidence": 0.5},
        {"label": "B", "polygon": outside, "confidence": 2.0},
        {"label": "C", "polygon": [[0, 0], [1, 1], [2, 2]], "confidence": 0.5},
        {"label": "D", "polygon": [[0, 0], [10, 10]], "confidence": 0.5},
        {"label": "E", "polygon": [[0, 0], [10, "x"], [5, 5]], "confidence": 0.5},
        {"label": "F", "polygon": nan_poly, "confidence": 0.5},
        {"label": "G", "polygon": "nope"},
        "junk",
        {"label": "H", "polygon": beyond, "confidence": 0.5},
        {"label": "L", "polygon": [[10, 10], [20, 10], [10, 10]], "confidence": 0.5},
        {"label": "I", "polygon": [[0, 0], [0.001, 0], [0.001, 0.001]], "confidence": 0.5},
        {"label": 7, "polygon": [[100, 100], [200, 100], [200, 200]], "confidence": True},
    ]
    png, extent = bitmap_image(closed_plan())
    provider = GeoProvider(geometry=json.dumps({"rooms": items}))
    out = read_rooms_vlm(png, extent, Frame.Y_DOWN, provider, None, CONFIG)
    assert out.error is None
    assert [r.label for r in out.rooms] == ["A", "B", ""]
    box = shapely.box(*extent)
    for room in out.rooms:
        assert room.polygon.is_valid and box.contains(room.polygon) and room.polygon.area >= 4
        assert 0.0 <= room.confidence <= 1.0
    assert out.rooms[1].polygon.bounds == pytest.approx((-0.5, -0.5, 359.5, 239.5), abs=0.5)
    text = "\n".join(out.warnings)
    for needle in (
        "réparé",
        "découpé",
        "dégénéré",
        "moins de 3",
        "sommet invalide",
        "forme invalide",
        "hors de l'image",
        "surface",
    ):
        assert needle in text
    many = answer([norm_poly((10, 10, 50, 50))] * (MAX_ROOMS + 5))
    capped = read_rooms_vlm(png, extent, Frame.Y_DOWN, GeoProvider(geometry=many), None, CONFIG)
    assert len(capped.rooms) == MAX_ROOMS and "maximum" in capped.warnings[0]


def test_reader_never_raises() -> None:
    png, extent = bitmap_image(closed_plan())
    for raw in ("not json", "[1]", '{"rooms": 3}', "```json\n" + EMPTY + "\n```"):
        out = read_rooms_vlm(png, extent, Frame.Y_DOWN, GeoProvider(geometry=raw), None, CONFIG)
        assert (out.error is None) == raw.startswith("```")
    assert read_rooms_vlm(b"nope", extent, Frame.Y_DOWN, GeoProvider(), None, CONFIG).error
    assert read_rooms_vlm(png, extent, Frame.Y_DOWN, LabelOnly(), None, CONFIG).error
    degenerate = (0.0, 0.0, 0.0, 0.0)
    bad = read_rooms_vlm(
        png, degenerate, Frame.Y_DOWN, GeoProvider(geometry=answer([[[1, 1]]])), None, CONFIG
    )
    assert bad.error
    assert vlm_reader.geometry_caller(LabelOnly()) is None
    assert vlm_reader._parse("```") is None
    assert to_labelled_polygons(()) == []


# ---------------------------------------------------------------------- G707


def test_G707_cache(
    tmp_workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = ingested(tmp_workspace, tmp_path)
    shifted = [norm_poly(b, shift=0.43 * (b[2] - b[0])) for b in GT_ROOMS]
    provider = GeoProvider(geometry=answer(shifted))
    first = run(ws, monkeypatch, provider)
    bytes_1, flags_1 = plan_file(ws).read_bytes(), flags(ws)
    assert len(provider.geo_calls) == 1 and first.vlm_calls >= 1
    second = run(ws, monkeypatch, provider, force=True)
    assert len(provider.geo_calls) == 1  # 0 new calls
    assert second.vlm_calls == 0 and second.vlm_cache_hits >= 1
    assert plan_file(ws).read_bytes() == bytes_1 and flags(ws) == flags_1
    cached = list(ws.path("cache", "vlm").glob("*.txt"))
    assert any("polygon" in p.read_text(encoding="utf-8") for p in cached)
    # an unusable answer is never cached
    png, extent = bitmap_image(closed_plan())
    cache = VlmCache(tmp_path / "other")
    assert read_rooms_vlm(png, extent, Frame.Y_DOWN, GeoProvider(geometry="x"), cache, CONFIG).error
    assert not list((tmp_path / "other").glob("*.txt"))


# ---------------------------------------------------------------------- G708


def test_G708_errors(
    tmp_workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = ingested(tmp_workspace, tmp_path)
    run_extract(ws, no_vlm=True)
    baseline = load(ws)
    for provider in (
        GeoProvider(error=VlmProviderError("Claude declined the request (refusal)")),
        GeoProvider(error=RuntimeError("boom")),
        GeoProvider(geometry="garbage"),
    ):
        report = run(ws, monkeypatch, provider, force=True)
        plan = load(ws)
        assert room_boxes(plan) == room_boxes(baseline)
        assert "géométrie : lecteur classique" in plan.warnings
        assert any(w.startswith("géométrie VLM") for w in plan.warnings)
        assert report.geometry_errors == 1 and report.failed == 0
        assert "GEOMETRY_DISAGREEMENT" not in flags(ws)


def test_G708_render_failure(
    tmp_workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = synthetic_plan([(1, 1, 5, 5)])
    report = ExtractReport()
    # a provider that cannot read geometry is not asked
    plain = counting_vlm(LabelOnly(), tmp_path / "d")
    same, _ = extract_mod._geometry(
        tmp_workspace, plan, plain, report, source=tmp_path / "x.png", bitmap=None
    )
    assert same is plan

    def boom(*a: Any, **k: Any) -> Any:
        raise OSError("no image")

    monkeypatch.setattr(extract_mod, "plan_image", boom)
    vlm = counting_vlm(GeoProvider(), tmp_path / "c")
    out, flag = extract_mod._geometry(
        tmp_workspace, plan, vlm, report, source=tmp_path / "x.png", bitmap=None
    )
    assert flag is None and out.rooms == plan.rooms
    assert "géométrie : lecteur classique" in out.warnings and report.geometry_errors == 1


# ---------------------------------------------------------------------- Anthropic client


def message(text: str, stop: str = "end_turn") -> Any:
    return SimpleNamespace(
        stop_reason=stop,
        content=[SimpleNamespace(type="text", text=text)],
        stop_details=SimpleNamespace(category="x"),
    )


class FakeClient:
    def __init__(self, result: Any) -> None:
        self.requests: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self.result = result

    def _create(self, **kw: Any) -> Any:
        self.requests.append(kw)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_anthropic_client_request_and_stops() -> None:
    png, extent = bitmap_image(closed_plan())
    good = FakeClient(message(answer([norm_poly(GT_ROOMS[0])])))
    provider = AnthropicVlmProvider(client=good)  # type: ignore[arg-type]
    out = read_rooms_vlm(png, extent, Frame.Y_DOWN, provider, None, CONFIG)
    assert len(out.rooms) == 1 and out.error is None
    req = good.requests[0]
    assert req["output_config"]["format"]["schema"] == GEOMETRY_SCHEMA
    assert req["output_config"]["effort"] == "low"
    assert req["thinking"] == {"type": "adaptive"} and req["fallbacks"] == "default"
    assert req["betas"] and not {"temperature", "top_p", "top_k"} & set(req)
    for result in (message("", "refusal"), message("x", "max_tokens"), RuntimeError("down")):
        client = FakeClient(result)
        sibling = AnthropicVlmProvider(client=client)  # type: ignore[arg-type]
        err = read_rooms_vlm(png, extent, Frame.Y_DOWN, sibling, None, CONFIG)
        assert err.error and not err.rooms


# ---------------------------------------------------------------------- compare


def test_compare_matching_is_optimal() -> None:
    boxes = [shapely.box(i * 10, 0, i * 10 + 10, 10) for i in range(4)]
    swapped = [boxes[2], boxes[0], boxes[3], boxes[1]]
    full = compare(boxes, swapped)
    assert full.matched == 4 and full.mean_iou == 1.0 and full.choice() == "classical"
    fewer = compare(boxes, swapped[:2])
    assert fewer.matched == 2 and fewer.unmatched_classical == 2 and fewer.unmatched_vlm == 0
    more = compare(boxes[:2], swapped)
    assert more.matched == 2 and more.unmatched_vlm == 2
    assert compare([], boxes).matched == 0
    assert compare_mod.iou(shapely.box(0, 0, 0, 0), boxes[0]) == 0.0
    assert math.isclose(compare_mod.iou(boxes[0], shapely.box(5, 0, 15, 10)), 1 / 3)
    bowtie = shapely.Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
    assert compare_mod.iou(bowtie, boxes[0]) == 0.0


# ---------------------------------------------------------------------- G709


def test_G709_gates() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "ale.contracts.lock", "--check"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert done.returncode == 0, done.stdout + done.stderr
