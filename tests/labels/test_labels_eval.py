"""Ticket 1.5 evaluation L1-L8 (fake providers only; no network)."""

from __future__ import annotations

from pathlib import Path

import pytest
from labels_helpers import (
    FakeProvider,
    norm_bbox,
    plan,
    png_bytes,
    rect,
    room,
    three_room_plan,
    vlm_config,
    vlm_json,
)

from ale.contracts.enums import Frame, LabelSource
from ale.labels import label as label_mod
from ale.labels import provider as provider_mod
from ale.labels.bbox import native_to_normalized, normalized_to_native
from ale.labels.cache import VlmCache
from ale.labels.label import assign_one_to_one, label_plan

IMG_SIZE = (300, 100)
EXTENT = (0.0, 0.0, 30.0, 10.0)


def _c_bbox(frame: Frame = Frame.Y_UP) -> list[int]:
    return norm_bbox((20, 0, 30, 10), image_size=IMG_SIZE, extent=EXTENT, frame=frame)


def _by_id(result: label_mod.LabelResult) -> dict[str, label_mod.LabelledPolygon]:
    return {r.id: r for r in result.plan.rooms}


@pytest.fixture
def cache(tmp_path: Path) -> VlmCache:
    return VlmCache(tmp_path / "ws" / "cache" / "vlm")


# --------------------------------------------------------------------------- L1


def test_L1_text_first(cache: VlmCache) -> None:
    fake = FakeProvider([vlm_json()])
    res = label_plan(
        three_room_plan(), image=None, provider=None, cache=cache, config=vlm_config("")
    )
    rooms = _by_id(res)
    assert rooms["A"].type == "office"
    assert rooms["A"].label_source is LabelSource.PDF_TEXT
    assert rooms["A"].raw_label == "BUREAU 3"
    assert rooms["B"].type == "sanitary"
    assert rooms["B"].label_source is LabelSource.PDF_TEXT
    assert rooms["C"].type is None
    assert res.api_calls == 0
    assert fake.calls == []


def test_L1_text_first_no_provider_calls_for_text_rooms(cache: VlmCache) -> None:
    # With a VLM enabled, the text-typed rooms are not sent: the fake only covers C and
    # a VLM box over A is ignored because A is already typed.
    a_box = norm_bbox((0, 0, 10, 10), image_size=IMG_SIZE, extent=EXTENT, frame=Frame.Y_UP)
    fake = FakeProvider([vlm_json(("Salle de réunion", a_box, 0.9))])
    res = label_plan(
        three_room_plan(),
        image=png_bytes(*IMG_SIZE),
        provider=fake,
        cache=cache,
        config=vlm_config(),
    )
    rooms = _by_id(res)
    assert rooms["A"].type == "office"
    assert rooms["A"].label_source is LabelSource.PDF_TEXT
    assert rooms["C"].type is None
    assert res.api_calls == 1
    assert any("matched no untyped room" in w for w in res.warnings)


def test_L1_already_typed_rooms_kept(cache: VlmCache) -> None:
    p = plan(
        [
            room(
                "A",
                rect(0, 0, 10, 10),
                rtype="storage",
                source=LabelSource.CAD_ZONE,
                confidence=1.0,
            )
        ],
        [],
    )
    p = p.model_copy(update={"texts": three_room_plan().texts})
    res = label_plan(p, image=None, provider=None, cache=cache, config=vlm_config(""))
    assert res.plan.rooms[0].type == "storage"
    assert res.plan.rooms[0].label_source is LabelSource.CAD_ZONE


# --------------------------------------------------------------------------- L2


def test_L2_vlm_fill(cache: VlmCache) -> None:
    fake = FakeProvider([vlm_json(("Salle de réunion", _c_bbox(), 0.9))])
    res = label_plan(
        three_room_plan(),
        image=png_bytes(*IMG_SIZE),
        provider=fake,
        cache=cache,
        config=vlm_config(),
    )
    c = _by_id(res)["C"]
    assert c.type == "meeting_room"
    assert c.label_source is LabelSource.VLM
    assert c.raw_label == "Salle de réunion"
    assert c.confidence == pytest.approx(0.9)  # 0.9 x overlap 1.0
    assert res.api_calls == 1
    assert len(fake.calls) == 1
    assert res.warnings == ()


def test_L2_vlm_fill_y_down(cache: VlmCache) -> None:
    p = three_room_plan(Frame.Y_DOWN)
    fake = FakeProvider([vlm_json(("Rangement", _c_bbox(Frame.Y_DOWN), 0.5))])
    res = label_plan(p, image=png_bytes(*IMG_SIZE), provider=fake, cache=cache, config=vlm_config())
    c = _by_id(res)["C"]
    assert (c.type, c.label_source) == ("storage", LabelSource.VLM)
    assert c.confidence == pytest.approx(0.5)


# --------------------------------------------------------------------------- L3


