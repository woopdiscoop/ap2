"""Concrete VLM providers for room labelling (Ticket P.1).

``make_provider(config)`` builds the provider named by ``[vlm] provider``. The Claude
provider needs the ``vlm`` extra (``anthropic``), imported only when a client is built.
"""

from __future__ import annotations

from ale.labels.providers.anthropic_provider import (
    DEFAULT_MODEL_ID,
    MAX_IMAGE_SIDE,
    AnthropicVlmProvider,
    MissingApiKeyError,
    PreparedImage,
    VlmProviderError,
    prepare_image,
)
from ale.labels.providers.factory import make_provider

__all__ = [
    "DEFAULT_MODEL_ID",
    "MAX_IMAGE_SIDE",
    "AnthropicVlmProvider",
    "MissingApiKeyError",
    "PreparedImage",
    "VlmProviderError",
    "make_provider",
    "prepare_image",
]
