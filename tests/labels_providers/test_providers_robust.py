"""Edge cases of the Claude VLM provider (mocked client; no network)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")

from providers_helpers import FakeClient, answer_json, message, png_bytes  # noqa: E402

from ale.labels.providers import (  # noqa: E402
    AnthropicVlmProvider,
    VlmProviderError,
    prepare_image,
)

REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status(cls: type[Exception], status: int) -> Exception:
    return cls("boom", response=httpx2.Response(status, request=REQ), body=None)  # type: ignore[call-arg]


def _prov(*outcomes: Any, **kw: Any) -> tuple[AnthropicVlmProvider, FakeClient]:
    client = FakeClient(*outcomes)
    return AnthropicVlmProvider(client=client, **kw), client  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("exc", "needle"),
    [
        (_status(anthropic.RateLimitError, 429), "rate limit"),
        (_status(anthropic.AuthenticationError, 401), "authentication"),
        (_status(anthropic.PermissionDeniedError, 403), "permission"),
        (_status(anthropic.BadRequestError, 400), "bad request"),
        (_status(anthropic.InternalServerError, 500), "(500)"),
        (anthropic.APITimeoutError(request=REQ), "timed out after 3 s"),
        (anthropic.APIConnectionError(request=REQ), "connection"),
        (anthropic.APIError("weird", REQ, body=None), "API error"),
    ],
)
def test_error_chain_most_specific_first(exc: Exception, needle: str) -> None:
    prov, _ = _prov(exc, timeout_s=3.0)
    with pytest.raises(VlmProviderError, match=None) as info:
        prov.label_image(png_bytes(10, 10), "p", temperature=0.0)
    assert needle in str(info.value)
    assert info.value.__cause__ is exc


def test_refusal_message_names_category() -> None:
    prov, _ = _prov(message(None, stop_reason="refusal", category="bio"))
    with pytest.raises(VlmProviderError, match="'bio'"):
        prov.label_image(png_bytes(10, 10), "p", temperature=0.0)


def test_unexpected_stop_and_empty_answer() -> None:
    prov, _ = _prov(message("x", stop_reason="pause_turn"))
    with pytest.raises(VlmProviderError, match="pause_turn"):
        prov.label_image(png_bytes(10, 10), "p", temperature=0.0)
    prov, _ = _prov(message("   "))
    with pytest.raises(VlmProviderError, match="no text"):
        prov.label_image(png_bytes(10, 10), "p", temperature=0.0)
    prov, _ = _prov(message(None))
    with pytest.raises(VlmProviderError, match="no text"):
        prov.label_image(png_bytes(10, 10), "p", temperature=0.0)


def test_text_after_fallback_switch_point_only() -> None:
    blocks = [
        SimpleNamespace(type="text", text="partial-from-declined-model"),
        SimpleNamespace(type="fallback"),
        SimpleNamespace(type="thinking", thinking=""),
    ]
    prov, _ = _prov(message(answer_json(), blocks=blocks))
    assert prov.label_image(png_bytes(10, 10), "p", temperature=0.0) == answer_json()


def test_temperature_must_be_zero() -> None:
    prov, client = _prov(message(answer_json()))
    with pytest.raises(AssertionError):
        prov.label_image(png_bytes(10, 10), "p", temperature=0.2)
    assert client.calls == []


def test_constructor_validation_and_defaults() -> None:
    with pytest.raises(ValueError, match="timeout_s"):
        AnthropicVlmProvider(client=FakeClient(), timeout_s=0)  # type: ignore[arg-type]
    prov, _ = _prov(model_id="")
    assert prov.model_id == "claude-opus-5-5"
    assert "claude-opus-5-5" in repr(prov)
    assert prov.last_image_size is None


def test_prepare_image_small_is_unchanged_and_invalid_raises() -> None:
    small = png_bytes(1568, 100)
    prepared = prepare_image(small)
    assert prepared.png is small
    assert prepared.size == (1568, 100)
    tall = prepare_image(png_bytes(50, 3136))
    assert tall.size == (25, 1568)
    with pytest.raises(VlmProviderError, match="not a valid PNG"):
        prepare_image(b"not a png")
    prov, client = _prov(message(answer_json()))
    with pytest.raises(VlmProviderError):
        prov.label_image(b"nope", "p", temperature=0.0)
    assert client.calls == []


def test_real_sdk_client_is_built_with_key_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALE_TEST_KEY_2", "sk-ant-dummy")
    prov = AnthropicVlmProvider(api_key_env="ALE_TEST_KEY_2", timeout_s=9.0, max_retries=1)
    client = prov._client
    assert isinstance(client, anthropic.Anthropic)
    assert client.max_retries == 1
    assert client.timeout == 9.0
