#!/usr/bin/env python3
"""Stage a flat-field calibration raw after a selected Lightroom scan batch."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import quote


EXIF_DATE_TAGS = (
    "SubSecDateTimeOriginal",
    "DateTimeOriginal",
    "SubSecCreateDate",
    "CreateDate",
    "ModifyDate",
    "FileModifyDate",
)


@dataclass(frozen=True)
class PhotoTime:
    path: Path
    dt: datetime
    epoch: float
    source: str


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", required=True, help="Existing flat-field/correction raw to copy.")
    parser.add_argument("--selected", action="append", default=[], help="Selected scan path. May be repeated.")
    parser.add_argument("--selected-list", help="Text file containing selected scan paths, one per line.")
    parser.add_argument("--exiftool", help="Optional exiftool executable path.")
    parser.add_argument("--result-file", help="Write Lightroom-friendly key/value results here.")
    parser.add_argument("--offset-seconds", type=int, default=1, help="Seconds after the latest selected photo.")
    parser.add_argument("--dry-run", action="store_true", help="Report the intended destination without copying.")
    return parser.parse_args(argv)


def read_selected_paths(args: argparse.Namespace) -> list[Path]:
    paths = [Path(path).expanduser() for path in args.selected]

    if args.selected_list:
        selected_list = Path(args.selected_list).expanduser()
        with selected_list.open("r", encoding="utf-8") as handle:
            paths.extend(Path(line.rstrip("\r\n")).expanduser() for line in handle if line.strip())

    return paths


def write_result(path: str | None, values: dict[str, object]) -> None:
    lines = [f"{key}={quote(str(value), safe='')}" for key, value in values.items()]
    text = "\n".join(lines) + "\n"

    if path:
        Path(path).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def find_exiftool(configured_path: str | None) -> str | None:
    if configured_path:
        candidate = Path(configured_path).expanduser()
        if candidate.exists():
            return str(candidate)
        return shutil.which(configured_path)

    return shutil.which("exiftool") or shutil.which("exiftool.exe")


def parse_exif_datetime(value: object) -> datetime | None:
    if value is None:
        return None

    text = str(value).strip().replace("\x00", "")
    if not text or text.startswith("0000:00:00"):
        return None

    match = re.search(
        r"(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(?:\s*(Z|[+-]\d{2}:?\d{2}))?",
        text,
    )
    if not match:
        return None

    year, month, day, hour, minute, second, fraction, offset = match.groups()
    microsecond = int((fraction or "0")[:6].ljust(6, "0"))
    tzinfo = None

    if offset:
        if offset == "Z":
            tzinfo = timezone.utc
        else:
            compact = offset.replace(":", "")
            sign = 1 if compact[0] == "+" else -1
            hours = int(compact[1:3])
            minutes = int(compact[3:5])
            tzinfo = timezone(sign * timedelta(hours=hours, minutes=minutes))

    try:
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second),
            microsecond,
            tzinfo=tzinfo,
        )
    except ValueError:
        return None


def epoch_for(dt: datetime) -> float:
    return dt.timestamp()


def filesystem_time(path: Path) -> PhotoTime:
    stat = path.stat()
    dt = datetime.fromtimestamp(stat.st_mtime)
    return PhotoTime(path=path, dt=dt, epoch=stat.st_mtime, source="filesystem mtime")


def read_exif_times(exiftool: str, paths: Iterable[Path]) -> dict[Path, datetime]:
    command = [
        exiftool,
        "-json",
        "-charset",
        "filename=utf8",
        *[f"-{tag}" for tag in EXIF_DATE_TAGS],
        *[str(path) for path in paths],
    ]
    completed = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace", check=False)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "exiftool could not read selected timestamps").strip())

    try:
        rows = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"exiftool returned invalid JSON: {exc}") from exc

    found: dict[Path, datetime] = {}
    for row in rows:
        source = row.get("SourceFile")
        if not source:
            continue

        parsed = None
        for tag in EXIF_DATE_TAGS:
            parsed = parse_exif_datetime(row.get(tag))
            if parsed:
                break

        if parsed:
            found[Path(source)] = parsed

    return found


def selected_times(paths: list[Path], exiftool: str | None) -> tuple[list[PhotoTime], list[str]]:
    warnings: list[str] = []
    exif_times: dict[Path, datetime] = {}

    if exiftool:
        try:
            exif_times = read_exif_times(exiftool, paths)
        except RuntimeError as exc:
            warnings.append(f"Could not read selected capture times with exiftool; using filesystem mtimes. {exc}")
    else:
        warnings.append("ExifTool was not found; using filesystem mtimes and leaving the copied raw metadata timestamps unchanged.")

    records: list[PhotoTime] = []
    for path in paths:
        resolved = Path(path)
        dt = exif_times.get(resolved)
        if dt is None:
            matching = [value for key, value in exif_times.items() if key.resolve() == resolved.resolve()]
            dt = matching[0] if matching else None

        if dt is not None:
            records.append(PhotoTime(path=resolved, dt=dt, epoch=epoch_for(dt), source="metadata"))
        else:
            records.append(filesystem_time(resolved))

    if exiftool and any(record.source == "filesystem mtime" for record in records):
        warnings.append("Some selected photos had no readable capture timestamp; filesystem mtime was used for those files.")

    return records, warnings


def increment_stem(stem: str) -> str:
    match = re.search(r"(\d+)(?!.*\d)", stem)
    if not match:
        return f"{stem}_flatfield"

    number_text = match.group(1)
    number = int(number_text) + 1
    return f"{stem[:match.start(1)]}{number:0{len(number_text)}d}{stem[match.end(1):]}_flatfield"


def unique_destination(latest_path: Path, calibration_path: Path) -> Path:
    folder = latest_path.parent
    extension = calibration_path.suffix or latest_path.suffix
    base_name = increment_stem(latest_path.stem)
    candidate = folder / f"{base_name}{extension}"
    index = 2

    while candidate.exists():
        candidate = folder / f"{base_name}-{index}{extension}"
        index += 1

    return candidate


def exif_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y:%m:%d %H:%M:%S")


def write_raw_timestamps(exiftool: str, path: Path, dt: datetime) -> None:
    timestamp = exif_timestamp(dt)
    command = [
        exiftool,
        "-overwrite_original",
        "-P",
        f"-DateTimeOriginal={timestamp}",
        f"-CreateDate={timestamp}",
        f"-ModifyDate={timestamp}",
        str(path),
    ]
    completed = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace", check=False)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "exiftool could not write timestamps").strip())


def stage(args: argparse.Namespace) -> dict[str, object]:
    calibration_path = Path(args.calibration).expanduser()
    selected_paths = read_selected_paths(args)

    if not calibration_path.is_file():
        raise FileNotFoundError(f"Calibration raw does not exist: {calibration_path}")
    if not selected_paths:
        raise ValueError("No selected scan paths were provided.")

    missing = [str(path) for path in selected_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("Selected scan path does not exist: " + missing[0])

    exiftool = find_exiftool(args.exiftool)
    records, warnings = selected_times(selected_paths, exiftool)
    latest = max(records, key=lambda record: (record.epoch, str(record.path)))
    destination = unique_destination(latest.path, calibration_path)
    staged_dt = latest.dt + timedelta(seconds=args.offset_seconds)
    staged_epoch = latest.epoch + args.offset_seconds

    if not args.dry_run:
        shutil.copy2(calibration_path, destination)

        if exiftool:
            try:
                write_raw_timestamps(exiftool, destination, staged_dt)
            except RuntimeError as exc:
                warnings.append(f"Could not rewrite raw metadata timestamps with exiftool; only filesystem mtime was changed. {exc}")

        os.utime(destination, (staged_epoch, staged_epoch))

    return {
        "status": "ok",
        "staged_path": str(destination),
        "latest_selected_path": str(latest.path),
        "timestamp_source": latest.source,
        "staged_capture_time": exif_timestamp(staged_dt),
        "exiftool": exiftool or "",
        "warning": " ".join(warnings),
    }


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    try:
        result = stage(args)
    except Exception as exc:  # Lightroom displays this message directly.
        write_result(args.result_file, {"status": "error", "message": str(exc)})
        return 1

    write_result(args.result_file, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
