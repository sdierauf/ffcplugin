from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ffc.accelerate import Backend
from ffc.flatfield import apply_profile, build_profile
from ffc.rawio import RawFrame, RawMetadata


def test_flatfield_profile_corrects_per_phase_gain() -> None:
    pattern = np.array([[0, 1], [3, 2]], dtype=np.uint8)
    correction = np.array(
        [
            [1000, 2000, 1000, 2000],
            [3000, 4000, 3000, 4000],
            [1000, 2000, 1000, 2000],
            [3000, 4000, 3000, 4000],
        ],
        dtype=np.uint16,
    )
    scan = np.array(
        [
            [2000, 2000, 2000, 2000],
            [2000, 2000, 2000, 2000],
            [2000, 2000, 2000, 2000],
            [2000, 2000, 2000, 2000],
        ],
        dtype=np.uint16,
    )

    meta = RawMetadata(
        path=__import__("pathlib").Path("scan.ARW"),
        make="SONY",
        model="TEST",
        unique_camera_model="Sony TEST",
        timestamp=None,
        raw_shape=(4, 4),
        crop_origin=(0, 0),
        crop_size=(4, 4),
        raw_pattern=pattern,
        dng_cfa_pattern=(0, 1, 1, 2),
        dng_cfa_repeat_dim=(2, 2),
        black_level_by_phase=(0.0, 0.0, 0.0, 0.0),
        white_level=16383,
        color_matrix=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        as_shot_neutral=(1.0, 1.0, 1.0),
        original_filename="scan.ARW",
    )

    profile = build_profile(RawFrame(meta, correction), smooth_sigma=0, clip_percentiles=None)
    corrected = apply_profile(RawFrame(meta, scan), profile, backend=Backend("numpy", "test"))

    assert corrected[0, 0] == 2000
    assert corrected[0, 1] == 2000
    assert corrected[1, 0] == 2000
    assert corrected[1, 1] == 2000


def test_crop_aware_profile_ignores_mask_outside_active_area() -> None:
    pattern = np.array([[0, 1], [3, 2]], dtype=np.uint8)
    correction = np.full((8, 8), 2000, dtype=np.uint16)
    correction[:, :2] = 200
    scan = np.full((8, 8), 2000, dtype=np.uint16)
    meta = RawMetadata(
        path=__import__("pathlib").Path("scan.ARW"),
        make="SONY",
        model="TEST",
        unique_camera_model="Sony TEST",
        timestamp=None,
        raw_shape=(8, 8),
        crop_origin=(2, 0),
        crop_size=(6, 8),
        raw_pattern=pattern,
        dng_cfa_pattern=(0, 1, 1, 2),
        dng_cfa_repeat_dim=(2, 2),
        black_level_by_phase=(0.0, 0.0, 0.0, 0.0),
        white_level=16383,
        color_matrix=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        as_shot_neutral=(1.0, 1.0, 1.0),
        original_filename="scan.ARW",
    )

    profile = build_profile(
        RawFrame(meta, correction),
        smooth_sigma=2,
        clip_percentiles=None,
        active_area=(2, 0, 6, 8),
    )
    corrected = apply_profile(RawFrame(meta, scan), profile, backend=Backend("numpy", "test"))

    assert np.all(corrected[:, 2:] == 2000)


def test_profile_accepts_rotated_crop_active_mask() -> None:
    pattern = np.array([[0, 1], [3, 2]], dtype=np.uint8)
    correction = np.full((8, 8), 2000, dtype=np.uint16)
    correction[:, :2] = 200
    scan = np.full((8, 8), 2000, dtype=np.uint16)
    active_mask = np.zeros((8, 8), dtype=bool)
    active_mask[:, 2:] = True
    meta = RawMetadata(
        path=__import__("pathlib").Path("scan.ARW"),
        make="SONY",
        model="TEST",
        unique_camera_model="Sony TEST",
        timestamp=None,
        raw_shape=(8, 8),
        crop_origin=(0, 0),
        crop_size=(8, 8),
        raw_pattern=pattern,
        dng_cfa_pattern=(0, 1, 1, 2),
        dng_cfa_repeat_dim=(2, 2),
        black_level_by_phase=(0.0, 0.0, 0.0, 0.0),
        white_level=16383,
        color_matrix=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        as_shot_neutral=(1.0, 1.0, 1.0),
        original_filename="scan.ARW",
    )

    profile = build_profile(
        RawFrame(meta, correction),
        smooth_sigma=2,
        clip_percentiles=None,
        active_mask=active_mask,
    )
    corrected = apply_profile(RawFrame(meta, scan), profile, backend=Backend("numpy", "test"))

    assert np.all(corrected[:, 2:] == 2000)


