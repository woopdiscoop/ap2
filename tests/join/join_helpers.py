"""Builders of synthetic ``PlanGeometry`` objects for the ticket 1.6 tests."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from ale.contracts.enums import Frame, LabelSource, OpeningKind, ScaleMethod, SourceKind
from ale.contracts.geometry import LineString, Polygon
from ale.contracts.models import LabelledPolygon, Opening, PlanGeometry, TextItem, Wall

SHA = "0" * 64


def wall(*pts: tuple[float, float], thickness: float | None = None) -> Wall:
    return Wall(centerline=LineString(coords=tuple(pts)), thickness=thickness)


def door(width: float, x: float = 0.0, y: float = 0.0) -> Opening:
    return Opening(
        kind=OpeningKind.DOOR,
        segment=LineString(coords=((x, y), (x + width, y))),
        width_native=width,
    )


def window(width: float) -> Opening:
    return Opening(
        kind=OpeningKind.WINDOW,
        segment=LineString(coords=((0.0, 0.0), (width, 0.0))),
        width_native=width,
    )


def text(
    s: str,
    x: float,
    y: float,
    *,
    height: float | None = 10.0,
    rotation: float = 0.0,
    source: str = "OCR",
) -> TextItem:
    return TextItem(
        text=s,
        insert=(x, y),
        height=height,
        rotation_deg=rotation,
        source=source,  # type: ignore[arg-type]
    )


def room(
    rid: str,
    w: float,
    h: float,
    *,
    x: float = 0.0,
    y: float = 0.0,
    typed: bool = True,
    area_text_m2: float | None = None,
) -> LabelledPolygon:
    return LabelledPolygon(
        id=rid,
        polygon=Polygon(exterior=((x, y), (x + w, y), (x + w, y + h), (x, y + h))),
        type="office" if typed else None,
        label_source=LabelSource.PDF_TEXT if typed else None,
        confidence=0.9 if typed else 0.0,
        area_text_m2=area_text_m2,
    )


def plan(
    kind: SourceKind = SourceKind.RASTER,
    *,
    walls: Sequence[Wall] = (),
    openings: Sequence[Opening] = (),
    rooms: Sequence[LabelledPolygon] = (),
    texts: Sequence[TextItem] = (),
    scale: float | None = None,
    method: ScaleMethod = ScaleMethod.UNKNOWN,
    confidence: float = 0.0,
    frame: Frame = Frame.Y_DOWN,
    units_label: str | None = None,
    **extra: Any,
) -> PlanGeometry:
    return PlanGeometry(
        source_sha256=SHA,
        page=0,
        plan_index=0,
        source_kind=kind,
        frame=frame,
        units_label=units_label,
        scale_m_per_unit=scale,
        scale_method=method,
        scale_confidence=confidence,
        walls=tuple(walls),
        openings=tuple(openings),
        rooms=tuple(rooms),
        texts=tuple(texts),
        **extra,
    )


def box_walls() -> list[Wall]:
    """Four walls of a 360 x 480 rectangle (bottom, left, top, right)."""
    return [
        wall((0.0, 0.0), (360.0, 0.0)),
        wall((0.0, 0.0), (0.0, 480.0)),
        wall((0.0, 480.0), (360.0, 480.0)),
        wall((360.0, 0.0), (360.0, 480.0)),
    ]


def dim_texts(*, outlier: bool = True) -> list[TextItem]:
    """``3.60`` / ``4.80`` / ``3.60`` along the box walls, plus an outlier ``12``."""
    items = [
        text("3.60", 150.0, 10.0),
        text("4.80", -10.0, 200.0, rotation=90.0),
        text("3.60", 150.0, 490.0),
    ]
    if outlier:
        items.append(text("12", 150.0, 470.0))
    return items


def doors(widths: Iterable[float]) -> list[Opening]:
    return [door(w) for w in widths]
