from __future__ import annotations

from pathlib import Path

import numpy as np

from ffc.lightroom_crop import (
    LightroomCrop,
    raw_crop_bounding_area,
    raw_crop_mask,
    raw_crop_polygon,
    relative_crop_for_area,
)
from ffc.rawio import RawMetadata


def _metadata() -> RawMetadata:
    return RawMetadata(
        path=Path("scan.ARW"),
        make="SONY",
        model="TEST",
        unique_camera_model="Sony TEST",
        timestamp=None,
        raw_shape=(100, 120),
        crop_origin=(10, 20),
        crop_size=(100, 60),
        raw_pattern=np.array([[0, 1], [3, 2]], dtype=np.uint8),
        dng_cfa_pattern=(0, 1, 1, 2),
        dng_cfa_repeat_dim=(2, 2),
        black_level_by_phase=(0.0, 0.0, 0.0, 0.0),
        white_level=16383,
        color_matrix=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        as_shot_neutral=(1.0, 1.0, 1.0),
        original_filename="scan.ARW",
    )


def test_axis_aligned_lightroom_crop_maps_to_raw_default_crop() -> None:
    crop = LightroomCrop(left=0.2, top=0.25, right=0.8, bottom=0.75)

    assert raw_crop_bounding_area(_metadata(), crop) == (30, 35, 60, 30)


def test_reversed_top_bottom_full_crop_is_tolerated() -> None:
    crop = LightroomCrop(left=0, top=1, right=1, bottom=0)

    assert raw_crop_bounding_area(_metadata(), crop) == (10, 20, 100, 60)


def test_rotated_lightroom_crop_builds_polygon_mask_and_relative_crop() -> None:
    metadata = _metadata()
    crop = LightroomCrop(left=0.25, top=0.25, right=0.75, bottom=0.75, angle=12.0)

    polygon = raw_crop_polygon(metadata, crop)
    area = raw_crop_bounding_area(metadata, crop)
    mask = raw_crop_mask(metadata, crop)
    adjusted = relative_crop_for_area(metadata, crop, area)

    assert polygon.shape == (4, 2)
    assert area[2] > 0
    assert area[3] > 0
    assert mask.dtype == bool
    assert mask[50, 60]
    assert not mask[20, 10]
    assert 0 <= adjusted.left <= 1
    assert 0 <= adjusted.top <= 1
    assert 0 <= adjusted.right <= 1
    assert 0 <= adjusted.bottom <= 1
    assert adjusted.angle == crop.angle
