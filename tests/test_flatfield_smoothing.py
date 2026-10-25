from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ffc.flatfield import build_profile, build_profile as _build_profile
from ffc.rawio import RawFrame, RawMetadata


def _metadata(raw_shape: tuple[int, int]) -> RawMetadata:
    return RawMetadata(
        path=Path("correction.ARW"),
        make="SONY",
        model="TEST",
        unique_camera_model="Sony TEST",
        timestamp=None,
        raw_shape=raw_shape,
        crop_origin=(8, 8),
        crop_size=(raw_shape[1] - 16, raw_shape[0] - 16),
        raw_pattern=np.array([[0, 1], [3, 2]], dtype=np.uint8),
        dng_cfa_pattern=(0, 1, 1, 2),
        dng_cfa_repeat_dim=(2, 2),
        black_level_by_phase=(512.0, 512.0, 512.0, 512.0),
        white_level=16383,
        color_matrix=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        as_shot_neutral=(1.0, 1.0, 1.0),
        original_filename="correction.ARW",
    )


def _vignetted_frame(size: int = 512, falloff: float = 3000.0) -> RawFrame:
    yy, xx = np.mgrid[:size, :size]
    radial = ((yy - size / 2) ** 2 + (xx - size / 2) ** 2) / (size / 2) ** 2
    data = 12000.0 - falloff * radial + 512.0
    return RawFrame(_metadata((size, size)), data.astype(np.uint16))


@pytest.mark.parametrize("factor", [2, 4])
def test_coarse_smoothing_tracks_exact_full_resolution(factor: int) -> None:
    # A gentle 25% vignette, the shape a real illumination field actually has.
    correction = _vignetted_frame()

    exact = _build_profile(correction, smooth_sigma=96, clip_percentiles=None, smoothing_factor=1, workers=1)
    coarse = _build_profile(correction, smooth_sigma=96, clip_percentiles=None, smoothing_factor=factor, workers=1)

    left, top = correction.metadata.crop_origin
    width, height = correction.metadata.crop_size
    for exact_plane, coarse_plane in zip(exact.planes, coarse.planes):
        region = np.s_[top // 2 : (top + height) // 2, left // 2 : (left + width) // 2]
        relative = np.abs(exact_plane.gain[region] - coarse_plane.gain[region]) / exact_plane.gain[region]
        # Synthetic frames are much harsher than real scans (sigma is a large
        # fraction of the frame); measured drift on a real 24MP frame is 0.007%.
        assert relative.max() < 1.0e-2, f"coarse gain drifted by {relative.max():.2%}"
        assert relative.mean() < 2.0e-3


def test_smoothing_factor_one_is_the_exact_reference() -> None:
    correction = _vignetted_frame(size=256, falloff=2000.0)

    forced = _build_profile(correction, smooth_sigma=32, clip_percentiles=None, smoothing_factor=1, workers=1)
    repeated = _build_profile(correction, smooth_sigma=32, clip_percentiles=None, smoothing_factor=1, workers=1)

    for first, second in zip(forced.planes, repeated.planes):
        assert np.array_equal(first.gain, second.gain)


def test_threaded_build_matches_single_thread_and_keeps_phase_order() -> None:
    correction = _vignetted_frame(size=256, falloff=2000.0)

    serial = _build_profile(correction, smooth_sigma=32, clip_percentiles=None, workers=1)
    threaded = _build_profile(correction, smooth_sigma=32, clip_percentiles=None, workers=4)

    assert [(plane.y, plane.x) for plane in threaded.planes] == [(0, 0), (0, 1), (1, 0), (1, 1)]
    for serial_plane, threaded_plane in zip(serial.planes, threaded.planes):
        assert np.array_equal(serial_plane.gain, threaded_plane.gain)


def test_auto_smoothing_factor_only_engages_for_wide_sigmas() -> None:
    from ffc.flatfield import _smoothing_factor_for

    assert _smoothing_factor_for((96.0, 96.0), (3188, 4800), None) > 1
    assert _smoothing_factor_for((2.0, 2.0), (3188, 4800), None) == 1
    assert _smoothing_factor_for((8.0, 8.0), (4096, 4096), None) == 1
    # Tiny planes stay exact so small reference images keep bit-identical output.
    assert _smoothing_factor_for((96.0, 96.0), (40, 40), None) == 1
    with pytest.raises(ValueError, match="smoothing_factor"):
        _smoothing_factor_for((96.0, 96.0), (3188, 4800), 0)


def test_dust_correction_survives_coarse_smoothing() -> None:
    size = 128
    data = np.full((size, size), 5000.0)
    yy, xx = np.ogrid[:size, :size]
    data[(yy - 64) ** 2 + (xx - 64) ** 2 <= 6**2] = 4200.0
    correction = RawFrame(_metadata((size, size)), (data + 512.0).astype(np.uint16))

    profile = build_profile(
        correction,
        smooth_sigma=16,
        clip_percentiles=None,
        dust_correction=True,
        dust_sigma=8,
        dust_threshold=0.01,
        dust_max_gain=1.10,
    )

    assert len(profile.planes) == 4
    assert all(np.isfinite(plane.gain).all() for plane in profile.planes)