def test_L3_cache(cache: VlmCache, monkeypatch: pytest.MonkeyPatch) -> None:
    image = png_bytes(*IMG_SIZE)
    answer = vlm_json(("Salle de réunion", _c_bbox(), 0.9))

    def run(fake: FakeProvider) -> label_mod.LabelResult:
        return label_plan(
            three_room_plan(), image=image, provider=fake, cache=cache, config=vlm_config()
        )

    first = run(FakeProvider([answer]))
    assert first.api_calls == 1
    second_fake = FakeProvider([answer])
    second = run(second_fake)
    assert second.api_calls == 0
    assert second_fake.calls == []
    assert second.plan == first.plan

    other_model = FakeProvider([answer], model_id="fake-vlm-2")
    assert run(other_model).api_calls == 1
    assert run(FakeProvider([answer], model_id="fake-vlm-2")).api_calls == 0

    monkeypatch.setattr(provider_mod, "PROMPT_VERSION", "v2")
    assert run(FakeProvider([answer])).api_calls == 1
    assert run(FakeProvider([answer])).api_calls == 0


def test_L3_cache_location_in_workspace(tmp_workspace: object) -> None:
    from ale.workspace import Workspace

    assert isinstance(tmp_workspace, Workspace)
    c = VlmCache.for_workspace(tmp_workspace)
    assert c.directory == tmp_workspace.path("cache", "vlm")
    res = label_plan(
        three_room_plan(),
        image=png_bytes(*IMG_SIZE),
        provider=FakeProvider([vlm_json(("Rangement", _c_bbox(), 1.0))]),
        cache=c,
        config=vlm_config(),
    )
    assert res.api_calls == 1
    assert len(list(c.directory.glob("*.txt"))) == 1


# --------------------------------------------------------------------------- L4


def test_L4_invalid_json_then_valid(cache: VlmCache) -> None:
    fake = FakeProvider(["this is not json {", vlm_json(("Rangement", _c_bbox(), 1.0))])
    res = label_plan(
        three_room_plan(),
        image=png_bytes(*IMG_SIZE),
        provider=fake,
        cache=cache,
        config=vlm_config(),
    )
    assert res.api_calls == 2
    assert len(fake.calls) == 2
    assert _by_id(res)["C"].type == "storage"
    assert fake.calls[1][0] != fake.calls[0][0]  # the retry carries a repair instruction
    assert "not valid JSON" in fake.calls[1][0]


def test_L4_invalid_json_twice(cache: VlmCache) -> None:
    fake = FakeProvider(["garbage", '{"rooms": [{"label": 3}]}'])
    res = label_plan(
        three_room_plan(),
        image=png_bytes(*IMG_SIZE),
        provider=fake,
        cache=cache,
        config=vlm_config(),
    )
    assert res.api_calls == 2
    assert _by_id(res)["C"].type is None
    assert _by_id(res)["C"].label_source is None
    assert any("invalid" in w for w in res.warnings)
    # an invalid answer is not cached: the next run calls the provider again
    again = label_plan(
        three_room_plan(),
        image=png_bytes(*IMG_SIZE),
        provider=FakeProvider(["nope"]),
        cache=cache,
        config=vlm_config(),
    )
    assert again.api_calls == 2


# --------------------------------------------------------------------------- L5


@pytest.mark.parametrize("frame", [Frame.Y_DOWN, Frame.Y_UP])
@pytest.mark.parametrize(
    ("image_size", "extent"),
    [
        ((1000, 1000), (0.0, 0.0, 100.0, 100.0)),
        ((300, 100), (0.0, 0.0, 30.0, 10.0)),
        ((1754, 1240), (-12.5, 3.25, 1741.5, 1243.25)),
        ((640, 480), (100.0, 200.0, 740.0, 680.0)),
        ((2480, 3508), (0.0, 0.0, 620.0, 877.0)),
        ((800, 600), (0.0, 0.0, 10.0, 10.0)),  # aspect mismatch: letterboxed
        ((7, 13), (-1.0, -2.0, 6.0, 11.0)),
    ],
)
def test_L5_bbox_roundtrip(
    frame: Frame, image_size: tuple[int, int], extent: tuple[float, float, float, float]
) -> None:
    x0, y0, x1, y1 = extent
    # native extent -> normalised -> native: exact
    n = native_to_normalized(extent, image_size=image_size, extent=extent, frame=frame)
    back = normalized_to_native(n, image_size=image_size, extent=extent, frame=frame)
    assert back == extent
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for cx, cy in corners:
        tiny = (cx, cy, cx, cy)
        nn = native_to_normalized(tiny, image_size=image_size, extent=extent, frame=frame)
        assert normalized_to_native(nn, image_size=image_size, extent=extent, frame=frame) == tiny
    w, h = image_size
    if w * (y1 - y0) == h * (x1 - x0):  # same aspect: extent fills the image exactly
        assert n == (0.0, 0.0, 1000.0, 1000.0)
        full = normalized_to_native(
            (0, 0, 1000, 1000), image_size=image_size, extent=extent, frame=frame
        )
        assert full == extent
        # image corner (top-left) is the extent's top-left in the plan's frame
        top_left = normalized_to_native(
            (0, 0, 0, 0), image_size=image_size, extent=extent, frame=frame
        )
        expected_y = y1 if frame is Frame.Y_UP else y0
        assert top_left == (x0, expected_y, x0, expected_y)


