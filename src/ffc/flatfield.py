from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter

from .accelerate import Backend, correct_plane
from .rawio import RawFrame, RawMetadata


@dataclass
class FlatFieldPlane:
    y: int
    x: int
    black: float
    norm: float
    gain: np.ndarray


@dataclass
class FlatFieldProfile:
    metadata: RawMetadata
    planes: list[FlatFieldPlane]


def build_profile(
    correction: RawFrame,
    *,
    smooth_sigma: float = 192.0,
    clip_percentiles: tuple[float, float] = (0.1, 99.9),
    norm_percentile: float = 70.0,
    active_area: tuple[int, int, int, int] | None = None,
) -> FlatFieldProfile:
    metadata = correction.metadata
    pattern_h, pattern_w = metadata.dng_cfa_repeat_dim
    planes: list[FlatFieldPlane] = []

    for phase_index, (phase_y, phase_x) in enumerate(_phase_positions(pattern_h, pattern_w)):
        black = metadata.black_level_by_phase[phase_index]
        plane = correction.raw[phase_y::pattern_h, phase_x::pattern_w].astype(np.float32, copy=True)
        plane -= black
        np.maximum(plane, 1.0, out=plane)
        crop_rows, crop_cols = _phase_active_slices(
            plane.shape,
            phase_y,
            phase_x,
            pattern_h,
            pattern_w,
            active_area,
        )
        active_plane = plane[crop_rows, crop_cols]

        if clip_percentiles is not None:
            low_p, high_p = clip_percentiles
            sample = active_plane[::8, ::8]
            low, high = np.percentile(sample, [low_p, high_p])
            np.clip(plane, max(1.0, float(low)), max(1.0, float(high)), out=plane)

        if smooth_sigma > 0:
            sigma = (smooth_sigma / pattern_h, smooth_sigma / pattern_w)
            if active_area is None:
                plane = gaussian_filter(plane, sigma=sigma, mode="nearest", truncate=3.0).astype(np.float32, copy=False)
                active_plane = plane[crop_rows, crop_cols]
            else:
                plane = _masked_gaussian(plane, crop_rows, crop_cols, sigma)
                active_plane = plane[crop_rows, crop_cols]

        norm = float(np.percentile(active_plane[::8, ::8], norm_percentile))
        eps = max(1.0, norm * 0.001)
        gain = (norm / np.maximum(plane, eps)).astype(np.float32, copy=False)
        planes.append(FlatFieldPlane(phase_y, phase_x, black, norm, gain))

    return FlatFieldProfile(metadata=metadata, planes=planes)


def apply_profile(scan: RawFrame, profile: FlatFieldProfile, *, backend: Backend) -> np.ndarray:
    _validate_compatible(scan, profile)

    metadata = scan.metadata
    pattern_h, pattern_w = metadata.dng_cfa_repeat_dim
    corrected = np.empty_like(scan.raw, dtype=np.uint16)

    for plane in profile.planes:
        scan_plane = scan.raw[plane.y::pattern_h, plane.x::pattern_w]
        corrected[plane.y::pattern_h, plane.x::pattern_w] = correct_plane(
            scan_plane,
            plane.gain,
            black=plane.black,
            white=float(metadata.white_level),
            backend=backend,
        )

    return corrected


def _phase_positions(pattern_h: int, pattern_w: int) -> list[tuple[int, int]]:
    return [(y, x) for y in range(pattern_h) for x in range(pattern_w)]


def _phase_active_slices(
    plane_shape: tuple[int, int],
    phase_y: int,
    phase_x: int,
    pattern_h: int,
    pattern_w: int,
    active_area: tuple[int, int, int, int] | None,
) -> tuple[slice, slice]:
    if active_area is None:
        return slice(0, plane_shape[0]), slice(0, plane_shape[1])

    left, top, width, height = active_area
    right = left + width
    bottom = top + height
    row0 = max(0, _ceil_div(top - phase_y, pattern_h))
    row1 = min(plane_shape[0], _ceil_div(bottom - phase_y, pattern_h))
    col0 = max(0, _ceil_div(left - phase_x, pattern_w))
    col1 = min(plane_shape[1], _ceil_div(right - phase_x, pattern_w))
    if row0 >= row1 or col0 >= col1:
        raise ValueError(f"Active crop {active_area} does not overlap CFA phase ({phase_y}, {phase_x}).")
    return slice(row0, row1), slice(col0, col1)


def _ceil_div(value: int, divisor: int) -> int:
    return -(-value // divisor)


def _masked_gaussian(plane: np.ndarray, rows: slice, cols: slice, sigma: tuple[float, float]) -> np.ndarray:
    mask = np.zeros_like(plane, dtype=np.float32)
    mask[rows, cols] = 1.0
    weighted = plane * mask
    smooth_values = gaussian_filter(weighted, sigma=sigma, mode="constant", cval=0.0, truncate=3.0)
    smooth_weights = gaussian_filter(mask, sigma=sigma, mode="constant", cval=0.0, truncate=3.0)
    fill = float(np.median(plane[rows, cols][::8, ::8]))
    smoothed = np.full_like(plane, fill, dtype=np.float32)
    np.divide(smooth_values, smooth_weights, out=smoothed, where=smooth_weights > 1.0e-6)
    return smoothed


def _validate_compatible(scan: RawFrame, profile: FlatFieldProfile) -> None:
    scan_meta = scan.metadata
    corr_meta = profile.metadata
    if scan_meta.raw_shape != corr_meta.raw_shape:
        raise ValueError(
            f"{scan_meta.path} has raw shape {scan_meta.raw_shape}, "
            f"but correction frame has {corr_meta.raw_shape}."
        )
    if tuple(scan_meta.dng_cfa_pattern) != tuple(corr_meta.dng_cfa_pattern):
        raise ValueError(
            f"{scan_meta.path} CFA pattern does not match correction frame "
            f"({scan_meta.dng_cfa_pattern} vs {corr_meta.dng_cfa_pattern})."
        )
