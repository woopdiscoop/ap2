"""Step 3 of the raster pipeline: rooms as connected components of the free space.

The wall mask (with door gaps bridged) is closed with a square kernel of the median wall
thickness; the free space is split into 4-connected components; components touching the
image border (the outside) and components smaller than 0.2 % of the image are dropped;
each remaining component's outer contour is simplified with Douglas-Peucker (epsilon 1 %
of its perimeter). Holes are not traced in v1.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import shapely
import shapely.affinity
from numpy.typing import NDArray

from ale.guards import bounded

__all__ = ["DP_SHARE", "MAX_ROOMS", "MIN_ROOM_SHARE", "RoomRegion", "trace_rooms"]

U8 = NDArray[np.uint8]

#: Components smaller than this share of the image area are dropped.
MIN_ROOM_SHARE = 0.002
#: Douglas-Peucker tolerance as a share of the contour perimeter.
DP_SHARE = 0.01
#: Rooms traced at most (largest first).
MAX_ROOMS = 2000
_TIME_BUDGET_S = 60.0


@dataclass(frozen=True)
class RoomRegion:
    """One room in working pixels."""

    polygon: shapely.Polygon
    area_px: int
    centroid: tuple[float, float]


def _simplify(component: U8) -> shapely.Polygon | None:
    contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    eps = DP_SHARE * cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, eps, True).reshape(-1, 2).astype(np.float64)
    if len(approx) < 3:
        return None
    poly = shapely.Polygon(approx)
    if not poly.is_valid:
        fixed = shapely.make_valid(poly)
        parts = [g for g in getattr(fixed, "geoms", [fixed]) if isinstance(g, shapely.Polygon)]
        if not parts:
            return None
        poly = max(parts, key=lambda g: g.area)
    if poly.is_empty or poly.area <= 0.0:
        return None
    return shapely.Polygon(poly.exterior.coords)


def trace_rooms(wall_mask: U8, median_thickness: float) -> tuple[list[RoomRegion], list[str]]:
    """Trace room polygons from a wall mask whose door gaps are already bridged."""
    h, w = wall_mask.shape
    warnings: list[str] = []
    k = max(1, round(median_thickness)) | 1  # odd: an even closing shifts the mask
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    closed = np.asarray(cv2.morphologyEx(wall_mask, cv2.MORPH_CLOSE, kernel), dtype=np.uint8)
    free = np.asarray(cv2.bitwise_not(closed), dtype=np.uint8)
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(free, connectivity=4)
    min_area = MIN_ROOM_SHARE * h * w
    candidates: list[int] = []
    for i in range(1, n):
        x, y, bw, bh, area = (int(v) for v in stats[i])
        if x == 0 or y == 0 or x + bw >= w or y + bh >= h:
            continue  # touches the border: outside
        if area < min_area:
            continue
        candidates.append(i)
    candidates.sort(key=lambda i: -int(stats[i, cv2.CC_STAT_AREA]))
    if len(candidates) > MAX_ROOMS:
        warnings.append(f"{len(candidates) - MAX_ROOMS} room(s) skipped (cap {MAX_ROOMS})")
        candidates = candidates[:MAX_ROOMS]
    rooms: list[RoomRegion] = []
    with bounded(MAX_ROOMS + 1, _TIME_BUDGET_S, label="raster.rooms", on_exhaust="stop") as budget:
        for i in candidates:
            if not budget.tick():
                warnings.append("room tracing stopped: time budget exhausted")
                break
            x, y, bw, bh, area = (int(v) for v in stats[i])
            sub = np.zeros((bh + 2, bw + 2), dtype=np.uint8)
            sub[1:-1, 1:-1][labels[y : y + bh, x : x + bw] == i] = 255
            poly = _simplify(sub)
            if poly is None:
                warnings.append(f"room component at ({x}, {y}) has no valid polygon")
                continue
            poly = shapely.affinity.translate(poly, x - 1, y - 1)
            cx, cy = (float(c) for c in centroids[i])
            rooms.append(RoomRegion(polygon=poly, area_px=area, centroid=(cx, cy)))
    rooms.sort(key=lambda r: (round(r.centroid[1]), round(r.centroid[0])))
    return rooms, warnings