@pytest.mark.parametrize("frame", [Frame.Y_DOWN, Frame.Y_UP])
def test_L5_bbox_roundtrip_inexact_aspect(frame: Frame) -> None:
    # Aspect ratios that give non-representable normalised values: one float rounding only.
    extent = (0.0, 0.0, 595.2756, 841.8898)
    for size in ((2481, 3508), (999, 1001), (7, 13)):
        n = native_to_normalized(extent, image_size=size, extent=extent, frame=frame)
        back = normalized_to_native(n, image_size=size, extent=extent, frame=frame)
        assert back == pytest.approx(extent, rel=1e-12, abs=1e-12)


def test_L5_letterbox_centred() -> None:
    n = native_to_normalized(
        (0.0, 0.0, 10.0, 10.0),
        image_size=(800, 600),
        extent=(0.0, 0.0, 10.0, 10.0),
        frame=Frame.Y_DOWN,
    )
    assert n == (0.0, 125.0, 1000.0, 875.0)


# --------------------------------------------------------------------------- L6


def test_L6_hungarian(cache: VlmCache) -> None:
    # Rooms L (0..10) and R (10..20). Box 1 covers R (2/3) and L (1/3); box 2 covers L (2/3)
    # and R (1/3): all four pairs are eligible (>= 0.3), the optimum is box1-R + box2-L.
    extent = (0.0, 0.0, 20.0, 10.0)
    size = (200, 100)
    p = plan([room("L", rect(0, 0, 10, 10)), room("R", rect(10, 0, 20, 10))])
    box1 = norm_bbox((5, 0, 20, 10), image_size=size, extent=extent, frame=Frame.Y_UP)
    box2 = norm_bbox((0, 0, 15, 10), image_size=size, extent=extent, frame=Frame.Y_UP)
    fake = FakeProvider([vlm_json(("Rangement", box1, 1.0), ("Archives", box2, 1.0))])
    res = label_plan(p, image=png_bytes(*size), provider=fake, cache=cache, config=vlm_config())
    rooms = _by_id(res)
    assert rooms["R"].raw_label == "Rangement"
    assert rooms["L"].raw_label == "Archives"
    assert rooms["R"].confidence == pytest.approx(10 / 15)
    assert rooms["L"].confidence == pytest.approx(10 / 15)


@pytest.mark.parametrize("use_scipy", [True, False])
def test_L6_assignment_maximises_total(use_scipy: bool) -> None:
    weights = [[0.4, 0.9], [0.8, 0.35]]
    assert assign_one_to_one(weights, use_scipy=use_scipy) == [(0, 1), (1, 0)]


def test_L6_scipy_path_used_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    import itertools
    import sys
    import types

    import numpy as np

    seen: list[object] = []

    def fake_lsa(matrix: np.ndarray, maximize: bool = False) -> tuple[list[int], list[int]]:
        seen.append(maximize)
        n_rows, n_cols = matrix.shape
        best: tuple[float, tuple[int, ...]] = (-1.0, ())
        for perm in itertools.permutations(range(n_cols), n_rows):
            total = float(sum(matrix[i, j] for i, j in enumerate(perm)))
            if total > best[0]:
                best = (total, perm)
        return list(range(n_rows)), list(best[1])

    mod = types.ModuleType("scipy.optimize")
    mod.linear_sum_assignment = fake_lsa  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scipy.optimize", mod)
    # greedy would pick (0,0)=0.9 then nothing eligible; the optimum is the cross pairing
    weights = [[0.9, 0.8], [0.85, 0.0]]
    assert assign_one_to_one(weights) == [(0, 1), (1, 0)]
    assert seen == [True]
    assert assign_one_to_one(weights, use_scipy=False) == [(0, 0)]


# --------------------------------------------------------------------------- L7


@pytest.mark.parametrize("with_provider", [True, False])
def test_L7_no_provider(cache: VlmCache, with_provider: bool) -> None:
    fake = FakeProvider([vlm_json(("Rangement", _c_bbox(), 1.0))])
    res = label_plan(
        three_room_plan(),
        image=png_bytes(*IMG_SIZE),
        provider=fake if with_provider else None,
        cache=cache,
        config=vlm_config(""),
    )
    assert _by_id(res)["C"].type is None
    assert res.api_calls == 0
    assert fake.calls == []


def test_L7_provider_none_but_config_set(cache: VlmCache) -> None:
    res = label_plan(
        three_room_plan(),
        image=png_bytes(*IMG_SIZE),
        provider=None,
        cache=cache,
        config=vlm_config("fake"),
    )
    assert _by_id(res)["C"].type is None
    assert res.api_calls == 0


# --------------------------------------------------------------------------- L8


def test_L8_temperature(cache: VlmCache) -> None:
    fake = FakeProvider(["bad", vlm_json(("Rangement", _c_bbox(), 1.0))])
    label_plan(
        three_room_plan(),
        image=png_bytes(*IMG_SIZE),
        provider=fake,
        cache=cache,
        config=vlm_config(),
    )
    assert len(fake.calls) == 2
    for _, temperature in fake.calls:
        assert type(temperature) is float
        assert temperature == 0.0
