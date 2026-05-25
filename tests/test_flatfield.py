from __future__ import annotations

import numpy as np

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
