"""Build the configured VLM provider from ``[vlm]`` (``make_provider``)."""

from __future__ import annotations

from ale.contracts.config import AleConfig
from ale.labels.provider import VlmProvider
from ale.labels.providers.anthropic_provider import DEFAULT_MODEL_ID, AnthropicVlmProvider

__all__ = ["make_provider"]


def make_provider(config: AleConfig) -> VlmProvider | None:
    """The provider named by ``config.vlm.provider``; ``None`` when the VLM is disabled.

    ``""`` → ``None``; ``"anthropic"`` → :class:`AnthropicVlmProvider` (model
    ``vlm.model_id`` or ``claude-opus-5-5``). Any other name raises :class:`ValueError`.
    A missing API key raises
    :class:`~ale.labels.providers.anthropic_provider.MissingApiKeyError`.
    """
    vlm = config.vlm
    name = vlm.provider
    if name == "":
        return None
    if name == "anthropic":
        return AnthropicVlmProvider(
            model_id=vlm.model_id or DEFAULT_MODEL_ID,
            api_key_env=vlm.api_key_env,
            timeout_s=vlm.timeout_s,
        )
    raise ValueError(f"unknown VLM provider {name!r} (supported: 'anthropic', or '' to disable)")
