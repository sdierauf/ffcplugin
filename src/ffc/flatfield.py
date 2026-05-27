from __future__ import annotations

import math
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
    active_mask: np.ndarray | None = None,
    use_visible_area: bool = True,
    dust_correction: bool = False,
    dust_sigma: float = 32.0,
    dust_threshold: float = 0.02,
    dust_amount: float = 1.0,
    dust_max_gain: float = 1.10,
) -> FlatFieldProfile:
    metadata = correction.metadata
    if active_area is not None and active_mask is not None:
        raise ValueError("Pass active_area or active_mask, not both.")
    if active_mask is not None:
        active_mask = np.asarray(active_mask, dtype=bool)
        if active_mask.shape != correction.raw.shape:
            raise ValueError(
                f"Active mask shape {active_mask.shape} does not match correction raw shape {correction.raw.shape}."
            )
    if active_area is None and active_mask is None and use_visible_area:
        active_area = _metadata_active_area(metadata)
    if active_area is not None:
        _validate_active_area(active_area, metadata.raw_shape)
    _validate_profile_options(
        smooth_sigma=smooth_sigma,
        clip_percentiles=clip_percentiles,
        norm_percentile=norm_percentile,
        dust_correction=dust_correction,
        dust_sigma=dust_sigma,
        dust_threshold=dust_threshold,
        dust_amount=dust_amount,
        dust_max_gain=dust_max_gain,
    )

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
        crop_mask = active_mask[phase_y::pattern_h, phase_x::pattern_w] if active_mask is not None else None
        if crop_mask is not None and not bool(np.any(crop_mask)):
            raise ValueError(f"Active mask does not overlap CFA phase ({phase_y}, {phase_x}).")

        def active_values() -> np.ndarray:
            if crop_mask is not None:
                return plane[crop_mask]
            return plane[crop_rows, crop_cols]

        active_plane = active_values()

        if clip_percentiles is not None:
            low_p, high_p = clip_percentiles
            sample = _sample_active(active_plane)
            low, high = np.percentile(sample, [low_p, high_p])
            np.clip(plane, max(1.0, float(low)), max(1.0, float(high)), out=plane)
            active_plane = active_values()

        detail_source = plane.copy() if dust_correction else None
        if smooth_sigma > 0:
            sigma = (smooth_sigma / pattern_h, smooth_sigma / pattern_w)
            if crop_mask is not None:
                plane = _masked_gaussian_mask(plane, crop_mask, sigma)
                active_plane = active_values()
            elif active_area is None:
                plane = gaussian_filter(plane, sigma=sigma, mode="nearest", truncate=3.0).astype(np.float32, copy=False)
                active_plane = plane[crop_rows, crop_cols]
            else:
                plane = _masked_gaussian(plane, crop_rows, crop_cols, sigma)
                active_plane = plane[crop_rows, crop_cols]

        if detail_source is not None:
            dust_sigma_by_phase = (dust_sigma / pattern_h, dust_sigma / pattern_w)
            plane = _add_dark_detail_layer(
                detail_source,
                plane,
                crop_rows,
                crop_cols,
                crop_mask,
                sigma=dust_sigma_by_phase,
                threshold=dust_threshold,
                amount=dust_amount,
                max_gain=dust_max_gain,
            )
            active_plane = active_values()

        norm = float(np.percentile(_sample_active(active_plane), norm_percentile))
        eps = max(1.0, norm * 0.001)
        gain = (norm / np.maximum(plane, eps)).astype(np.float32, copy=False)
        planes.append(FlatFieldPlane(phase_y, phase_x, black, norm, gain))

    return FlatFieldProfile(metadata=metadata, planes=planes)


