from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from .accelerate import choose_backend
from .dng import CompressionMode, compress_with_adobe_dng_converter, find_adobe_dng_converter, write_mosaic_dng
from .flatfield import apply_profile, build_profile
from .rawio import read_raw_frame

DEFAULT_PATTERNS = ("*.ARW", "*.arw")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    correction_path = Path(args.correction).expanduser()
    input_path = Path(args.input).expanduser()
    output_dir = Path(args.output).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = _discover_inputs(input_path, args.include, args.recursive, correction_path)
    if not inputs:
        parser.error(f"No input scans found in {input_path}")

    output_paths = [output_dir / f"{scan_path.stem}{args.suffix}.dng" for scan_path in inputs]
    for output_path in output_paths:
        if output_path.exists() and not args.dry_run:
            if args.overwrite and not args.dry_run:
                output_path.unlink()
            elif not args.overwrite:
                raise FileExistsError(f"{output_path} already exists; pass --overwrite to replace it.")

    if args.dry_run:
        for path in output_paths:
            print(path)
        return 0

    converter = find_adobe_dng_converter(args.dng_converter)
    compression: CompressionMode = args.compression
    if compression == "auto" and converter is None:
        print("Adobe DNG Converter not found; writing uncompressed DNGs.", file=sys.stderr)
    elif compression not in ("auto", "none") and converter is None:
        raise RuntimeError(f"--compression {compression} requires Adobe DNG Converter; pass --compression none to skip it.")
    elif compression != "none" and converter is not None:
        print(f"Using Adobe DNG Converter: {converter}", file=sys.stderr)

    backend = choose_backend(args.backend, args.numexpr_threads)
    print(f"Using correction backend: {backend.detail}", file=sys.stderr)
    print(f"Reading correction frame: {correction_path}", file=sys.stderr)
    correction = read_raw_frame(correction_path)
    profile = build_profile(
        correction,
        smooth_sigma=args.smooth_sigma,
        clip_percentiles=(args.clip_low, args.clip_high),
    )

    use_converter = compression != "none" and converter is not None
    resolved_compression = "lossless-jpeg" if compression == "auto" else compression

    tempdir_context = tempfile.TemporaryDirectory(prefix="ffcplugin-dng-") if use_converter else _null_tempdir()
    with tempdir_context as tmp:
        write_dir = Path(tmp) if use_converter else output_dir
        temp_paths: list[Path] = []

        for index, scan_path in enumerate(inputs, start=1):
            final_path = output_paths[index - 1]
            write_path = write_dir / final_path.name
            print(f"[{index}/{len(inputs)}] Correcting {scan_path.name}", file=sys.stderr)
            scan = read_raw_frame(scan_path)
            corrected = apply_profile(scan, profile, backend=backend)
            write_mosaic_dng(write_path, corrected, scan.metadata, software="ffcplugin")
            temp_paths.append(write_path)

        if use_converter:
            assert converter is not None
            compress_with_adobe_dng_converter(
                temp_paths,
                output_dir,
                converter_path=converter,
                mode=resolved_compression,  # type: ignore[arg-type]
            )

    for path in output_paths:
        print(path)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ffc-apply",
        description="Apply a reusable flat-field correction raw to a folder of scans and write mosaic DNGs.",
    )
    parser.add_argument("correction", help="Path to the flat-field/correction raw image.")
    parser.add_argument("input", help="Scan raw file or folder of scan raws.")
    parser.add_argument("-o", "--output", default="ffc-output", help="Output folder for corrected DNGs.")
    parser.add_argument(
        "--include",
        action="append",
        default=None,
        help="Glob for input files. Can be repeated. Default: *.ARW and *.arw.",
    )
    parser.add_argument("--recursive", action="store_true", help="Search input folders recursively.")
    parser.add_argument("--suffix", default="-ffc", help="Suffix added before .dng for output files.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing outputs.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned output paths without writing files.")
    parser.add_argument(
        "--smooth-sigma",
        type=float,
        default=96.0,
        help="Gaussian smoothing sigma in full-resolution pixels for the correction frame; 0 disables smoothing.",
    )
    parser.add_argument("--clip-low", type=float, default=0.1, help="Low percentile clip for correction-frame outliers.")
    parser.add_argument("--clip-high", type=float, default=99.9, help="High percentile clip for correction-frame outliers.")
    parser.add_argument(
        "--backend",
        choices=("auto", "numpy", "numexpr", "mlx"),
        default="auto",
        help="Math backend for applying the gain map.",
    )
    parser.add_argument("--numexpr-threads", type=int, default=None, help="Thread count for the NumExpr backend.")
    parser.add_argument(
        "--compression",
        choices=("auto", "none", "lossless-jpeg", "lossless-jxl"),
        default="auto",
        help="DNG compression. 'auto' uses Adobe DNG Converter when found, else uncompressed DNG.",
    )
    parser.add_argument("--dng-converter", default=None, help="Path to Adobe DNG Converter executable or .app bundle.")
    return parser


def _discover_inputs(input_path: Path, patterns: list[str] | None, recursive: bool, correction_path: Path) -> list[Path]:
    if input_path.is_file():
        return [] if input_path.resolve() == correction_path.resolve() else [input_path]

    globs = patterns or list(DEFAULT_PATTERNS)
    results: list[Path] = []
    for pattern in globs:
        iterator = input_path.rglob(pattern) if recursive else input_path.glob(pattern)
        for path in iterator:
            if path.is_file() and path.resolve() != correction_path.resolve():
                results.append(path)
    return sorted(set(results))


class _null_tempdir:
    def __enter__(self) -> str:
        return ""

    def __exit__(self, *args: object) -> None:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
