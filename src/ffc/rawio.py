from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import rawpy
import tifffile


@dataclass(frozen=True)
class RawMetadata:
    path: Path
    make: str
    model: str
    unique_camera_model: str
    timestamp: datetime | None
    raw_shape: tuple[int, int]
    crop_origin: tuple[int, int]
    crop_size: tuple[int, int]
    raw_pattern: np.ndarray
    dng_cfa_pattern: tuple[int, ...]
    dng_cfa_repeat_dim: tuple[int, int]
    black_level_by_phase: tuple[float, ...]
    white_level: int
    color_matrix: tuple[float, ...]
    as_shot_neutral: tuple[float, float, float] | None
    original_filename: str


@dataclass
class RawFrame:
    metadata: RawMetadata
    raw: np.ndarray


def read_raw_frame(path: Path) -> RawFrame:
    path = Path(path)
    with rawpy.imread(str(path)) as raw:
        raw_image = raw.raw_image.copy()
        metadata = _metadata_from_rawpy(path, raw, raw_image.shape)
    return RawFrame(metadata=metadata, raw=raw_image)


def _metadata_from_rawpy(path: Path, raw: rawpy.RawPy, raw_shape: tuple[int, int]) -> RawMetadata:
    make, model, datetime_tag = _read_tiff_identity(path)
    timestamp = raw.other.timestamp if raw.other.timestamp else _parse_tiff_datetime(datetime_tag)
    raw_pattern = np.array(raw.raw_pattern, dtype=np.uint8, copy=True)
    color_desc = raw.color_desc.decode("ascii", errors="ignore")
    dng_pattern = _dng_cfa_pattern(raw_pattern, color_desc)
    black_by_phase = _black_levels_by_phase(raw.black_level_per_channel, raw_pattern)
    white_level = _white_level(raw)
    crop_origin, crop_size = _crop(raw, raw_shape)
    color_matrix = tuple(float(v) for v in raw.rgb_xyz_matrix[:3, :].reshape(-1))
    as_shot_neutral = _as_shot_neutral(raw.camera_whitebalance)

    return RawMetadata(
        path=path,
        make=make,
        model=model,
        unique_camera_model=_unique_camera_model(make, model),
        timestamp=timestamp,
        raw_shape=raw_shape,
        crop_origin=crop_origin,
        crop_size=crop_size,
        raw_pattern=raw_pattern,
        dng_cfa_pattern=dng_pattern,
        dng_cfa_repeat_dim=(int(raw_pattern.shape[0]), int(raw_pattern.shape[1])),
        black_level_by_phase=black_by_phase,
        white_level=white_level,
        color_matrix=color_matrix,
        as_shot_neutral=as_shot_neutral,
        original_filename=path.name,
    )


def _read_tiff_identity(path: Path) -> tuple[str, str, str | None]:
    make = ""
    model = ""
    datetime_tag = None
    try:
        with tifffile.TiffFile(path) as tif:
            for page in tif.pages:
                make_tag = page.tags.get("Make")
                model_tag = page.tags.get("Model")
                datetime_value = page.tags.get("DateTime")
                if make_tag and not make:
                    make = str(make_tag.value).strip()
                if model_tag and not model:
                    model = str(model_tag.value).strip()
                if datetime_value and datetime_tag is None:
                    datetime_tag = str(datetime_value.value).strip()
                if make and model and datetime_tag:
                    break
    except Exception:
        pass
    return make or "Unknown", model or "Unknown", datetime_tag


def _parse_tiff_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _dng_cfa_pattern(raw_pattern: np.ndarray, color_desc: str) -> tuple[int, ...]:
    plane_by_color = {"R": 0, "G": 1, "B": 2}
    values: list[int] = []
    for code in raw_pattern.reshape(-1):
        try:
            color = color_desc[int(code)]
        except IndexError as exc:
            raise ValueError(f"Unsupported CFA color code {int(code)} for color descriptor {color_desc!r}") from exc
        if color not in plane_by_color:
            raise ValueError(f"Unsupported CFA color {color!r}; only RGB Bayer-style mosaics are supported.")
        values.append(plane_by_color[color])
    return tuple(values)


def _black_levels_by_phase(black_levels: list[int], raw_pattern: np.ndarray) -> tuple[float, ...]:
    values: list[float] = []
    for code in raw_pattern.reshape(-1):
        idx = int(code)
        if idx >= len(black_levels):
            idx = min(idx, len(black_levels) - 1)
        values.append(float(black_levels[idx]))
    return tuple(values)


def _white_level(raw: rawpy.RawPy) -> int:
    if raw.white_level and raw.white_level > 0:
        return int(raw.white_level)
    channel_levels = [v for v in raw.camera_white_level_per_channel if v and v > 0]
    if channel_levels:
        return int(min(channel_levels))
    return 65535


def _crop(raw: rawpy.RawPy, raw_shape: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    raw_h, raw_w = raw_shape
    crop_w = int(raw.sizes.crop_width or raw.sizes.width or raw_w)
    crop_h = int(raw.sizes.crop_height or raw.sizes.height or raw_h)

    visible_w = int(raw.raw_image_visible.shape[1])
    inferred_left = max(0, raw_w - visible_w)
    crop_left = int(raw.sizes.crop_left_margin or inferred_left or max(0, (raw_w - crop_w) // 2))
    crop_top = int(raw.sizes.crop_top_margin or max(0, (raw_h - crop_h) // 2))

    return (crop_left, crop_top), (crop_w, crop_h)


def _as_shot_neutral(camera_wb: list[float]) -> tuple[float, float, float] | None:
    if len(camera_wb) < 3 or camera_wb[0] <= 0 or camera_wb[1] <= 0 or camera_wb[2] <= 0:
        return None
    green = float(camera_wb[1])
    return (green / float(camera_wb[0]), 1.0, green / float(camera_wb[2]))


def _unique_camera_model(make: str, model: str) -> str:
    nice_make = make.title() if make.isupper() else make
    if model.lower().startswith(nice_make.lower()):
        return model
    return f"{nice_make} {model}".strip()

