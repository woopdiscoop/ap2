"""Synthetic floor-plan images with a declared ground truth for the Ticket 1.4 tests.

Reference plan (1200 x 800 px, white background, black walls 8 px thick):

* outer walls: the band between x = 100..1100 and y = 100..700 (pixel indices inclusive);
* a vertical partition on x = 500..507 with a 40 px door gap on y = 200..239;
* a horizontal partition on y = 396..403 (right half) with a 50 px door gap on x = 780..829.

Three rooms (left, right-top, right-bottom), two doors. Pixel centres sit on integer
coordinates, so a run of pixels ``i..j`` covers ``[i - 0.5, j + 0.5]``.
"""

from __future__ import annotations

import hashlib
import math

import cv2
import numpy as np
import shapely
from numpy.typing import NDArray

from ale.contracts.models import PlanGeometry

SHA = hashlib.sha256(b"ale raster test").hexdigest()

W, H = 1200, 800
T = 8
#: Wall rectangles (x0, y0, x1, y1), pixel indices inclusive.
GT_WALL_RECTS: tuple[tuple[int, int, int, int], ...] = (
    (100, 100, 1100, 107),  # top
    (100, 693, 1100, 700),  # bottom
    (100, 100, 107, 700),  # left
    (1093, 100, 1100, 700),  # right
    (500, 108, 507, 199),  # vertical partition, above the door
    (500, 240, 507, 692),  # vertical partition, below the door
    (508, 396, 779, 403),  # horizontal partition, left of the door
    (830, 396, 1092, 403),  # horizontal partition, right of the door
)
GT_DOOR_WIDTHS = (40.0, 50.0)
#: Room interiors as continuous boxes (minx, miny, maxx, maxy).
GT_ROOMS: tuple[tuple[float, float, float, float], ...] = (
    (107.5, 107.5, 499.5, 692.5),
    (507.5, 107.5, 1092.5, 395.5),
    (507.5, 403.5, 1092.5, 692.5),
)


def gt_wall_mask() -> NDArray[np.uint8]:
    mask = np.zeros((H, W), dtype=np.uint8)
    for x0, y0, x1, y1 in GT_WALL_RECTS:
        mask[y0 : y1 + 1, x0 : x1 + 1] = 255
    return mask


def plan_image() -> NDArray[np.uint8]:
    """The reference plan, grey uint8 (255 background, 0 walls)."""
    return np.asarray(255 - gt_wall_mask(), dtype=np.uint8)


def rotation_matrix(angle_deg: float) -> NDArray[np.float64]:
    return np.asarray(cv2.getRotationMatrix2D(((W - 1) / 2, (H - 1) / 2), angle_deg, 1.0))


def rotate(img: NDArray[np.uint8], angle_deg: float, border: int) -> NDArray[np.uint8]:
    out = cv2.warpAffine(
        img,
        rotation_matrix(angle_deg),
        (img.shape[1], img.shape[0]),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border,
    )
    return np.asarray(out, dtype=np.uint8)


def noisy_skewed(
    angle_deg: float = 2.0, seed: int = 7
) -> tuple[NDArray[np.uint8], NDArray[np.uint8]]:
    """(image, ground-truth wall mask), both rotated by ``angle_deg``; sigma-10 noise, 0.5 % s&p."""
    rng = np.random.default_rng(seed)
    img = rotate(plan_image(), angle_deg, 255).astype(np.float64)
    img += rng.normal(0.0, 10.0, img.shape)
    img = np.clip(img, 0, 255)
    sp = rng.random(img.shape)
    img[sp < 0.0025] = 0
    img[sp > 1 - 0.0025] = 255
    mask = rotate(gt_wall_mask(), angle_deg, 0)
    return img.astype(np.uint8), np.where(mask >= 128, 255, 0).astype(np.uint8)


def walls_mask(plan: PlanGeometry, shape: tuple[int, int]) -> NDArray[np.uint8]:
    """Rasterise the plan's walls as rectangles around their centrelines (pixel centres)."""
    mask = np.zeros(shape, dtype=np.uint8)
    for wall in plan.walls:
        (x0, y0), (x1, y1) = wall.centerline.coords[0], wall.centerline.coords[-1]
        length = math.hypot(x1 - x0, y1 - y0)
        if length == 0:
            continue
        nx, ny = -(y1 - y0) / length, (x1 - x0) / length
        half = max(0.0, ((wall.thickness or 1.0) - 1.0) / 2.0)
        corners = np.array(
            [
                (x0 + nx * half, y0 + ny * half),
                (x1 + nx * half, y1 + ny * half),
                (x1 - nx * half, y1 - ny * half),
                (x0 - nx * half, y0 - ny * half),
            ]
        )
        cv2.fillPoly(mask, [np.rint(corners * 16).astype(np.int32)], 255, cv2.LINE_8, 4)
    return mask


def iou_masks(a: NDArray[np.uint8], b: NDArray[np.uint8]) -> float:
    inter = np.count_nonzero((a > 0) & (b > 0))
    union = np.count_nonzero((a > 0) | (b > 0))
    return inter / union if union else 0.0


def iou_polygons(a: shapely.Geometry, b: shapely.Geometry) -> float:
    union = a.union(b).area
    return float(a.intersection(b).area / union) if union else 0.0
