"""Helpers for the labelling tests: plans, PNG bytes and fake VLM providers (no network)."""

from __future__ import annotations

import json
import struct
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field

from ale.config import AleConfig
from ale.contracts.enums import Frame, LabelSource, SourceKind
from ale.contracts.geometry import Polygon
from ale.contracts.models import LabelledPolygon, PlanGeometry, TextItem
from ale.labels.bbox import native_to_normalized

SHA = "ab" * 32


def png_bytes(width: int, height: int, seed: int = 0) -> bytes:
    """A real (tiny-content) grey PNG of the given size."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes([seed % 256]) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def rect(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return Polygon(exterior=((x0, y0), (x1, y0), (x1, y1), (x0, y1)))


def room(
    rid: str,
    poly: Polygon,
    *,
    rtype: str | None = None,
    source: LabelSource | None = None,
    confidence: float = 0.0,
) -> LabelledPolygon:
    return LabelledPolygon(
        id=rid, polygon=poly, type=rtype, label_source=source, confidence=confidence
    )


def text(s: str, x: float, y: float, source: str = "PDF") -> TextItem:
    return TextItem(text=s, insert=(x, y), source=source)  # type: ignore[arg-type]


def plan(
    rooms: Sequence[LabelledPolygon],
    texts: Sequence[TextItem] = (),
    *,
    frame: Frame = Frame.Y_UP,
    sha: str = SHA,
) -> PlanGeometry:
    return PlanGeometry(
        source_sha256=sha,
        page=0,
        plan_index=0,
        source_kind=SourceKind.PDF_VECTOR,
        frame=frame,
        rooms=tuple(rooms),
        texts=tuple(texts),
    )


def three_room_plan(frame: Frame = Frame.Y_UP) -> PlanGeometry:
    """Rooms A, B, C side by side (each 10 x 10, extent 30 x 10); texts in A and B."""
    return plan(
        [
            room("A", rect(0, 0, 10, 10)),
            room("B", rect(10, 0, 20, 10)),
            room("C", rect(20, 0, 30, 10)),
        ],
        [text("BUREAU 3", 5, 5), text("WC H/F", 15, 5)],
        frame=frame,
    )


def norm_bbox(
    box: tuple[float, float, float, float],
    *,
    image_size: tuple[int, int],
    extent: tuple[float, float, float, float],
    frame: Frame,
) -> list[int]:
    """Integer normalised ``[ymin, xmin, ymax, xmax]`` of a native box (rounded)."""
    n = native_to_normalized(box, image_size=image_size, extent=extent, frame=frame)
    return [round(v) for v in n]


def vlm_json(*rooms: tuple[str, list[int], float]) -> str:
    return json.dumps(
        {"rooms": [{"label": lab, "bbox": bb, "confidence": c} for lab, bb, c in rooms]}
    )


@dataclass
class FakeProvider:
    """Replays canned responses; records every call (prompt, temperature)."""

    responses: list[str]
    model_id: str = "fake-vlm-1"
    calls: list[tuple[str, float]] = field(default_factory=list)

    def label_image(self, image_png: bytes, prompt: str, *, temperature: float) -> str:
        self.calls.append((prompt, temperature))
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[idx]


@dataclass
class RaisingProvider:
    model_id: str = "boom"
    calls: int = 0

    def label_image(self, image_png: bytes, prompt: str, *, temperature: float) -> str:
        self.calls += 1
        raise RuntimeError("network down (simulated)")


def vlm_config(provider: str = "fake", retries: int = 1) -> AleConfig:
    return AleConfig.model_validate(
        {
            "vlm": {
                "provider": provider,
                "model_id": "fake-vlm-1",
                "max_invalid_json_retries": retries,
            }
        }
    )
