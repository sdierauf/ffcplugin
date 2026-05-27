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
ensure_unique_paths = None
read_raw_frame = None
LightroomCrop = None
raw_crop_bounding_area = None
raw_crop_mask = None
relative_crop_for_area = None


def load_pipeline_modules() -> None:
    global choose_backend
    global compress_with_adobe_dng_converter
    global compress_with_dnglab
    global find_adobe_dng_converter
    global find_dnglab
    global write_mosaic_dng
    global apply_profile
    global build_profile
    global ensure_unique_paths
    global read_raw_frame
    global LightroomCrop
    global raw_crop_bounding_area
    global raw_crop_mask
    global relative_crop_for_area

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
    from ffc.lightroom_crop import LightroomCrop as _LightroomCrop
    from ffc.lightroom_crop import raw_crop_bounding_area as _raw_crop_bounding_area
    from ffc.lightroom_crop import raw_crop_mask as _raw_crop_mask
    from ffc.lightroom_crop import relative_crop_for_area as _relative_crop_for_area
    from ffc.paths import ensure_unique_paths as _ensure_unique_paths
    from ffc.rawio import read_raw_frame as _read_raw_frame

    choose_backend = _choose_backend
    compress_with_adobe_dng_converter = _compress_with_adobe_dng_converter
    compress_with_dnglab = _compress_with_dnglab
    find_adobe_dng_converter = _find_adobe_dng_converter
    find_dnglab = _find_dnglab
    write_mosaic_dng = _write_mosaic_dng
    apply_profile = _apply_profile
    build_profile = _build_profile
    ensure_unique_paths = _ensure_unique_paths
    read_raw_frame = _read_raw_frame
    LightroomCrop = _LightroomCrop
    raw_crop_bounding_area = _raw_crop_bounding_area
    raw_crop_mask = _raw_crop_mask
    relative_crop_for_area = _relative_crop_for_area


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", required=True, help="Flat-field correction raw.")
    parser.add_argument("--selected-list", required=True, help="Text file of selected raw paths.")
    parser.add_argument("--crop-list", help="Optional Lightroom crop list: path, left, top, right, bottom, angle per line.")
    parser.add_argument("--output-crop-list", help="Optional path for Lightroom crop settings adjusted for generated DNGs.")
    parser.add_argument("--output-list", required=True, help="Write generated DNG paths here.")
    parser.add_argument("--output-dir", help="Output directory. Defaults to a subfolder beside the first selected scan.")
    parser.add_argument("--output-subdir", default="flatfield-corrected", help="Default output subfolder name.")
    parser.add_argument("--result-file", help="Write Lightroom-friendly key/value results here.")
    parser.add_argument("--progress-file", help="Write Lightroom-friendly progress key/value updates here.")
    parser.add_argument("--backend", choices=("auto", "numpy", "numexpr"), default="auto")
    parser.add_argument("--compressor", choices=("auto", "adobe", "dnglab", "none"), default="auto")
    parser.add_argument("--compression", choices=("auto", "none", "lossless-jpeg", "lossless-jxl"), default="auto")
    parser.add_argument("--dnglab", help="Optional dnglab executable path.")
    parser.add_argument("--dng-converter", help="Optional Adobe DNG Converter executable or .app path.")
    parser.add_argument("--smooth-sigma", type=float, default=192.0)
    parser.add_argument("--norm-percentile", type=float, default=70.0)
    parser.add_argument("--dust-correction", action="store_true")
    parser.add_argument("--dust-sigma", type=float, default=32.0)
    parser.add_argument("--dust-threshold", type=float, default=0.02)
    parser.add_argument("--dust-amount", type=float, default=1.0)
    parser.add_argument("--dust-max-gain", type=float, default=1.10)
    parser.add_argument("--suffix", default="_ffc")
    parser.add_argument("--replace-existing", action="store_true", default=True)
    return parser.parse_args(argv)


def read_selected(path: Path) -> list[Path]:
    with path.open("r", encoding="utf-8") as handle:
        return [Path(line.rstrip("\r\n")).expanduser() for line in handle if line.strip()]


def read_crop_list(path: str | None):
    assert LightroomCrop is not None
    if not path:
        return {}

    crops = {}
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) < 5:
                continue
            angle = float(parts[5]) if len(parts) >= 6 and parts[5] else 0.0
            orientation = parts[6] if len(parts) >= 7 and parts[6] else "AB"
            crops[Path(parts[0]).expanduser()] = LightroomCrop(
                left=float(parts[1]),
                top=float(parts[2]),
                right=float(parts[3]),
                bottom=float(parts[4]),
                angle=angle,
                orientation=orientation,
            )
    return crops


def write_result(path: str | None, values: dict[str, object]) -> None:
    lines = [f"{key}={quote(str(value), safe='')}" for key, value in values.items()]
    text = "\n".join(lines) + "\n"
    if path:
        Path(path).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def write_progress(
    path: str | None,
    caption: str,
    *,
    current: int = 0,
    total: int = 0,
    status: str = "running",
) -> None:
    if not path:
        return

    progress_path = Path(path).expanduser()
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "status": status,
        "caption": caption,
        "current": current,
        "total": total,
    }
    text = "\n".join(f"{key}={quote(str(value), safe='')}" for key, value in values.items()) + "\n"
    tmp_path = progress_path.with_name(progress_path.name + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, progress_path)


def choose_output_dir(args: argparse.Namespace, selected: list[Path]) -> Path:
    if args.output_dir:
        return Path(args.output_dir).expanduser()
    return selected[0].parent / args.output_subdir


