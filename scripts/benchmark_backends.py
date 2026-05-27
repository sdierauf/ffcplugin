#!/usr/bin/env python3
"""Benchmark flat-field correction backends without DNG write/compression noise."""

from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

from ffc.accelerate import choose_backend
from ffc.flatfield import apply_profile, build_profile
from ffc.rawio import read_raw_frame


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("correction", help="Flat-field correction raw.")
    parser.add_argument("input", help="Input raw file or folder.")
    parser.add_argument("--include", action="append", default=["*.ARW", "*.arw"], help="Input glob; repeatable.")
    parser.add_argument("--recursive", action="store_true", help="Search folders recursively.")
    parser.add_argument("--repeat", type=int, default=3, help="Benchmark repeats.")
    parser.add_argument("--limit", type=int, default=0, help="Limit input files for quick runs.")
    parser.add_argument("--smooth-sigma", type=float, default=192.0, help="Correction-frame smoothing sigma.")
    parser.add_argument("--numexpr-threads", type=int, default=None, help="NumExpr thread count.")
    parser.add_argument("--backends", nargs="+", default=["numpy", "numexpr"], choices=["numpy", "numexpr"])
    return parser.parse_args()


def discover(path: Path, patterns: list[str], recursive: bool, correction: Path) -> list[Path]:
    if path.is_file():
        return [path]
    found: list[Path] = []
    for pattern in patterns:
        iterator = path.rglob(pattern) if recursive else path.glob(pattern)
        found.extend(candidate for candidate in iterator if candidate.is_file() and candidate.resolve() != correction.resolve())
    return sorted(set(found))


def main() -> int:
    args = parse_args()
    correction_path = Path(args.correction).expanduser()
    input_path = Path(args.input).expanduser()
    paths = discover(input_path, args.include, args.recursive, correction_path)
    if args.limit:
        paths = paths[: args.limit]
    if not paths:
        raise SystemExit("No input raws found.")

    print(f"reading correction: {correction_path}")
    correction = read_raw_frame(correction_path)
    profile = build_profile(correction, smooth_sigma=args.smooth_sigma)
    print(f"reading scans: {len(paths)}")
    scans = [read_raw_frame(path) for path in paths]

    print("backend,repeat,total_s,files_per_s,megapixels_per_s")
    megapixels = sum(scan.raw.size for scan in scans) / 1_000_000
    for backend_name in args.backends:
        try:
            backend = choose_backend(backend_name, args.numexpr_threads)
        except RuntimeError as exc:
            print(f"{backend_name},skip,{exc},,")
            continue

        totals: list[float] = []
        for repeat in range(args.repeat):
            start = time.perf_counter()
            checksum = 0
            for scan in scans:
                corrected = apply_profile(scan, profile, backend=backend)
                checksum ^= int(corrected[0, 0])
            elapsed = time.perf_counter() - start
            totals.append(elapsed)
            print(f"{backend_name},{repeat + 1},{elapsed:.4f},{len(scans) / elapsed:.3f},{megapixels / elapsed:.1f}")
            if checksum < 0:
                raise AssertionError("unreachable checksum guard")

        print(f"{backend_name},median,{statistics.median(totals):.4f},{len(scans) / statistics.median(totals):.3f},{megapixels / statistics.median(totals):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
