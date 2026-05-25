from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .rawio import RawMetadata


@dataclass(frozen=True)
class LightroomCrop:
    left: float
    top: float
    right: float
    bottom: float
    angle: float = 0.0
    orientation: str = "AB"


def raw_crop_polygon(metadata: RawMetadata, crop: LightroomCrop) -> np.ndarray:
    """Return Lightroom's crop rectangle corners in raw top-left pixel coordinates."""
    base_left, base_top = metadata.crop_origin
    base_width, base_height = metadata.crop_size
    left, right = sorted((_clamp01(crop.left), _clamp01(crop.right)))
    top, bottom = sorted((_clamp01(crop.top), _clamp01(crop.bottom)))

    upper_left = np.array([left * base_width, (1.0 - top) * base_height], dtype=np.float64)
    lower_right = np.array([right * base_width, (1.0 - bottom) * base_height], dtype=np.float64)
    center = (upper_left + lower_right) / 2.0
    angle = math.radians(-float(crop.angle))

    unrotated_upper_left = _rotate_point(upper_left, center, -angle)
    unrotated_lower_right = _rotate_point(lower_right, center, -angle)
    unrotated_lower_left = np.array([unrotated_upper_left[0], unrotated_lower_right[1]], dtype=np.float64)
    unrotated_upper_right = np.array([unrotated_lower_right[0], unrotated_upper_left[1]], dtype=np.float64)

    lower_left = _rotate_point(unrotated_lower_left, center, angle)
    upper_right = _rotate_point(unrotated_upper_right, center, angle)
    lower_left_origin = np.array([upper_left, upper_right, lower_right, lower_left], dtype=np.float64)

    polygon = np.empty_like(lower_left_origin)
    polygon[:, 0] = base_left + lower_left_origin[:, 0]
    polygon[:, 1] = base_top + (base_height - lower_left_origin[:, 1])
    return polygon


def raw_crop_bounding_area(metadata: RawMetadata, crop: LightroomCrop) -> tuple[int, int, int, int]:
    return polygon_bounding_area(metadata.raw_shape, raw_crop_polygon(metadata, crop))


def raw_crop_mask(metadata: RawMetadata, crop: LightroomCrop) -> np.ndarray:
    return polygon_mask(metadata.raw_shape, raw_crop_polygon(metadata, crop))


def relative_crop_for_area(
    metadata: RawMetadata,
    crop: LightroomCrop,
    area: tuple[int, int, int, int],
) -> LightroomCrop:
    polygon = raw_crop_polygon(metadata, crop)
    area_left, area_top, area_width, area_height = area
    upper_left = polygon[0]
    lower_right = polygon[2]
    return LightroomCrop(
        left=_clamp01((upper_left[0] - area_left) / area_width),
        top=_clamp01((upper_left[1] - area_top) / area_height),
        right=_clamp01((lower_right[0] - area_left) / area_width),
        bottom=_clamp01((lower_right[1] - area_top) / area_height),
        angle=crop.angle,
        orientation=crop.orientation,
    )


def polygon_bounding_area(raw_shape: tuple[int, int], polygon: np.ndarray) -> tuple[int, int, int, int]:
    raw_height, raw_width = raw_shape
    left = max(0, min(raw_width - 1, int(math.floor(float(np.min(polygon[:, 0]))))))
    top = max(0, min(raw_height - 1, int(math.floor(float(np.min(polygon[:, 1]))))))
    right = max(left + 1, min(raw_width, int(math.ceil(float(np.max(polygon[:, 0]))))))
    bottom = max(top + 1, min(raw_height, int(math.ceil(float(np.max(polygon[:, 1]))))))
    return left, top, right - left, bottom - top


def polygon_mask(raw_shape: tuple[int, int], polygon: np.ndarray) -> np.ndarray:
    raw_height, raw_width = raw_shape
    mask = np.zeros(raw_shape, dtype=bool)
    row_start = max(0, int(math.floor(float(np.min(polygon[:, 1])))))
    row_stop = min(raw_height, int(math.ceil(float(np.max(polygon[:, 1])))))

    for row in range(row_start, row_stop):
        scan_y = row + 0.5
        intersections: list[float] = []
        for index in range(len(polygon)):
            x0, y0 = polygon[index]
            x1, y1 = polygon[(index + 1) % len(polygon)]
            if (y0 <= scan_y < y1) or (y1 <= scan_y < y0):
                fraction = (scan_y - y0) / (y1 - y0)
                intersections.append(float(x0 + fraction * (x1 - x0)))

        intersections.sort()
        for start, stop in zip(intersections[0::2], intersections[1::2], strict=False):
            col_start = max(0, int(math.ceil(min(start, stop) - 0.5)))
            col_stop = min(raw_width, int(math.ceil(max(start, stop) - 0.5)))
            if col_start < col_stop:
                mask[row, col_start:col_stop] = True

    return mask


def _rotate_point(point: np.ndarray, center: np.ndarray, angle: float) -> np.ndarray:
    dx, dy = point - center
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return np.array(
        [
            center[0] + dx * cos_a - dy * sin_a,
            center[1] + dx * sin_a + dy * cos_a,
        ],
        dtype=np.float64,
    )


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
