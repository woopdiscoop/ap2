"""Provider-agnostic VLM interface: response model, protocol, prompt and parsing.

No real provider is implemented here (decision O-3): a provider is any object with a
``model_id`` and a ``label_image`` method. Nothing in this module performs I/O.
"""

from __future__ import annotations

import functools
import json
from typing import Annotated, Final, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError, model_validator

from ale.contracts.taxonomy import UNKNOWN, load_taxonomy

__all__ = [
    "PROMPT_VERSION",
    "VlmProvider",
    "VlmResponse",
    "VlmRoom",
    "build_prompt",
    "parse_response",
    "repair_prompt",
]

#: Version of the prompt text; part of the cache key.
PROMPT_VERSION: Final = "v1"

_CONFIG = ConfigDict(extra="forbid", frozen=True)

NormCoord = Annotated[int, Field(ge=0, le=1000)]


class VlmRoom(BaseModel):
    """One room seen by the VLM: ``bbox`` is ``[ymin, xmin, ymax, xmax]`` normalised 0..1000."""

    model_config = _CONFIG

    label: StrictStr
    bbox: tuple[NormCoord, NormCoord, NormCoord, NormCoord]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]

    @model_validator(mode="after")
    def _ordered(self) -> VlmRoom:
        ymin, xmin, ymax, xmax = self.bbox
        if ymin > ymax or xmin > xmax:
            raise ValueError("bbox must be [ymin, xmin, ymax, xmax] with min <= max")
        return self


class VlmResponse(BaseModel):
    """Parsed VLM answer."""

    model_config = _CONFIG

    rooms: tuple[VlmRoom, ...]


@runtime_checkable
class VlmProvider(Protocol):
    """A vision-language model able to label a plan image."""

    model_id: str

    def label_image(self, image_png: bytes, prompt: str, *, temperature: float) -> str:
        """Raw text answer of the model (expected to be JSON)."""
        ...


@functools.cache
def build_prompt() -> str:
    """The labelling prompt (version :data:`PROMPT_VERSION`), French then English."""
    lines = [
        f"[ale prompt {PROMPT_VERSION}]",
        "FR : Ceci est un plan d'étage d'un bâtiment. Repère chaque pièce visible et donne "
        "son type. Pour « label », écris le libellé français exact d'un des types "
        "ci-dessous (ou, à défaut, le nom de la pièce tel qu'écrit sur le plan).",
        "EN: This is a building floor plan. Find every visible room and give its type. For "
        '"label", write the exact French label of one of the types below (or, failing '
        "that, the room name as written on the plan).",
        "",
        "Types autorisés / allowed types (key: label_fr / label_en):",
    ]
    for t in load_taxonomy().types:
        if t.key == UNKNOWN:
            continue
        lines.append(f"- {t.key}: {t.label_fr} / {t.label_en}")
    lines += [
        "",
        "Réponds uniquement en JSON / Answer with JSON only, no other text:",
        '{"rooms": [{"label": "<label>", "bbox": [ymin, xmin, ymax, xmax], "confidence": <0..1>}]}',
        "bbox: entiers normalisés 0-1000 par rapport à l'image, origine en haut à gauche / "
        "integers normalised 0-1000 relative to the image, origin at the top-left corner.",
    ]
    return "\n".join(lines)


def repair_prompt(error: str) -> str:
    """Prompt for the retry after an invalid answer (the original prompt + a repair note)."""
    short = error.strip().replace("\n", " ")[:500]
    return (
        f"{build_prompt()}\n\n"
        "FR : Ta réponse précédente n'était pas un JSON valide conforme au schéma. "
        "EN: Your previous answer was not valid JSON matching the schema. "
        f"Error: {short}\n"
        'Réponds uniquement avec / Reply only with: {"rooms": [...]}'
    )


def _strip_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        s = s[first_nl + 1 :] if first_nl >= 0 else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def parse_response(raw: str) -> tuple[VlmResponse | None, str | None]:
    """``(response, None)`` on success, ``(None, error)`` otherwise (never raises).

    Accepts the JSON object alone or wrapped in a Markdown code fence.
    """
    text = _strip_fences(raw)
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        return None, f"invalid JSON: {exc}"
    try:
        return VlmResponse.model_validate(data), None
    except ValidationError as exc:
        return None, f"schema mismatch: {exc.error_count()} error(s): {exc.errors()[0]['msg']}"
