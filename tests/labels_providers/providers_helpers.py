"""Helpers for the VLM provider tests: a fake Anthropic client (no network), PNGs, plans."""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from ale.config import AleConfig
from ale.contracts.enums import Frame, SourceKind
from ale.contracts.geometry import Polygon
from ale.contracts.models import LabelledPolygon, PlanGeometry
from ale.labels.bbox import native_to_normalized

SHA = "cd" * 32
IMG_SIZE = (300, 100)
EXTENT = (0.0, 0.0, 30.0, 10.0)


def png_bytes(width: int, height: int, value: int = 200) -> bytes:
    """A real grey PNG of the given size."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    row = b"\x00" + bytes([value]) * width
    raw = row * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 1))
        + chunk(b"IEND", b"")
    )


def rect(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return Polygon(exterior=((x0, y0), (x1, y0), (x1, y1), (x0, y1)))


def two_room_plan() -> PlanGeometry:
    """Untyped rooms A (0..10) and B (10..30), extent 30 x 10, no texts."""
    return PlanGeometry(
        source_sha256=SHA,
        page=0,
        plan_index=0,
        source_kind=SourceKind.PDF_VECTOR,
        frame=Frame.Y_UP,
        rooms=(
            LabelledPolygon(id="A", polygon=rect(0, 0, 10, 10)),
            LabelledPolygon(id="B", polygon=rect(10, 0, 30, 10)),
        ),
    )


def norm_bbox(box: tuple[float, float, float, float]) -> list[int]:
    n = native_to_normalized(box, image_size=IMG_SIZE, extent=EXTENT, frame=Frame.Y_UP)
    return [round(v) for v in n]


def answer_json() -> str:
    return json.dumps(
        {
            "rooms": [
                {"label": "office", "bbox": norm_bbox((0, 0, 10, 10)), "confidence": 0.9},
                {"label": "office", "bbox": norm_bbox((10, 0, 30, 10)), "confidence": 0.8},
            ]
        }
    )


def anthropic_config(**vlm: Any) -> AleConfig:
    return AleConfig.model_validate({"vlm": {"provider": "anthropic", **vlm}})


def message(
    text: str | None,
    *,
    stop_reason: str = "end_turn",
    blocks: list[Any] | None = None,
    category: str | None = None,
) -> SimpleNamespace:
    """A stand-in for ``BetaMessage`` with only the fields the provider reads."""
    content: list[Any] = list(blocks or [])
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    details = SimpleNamespace(type="refusal", category=category) if category else None
    return SimpleNamespace(stop_reason=stop_reason, stop_details=details, content=content)


@dataclass
class FakeMessages:
    outcomes: list[Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeClient:
    """Mimics ``anthropic.Anthropic`` for ``client.beta.messages.create`` only."""

    def __init__(self, *outcomes: Any) -> None:
        self.messages = FakeMessages(list(outcomes))
        self.beta = SimpleNamespace(messages=self.messages)

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.messages.calls