def write_crop_list(path: str | None, crops) -> None:
    if not path:
        return

    lines = []
    for output_path, crop in crops:
        lines.append(
            "\t".join(
                [
                    str(output_path),
                    str(crop.left),
                    str(crop.top),
                    str(crop.right),
                    str(crop.bottom),
                    str(crop.angle),
                    str(crop.orientation),
                ]
            )
        )
    Path(path).expanduser().write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def crop_for_path(crops, path: Path):
    if path in crops:
        return crops[path]
    resolved = path.resolve()
    for candidate, crop in crops.items():
        if candidate.resolve() == resolved:
            return crop
    return None


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
    assert ensure_unique_paths is not None
    assert raw_crop_bounding_area is not None
    assert raw_crop_mask is not None
    assert relative_crop_for_area is not None

    calibration = Path(args.calibration).expanduser()
    selected = read_selected(Path(args.selected_list).expanduser())
    if not calibration.is_file():
        raise FileNotFoundError(f"Calibration raw does not exist: {calibration}")
    if not selected:
        raise ValueError("No selected scan paths were provided.")

    missing = [path for path in selected if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Selected scan path does not exist: {missing[0]}")

    total = len(selected)
    write_progress(args.progress_file, "Preparing output folder", current=0, total=total)
    output_dir = choose_output_dir(args, selected)
    output_dir.mkdir(parents=True, exist_ok=True)
    crops = read_crop_list(args.crop_list)

    write_progress(args.progress_file, "Resolving compressor and backend", current=0, total=total)
    compressor, compressor_path, resolved_compression = choose_compressor(args)
    backend = choose_backend(args.backend)
    write_progress(args.progress_file, "Reading flat-field calibration frame", current=0, total=total)
    correction = read_raw_frame(calibration)
    calibration_crop = crop_for_path(crops, calibration)
    active_mask = raw_crop_mask(correction.metadata, calibration_crop) if calibration_crop else None
    write_progress(args.progress_file, "Calculating flat-field profile", current=0, total=total)
    profile = build_profile(
        correction,
        smooth_sigma=args.smooth_sigma,
        norm_percentile=args.norm_percentile,
        active_mask=active_mask,
        dust_correction=args.dust_correction,
        dust_sigma=args.dust_sigma,
        dust_threshold=args.dust_threshold,
        dust_amount=args.dust_amount,
        dust_max_gain=args.dust_max_gain,
    )

    output_paths = [output_dir / f"{path.stem}{args.suffix}.dng" for path in selected]
    ensure_unique_paths(output_paths, "output DNG path")
    for path in output_paths:
        if path.exists() and args.replace_existing:
            path.unlink()
        elif path.exists():
            raise FileExistsError(f"{path} already exists.")

    temp_paths: list[Path] = []
    output_crops = []
    write_dir = output_dir
    temp_root = None
    if compressor != "none":
        import tempfile

        temp_root = tempfile.TemporaryDirectory(prefix="ffcplugin-lightroom-")
        write_dir = Path(temp_root.name)

    try:
        for index, (selected_path, output_path) in enumerate(zip(selected, output_paths, strict=True), start=1):
            write_progress(
                args.progress_file,
                f"Processing {index}/{total}: {selected_path.name}",
                current=index - 1,
                total=total,
            )
            scan = read_raw_frame(selected_path)
            corrected = apply_profile(scan, profile, backend=backend)
            metadata = scan.metadata
            scan_crop = crop_for_path(crops, selected_path)
            if scan_crop:
                left, top, width, height = raw_crop_bounding_area(metadata, scan_crop)
                output_crops.append(
                    (output_path, relative_crop_for_area(metadata, scan_crop, (left, top, width, height)))
                )
                metadata = replace(metadata, crop_origin=(left, top), crop_size=(width, height))
            temp_path = write_dir / output_path.name
            write_mosaic_dng(temp_path, corrected, metadata, software="ffcplugin")
            temp_paths.append(temp_path)
            write_progress(
                args.progress_file,
                f"Processed {index}/{total}: {selected_path.name}",
                current=index,
                total=total,
            )

        if compressor == "dnglab":
            assert compressor_path is not None
            write_progress(args.progress_file, "Compressing DNGs with dnglab", current=total, total=total)
            compress_with_dnglab(temp_paths, output_dir, dnglab_path=compressor_path)
        elif compressor == "adobe":
            assert compressor_path is not None
            write_progress(args.progress_file, "Compressing DNGs with Adobe DNG Converter", current=total, total=total)
            compress_with_adobe_dng_converter(
                temp_paths,
                output_dir,
                converter_path=compressor_path,
                mode=resolved_compression,
            )
    finally:
        if temp_root is not None:
            temp_root.cleanup()

    write_progress(args.progress_file, "Writing Lightroom output lists", current=total, total=total)
    Path(args.output_list).write_text("\n".join(str(path) for path in output_paths) + "\n", encoding="utf-8")
    write_crop_list(args.output_crop_list, output_crops)
    return {
        "status": "ok",
        "count": len(output_paths),
        "output_dir": str(output_dir),
        "output_list": args.output_list,
        "backend": backend.name,
        "compressor": compressor,
        "compression": resolved_compression,
        "crop_aware": "true" if active_mask is not None else "false",
        "norm_percentile": args.norm_percentile,
        "dust_correction": "true" if args.dust_correction else "false",
        "warning": "" if compressor != "none" else "No compact DNG compressor was used; outputs are uncompressed and large.",
    }


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        write_progress(args.progress_file, "Loading Python pipeline", current=0, total=1)
        load_pipeline_modules()
        result = run(args)
    except Exception as exc:
        write_progress(args.progress_file, f"Failed: {exc}", current=0, total=1, status="error")
        write_result(args.result_file, {"status": "error", "message": str(exc)})
        return 1

    write_progress(args.progress_file, "Python flat-field correction complete", current=1, total=1, status="done")
    write_result(args.result_file, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
