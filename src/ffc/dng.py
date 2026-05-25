from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, Literal

import numpy as np
import tifffile

from .rawio import RawMetadata

CompressionMode = Literal["auto", "none", "lossless-jpeg", "lossless-jxl"]


def write_mosaic_dng(path: Path, raw: np.ndarray, metadata: RawMetadata, *, software: str = "ffcplugin") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tags = _dng_tags(metadata)
    tifffile.imwrite(
        path,
        raw,
        dtype=np.uint16,
        photometric=32803,
        compression=None,
        rowsperstrip=256,
        metadata=None,
        description=None,
        software=software,
        datetime=_datetime_tag(metadata.timestamp),
        extratags=tags,
    )
    if metadata.timestamp is not None:
        epoch = metadata.timestamp.timestamp()
        os.utime(path, (epoch, epoch))


def compress_with_adobe_dng_converter(
    input_paths: list[Path],
    output_dir: Path,
    *,
    converter_path: Path,
    mode: Literal["lossless-jpeg", "lossless-jxl"] = "lossless-jpeg",
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    options = ["-c"] if mode == "lossless-jpeg" else ["-losslessJXL"]
    if len(input_paths) > 1:
        options.append("-mp")
    cmd = [str(converter_path), *options, "-d", str(output_dir), *map(str, input_paths)]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        details = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
        raise RuntimeError(f"Adobe DNG Converter failed with exit code {result.returncode}.\n{details}")

    missing = [output_dir / path.name for path in input_paths if not (output_dir / path.name).exists()]
    if missing:
        raise RuntimeError(f"Adobe DNG Converter did not create expected output: {missing[0]}")
    for input_path in input_paths:
        _preserve_datetime_and_mtime(input_path, output_dir / input_path.name)


def compress_with_dnglab(input_paths: list[Path], output_dir: Path, *, dnglab_path: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for input_path in input_paths:
        output_path = output_dir / input_path.name
        cmd = [
            str(dnglab_path),
            "convert",
            "-f",
            "--embed-raw",
            "false",
            "--dng-preview",
            "false",
            "--dng-thumbnail",
            "false",
            str(input_path),
            str(output_path),
        ]
        result = subprocess.run(cmd, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            details = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
            raise RuntimeError(f"dnglab failed with exit code {result.returncode}.\n{details}")
        if not output_path.exists():
            raise RuntimeError(f"dnglab did not create expected output: {output_path}")
        _preserve_datetime_and_mtime(input_path, output_path)


def find_adobe_dng_converter(explicit: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    which = shutil.which("Adobe DNG Converter")
    if which:
        candidates.append(Path(which))
    candidates.extend(
        [
            Path("/Applications/Adobe DNG Converter.app/Contents/MacOS/Adobe DNG Converter"),
            Path("/Applications/Adobe DNG Converter.app"),
            Path(r"C:\Program Files\Adobe\Adobe DNG Converter\Adobe DNG Converter.exe"),
            Path(r"C:\Program Files\Adobe DNG Converter.exe"),
        ]
    )
    for candidate in candidates:
        executable = _converter_executable(candidate)
        if executable and executable.exists():
            return executable
    return None


def find_dnglab(explicit: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    which = shutil.which("dnglab")
    if which:
        candidates.append(Path(which))
    candidates.extend(
        [
            Path("/opt/homebrew/bin/dnglab"),
            Path("/usr/local/bin/dnglab"),
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def write_batch_dngs(
    outputs: Iterable[tuple[Path, np.ndarray, RawMetadata]],
    *,
    compression: CompressionMode,
    converter_path: Path | None,
    software: str = "ffcplugin",
) -> list[Path]:
    output_items = list(outputs)
    if compression == "none":
        written: list[Path] = []
        for path, raw, metadata in output_items:
            write_mosaic_dng(path, raw, metadata, software=software)
            written.append(path)
        return written

    resolved_mode: Literal["lossless-jpeg", "lossless-jxl"]
    if compression == "auto":
        if converter_path is None:
            resolved_mode = "lossless-jpeg"
            for path, raw, metadata in output_items:
                write_mosaic_dng(path, raw, metadata, software=software)
            return [item[0] for item in output_items]
        resolved_mode = "lossless-jpeg"
    else:
        if converter_path is None:
            raise RuntimeError(f"Compression mode {compression!r} requires Adobe DNG Converter.")
        resolved_mode = compression

    assert converter_path is not None
    if not output_items:
        return []

    final_dir = output_items[0][0].parent
    if any(path.parent != final_dir for path, _, _ in output_items):
        raise ValueError("Compressed batch outputs must share one output directory.")

    with tempfile.TemporaryDirectory(prefix="ffcplugin-dng-") as tmp:
        tmp_dir = Path(tmp)
        tmp_paths: list[Path] = []
        for final_path, raw, metadata in output_items:
            tmp_path = tmp_dir / final_path.name
            write_mosaic_dng(tmp_path, raw, metadata, software=software)
            tmp_paths.append(tmp_path)
        compress_with_adobe_dng_converter(tmp_paths, final_dir, converter_path=converter_path, mode=resolved_mode)

    return [item[0] for item in output_items]


def _dng_tags(metadata: RawMetadata) -> list[tuple[int, str, int, object, bool]]:
    crop_left, crop_top = metadata.crop_origin
    crop_w, crop_h = metadata.crop_size
    raw_h, raw_w = metadata.raw_shape

    tags: list[tuple[int, str, int, object, bool]] = [
        (254, "I", 1, 0, False),
        (271, "s", 0, metadata.make, False),
        (272, "s", 0, metadata.model, False),
        (33421, "H", 2, metadata.dng_cfa_repeat_dim, False),
        (33422, "B", len(metadata.dng_cfa_pattern), metadata.dng_cfa_pattern, False),
        (50706, "B", 4, (1, 4, 0, 0), False),
        (50707, "B", 4, (1, 3, 0, 0), False),
        (50708, "s", 0, metadata.unique_camera_model, False),
        (50710, "B", 3, (0, 1, 2), False),
        (50711, "H", 1, 1, False),
        (50713, "H", 2, metadata.dng_cfa_repeat_dim, False),
        _black_level_tag(metadata.black_level_by_phase),
        (50717, "H", 1, int(metadata.white_level), False),
        (50718, "2I", 2, (_urational(1), _urational(1)), False),
        (50719, "2I", 2, (_urational(crop_left), _urational(crop_top)), False),
        (50720, "2I", 2, (_urational(crop_w), _urational(crop_h)), False),
        (50721, "2i", 9, tuple(_srational(v) for v in metadata.color_matrix), False),
        (50722, "2i", 9, tuple(_srational(v) for v in metadata.color_matrix), False),
        (50778, "H", 1, 17, False),
        (50779, "H", 1, 21, False),
        (50827, "s", 0, metadata.original_filename, False),
        (50829, "I", 4, (0, 0, raw_h, raw_w), False),
    ]
    if metadata.as_shot_neutral is not None:
        tags.append((50728, "2I", 3, tuple(_urational_float(v) for v in metadata.as_shot_neutral), False))
    return tags


def _black_level_tag(values: tuple[float, ...]) -> tuple[int, str, int, object, bool]:
    if all(float(value).is_integer() and 0 <= value <= 65535 for value in values):
        return (50714, "H", len(values), tuple(int(value) for value in values), False)
    return (50714, "2I", len(values), tuple(_urational_float(value) for value in values), False)


def _urational(value: int | float) -> tuple[int, int]:
    return (int(round(float(value))), 1)


def _urational_float(value: float, denominator: int = 1_000_000) -> tuple[int, int]:
    return (max(0, int(round(value * denominator))), denominator)


def _srational(value: float, denominator: int = 1_000_000) -> tuple[int, int]:
    return (int(round(value * denominator)), denominator)


def _datetime_tag(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%Y:%m:%d %H:%M:%S")


def _converter_executable(path: Path) -> Path | None:
    if path.is_dir() and path.suffix == ".app":
        return path / "Contents" / "MacOS" / "Adobe DNG Converter"
    return path


def _preserve_datetime_and_mtime(source: Path, output: Path) -> None:
    timestamp = _read_tiff_datetime(source)
    if timestamp:
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                with tifffile.TiffFile(output, mode="r+b") as tif:
                    tag = tif.pages[0].tags.get("DateTime")
                    if tag is not None:
                        tag.overwrite(timestamp)
        except Exception:
            pass

    try:
        source_stat = source.stat()
        os.utime(output, (source_stat.st_atime, source_stat.st_mtime))
    except OSError:
        pass


def _read_tiff_datetime(path: Path) -> str | None:
    try:
        with tifffile.TiffFile(path) as tif:
            for page in tif.pages:
                tag = page.tags.get("DateTime")
                if tag is not None:
                    value = str(tag.value)
                    if len(value) == 19:
                        return value
    except Exception:
        return None
    return None
