"""Edge cases of Ticket 1.5: nothing raises, problems become warnings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from labels_helpers import (
    SHA,
    FakeProvider,
    RaisingProvider,
    norm_bbox,
    plan,
    png_bytes,
    rect,
    room,
    text,
    three_room_plan,
    vlm_config,
    vlm_json,
)

from ale.contracts.enums import Frame, LabelSource
from ale.contracts.geometry import LineString, Polygon
from ale.contracts.models import LabelledPolygon, Wall
from ale.contracts.taxonomy import load_taxonomy
from ale.labels import (
    PROMPT_VERSION,
    VlmCache,
    VlmProvider,
    VlmRoom,
    build_prompt,
    cache_key,
    label_plan,
    normalized_to_native,
    parse_response,
    plan_extent,
    png_size,
)
from ale.labels import label as label_mod

IMG = (300, 100)
EXT = (0.0, 0.0, 30.0, 10.0)


def _c_bbox() -> list[int]:
    return norm_bbox((20, 0, 30, 10), image_size=IMG, extent=EXT, frame=Frame.Y_UP)


@pytest.fixture
def cache(tmp_path: Path) -> VlmCache:
    return VlmCache(tmp_path / "vlm")


def _run(p: object = None, **kw: object) -> label_mod.LabelResult:
    args: dict[str, object] = {
        "image": png_bytes(*IMG),
        "provider": FakeProvider([vlm_json(("Rangement", _c_bbox(), 1.0))]),
        "config": vlm_config(),
    }
    args.update(kw)
    return label_plan(p if p is not None else three_room_plan(), **args)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- text stage


def test_cad_text_source_and_prefix_confidence(cache: VlmCache) -> None:
    p = plan(
        [room("A", rect(0, 0, 10, 10)), room("B", rect(10, 0, 20, 10))],
        [text("Bureau", 5, 5, source="CAD"), text("BUREAU DU DIRECTEUR", 15, 5, source="OCR")],
    )
    res = label_plan(p, image=None, provider=None, cache=cache, config=vlm_config(""))
    a, b = res.plan.rooms
    assert (a.type, a.label_source, a.confidence) == ("office", LabelSource.CAD_TEXT, 1.0)
    assert b.type == "office"
    assert b.label_source is LabelSource.PDF_TEXT
    assert b.confidence == pytest.approx(0.8)


def test_best_text_wins_and_unknown_ignored(cache: VlmCache) -> None:
    p = plan(
        [room("A", rect(0, 0, 10, 10))],
        [text("ZZZ QQQ", 2, 2), text("Bureau 12", 4, 4), text("Salle de réunion", 6, 6)],
    )
    res = label_plan(p, image=None, provider=None, cache=cache, config=vlm_config(""))
    assert res.plan.rooms[0].type == "meeting_room"
    p2 = plan([room("A", rect(0, 0, 10, 10))], [text("ZZZ QQQ", 2, 2), text("Bureau", 50, 50)])
    res2 = label_plan(p2, image=None, provider=None, cache=cache, config=vlm_config(""))
    assert res2.plan.rooms[0].type is None


def test_text_in_hole_does_not_label(cache: VlmCache) -> None:
    poly = Polygon(
        exterior=((0, 0), (10, 0), (10, 10), (0, 10)), holes=(((4, 4), (6, 4), (6, 6), (4, 6)),)
    )
    p = plan([room("A", poly)], [text("Bureau", 5, 5)])
    res = label_plan(p, image=None, provider=None, cache=cache, config=vlm_config(""))
    assert res.plan.rooms[0].type is None


def test_invalid_polygon_is_made_valid() -> None:
    # The contract rejects self-intersecting rings; bypass it to exercise the guard.
    bowtie = Polygon.model_construct(exterior=((0, 0), (10, 10), (10, 0), (0, 10)), holes=())
    lp = LabelledPolygon.model_construct(
        id="A", polygon=bowtie, type=None, label_source=None, confidence=0.0
    )
    got = label_mod._label_from_texts(lp, [text("Bureau", 9, 5)])
    assert got is not None and got.type == "office"


def test_text_labelling_error_becomes_warning(
    cache: VlmCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: object) -> None:
        raise RuntimeError("geos")

    monkeypatch.setattr(label_mod, "_label_from_texts", boom)
    res = label_plan(
        three_room_plan(), image=None, provider=None, cache=cache, config=vlm_config("")
    )
    assert all(r.type is None for r in res.plan.rooms)
    assert sum("text labelling failed" in w for w in res.warnings) == 3


def test_total_failure_returns_input_plan(cache: VlmCache, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object, **__: object) -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(label_mod, "plan_extent", boom)
    p = three_room_plan()
    res = _run(p, cache=cache)
    rooms = {r.id: r for r in res.plan.rooms}
    assert rooms["A"].type == "office"  # the text stage result is kept
    assert rooms["C"].type is None
    assert any("VLM labelling failed" in w for w in res.warnings)


def test_outer_failure_returns_input_plan(cache: VlmCache) -> None:
    class BadConfig:
        @property
        def vlm(self) -> object:
            raise RuntimeError("broken config")

    p = three_room_plan()
    res = _run(p, cache=cache, config=BadConfig())
    assert res.plan == p
    assert res.api_calls == 0
    assert any("labelling failed" in w for w in res.warnings)


def test_cache_write_cleans_temp_file(cache: VlmCache, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(self: Path, target: Path) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", fail)
    err = cache.put("0" * 64, "raw")
    assert err is not None and "disk full" in err
    assert list(cache.directory.iterdir()) == []


# --------------------------------------------------------------------------- VLM stage guards


def test_no_image_warning(cache: VlmCache) -> None:
    res = _run(cache=cache, image=None)
    assert res.api_calls == 0
    assert any("no image" in w for w in res.warnings)


def test_non_png_image(cache: VlmCache) -> None:
    res = _run(cache=cache, image=b"GIF89a....")
    assert res.api_calls == 0
    assert any("not a valid PNG" in w for w in res.warnings)


def test_no_extent(cache: VlmCache) -> None:
    res = _run(cache=cache, extent=(0.0, 0.0, 0.0, 10.0))
    assert res.api_calls == 0
    assert any("extent" in w for w in res.warnings)


def test_explicit_extent_used(cache: VlmCache) -> None:
    # same image, extent twice as wide: the box over C now covers x 40..60 → nothing matches
    res = _run(cache=cache, extent=(0.0, 0.0, 60.0, 20.0))
    assert res.api_calls == 1
    assert all(r.label_source is not LabelSource.VLM for r in res.plan.rooms)


def test_all_typed_no_call(cache: VlmCache) -> None:
    p = plan([room("A", rect(0, 0, 10, 10))], [text("Bureau", 5, 5)])
    fake = FakeProvider([vlm_json()])
    res = label_plan(p, image=png_bytes(*IMG), provider=fake, cache=cache, config=vlm_config())
    assert res.api_calls == 0
    assert fake.calls == []


def test_provider_exception(cache: VlmCache) -> None:
    prov = RaisingProvider()
    res = _run(cache=cache, provider=prov)
    assert prov.calls == 1
    assert res.api_calls == 1
    assert any("provider call failed" in w for w in res.warnings)
    assert all(r.label_source is not LabelSource.VLM for r in res.plan.rooms)


def test_provider_returns_non_str(cache: VlmCache) -> None:
    class BytesProvider:
        model_id = "bytes"

        def label_image(self, image_png: bytes, prompt: str, *, temperature: float) -> object:
            return b"{}"

    res = _run(cache=cache, provider=BytesProvider())
    assert res.api_calls == 2
    assert any("invalid" in w for w in res.warnings)


@pytest.mark.parametrize(("retries", "calls"), [(0, 1), (1, 2), (3, 4)])
def test_retry_count_follows_config(cache: VlmCache, retries: int, calls: int) -> None:
    fake = FakeProvider(["garbage"])
    res = _run(cache=cache, provider=fake, config=vlm_config(retries=retries))
    assert res.api_calls == calls == len(fake.calls)


def test_corrupt_cache_entry_is_ignored(cache: VlmCache) -> None:
    image = png_bytes(*IMG)
    key = cache_key(
        source_sha256=SHA,
        page=0,
        plan_index=0,
        prompt_version=PROMPT_VERSION,
        model_id="fake-vlm-1",
        image=image,
    )
    assert cache.put(key, "not json") is None
    res = _run(cache=cache, image=image)
    assert res.api_calls == 1
    assert any("cached VLM response ignored" in w for w in res.warnings)
    assert cache.get(key) is not None and json.loads(cache.get(key) or "")["rooms"]


def test_cache_write_failure_is_a_warning(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    res = _run(cache=VlmCache(blocker / "vlm"))
    assert res.api_calls == 1
    assert any("cache write failed" in w for w in res.warnings)
    assert any(r.label_source is LabelSource.VLM for r in res.plan.rooms)


def test_cache_bad_key(cache: VlmCache) -> None:
    assert cache.get("../etc") is None
    assert cache.put("XYZ", "x") is not None


def test_cache_key_inputs_matter() -> None:
    base = dict(
        source_sha256=SHA, page=0, plan_index=0, prompt_version="v1", model_id="m", image=b"x"
    )
    k0 = cache_key(**base)  # type: ignore[arg-type]
    for field, value in [
        ("source_sha256", "cd" * 32),
        ("page", 1),
        ("plan_index", 1),
        ("prompt_version", "v2"),
        ("model_id", "n"),
        ("image", b"y"),
    ]:
        assert cache_key(**{**base, field: value}) != k0  # type: ignore[arg-type]
    assert len(k0) == 64


def test_prompt_version_config_mismatch_warns(cache: VlmCache) -> None:
    cfg = vlm_config().model_copy(
        update={"vlm": vlm_config().vlm.model_copy(update={"prompt_version": "v9"})}
    )
    res = _run(cache=cache, config=cfg)
    assert any("prompt_version" in w for w in res.warnings)
    assert res.api_calls == 1


# --------------------------------------------------------------------------- VLM matching


def test_vlm_key_label_and_unknown_label(cache: VlmCache) -> None:
    p = plan([room("L", rect(0, 0, 10, 10)), room("R", rect(10, 0, 20, 10))])
    ext, size = (0.0, 0.0, 20.0, 10.0), (200, 100)
    bl = norm_bbox((0, 0, 10, 10), image_size=size, extent=ext, frame=Frame.Y_UP)
    br = norm_bbox((10, 0, 20, 10), image_size=size, extent=ext, frame=Frame.Y_UP)
    fake = FakeProvider([vlm_json(("office", bl, 0.7), ("Pièce mystère", br, 0.6))])
    res = label_plan(p, image=png_bytes(*size), provider=fake, cache=cache, config=vlm_config())
    left, right = res.plan.rooms
    assert left.type == "office"  # an exact taxonomy key is accepted as such
    assert (right.type, right.label_source) == ("unknown", LabelSource.VLM)
    assert right.confidence == pytest.approx(0.6)


def test_low_overlap_and_degenerate_box_not_matched(cache: VlmCache) -> None:
    # box mostly outside the room (overlap 0.2 < 0.3) and a zero-area box
    wide = norm_bbox((18, 0, 28, 10), image_size=IMG, extent=EXT, frame=Frame.Y_UP)
    flat = [500, 700, 500, 900]
    fake = FakeProvider([vlm_json(("Rangement", wide, 1.0), ("Archives", flat, 1.0))])
    p = plan([room("C", rect(20, 0, 30, 10)), room("Z", rect(0, 0, 18, 10))])
    res = label_plan(p, image=png_bytes(*IMG), provider=fake, cache=cache, config=vlm_config())
    c, z = res.plan.rooms
    assert c.type == "storage"  # 8/10 of the box over C
    assert c.confidence == pytest.approx(0.8, abs=1e-3)
    assert z.type is None
    assert any("1 VLM room(s) matched no" in w for w in res.warnings)


def test_more_boxes_than_rooms(cache: VlmCache) -> None:
    b = _c_bbox()
    fake = FakeProvider([vlm_json(("Rangement", b, 0.9), ("Archives", b, 0.8))])
    res = _run(cache=cache, provider=fake)
    c = {r.id: r for r in res.plan.rooms}["C"]
    assert c.raw_label == "Rangement"  # equal overlap: lowest index wins (deterministic)


def test_assign_empty() -> None:
    assert label_mod.assign_one_to_one([]) == []
    assert label_mod.assign_one_to_one([[]]) == []
    assert label_mod.assign_one_to_one([[0.0, 0.0]]) == []


def test_scipy_without_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    monkeypatch.setitem(sys.modules, "scipy.optimize", types.ModuleType("scipy.optimize"))
    assert label_mod._scipy_solver() is None
    assert label_mod.assign_one_to_one([[0.5]]) == [(0, 0)]


# --------------------------------------------------------------------------- provider helpers


def test_prompt_lists_taxonomy_fr_en() -> None:
    prompt = build_prompt()
    assert PROMPT_VERSION in prompt
    assert "FR" in prompt and "EN" in prompt
    for t in load_taxonomy().types:
        if t.key != "unknown":
            assert f"- {t.key}: {t.label_fr} / {t.label_en}" in prompt
    assert '"rooms"' in prompt and "bbox" in prompt


def test_parse_response_variants() -> None:
    good = vlm_json(("Bureau", [0, 0, 10, 10], 0.5))
    assert parse_response(good)[0] is not None
    assert parse_response(f"```json\n{good}\n```")[0] is not None
    assert parse_response("```\n")[0] is None
    resp, err = parse_response('{"rooms": [{"label": "x", "bbox": [5, 0, 1, 1], "confidence": 1}]}')
    assert resp is None and err is not None and "schema" in err
    assert (
        parse_response('{"rooms": [{"label": "x", "bbox": [0, 0, 1, 1001], "confidence": 1}]}')[0]
        is None
    )
    assert (
        parse_response('{"rooms": [{"label": "x", "bbox": [0, 0, 1, 1], "confidence": 2}]}')[0]
        is None
    )
    assert parse_response("[" * 100000)[0] is None


def test_vlm_room_model() -> None:
    r = VlmRoom(label="a", bbox=(0, 1, 2, 3), confidence=0.5)
    assert r.bbox == (0, 1, 2, 3)
    with pytest.raises(ValueError):
        VlmRoom(label="a", bbox=(3, 1, 2, 3), confidence=0.5)


def test_fake_is_a_provider() -> None:
    assert isinstance(FakeProvider([]), VlmProvider)


def test_png_size() -> None:
    assert png_size(png_bytes(17, 5)) == (17, 5)
    assert png_size(b"") is None
    assert png_size(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16) is None
    zero = bytearray(png_bytes(3, 3))
    zero[16:20] = b"\x00\x00\x00\x00"
    assert png_size(bytes(zero)) is None


def test_bbox_bad_inputs() -> None:
    with pytest.raises(ValueError):
        normalized_to_native((0, 0, 1, 1), image_size=(0, 10), extent=EXT, frame=Frame.Y_UP)
    with pytest.raises(ValueError):
        normalized_to_native(
            (0, 0, 1, 1), image_size=(10, 10), extent=(0, 0, 0, 1), frame=Frame.Y_UP
        )


def test_plan_extent() -> None:
    assert plan_extent(plan([])) is None
    assert plan_extent(three_room_plan()) == EXT
    walls_only = plan([]).model_copy(
        update={"walls": (Wall(centerline=LineString(coords=((-5.0, 1.0), (5.0, 7.0)))),)}
    )
    assert plan_extent(walls_only) == (-5.0, 1.0, 5.0, 7.0)
    horizontal = plan([]).model_copy(
        update={"walls": (Wall(centerline=LineString(coords=((0.0, 1.0), (5.0, 1.0)))),)}
    )
    assert plan_extent(horizontal) is None
