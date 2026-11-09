"""Ticket P.1 evaluation V1-V8 (the Anthropic SDK client is mocked; no network)."""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

import pytest

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")

from providers_helpers import (  # noqa: E402
    IMG_SIZE,
    FakeClient,
    answer_json,
    anthropic_config,
    message,
    png_bytes,
    two_room_plan,
)

from ale.config import AleConfig  # noqa: E402
from ale.contracts.enums import LabelSource  # noqa: E402
from ale.labels import VlmResponse, VlmRoom, build_prompt, label_plan, parse_response  # noqa: E402
from ale.labels.bbox import png_size  # noqa: E402
from ale.labels.cache import VlmCache  # noqa: E402
from ale.labels.providers import (  # noqa: E402
    AnthropicVlmProvider,
    MissingApiKeyError,
    VlmProviderError,
    make_provider,
    prepare_image,
)
from ale.labels.providers import anthropic_provider as ap  # noqa: E402

KEY_ENV = "ALE_TEST_VLM_KEY"
SECRET = "sk-ant-test-DO-NOT-LEAK-0123456789"
REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls: type[Exception], status: int) -> Exception:
    resp = httpx2.Response(status, request=REQ)
    return cls(f"simulated {status}", response=resp, body=None)  # type: ignore[call-arg]


@pytest.fixture
def cache(tmp_path: Path) -> VlmCache:
    return VlmCache(tmp_path / "ws" / "cache" / "vlm")


def _provider(client: FakeClient) -> AnthropicVlmProvider:
    return AnthropicVlmProvider(client=client)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- V1


def test_V1_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    assert make_provider(AleConfig()) is None
    assert make_provider(AleConfig.model_validate({"vlm": {"provider": ""}})) is None

    monkeypatch.setenv("ALE_VLM_API_KEY", SECRET)
    prov = make_provider(anthropic_config())
    assert isinstance(prov, AnthropicVlmProvider)
    assert prov.model_id == "claude-opus-5-5"
    assert prov.api_key_env == "ALE_VLM_API_KEY"
    assert prov.timeout_s == 120.0

    monkeypatch.setenv(KEY_ENV, SECRET)
    custom = make_provider(
        anthropic_config(model_id="claude-sonnet-5-5", api_key_env=KEY_ENV, timeout_s=7.5)
    )
    assert isinstance(custom, AnthropicVlmProvider)
    assert custom.model_id == "claude-sonnet-5-5"
    assert custom.api_key_env == KEY_ENV
    assert custom.timeout_s == 7.5

    with pytest.raises(ValueError, match="openai-ish"):
        make_provider(AleConfig.model_validate({"vlm": {"provider": "openai-ish"}}))


# --------------------------------------------------------------------------- V2


