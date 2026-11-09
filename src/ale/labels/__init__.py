"""Semantic labelling of room polygons (Ticket 1.5): text first, then a VLM.

Library only. The VLM interface is provider-agnostic (:class:`VlmProvider`); no real
provider is shipped here and nothing performs network calls.
"""

from __future__ import annotations

from ale.labels.bbox import native_to_normalized, normalized_to_native, png_size
from ale.labels.cache import VlmCache, cache_key
from ale.labels.label import MIN_OVERLAP, LabelResult, assign_one_to_one, label_plan, plan_extent
from ale.labels.provider import (
    PROMPT_VERSION,
    VlmProvider,
    VlmResponse,
    VlmRoom,
    build_prompt,
    parse_response,
    repair_prompt,
)

__all__ = [
    "MIN_OVERLAP",
    "PROMPT_VERSION",
    "LabelResult",
    "VlmCache",
    "VlmProvider",
    "VlmResponse",
    "VlmRoom",
    "assign_one_to_one",
    "build_prompt",
    "cache_key",
    "label_plan",
    "native_to_normalized",
    "normalized_to_native",
    "parse_response",
    "plan_extent",
    "png_size",
    "repair_prompt",
]