def test_optional_dust_detail_corrects_capped_dark_blob() -> None:
    pattern = np.array([[0, 1], [3, 2]], dtype=np.uint8)
    correction = np.full((80, 80), 2000, dtype=np.uint16)
    scan = np.full((80, 80), 2000, dtype=np.uint16)
    yy, xx = np.ogrid[:80, :80]
    blob = (yy - 40) ** 2 + (xx - 40) ** 2 <= 8**2
    correction[blob] = 1600
    scan[blob] = 1600
    meta = RawMetadata(
        path=__import__("pathlib").Path("scan.ARW"),
        make="SONY",
        model="TEST",
        unique_camera_model="Sony TEST",
        timestamp=None,
        raw_shape=(80, 80),
        crop_origin=(0, 0),
        crop_size=(80, 80),
        raw_pattern=pattern,
        dng_cfa_pattern=(0, 1, 1, 2),
        dng_cfa_repeat_dim=(2, 2),
        black_level_by_phase=(0.0, 0.0, 0.0, 0.0),
        white_level=16383,
        color_matrix=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        as_shot_neutral=(1.0, 1.0, 1.0),
        original_filename="scan.ARW",
    )

    broad_profile = build_profile(
        RawFrame(meta, correction),
        smooth_sigma=32,
        clip_percentiles=None,
    )
    dust_profile = build_profile(
        RawFrame(meta, correction),
        smooth_sigma=32,
        clip_percentiles=None,
        dust_correction=True,
        dust_sigma=4,
        dust_threshold=0.01,
        dust_max_gain=1.10,
    )

    broad_corrected = apply_profile(RawFrame(meta, scan), broad_profile, backend=Backend("numpy", "test"))
    dust_corrected = apply_profile(RawFrame(meta, scan), dust_profile, backend=Backend("numpy", "test"))

    assert int(dust_corrected[40, 40]) > int(broad_corrected[40, 40])
    assert int(dust_corrected[40, 40]) <= 1780
    assert abs(int(dust_corrected[10, 10]) - 2000) <= 5


def test_profile_defaults_to_metadata_visible_area() -> None:
    pattern = np.array([[0, 1], [3, 2]], dtype=np.uint8)
    correction = np.full((8, 8), 2000, dtype=np.uint16)
    correction[:, :2] = 200
    scan = np.full((8, 8), 2000, dtype=np.uint16)
    meta = _metadata(
        raw_shape=(8, 8),
        crop_origin=(2, 0),
        crop_size=(6, 8),
        raw_pattern=pattern,
        dng_cfa_pattern=(0, 1, 1, 2),
        dng_cfa_repeat_dim=(2, 2),
        black_level_by_phase=(0.0, 0.0, 0.0, 0.0),
    )

    profile = build_profile(RawFrame(meta, correction), smooth_sigma=2, clip_percentiles=None)
    corrected = apply_profile(RawFrame(meta, scan), profile, backend=Backend("numpy", "test"))

    assert np.all(corrected[:, 2:] == 2000)


def test_apply_profile_uses_scan_black_level_not_calibration_black_level() -> None:
    pattern = np.array([[0]], dtype=np.uint8)
    correction_meta = _metadata(
        raw_shape=(1, 2),
        raw_pattern=pattern,
        dng_cfa_pattern=(0,),
        dng_cfa_repeat_dim=(1, 1),
        black_level_by_phase=(64.0,),
    )
    scan_meta = _metadata(
        raw_shape=(1, 2),
        raw_pattern=pattern,
        dng_cfa_pattern=(0,),
        dng_cfa_repeat_dim=(1, 1),
        black_level_by_phase=(512.0,),
    )
    correction = np.array([[1064, 2064]], dtype=np.uint16)
    scan = np.array([[1512, 2512]], dtype=np.uint16)

    profile = build_profile(
        RawFrame(correction_meta, correction),
        smooth_sigma=0,
        clip_percentiles=None,
        norm_percentile=50,
    )
    corrected = apply_profile(RawFrame(scan_meta, scan), profile, backend=Backend("numpy", "test"))

    assert corrected.tolist() == [[2012, 2012]]


def test_profile_rejects_invalid_percentile_options() -> None:
    meta = _metadata()
    correction = np.full((4, 4), 2000, dtype=np.uint16)

    with pytest.raises(ValueError, match="clip_percentiles"):
        build_profile(RawFrame(meta, correction), clip_percentiles=(99.0, 1.0))

    with pytest.raises(ValueError, match="norm_percentile"):
        build_profile(RawFrame(meta, correction), norm_percentile=101.0)


def test_profile_rejects_invalid_sigma_options() -> None:
    meta = _metadata()
    correction = np.full((4, 4), 2000, dtype=np.uint16)

    with pytest.raises(ValueError, match="smooth_sigma"):
        build_profile(RawFrame(meta, correction), smooth_sigma=-1.0)

    with pytest.raises(ValueError, match="dust_sigma"):
        build_profile(RawFrame(meta, correction), dust_correction=True, dust_sigma=0)


def _metadata(
    *,
    raw_shape: tuple[int, int] = (4, 4),
    crop_origin: tuple[int, int] = (0, 0),
    crop_size: tuple[int, int] | None = None,
    raw_pattern: np.ndarray | None = None,
    dng_cfa_pattern: tuple[int, ...] = (0, 1, 1, 2),
    dng_cfa_repeat_dim: tuple[int, int] = (2, 2),
    black_level_by_phase: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0),
) -> RawMetadata:
    if crop_size is None:
        crop_size = (raw_shape[1], raw_shape[0])
    if raw_pattern is None:
        raw_pattern = np.array([[0, 1], [3, 2]], dtype=np.uint8)

    return RawMetadata(
        path=Path("scan.ARW"),
        make="SONY",
        model="TEST",
        unique_camera_model="Sony TEST",
        timestamp=None,
        raw_shape=raw_shape,
        crop_origin=crop_origin,
        crop_size=crop_size,
        raw_pattern=raw_pattern,
        dng_cfa_pattern=dng_cfa_pattern,
        dng_cfa_repeat_dim=dng_cfa_repeat_dim,
        black_level_by_phase=black_level_by_phase,
        white_level=16383,
        color_matrix=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        as_shot_neutral=(1.0, 1.0, 1.0),
        original_filename="scan.ARW",
    )
