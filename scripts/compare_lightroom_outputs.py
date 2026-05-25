#!/usr/bin/env python3
"""Compare corrected DNG raw mosaics against Lightroom flat-field DNGs."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rawpy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool_outputs", help="Folder containing this tool's corrected DNGs.")
    parser.add_argument("lightroom_outputs", help="Folder containing Lightroom corrected DNGs.")
    parser.add_argument("--suffix", default="-ffc", help="Suffix used on this tool's output stems.")
    return parser.parse_args()


def read_raw(path: Path) -> tuple[np.ndarray, rawpy.ImageSizes, list[int], int]:
    with rawpy.imread(str(path)) as raw:
        return raw.raw_image.copy(), raw.sizes, list(raw.black_level_per_channel), int(raw.white_level)


def main() -> int:
    args = parse_args()
    tool_dir = Path(args.tool_outputs).expanduser()
    lr_dir = Path(args.lightroom_outputs).expanduser()
    rows: list[tuple[str, float, float, float, float, float]] = []

    for tool_path in sorted(tool_dir.glob("*.dng")):
        stem = tool_path.stem
        if args.suffix and stem.endswith(args.suffix):
            stem = stem[: -len(args.suffix)]
        lr_path = lr_dir / f"{stem}.dng"
        if not lr_path.exists():
            continue

        tool_raw, tool_sizes, _, _ = read_raw(tool_path)
        lr_raw, lr_sizes, _, _ = read_raw(lr_path)
        if tool_raw.shape != lr_raw.shape:
            raise ValueError(f"Shape mismatch for {tool_path.name}: {tool_raw.shape} vs {lr_raw.shape}")

        left = lr_sizes.crop_left_margin
        top = lr_sizes.crop_top_margin
        right = left + lr_sizes.crop_width
        bottom = top + lr_sizes.crop_height
        diff = tool_raw[top:bottom, left:right].astype(np.int32) - lr_raw[top:bottom, left:right].astype(np.int32)
        absdiff = np.abs(diff)
        rows.append(
            (
                stem,
                float(absdiff.mean()),
                float(np.median(absdiff)),
                float(np.percentile(absdiff, 95)),
                float(np.percentile(absdiff, 99)),
                float(diff.mean()),
            )
        )

    print("stem,mean_abs,median_abs,p95_abs,p99_abs,bias")
    for row in rows:
        print(f"{row[0]},{row[1]:.3f},{row[2]:.3f},{row[3]:.3f},{row[4]:.3f},{row[5]:.3f}")
    if rows:
        values = np.array([row[1:] for row in rows], dtype=np.float64)
        means = values.mean(axis=0)
        print(f"AVERAGE,{means[0]:.3f},{means[1]:.3f},{means[2]:.3f},{means[3]:.3f},{means[4]:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