def apply_profile(scan: RawFrame, profile: FlatFieldProfile, *, backend: Backend) -> np.ndarray:
    _validate_compatible(scan, profile)

    metadata = scan.metadata
    pattern_h, pattern_w = metadata.dng_cfa_repeat_dim
    corrected = np.empty_like(scan.raw, dtype=np.uint16)

    for phase_index, plane in enumerate(profile.planes):
        scan_plane = scan.raw[plane.y::pattern_h, plane.x::pattern_w]
        corrected[plane.y::pattern_h, plane.x::pattern_w] = correct_plane(
            scan_plane,
            plane.gain,
            black=metadata.black_level_by_phase[phase_index],
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


def _metadata_active_area(metadata: RawMetadata) -> tuple[int, int, int, int]:
    left, top = metadata.crop_origin
    width, height = metadata.crop_size
    return left, top, width, height


def _validate_active_area(active_area: tuple[int, int, int, int], raw_shape: tuple[int, int]) -> None:
    left, top, width, height = active_area
    raw_h, raw_w = raw_shape
    if width <= 0 or height <= 0:
        raise ValueError(f"Active area must have positive width and height, got {active_area}.")
    if left >= raw_w or top >= raw_h or left + width <= 0 or top + height <= 0:
        raise ValueError(f"Active area {active_area} does not overlap raw shape {raw_shape}.")


def _validate_profile_options(
    *,
    smooth_sigma: float,
    clip_percentiles: tuple[float, float] | None,
    norm_percentile: float,
    dust_correction: bool,
    dust_sigma: float,
    dust_threshold: float,
    dust_amount: float,
    dust_max_gain: float,
) -> None:
    _require_finite("smooth_sigma", smooth_sigma)
    if smooth_sigma < 0:
        raise ValueError("smooth_sigma must be greater than or equal to 0.")

    _require_finite("norm_percentile", norm_percentile)
    if not 0 <= norm_percentile <= 100:
        raise ValueError("norm_percentile must be between 0 and 100.")

    if clip_percentiles is not None:
        low_p, high_p = clip_percentiles
        _require_finite("clip_low", low_p)
        _require_finite("clip_high", high_p)
        if not 0 <= low_p < high_p <= 100:
            raise ValueError("clip_percentiles must satisfy 0 <= low < high <= 100.")

    if dust_correction:
        _require_finite("dust_sigma", dust_sigma)
        _require_finite("dust_threshold", dust_threshold)
        _require_finite("dust_amount", dust_amount)
        _require_finite("dust_max_gain", dust_max_gain)
        if dust_sigma <= 0:
            raise ValueError("dust_sigma must be greater than 0 when dust correction is enabled.")
        if dust_threshold < 0:
            raise ValueError("dust_threshold must be greater than or equal to 0.")
        if dust_amount < 0:
            raise ValueError("dust_amount must be greater than or equal to 0.")
        if dust_max_gain < 1:
            raise ValueError("dust_max_gain must be greater than or equal to 1.")


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite.")


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


def _masked_gaussian_mask(plane: np.ndarray, active_mask: np.ndarray, sigma: tuple[float, float]) -> np.ndarray:
    mask = active_mask.astype(np.float32, copy=False)
    weighted = plane * mask
    smooth_values = gaussian_filter(weighted, sigma=sigma, mode="constant", cval=0.0, truncate=3.0)
    smooth_weights = gaussian_filter(mask, sigma=sigma, mode="constant", cval=0.0, truncate=3.0)
    fill = float(np.median(_sample_active(plane[active_mask])))
    smoothed = np.full_like(plane, fill, dtype=np.float32)
    np.divide(smooth_values, smooth_weights, out=smoothed, where=smooth_weights > 1.0e-6)
    return smoothed


def _add_dark_detail_layer(
    source: np.ndarray,
    broad: np.ndarray,
    rows: slice,
    cols: slice,
    active_mask: np.ndarray | None,
    *,
    sigma: tuple[float, float],
    threshold: float,
    amount: float,
    max_gain: float,
) -> np.ndarray:
    if amount <= 0 or max_gain <= 1 or sigma[0] <= 0 or sigma[1] <= 0:
        return broad

    if active_mask is not None:
        fine = _masked_gaussian_mask(source, active_mask, sigma)
    elif _is_full_slice(rows, source.shape[0]) and _is_full_slice(cols, source.shape[1]):
        fine = gaussian_filter(source, sigma=sigma, mode="nearest", truncate=3.0).astype(np.float32, copy=False)
    else:
        fine = _masked_gaussian(source, rows, cols, sigma)

    corrected = broad.copy()
    min_factor = 1.0 / float(max_gain)
    threshold = max(0.0, float(threshold))
    amount = max(0.0, float(amount))

    if active_mask is not None:
        _apply_dark_detail(corrected, broad, fine, active_mask, threshold, amount, min_factor)
    elif _is_full_slice(rows, source.shape[0]) and _is_full_slice(cols, source.shape[1]):
        _apply_dark_detail(corrected, broad, fine, None, threshold, amount, min_factor)
    else:
        region = (rows, cols)
        _apply_dark_detail(corrected, broad, fine, region, threshold, amount, min_factor)

    return corrected


def _apply_dark_detail(
    output: np.ndarray,
    broad: np.ndarray,
    fine: np.ndarray,
    selector: np.ndarray | tuple[slice, slice] | None,
    threshold: float,
    amount: float,
    min_factor: float,
) -> None:
    if selector is None:
        broad_values = broad
        fine_values = fine
    else:
        broad_values = broad[selector]
        fine_values = fine[selector]

    ratio = fine_values / np.maximum(broad_values, 1.0)
    darkness = np.maximum(0.0, 1.0 - ratio - threshold)
    factor = np.maximum(min_factor, 1.0 - amount * darkness)

    if selector is None:
        np.multiply(broad_values, factor, out=output)
    else:
        output[selector] = broad_values * factor


def _is_full_slice(value: slice, size: int) -> bool:
    start = 0 if value.start is None else value.start
    stop = size if value.stop is None else value.stop
    step = 1 if value.step is None else value.step
    return start == 0 and stop == size and step == 1


def _sample_active(values: np.ndarray, max_samples: int = 262_144) -> np.ndarray:
    flattened = values.reshape(-1)
    if flattened.size <= max_samples:
        return flattened

    if values.ndim == 1:
        stride = max(1, math.ceil(flattened.size / max_samples))
        return flattened[::stride]

    stride = max(1, math.ceil(math.sqrt(flattened.size / max_samples)))
    sample = values[::stride, ::stride].reshape(-1)
    if sample.size == 0:
        return flattened
    return sample


def _validate_compatible(scan: RawFrame, profile: FlatFieldProfile) -> None:
    scan_meta = scan.metadata
    corr_meta = profile.metadata
    if scan_meta.raw_shape != corr_meta.raw_shape:
        raise ValueError(
            f"{scan_meta.path} has raw shape {scan_meta.raw_shape}, "
            f"but correction frame has {corr_meta.raw_shape}."
        )
    if scan_meta.dng_cfa_repeat_dim != corr_meta.dng_cfa_repeat_dim:
        raise ValueError(
            f"{scan_meta.path} CFA repeat dimension does not match correction frame "
            f"({scan_meta.dng_cfa_repeat_dim} vs {corr_meta.dng_cfa_repeat_dim})."
        )
    if tuple(scan_meta.dng_cfa_pattern) != tuple(corr_meta.dng_cfa_pattern):
        raise ValueError(
            f"{scan_meta.path} CFA pattern does not match correction frame "
            f"({scan_meta.dng_cfa_pattern} vs {corr_meta.dng_cfa_pattern})."
        )
    if len(scan_meta.black_level_by_phase) != len(profile.planes):
        raise ValueError(
            f"{scan_meta.path} has {len(scan_meta.black_level_by_phase)} black-level phases, "
            f"but correction profile has {len(profile.planes)} planes."
        )
