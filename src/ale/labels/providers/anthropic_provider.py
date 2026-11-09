"""Claude (Anthropic API) implementation of :class:`~ale.labels.provider.VlmProvider`.

One Messages API call per :meth:`AnthropicVlmProvider.label_image`: the user turn holds
the plan image (base64 PNG) followed by the text prompt; the answer is constrained to
JSON matching :class:`~ale.labels.provider.VlmResponse` with structured outputs
(``output_config.format``). No sampling parameter is sent (current models reject
``temperature``); determinism comes from :class:`~ale.labels.cache.VlmCache`.

Refusals: the server-side refusal fallback is enabled (``fallbacks="default"`` under the
``server-side-fallback-2026-07-01`` beta), so a classifier decline is retried on the
model Anthropic recommends for that refusal category inside the same call. A final
``refusal`` (the whole chain declined) or ``max_tokens`` stop raises
:class:`VlmProviderError`.

The ``anthropic`` package (extra ``vlm``) is imported lazily, so this module can be
imported without it. The API key is read from the environment variable named in the
configuration and handed to the SDK client; it is never stored on the provider, logged
or written anywhere.
"""

from __future__ import annotations

import base64
import io
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from ale.labels.bbox import png_size

if TYPE_CHECKING:
    import anthropic

__all__ = [
    "DEFAULT_MODEL_ID",
    "FALLBACK_BETA",
    "MAX_IMAGE_SIDE",
    "RESPONSE_SCHEMA",
    "AnthropicVlmProvider",
    "MissingApiKeyError",
    "PreparedImage",
    "VlmProviderError",
    "prepare_image",
]

#: Default Claude model (``vlm.model_id`` empty).
DEFAULT_MODEL_ID: Final = "claude-opus-5-5"
#: Images whose long side exceeds this are downscaled before encoding.
MAX_IMAGE_SIDE: Final = 1568
#: Beta header of the ``fallbacks="default"`` server-side refusal fallback.
FALLBACK_BETA: Final = "server-side-fallback-2026-07-01"
#: Output cap of one labelling answer (non-streaming request).
MAX_TOKENS: Final = 16000

#: JSON schema of :class:`~ale.labels.provider.VlmResponse` for structured outputs.
#: Numeric ranges (bbox 0..1000, confidence 0..1, min <= max) are not expressible in the
#: structured-output schema subset; :func:`~ale.labels.provider.parse_response` checks them.
RESPONSE_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "rooms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "bbox": {"type": "array", "items": {"type": "integer"}},
                    "confidence": {"type": "number"},
                },
                "required": ["label", "bbox", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["rooms"],
    "additionalProperties": False,
}

_OK_STOPS: Final = frozenset({"end_turn", "stop_sequence"})


class VlmProviderError(RuntimeError):
    """A VLM call failed (API error, refusal, truncated or empty answer, bad image)."""


class MissingApiKeyError(VlmProviderError):
    """The environment variable that should hold the API key is unset or empty."""


@dataclass(frozen=True)
class PreparedImage:
    """The PNG actually sent to the API and its ``(width, height)`` in pixels."""

    png: bytes
    size: tuple[int, int]


def prepare_image(image_png: bytes, *, max_side: int = MAX_IMAGE_SIDE) -> PreparedImage:
    """Downscale ``image_png`` (aspect kept) so its long side is ``<= max_side``.

    An image already within the limit is returned unchanged (same bytes), so calling
    this before :func:`ale.labels.label.label_plan` makes the image given to
    ``label_plan`` (bbox conversion, cache key) identical to the one the provider sends.
    Downscaling needs Pillow (extra ``raster``).
    """
    size = png_size(image_png)
    if size is None:
        raise VlmProviderError("image is not a valid PNG")
    width, height = size
    long_side = max(width, height)
    if long_side <= max_side:
        return PreparedImage(png=image_png, size=size)
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - Pillow is installed in CI
        raise VlmProviderError(
            f"image {width}x{height} exceeds {max_side} px and Pillow (extra 'raster') "
            "is not installed to downscale it"
        ) from exc
    scale = max_side / long_side
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    with Image.open(io.BytesIO(image_png)) as img:
        img.load()
        resized = img.resize(new_size, Image.Resampling.LANCZOS)
    out = io.BytesIO()
    resized.save(out, format="PNG", optimize=True)
    data = out.getvalue()
    sent = png_size(data)
    if sent is None:  # pragma: no cover - Pillow always writes a valid PNG
        raise VlmProviderError("downscaled image is not a valid PNG")
    return PreparedImage(png=data, size=sent)


