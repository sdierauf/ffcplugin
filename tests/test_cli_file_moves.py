from __future__ import annotations

from pathlib import Path

import pytest

from ffc.cli import _default_originals_dir, _default_output_dir, _discover_inputs, _move_originals, _parser


def test_default_paths_are_scan_root_and_originals_subfolder(tmp_path: Path) -> None:
    scan_dir = tmp_path / "roll"
    scan_dir.mkdir()

    assert _default_output_dir(scan_dir) == scan_dir
    assert _default_originals_dir(scan_dir, "originals") == scan_dir / "originals"


def test_move_originals_preserves_relative_paths_and_sidecars(tmp_path: Path) -> None:
    scan_dir = tmp_path / "roll"
    nested = scan_dir / "nested"
    nested.mkdir(parents=True)
    raw = nested / "DSC0001.ARW"
    sidecar = nested / "DSC0001.XMP"
    raw.write_bytes(b"raw")
    sidecar.write_text("sidecar", encoding="utf-8")

    moved = _move_originals([raw], scan_dir, scan_dir / "originals")

    assert moved == [scan_dir / "originals" / "nested" / "DSC0001.ARW"]
    assert not raw.exists()
    assert not sidecar.exists()
    assert (scan_dir / "originals" / "nested" / "DSC0001.ARW").read_bytes() == b"raw"
    assert (scan_dir / "originals" / "nested" / "DSC0001.XMP").read_text(encoding="utf-8") == "sidecar"


def test_replace_existing_is_the_output_replacement_flag() -> None:
    parser = _parser()

    args = parser.parse_args(["correction.ARW", "scans", "--replace-existing"])

    assert args.replace_existing is True
    with pytest.raises(SystemExit):
        parser.parse_args(["correction.ARW", "scans", "--overwrite"])


def test_discover_inputs_ignores_macos_appledouble_files(tmp_path: Path) -> None:
    scan_dir = tmp_path / "roll"
    scan_dir.mkdir()
    correction = scan_dir / "correction.ARW"
    raw = scan_dir / "DSC0001.ARW"
    apple_double = scan_dir / "._DSC0001.ARW"
    correction.write_bytes(b"correction")
    raw.write_bytes(b"raw")
    apple_double.write_bytes(b"metadata")

    inputs = _discover_inputs(scan_dir, None, False, correction)

    assert inputs == [raw]
