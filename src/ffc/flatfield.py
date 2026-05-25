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
    smooth_sigma: float = 96.0,
    clip_percentiles: tuple[float, float] = (0.1, 99.9),
) -> FlatFieldProfile:
    metadata = correction.metadata
    pattern_h, pattern_w = metadata.dng_cfa_repeat_dim
    planes: list[FlatFieldPlane] = []

    for phase_index, (phase_y, phase_x) in enumerate(_phase_positions(pattern_h, pattern_w)):
        black = metadata.black_level_by_phase[phase_index]
        plane = correction.raw[phase_y::pattern_h, phase_x::pattern_w].astype(np.float32, copy=True)
        plane -= black
        np.maximum(plane, 1.0, out=plane)

        if clip_percentiles is not None:
            low_p, high_p = clip_percentiles
            sample = plane[::8, ::8]
            low, high = np.percentile(sample, [low_p, high_p])
            np.clip(plane, max(1.0, float(low)), max(1.0, float(high)), out=plane)

        if smooth_sigma > 0:
            sigma = (smooth_sigma / pattern_h, smooth_sigma / pattern_w)
            plane = gaussian_filter(plane, sigma=sigma, mode="nearest", truncate=3.0).astype(np.float32, copy=False)

        norm = float(np.median(plane[::8, ::8]))
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