class AnthropicVlmProvider:
    """Room labelling with Claude through the Anthropic Messages API."""

    def __init__(
        self,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        api_key_env: str = "ALE_VLM_API_KEY",
        timeout_s: float = 120.0,
        max_retries: int = 2,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        """Create the provider (and its SDK client unless ``client`` is given).

        Raises :class:`MissingApiKeyError` when ``client`` is ``None`` and the
        environment variable ``api_key_env`` is unset or empty; no client is created.
        ``timeout_s`` bounds each HTTP request; the SDK retries connection errors,
        429 and 5xx up to ``max_retries`` times.
        """
        if timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")
        self.model_id = model_id or DEFAULT_MODEL_ID
        self.api_key_env = api_key_env
        self.timeout_s = float(timeout_s)
        #: ``(width, height)`` of the image sent by the last :meth:`label_image` call.
        self.last_image_size: tuple[int, int] | None = None
        if client is None:
            key = os.environ.get(api_key_env, "")
            if not key.strip():
                raise MissingApiKeyError(
                    f"no API key: environment variable {api_key_env!r} is unset or empty "
                    "(set it to your Anthropic API key, or change vlm.api_key_env)"
                )
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - the extra is installed in CI
                raise VlmProviderError(
                    "the 'anthropic' package is not installed (pip install 'ale[vlm]')"
                ) from exc

            client = anthropic.Anthropic(
                api_key=key, timeout=self.timeout_s, max_retries=max_retries
            )
            del key
        self._client = client

    def __repr__(self) -> str:
        return (
            f"AnthropicVlmProvider(model_id={self.model_id!r}, "
            f"api_key_env={self.api_key_env!r}, timeout_s={self.timeout_s!r})"
        )

    def build_request(self, image_png: bytes, prompt: str) -> dict[str, Any]:
        """Keyword arguments of the ``client.beta.messages.create`` call (image as sent)."""
        prepared = prepare_image(image_png)
        self.last_image_size = prepared.size
        data = base64.standard_b64encode(prepared.png).decode("ascii")
        return {
            "model": self.model_id,
            "max_tokens": MAX_TOKENS,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": data},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "thinking": {"type": "adaptive"},
            "output_config": {
                "effort": "low",
                "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
            },
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
            "timeout": self.timeout_s,
        }

    def label_image(self, image_png: bytes, prompt: str, *, temperature: float) -> str:
        """JSON text of the model's answer; raises :class:`VlmProviderError` on failure.

        ``temperature`` must be ``0.0`` and is not sent to the API.
        """
        assert temperature == 0.0, "temperature must equal 0.0 (deterministic extraction)"
        import anthropic

        request = self.build_request(image_png, prompt)
        try:
            message = self._client.beta.messages.create(**request)
        except anthropic.RateLimitError as exc:
            raise VlmProviderError(f"Anthropic rate limit (429): {exc.message}") from exc
        except anthropic.AuthenticationError as exc:
            raise VlmProviderError(
                f"Anthropic authentication failed (401): check {self.api_key_env!r}"
            ) from exc
        except anthropic.PermissionDeniedError as exc:
            raise VlmProviderError(f"Anthropic permission denied (403): {exc.message}") from exc
        except anthropic.BadRequestError as exc:
            raise VlmProviderError(f"Anthropic bad request (400): {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise VlmProviderError(
                f"Anthropic API error ({exc.status_code}): {exc.message}"
            ) from exc
        except anthropic.APITimeoutError as exc:
            raise VlmProviderError(
                f"Anthropic request timed out after {self.timeout_s:g} s"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise VlmProviderError(f"Anthropic connection error: {exc.message}") from exc
        except anthropic.APIError as exc:
            raise VlmProviderError(f"Anthropic API error: {exc.message}") from exc
        return _answer_text(message)


def _answer_text(message: Any) -> str:
    """Text of the final answer; raises on refusal, truncation or an empty answer."""
    stop = getattr(message, "stop_reason", None)
    if stop == "refusal":
        details = getattr(message, "stop_details", None)
        category = getattr(details, "category", None) if details is not None else None
        raise VlmProviderError(
            f"Claude declined the request (refusal, category={category!r}) "
            "after the server-side fallback"
        )
    if stop == "max_tokens":
        raise VlmProviderError(f"Claude answer truncated (max_tokens={MAX_TOKENS})")
    if stop not in _OK_STOPS:
        raise VlmProviderError(f"unexpected stop_reason {stop!r}")
    blocks = list(getattr(message, "content", None) or [])
    # Only the text after the last fallback switch point is the final model's answer.
    start = 0
    for i, block in enumerate(blocks):
        if getattr(block, "type", None) == "fallback":
            start = i + 1
    text = "".join(
        str(getattr(b, "text", "")) for b in blocks[start:] if getattr(b, "type", None) == "text"
    )
    if not text.strip():
        raise VlmProviderError("Claude returned no text answer")
    return text
