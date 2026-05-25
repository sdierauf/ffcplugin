#!/usr/bin/env python3
"""Run the ffcplugin Python pipeline for Lightroom-selected raw files."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote


def add_repo_src_to_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src = repo_root / "src"
    if src.exists():
        sys.path.insert(0, str(src))


add_repo_src_to_path()

choose_backend = None
compress_with_adobe_dng_converter = None
compress_with_dnglab = None
find_adobe_dng_converter = None
find_dnglab = None
write_mosaic_dng = None
apply_profile = None
build_profile = None
read_raw_frame = None


def load_pipeline_modules() -> None:
    global choose_backend
    global compress_with_adobe_dng_converter
    global compress_with_dnglab
    global find_adobe_dng_converter
    global find_dnglab
    global write_mosaic_dng
    global apply_profile
    global build_profile
    global read_raw_frame

    from ffc.accelerate import choose_backend as _choose_backend
    from ffc.dng import (
        compress_with_adobe_dng_converter as _compress_with_adobe_dng_converter,
        compress_with_dnglab as _compress_with_dnglab,
        find_adobe_dng_converter as _find_adobe_dng_converter,
        find_dnglab as _find_dnglab,
        write_mosaic_dng as _write_mosaic_dng,
    )
    from ffc.flatfield import apply_profile as _apply_profile
    from ffc.flatfield import build_profile as _build_profile
    from ffc.rawio import read_raw_frame as _read_raw_frame

    choose_backend = _choose_backend
    compress_with_adobe_dng_converter = _compress_with_adobe_dng_converter
    compress_with_dnglab = _compress_with_dnglab
    find_adobe_dng_converter = _find_adobe_dng_converter
    find_dnglab = _find_dnglab
    write_mosaic_dng = _write_mosaic_dng
    apply_profile = _apply_profile
    build_profile = _build_profile
    read_raw_frame = _read_raw_frame


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", required=True, help="Flat-field correction raw.")
    parser.add_argument("--selected-list", required=True, help="Text file of selected raw paths.")
    parser.add_argument("--crop-list", help="Optional Lightroom crop list: path, left, top, right, bottom per line.")
    parser.add_argument("--output-list", required=True, help="Write generated DNG paths here.")
    parser.add_argument("--output-dir", help="Output directory. Defaults to a subfolder beside the first selected scan.")
    parser.add_argument("--output-subdir", default="flatfield-corrected", help="Default output subfolder name.")
    parser.add_argument("--result-file", help="Write Lightroom-friendly key/value results here.")
    parser.add_argument("--backend", choices=("auto", "numpy", "numexpr", "mlx"), default="auto")
    parser.add_argument("--compressor", choices=("auto", "adobe", "dnglab", "none"), default="auto")
    parser.add_argument("--compression", choices=("auto", "none", "lossless-jpeg", "lossless-jxl"), default="auto")
    parser.add_argument("--dnglab", help="Optional dnglab executable path.")
    parser.add_argument("--dng-converter", help="Optional Adobe DNG Converter executable or .app path.")
    parser.add_argument("--smooth-sigma", type=float, default=96.0)
    parser.add_argument("--suffix", default="-ffc")
    parser.add_argument("--overwrite", action="store_true", default=True)
    return parser.parse_args(argv)


def read_selected(path: Path) -> list[Path]:
    with path.open("r", encoding="utf-8") as handle:
        return [Path(line.rstrip("\r\n")).expanduser() for line in handle if line.strip()]


def read_crop_list(path: str | None) -> dict[Path, tuple[float, float, float, float]]:
    if not path:
        return {}

    crops: dict[Path, tuple[float, float, float, float]] = {}
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) < 5:
                continue
            crop = tuple(float(value) for value in parts[1:5])
            crops[Path(parts[0]).expanduser()] = crop  # type: ignore[assignment]
    return crops


def write_result(path: str | None, values: dict[str, object]) -> None:
    lines = [f"{key}={quote(str(value), safe='')}" for key, value in values.items()]
    text = "\n".join(lines) + "\n"
    if path:
        Path(path).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def choose_output_dir(args: argparse.Namespace, selected: list[Path]) -> Path:
    if args.output_dir:
        return Path(args.output_dir).expanduser()
    return selected[0].parent / args.output_subdir


def crop_for_path(crops: dict[Path, tuple[float, float, float, float]], path: Path) -> tuple[float, float, float, float] | None:
    if path in crops:
        return crops[path]
    resolved = path.resolve()
    for candidate, crop in crops.items():
        if candidate.resolve() == resolved:
            return crop
    return None


def normalized_crop_to_raw_area(metadata, crop: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    left_n, top_n, right_n, bottom_n = crop
    # Lightroom develop crop coordinates use a bottom-left y axis:
    # full frame is typically CropTop=1 and CropBottom=0.
    left_f = min(left_n, right_n)
    right_f = max(left_n, right_n)
    top_f = 1.0 - max(top_n, bottom_n)
    bottom_f = 1.0 - min(top_n, bottom_n)

    base_left, base_top = metadata.crop_origin
    base_w, base_h = metadata.crop_size
    left = base_left + int(round(_clamp01(left_f) * base_w))
    top = base_top + int(round(_clamp01(top_f) * base_h))
    right = base_left + int(round(_clamp01(right_f) * base_w))
    bottom = base_top + int(round(_clamp01(bottom_f) * base_h))

    raw_h, raw_w = metadata.raw_shape
    left = max(0, min(raw_w - 1, left))
    top = max(0, min(raw_h - 1, top))
    right = max(left + 1, min(raw_w, right))
    bottom = max(top + 1, min(raw_h, bottom))
    return left, top, right - left, bottom - top


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def choose_compressor(args: argparse.Namespace):
    assert find_adobe_dng_converter is not None
    assert find_dnglab is not None

    adobe = find_adobe_dng_converter(args.dng_converter)
    dnglab = find_dnglab(args.dnglab)

    if args.compressor == "none" or args.compression == "none":
        return "none", None, "none"

    if args.compression == "lossless-jxl":
        if args.compressor == "dnglab":
            raise RuntimeError("dnglab does not support lossless JPEG XL DNG output.")
        if adobe is None:
            raise RuntimeError("Adobe DNG Converter is required for lossless JPEG XL output.")
        return "adobe", adobe, "lossless-jxl"

    if args.compressor == "dnglab":
        if dnglab is None:
            raise RuntimeError("dnglab was not found; configure its path or use another compressor.")
        return "dnglab", dnglab, "lossless-jpeg"

    if args.compressor == "adobe":
        if adobe is None:
            raise RuntimeError("Adobe DNG Converter was not found; configure its path or use another compressor.")
        return "adobe", adobe, "lossless-jpeg" if args.compression == "auto" else args.compression

    if dnglab is not None:
        return "dnglab", dnglab, "lossless-jpeg"
    if adobe is not None:
        return "adobe", adobe, "lossless-jpeg" if args.compression == "auto" else args.compression
    return "none", None, "none"


def run(args: argparse.Namespace) -> dict[str, object]:
    assert choose_backend is not None
    assert read_raw_frame is not None
    assert build_profile is not None
    assert apply_profile is not None
    assert write_mosaic_dng is not None
    assert compress_with_dnglab is not None
    assert compress_with_adobe_dng_converter is not None

    calibration = Path(args.calibration).expanduser()
    selected = read_selected(Path(args.selected_list).expanduser())
    if not calibration.is_file():
        raise FileNotFoundError(f"Calibration raw does not exist: {calibration}")
    if not selected:
        raise ValueError("No selected scan paths were provided.")

    missing = [path for path in selected if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Selected scan path does not exist: {missing[0]}")

    output_dir = choose_output_dir(args, selected)
    output_dir.mkdir(parents=True, exist_ok=True)
    crops = read_crop_list(args.crop_list)

    compressor, compressor_path, resolved_compression = choose_compressor(args)
    backend = choose_backend(args.backend)
    correction = read_raw_frame(calibration)
    calibration_crop = crop_for_path(crops, calibration)
    active_area = normalized_crop_to_raw_area(correction.metadata, calibration_crop) if calibration_crop else None
    profile = build_profile(correction, smooth_sigma=args.smooth_sigma, active_area=active_area)

    output_paths = [output_dir / f"{path.stem}{args.suffix}.dng" for path in selected]
    for path in output_paths:
        if path.exists() and args.overwrite:
            path.unlink()
        elif path.exists():
            raise FileExistsError(f"{path} already exists.")

    temp_paths: list[Path] = []
    write_dir = output_dir
    temp_root = None
    if compressor != "none":
        import tempfile

        temp_root = tempfile.TemporaryDirectory(prefix="ffcplugin-lightroom-")
        write_dir = Path(temp_root.name)

    try:
        for selected_path, output_path in zip(selected, output_paths, strict=True):
            scan = read_raw_frame(selected_path)
            corrected = apply_profile(scan, profile, backend=backend)
            metadata = scan.metadata
            scan_crop = crop_for_path(crops, selected_path)
            if scan_crop:
                left, top, width, height = normalized_crop_to_raw_area(metadata, scan_crop)
                metadata = replace(metadata, crop_origin=(left, top), crop_size=(width, height))
            temp_path = write_dir / output_path.name
            write_mosaic_dng(temp_path, corrected, metadata, software="ffcplugin")
            temp_paths.append(temp_path)

        if compressor == "dnglab":
            assert compressor_path is not None
            compress_with_dnglab(temp_paths, output_dir, dnglab_path=compressor_path)
        elif compressor == "adobe":
            assert compressor_path is not None
            compress_with_adobe_dng_converter(
                temp_paths,
                output_dir,
                converter_path=compressor_path,
                mode=resolved_compression,
            )
    finally:
        if temp_root is not None:
            temp_root.cleanup()

    Path(args.output_list).write_text("\n".join(str(path) for path in output_paths) + "\n", encoding="utf-8")
    return {
        "status": "ok",
        "count": len(output_paths),
        "output_dir": str(output_dir),
        "output_list": args.output_list,
        "backend": backend.name,
        "compressor": compressor,
        "compression": resolved_compression,
        "crop_aware": "true" if active_area else "false",
        "warning": "" if compressor != "none" else "No compact DNG compressor was used; outputs are uncompressed and large.",
    }


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        load_pipeline_modules()
        result = run(args)
    except Exception as exc:
        write_result(args.result_file, {"status": "error", "message": str(exc)})
        return 1

    write_result(args.result_file, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