def test_V2_request_shape() -> None:
    client = FakeClient(message(answer_json()))
    prov = _provider(client)
    img = png_bytes(*IMG_SIZE)
    prov.label_image(img, build_prompt(), temperature=0.0)

    assert len(client.calls) == 1
    req = client.calls[0]
    assert req["model"] == "claude-opus-5-5"
    for forbidden in ("temperature", "top_p", "top_k"):
        assert forbidden not in req
    (msg,) = req["messages"]
    assert msg["role"] == "user"
    image_block, text_block = msg["content"]
    assert image_block["type"] == "image"
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/png"
    assert base64.standard_b64decode(image_block["source"]["data"]) == img
    assert text_block == {"type": "text", "text": build_prompt()}

    assert req["output_config"]["effort"] == "low"
    fmt = req["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    schema = fmt["schema"]
    # The schema matches VlmResponse: same fields, all required, nothing extra.
    assert set(schema["properties"]) == set(VlmResponse.model_fields)
    assert schema["required"] == ["rooms"]
    assert schema["additionalProperties"] is False
    room = schema["properties"]["rooms"]["items"]
    assert set(room["properties"]) == set(VlmRoom.model_fields)
    assert set(room["required"]) == set(VlmRoom.model_fields)
    assert room["additionalProperties"] is False
    import jsonschema

    jsonschema.validate(json.loads(answer_json()), schema)
    # Adaptive thinking, refusal fallback, timeout.
    assert req["thinking"] == {"type": "adaptive"}
    assert req["fallbacks"] == "default"
    assert req["betas"] == ["server-side-fallback-2026-07-01"]
    assert req["timeout"] == 120.0


# --------------------------------------------------------------------------- V3


def test_V3_json_roundtrip(cache: VlmCache) -> None:
    client = FakeClient(message(answer_json()))
    prov = _provider(client)
    raw = prov.label_image(png_bytes(*IMG_SIZE), build_prompt(), temperature=0.0)
    resp, err = parse_response(raw)
    assert err is None and resp is not None and len(resp.rooms) == 2

    client2 = FakeClient(message(answer_json()))
    prov2 = _provider(client2)
    img = png_bytes(*IMG_SIZE)
    cfg = anthropic_config()
    res = label_plan(two_room_plan(), image=img, provider=prov2, cache=cache, config=cfg)
    rooms = {r.id: r for r in res.plan.rooms}
    assert rooms["A"].type == "office"
    assert rooms["A"].label_source is LabelSource.VLM
    assert rooms["B"].label_source is LabelSource.VLM
    assert res.api_calls == 1
    assert len(client2.calls) == 1

    again = label_plan(two_room_plan(), image=img, provider=prov2, cache=cache, config=cfg)
    assert again.api_calls == 0
    assert len(client2.calls) == 1
    assert again.plan == res.plan


# --------------------------------------------------------------------------- V4


def _error_outcomes() -> list[tuple[str, Any]]:
    return [
        ("refusal", message(None, stop_reason="refusal", category="cyber")),
        ("max_tokens", message('{"rooms": [', stop_reason="max_tokens")),
        ("rate_limit", _status_error(anthropic.RateLimitError, 429)),
        ("auth", _status_error(anthropic.AuthenticationError, 401)),
        ("connection", anthropic.APIConnectionError(request=REQ)),
    ]


@pytest.mark.parametrize(("name", "outcome"), _error_outcomes(), ids=lambda v: str(v)[:12])
def test_V4_errors(name: str, outcome: Any, cache: VlmCache) -> None:
    client = FakeClient(outcome)
    prov = _provider(client)
    with pytest.raises(VlmProviderError):
        prov.label_image(png_bytes(*IMG_SIZE), build_prompt(), temperature=0.0)

    client2 = FakeClient(outcome)
    res = label_plan(
        two_room_plan(),
        image=png_bytes(*IMG_SIZE),
        provider=_provider(client2),
        cache=cache,
        config=anthropic_config(),
    )
    assert all(r.type is None for r in res.plan.rooms), name
    assert any("VlmProviderError" in w for w in res.warnings), res.warnings
    assert res.api_calls == 1
    assert list(cache.directory.glob("*.txt")) == []


# --------------------------------------------------------------------------- V5


def test_V5_key_hygiene(
    monkeypatch: pytest.MonkeyPatch, cache: VlmCache, caplog: pytest.LogCaptureFixture
) -> None:
    created: list[dict[str, Any]] = []

    def fake_ctor(**kwargs: Any) -> FakeClient:
        created.append(kwargs)
        return FakeClient(message(answer_json()))

    monkeypatch.setattr(anthropic, "Anthropic", fake_ctor)

    # Missing (or empty) env var: clear error naming the variable, no client created.
    monkeypatch.delenv(KEY_ENV, raising=False)
    with pytest.raises(MissingApiKeyError, match=KEY_ENV):
        AnthropicVlmProvider(api_key_env=KEY_ENV)
    monkeypatch.setenv(KEY_ENV, "  ")
    with pytest.raises(MissingApiKeyError):
        make_provider(anthropic_config(api_key_env=KEY_ENV))
    assert created == []

    # Present: passed explicitly to the client, never kept, logged or cached.
    monkeypatch.setenv(KEY_ENV, SECRET)
    caplog.set_level(logging.DEBUG)
    prov = make_provider(anthropic_config(api_key_env=KEY_ENV))
    assert prov is not None
    assert len(created) == 1 and created[0]["api_key"] == SECRET
    assert created[0]["timeout"] == 120.0
    assert SECRET not in repr(prov)
    assert all(SECRET not in repr(v) for v in vars(prov).values() if not isinstance(v, FakeClient))

    res = label_plan(
        two_room_plan(),
        image=png_bytes(*IMG_SIZE),
        provider=prov,
        cache=cache,
        config=anthropic_config(api_key_env=KEY_ENV),
    )
    assert res.api_calls == 1
    # An auth failure message names the variable, not the value.
    failing = AnthropicVlmProvider(
        api_key_env=KEY_ENV,
        client=FakeClient(_status_error(anthropic.AuthenticationError, 401)),  # type: ignore[arg-type]
    )
    with pytest.raises(VlmProviderError) as info:
        failing.label_image(png_bytes(*IMG_SIZE), "p", temperature=0.0)
    assert KEY_ENV in str(info.value) and SECRET not in str(info.value)

    assert SECRET not in caplog.text
    assert all(SECRET not in w for w in res.warnings)
    files = [p for p in cache.directory.rglob("*") if p.is_file()]
    assert files, "the response should have been cached"
    for p in files:
        assert SECRET.encode() not in p.read_bytes()


# --------------------------------------------------------------------------- V6


def test_V6_downscale() -> None:
    big = png_bytes(4000, 3000)
    client = FakeClient(message(answer_json()))
    prov = _provider(client)
    prov.label_image(big, build_prompt(), temperature=0.0)

    data = client.calls[0]["messages"][0]["content"][0]["source"]["data"]
    sent = base64.standard_b64decode(data)
    size = png_size(sent)
    assert size is not None
    w, h = size
    assert max(w, h) <= 1568
    assert (w, h) == (1568, 1176)
    assert abs(w / h - 4000 / 3000) < 1e-3
    assert prov.last_image_size == size

    prepared = prepare_image(big)
    assert prepared.size == size
    assert png_size(prepared.png) == prepared.size


# --------------------------------------------------------------------------- V7


@pytest.mark.skipif(os.environ.get("ALE_LIVE_VLM") != "1", reason="live VLM test (ALE_LIVE_VLM=1)")
def test_V7_live_smoke(cache: VlmCache) -> None:  # pragma: no cover - never in CI
    import io

    from PIL import Image, ImageDraw

    img = Image.new("RGB", IMG_SIZE, "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 99, 99), outline="black", width=3)
    draw.rectangle((100, 0, 299, 99), outline="black", width=3)
    draw.text((20, 45), "BUREAU", fill="black")
    draw.text((140, 45), "SALLE DE REUNION", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    cfg = anthropic_config()
    prov = make_provider(cfg)
    res = label_plan(two_room_plan(), image=buf.getvalue(), provider=prov, cache=cache, config=cfg)
    assert sum(r.type is not None for r in res.plan.rooms) >= 1, res.warnings


# --------------------------------------------------------------------------- V8


def test_V8_gates_module_surface() -> None:
    # Importing the provider package never imports a client eagerly; the protocol holds.
    from ale.labels import VlmProvider

    prov = _provider(FakeClient(message(answer_json())))
    assert isinstance(prov, VlmProvider)
    assert ap.DEFAULT_MODEL_ID == "claude-opus-5-5"
